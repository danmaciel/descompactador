"""Motor de extração: orquestra backends, senhas e mesclagem (sem dependência de Qt).

Para cada ``ArchiveSet``: escolhe o backend → verifica se precisa de senha →
extrai numa área temporária dentro do destino → mescla no destino → apaga a
área temporária (sempre, mesmo em erro ou cancelamento).
"""

from __future__ import annotations

import enum
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .backends import Backend, Tools, candidates, looks_like_rar
from .errors import Cancelled, ExtractError, MissingTool, UnsupportedFormat, WrongPassword
from .merge import Action, Conflict, Merger, MergeStats, Resolution
from .volumes import ArchiveSet

STAGING_PREFIX = ".descompactador-"


class Status(enum.Enum):
    OK = "ok"
    ERROR = "erro"
    SKIPPED = "pulado"
    CANCELLED = "cancelado"


@dataclass
class JobResult:
    archive: ArchiveSet
    status: Status
    message: str = ""
    stats: MergeStats = field(default_factory=MergeStats)


class Callbacks:
    """Ponte entre o motor e a interface. Qualquer método pode levantar ``Cancelled``."""

    def on_conflict(self, conflict: Conflict) -> Resolution:
        raise NotImplementedError

    def on_password(self, archive: ArchiveSet, attempt: int, error: str | None) -> str | None:
        """Pede a senha. ``None`` pula este arquivo."""
        return None

    def on_progress(self, index: int, fraction: float, message: str) -> None:
        pass

    def on_log(self, message: str) -> None:
        pass

    def on_job_done(self, index: int, result: JobResult) -> None:
        pass


class _Skipped(Exception):
    pass


class Engine:
    def __init__(
        self,
        callbacks: Callbacks,
        cancel: threading.Event | None = None,
        tools: Tools | None = None,
        known_passwords: list[str] | None = None,
    ) -> None:
        self.cb = callbacks
        self.cancel = cancel or threading.Event()
        self.tools = tools or Tools.detect()
        # Senhas que funcionaram nesta sessão (só em memória), a mais recente primeiro.
        self.known_passwords = known_passwords if known_passwords is not None else []

    def run(self, archives: list[ArchiveSet], dest: Path, policy: Action | None = None) -> list[JobResult]:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        merger = Merger(dest, self.cb.on_conflict, self.cancel, policy, self.cb.on_log)
        results = []
        for index, archive in enumerate(archives):
            if self.cancel.is_set():
                result = JobResult(archive, Status.CANCELLED, "Cancelado")
            else:
                result = self._run_job(index, archive, dest, merger)
            results.append(result)
            self.cb.on_job_done(index, result)
        return results

    def _run_job(self, index: int, archive: ArchiveSet, dest: Path, merger: Merger) -> JobResult:
        name = archive.first.name
        if archive.missing_first:
            return JobResult(archive, Status.ERROR, "Volume inicial não encontrado")
        if not archive.first.is_file():
            return JobResult(archive, Status.ERROR, "Arquivo não encontrado")
        self.cb.on_progress(index, 0.0, "Analisando")
        try:
            backend, encrypted = self._pick_backend(archive.first)
            self.cb.on_log(f"{name}: extraindo com {backend.name}"
                           + (" (protegido por senha)" if encrypted else ""))
            stats = self._extract_and_merge(index, archive, backend, encrypted, dest, merger)
        except Cancelled:
            self.cancel.set()
            return JobResult(archive, Status.CANCELLED, "Cancelado")
        except _Skipped:
            return JobResult(archive, Status.SKIPPED, "Pulado (sem senha)")
        except ExtractError as exc:
            self.cb.on_log(f"{name}: erro: {exc}")
            return JobResult(archive, Status.ERROR, str(exc))
        except OSError as exc:
            self.cb.on_log(f"{name}: erro: {exc}")
            return JobResult(archive, Status.ERROR, f"Erro de arquivo: {exc.strerror or exc}")
        return JobResult(archive, Status.OK, "", stats)

    def _pick_backend(self, path: Path) -> tuple[Backend, bool]:
        errors = []
        for backend in candidates(path, self.tools):
            try:
                return backend, backend.probe(path, self.cancel)
            except UnsupportedFormat as exc:
                errors.append(f"{backend.name}: {exc}")
        if self.tools.unar is None and looks_like_rar(path):
            raise MissingTool("Para extrair RAR, instale o pacote 'unar'.")
        raise ExtractError("Formato não reconhecido (" + "; ".join(errors) + ")")

    def _extract_and_merge(self, index: int, archive: ArchiveSet, backend: Backend, encrypted: bool,
                           dest: Path, merger: Merger) -> MergeStats:
        last_percent = -1

        def progress(fraction: float) -> None:
            nonlocal last_percent
            percent = int(fraction * 100)
            if percent != last_percent:
                last_percent = percent
                self.cb.on_progress(index, fraction, "Extraindo")

        def log(message: str) -> None:
            self.cb.on_log(f"{archive.first.name}: {message}")

        # Primeiro as senhas que já funcionaram nesta sessão; depois, pergunta ao usuário.
        to_try: list[str | None] = list(self.known_passwords) if encrypted else [None]
        attempt = 0
        error: str | None = None
        while True:
            if to_try:
                password, from_user = to_try.pop(0), False
            else:
                password = self.cb.on_password(archive, attempt, error)
                attempt += 1
                if password is None:
                    raise _Skipped()
                from_user = True

            staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=dest))
            try:
                try:
                    backend.extract(archive.first, staging, password, progress, log, self.cancel)
                except WrongPassword as exc:
                    if from_user:
                        error = str(exc)
                    continue
                if password:
                    if password in self.known_passwords:
                        self.known_passwords.remove(password)
                    self.known_passwords.insert(0, password)
                self.cb.on_progress(index, 1.0, "Mesclando")
                return merger.merge(staging, archive.first.name)
            finally:
                shutil.rmtree(staging, ignore_errors=True)


def summarize(results: list[JobResult]) -> str:
    """Resumo legível de um lote."""
    count = {s: sum(1 for r in results if r.status is s) for s in Status}
    total = MergeStats()
    for r in results:
        total += r.stats
    parts = [f"{count[Status.OK]} extraído(s)"]
    if count[Status.ERROR]:
        parts.append(f"{count[Status.ERROR]} com erro")
    if count[Status.SKIPPED]:
        parts.append(f"{count[Status.SKIPPED]} pulado(s)")
    if count[Status.CANCELLED]:
        parts.append(f"{count[Status.CANCELLED]} cancelado(s)")
    lines = [", ".join(parts) + "."]
    detail = [f"{total.added} arquivo(s) novo(s)"]
    if total.overwritten:
        detail.append(f"{total.overwritten} sobrescrito(s)")
    if total.renamed:
        detail.append(f"{total.renamed} renomeado(s)")
    if total.skipped:
        detail.append(f"{total.skipped} mantido(s) sem alteração")
    if total.identical:
        detail.append(f"{total.identical} idêntico(s) ignorado(s)")
    lines.append(", ".join(detail) + ".")
    return "\n".join(lines)
