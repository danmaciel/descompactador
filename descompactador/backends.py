"""Backends de extração: tarfile (biblioteca padrão), 7z e unar.

Todos extraem para uma pasta (a área temporária) e informam:
  * ``probe``: se o arquivo precisa de senha (ou ``UnsupportedFormat``);
  * ``extract``: extrai, chamando ``progress(fração)`` e ``log(msg)``;
    levanta ``WrongPassword``, ``ExtractError`` ou ``Cancelled``.

Os programas externos rodam com ``stdin=DEVNULL`` e sempre recebem uma senha
(fictícia quando não há), para nunca ficarem parados esperando digitação.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import Cancelled, ExtractError, MissingTool, UnsupportedFormat, WrongPassword

ProgressCb = Callable[[float], None]
LogCb = Callable[[str], None]

# Senha usada quando o usuário não informou nenhuma: impede o 7z de pedir na tela.
DUMMY_PASSWORD = "descompactador-sem-senha-7f3a9c"

_TAR_SUFFIXES = (".tar", ".tgz", ".taz", ".tbz", ".tbz2", ".tb2", ".txz", ".tzst")
_COMPRESSED_SUFFIXES = (".gz", ".bz2", ".xz", ".zst", ".zstd", ".lzma")
_RAR_NAME = re.compile(r"\.(rar|r\d{2,3})$", re.IGNORECASE)
_RAR_MAGIC = b"Rar!\x1a\x07"
_PERCENT = re.compile(r"(\d{1,3})%")
_NOT_ARCHIVE = re.compile(r"Can ?not open the file as (\[\w+\] )?archive|Is not archive")


def _env() -> dict[str, str]:
    # Mensagens em inglês (para reconhecê-las) e nomes de arquivo em UTF-8.
    return {**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}


@dataclass
class _RunResult:
    returncode: int
    stdout: str
    stderr: str
    stopped: bool  # processo encerrado a pedido de um callback


def _run(
    cmd: list[str],
    cancel: threading.Event,
    on_stdout: Callable[[str], bool] | None = None,
    on_stderr_line: Callable[[str], bool] | None = None,
) -> _RunResult:
    """Roda ``cmd`` lendo stdout/stderr em paralelo.

    Os callbacks devolvem ``True`` para pedir que o processo seja encerrado.
    Sem ``on_stdout``, a saída padrão é guardada inteira no resultado.
    """
    if cancel.is_set():
        raise Cancelled()
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env()
    )
    stop = threading.Event()
    out_parts: list[str] = []
    err_lines: deque[str] = deque(maxlen=500)

    def read_stdout() -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        fd = proc.stdout.fileno()
        while data := os.read(fd, 65536):
            text = decoder.decode(data)
            if on_stdout is None:
                out_parts.append(text)
            elif on_stdout(text):
                stop.set()

    def read_stderr() -> None:
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            err_lines.append(line)
            if on_stderr_line is not None and on_stderr_line(line):
                stop.set()

    threads = [threading.Thread(target=read_stdout, daemon=True),
               threading.Thread(target=read_stderr, daemon=True)]
    for t in threads:
        t.start()
    try:
        while True:
            try:
                proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled()
            if stop.is_set():
                proc.kill()
                proc.wait()
                break
    finally:
        for t in threads:
            t.join(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
    return _RunResult(proc.returncode, "".join(out_parts), "\n".join(err_lines), stop.is_set())


def _error_summary(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.upper().startswith("ERROR")] or lines
    return " | ".join(errors[:3]) or fallback


class Backend:
    name = ""

    def probe(self, archive: Path, cancel: threading.Event) -> bool:
        """Devolve True se o arquivo precisa de senha."""
        raise NotImplementedError

    def extract(self, archive: Path, out: Path, password: str | None,
                progress: ProgressCb, log: LogCb, cancel: threading.Event) -> None:
        raise NotImplementedError


class TarBackend(Backend):
    """tar puro ou comprimido (gz, bz2, xz, zst, lzma) com ``filter="data"``."""

    name = "tar"

    def probe(self, archive: Path, cancel: threading.Event) -> bool:
        return False

    def extract(self, archive, out, password, progress, log, cancel):
        size = max(archive.stat().st_size, 1)
        try:
            with open(archive, "rb") as raw, tarfile.open(fileobj=raw, mode="r:*") as tf:
                for member in tf:
                    if cancel.is_set():
                        raise Cancelled()
                    try:
                        tf.extract(member, out, filter="data")
                    except tarfile.FilterError as exc:
                        log(f"Ignorado por segurança: {member.name} ({exc})")
                    progress(min(raw.tell() / size, 1.0))
        except Cancelled:
            raise
        except Exception as exc:
            raise ExtractError(f"Falha ao ler o tar: {exc}") from exc


class SevenZipBackend(Backend):
    name = "7z"

    def __init__(self, exe: str) -> None:
        self.exe = exe

    def probe(self, archive, cancel):
        r = _run([self.exe, "l", "-slt", f"-p{DUMMY_PASSWORD}", "--", str(archive)], cancel)
        text = r.stdout + "\n" + r.stderr
        if r.returncode in (0, 1):
            return "Encrypted = +" in r.stdout
        if "Wrong password" in text:
            return True  # cabeçalho criptografado: nem a listagem abre
        if _NOT_ARCHIVE.search(text):
            raise UnsupportedFormat("7z não reconhece o formato")
        raise ExtractError(_error_summary(r.stderr, f"7z falhou (código {r.returncode})"))

    def extract(self, archive, out, password, progress, log, cancel):
        def on_stdout(text: str) -> bool:
            found = _PERCENT.findall(text)
            if found:
                progress(min(int(found[-1]), 100) / 100)
            return False

        def on_stderr(line: str) -> bool:
            return "Wrong password" in line

        cmd = [self.exe, "x", "-y", "-bso0", "-bsp1", f"-o{out}",
               f"-p{password or DUMMY_PASSWORD}", "--", str(archive)]
        r = _run(cmd, cancel, on_stdout, on_stderr)
        if r.stopped or "Wrong password" in r.stderr:
            raise WrongPassword("Senha incorreta" if password else "O arquivo precisa de senha")
        if r.returncode == 1:
            log(f"Avisos do 7z: {_error_summary(r.stderr, 'avisos não especificados')}")
        elif r.returncode != 0:
            if _NOT_ARCHIVE.search(r.stderr):
                raise UnsupportedFormat("7z não reconhece o formato")
            raise ExtractError(_error_summary(r.stderr, f"7z falhou (código {r.returncode})"))


class UnarBackend(Backend):
    """unar/lsar (The Unarchiver): usado para RAR, que o 7z do Fedora não abre."""

    name = "unar"

    def __init__(self, unar: str, lsar: str | None) -> None:
        self.unar = unar
        self.lsar = lsar
        self._entries: dict[Path, int] = {}

    def probe(self, archive, cancel):
        if self.lsar is None:
            return False  # sem lsar, descobrimos a senha só na extração
        r = _run([self.lsar, "-j", str(archive)], cancel)
        encrypted = "requires a password" in r.stderr
        try:
            data = json.loads(r.stdout)
        except ValueError:
            data = None
        if data is not None:
            if "lsarFormatName" not in data and not encrypted:
                raise UnsupportedFormat("unar não reconhece o formato")
            contents = data.get("lsarContents") or []
            self._entries[archive] = len(contents)
            encrypted = encrypted or any(e.get("XADIsEncrypted") for e in contents)
        elif r.returncode != 0 and not encrypted:
            raise ExtractError(_error_summary(r.stderr or r.stdout, f"lsar falhou (código {r.returncode})"))
        return encrypted

    def extract(self, archive, out, password, progress, log, cancel):
        total = self._entries.get(archive, 0)
        done = 0
        pending = ""
        wrong_pw = False
        output: deque[str] = deque(maxlen=50)

        def on_stdout(text: str) -> bool:
            nonlocal done, pending, wrong_pw
            pending += text
            *lines, pending = pending.split("\n")
            for line in lines:
                output.append(line)
                if "wrong password" in line.lower():
                    wrong_pw = True
                    return True
                if line.endswith("OK.") or "Failed!" in line:
                    done += 1
                    if total:
                        progress(min(done / total, 1.0))
            return False

        cmd = [self.unar, "-o", str(out), "-D", "-f", "-k", "skip"]
        if password:
            cmd += ["-p", password]
        cmd.append(str(archive))
        r = _run(cmd, cancel, on_stdout)
        if pending:
            output.append(pending)
        text = "\n".join(output) + "\n" + r.stderr
        if wrong_pw or "wrong password" in text.lower() or (password and "decrunching" in text):
            raise WrongPassword("Senha incorreta" if password else "O arquivo precisa de senha")
        if r.returncode != 0:
            if "Couldn't recognize the archive format" in text:
                raise UnsupportedFormat("unar não reconhece o formato")
            failed = [ln.strip() for ln in output if "Failed!" in ln or "failed" in ln.lower()]
            raise ExtractError(" | ".join(failed[:3]) or _error_summary(text, "unar falhou"))


@dataclass
class Tools:
    sevenzip: str | None
    unar: str | None
    lsar: str | None

    @classmethod
    def detect(cls) -> Tools:
        return cls(
            sevenzip=shutil.which("7z") or shutil.which("7zz") or shutil.which("7za"),
            unar=shutil.which("unar"),
            lsar=shutil.which("lsar"),
        )


def looks_like_tar(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(_TAR_SUFFIXES) or any(name.endswith(".tar" + s) for s in _COMPRESSED_SUFFIXES):
        return True
    if name.endswith(_COMPRESSED_SUFFIXES):
        try:
            return tarfile.is_tarfile(path)
        except Exception:
            return False
    return False


def looks_like_rar(path: Path) -> bool:
    if _RAR_NAME.search(path.name):
        return True
    try:
        with open(path, "rb") as f:
            return f.read(len(_RAR_MAGIC)) == _RAR_MAGIC
    except OSError:
        return False


def candidates(path: Path, tools: Tools) -> list[Backend]:
    """Backends a tentar, em ordem, para o volume inicial ``path``."""
    if looks_like_tar(path):
        return [TarBackend()]
    sevenzip = [SevenZipBackend(tools.sevenzip)] if tools.sevenzip else []
    unar = [UnarBackend(tools.unar, tools.lsar)] if tools.unar else []
    if looks_like_rar(path):
        if not unar and not sevenzip:
            raise MissingTool("Para extrair RAR, instale o pacote 'unar'.")
        return unar + sevenzip
    backends = sevenzip + unar
    if not backends:
        raise MissingTool("Nenhum extrator encontrado: instale '7zip' ou 'unar'.")
    return backends
