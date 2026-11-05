"""Mesclagem do conteúdo extraído (área temporária) com a pasta de destino.

Regras:
  * diretório que já existe no destino é mesclado recursivamente;
  * item que não existe no destino é movido inteiro (``rename``, instantâneo);
  * arquivos idênticos (mesmo tamanho e conteúdo) são pulados sem perguntar;
  * nos demais conflitos, a decisão vem do callback ``ask`` ou da política
    "aplicar a todos";
  * um diretório existente nunca é apagado: em conflitos de tipos diferentes
    (arquivo × pasta, symlink × pasta), Sobrescrever e Manter o mais novo
    viram Renomear;
  * symlinks nunca são seguidos (``lstat``); um symlink no destino é tratado
    como arquivo e o app nunca mescla para dentro dele.
"""

from __future__ import annotations

import enum
import errno
import os
import shutil
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import Cancelled


class Action(enum.Enum):
    OVERWRITE = "sobrescrever"
    SKIP = "pular"
    RENAME = "renomear"
    KEEP_NEWER = "manter_mais_novo"


@dataclass
class Resolution:
    action: Action
    apply_to_all: bool = False


@dataclass
class Conflict:
    rel_path: Path          # caminho relativo ao destino
    existing: Path          # item que já está no destino
    incoming: Path          # item novo, ainda na área temporária
    source: str             # nome do arquivo compactado de onde veio o item novo
    existing_is_dir: bool
    incoming_is_dir: bool

    @property
    def type_mismatch(self) -> bool:
        return self.existing_is_dir != self.incoming_is_dir


@dataclass
class MergeStats:
    added: int = 0          # arquivos novos colocados no destino
    overwritten: int = 0
    renamed: int = 0
    skipped: int = 0
    identical: int = 0

    def __iadd__(self, other: MergeStats) -> MergeStats:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self


AskCallback = Callable[[Conflict], Resolution]

_CHUNK = 1024 * 1024


def same_content(a: Path, b: Path) -> bool:
    """Compara dois arquivos regulares byte a byte (tamanhos já conferidos)."""
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ca = fa.read(_CHUNK)
            cb = fb.read(_CHUNK)
            if ca != cb:
                return False
            if not ca:
                return True


def free_name(path: Path, is_dir: bool = False) -> Path:
    """Primeiro nome livre no formato ``nome (N).ext`` (pastas: ``nome (N)``)."""
    stem, suffix = (path.name, "") if is_dir else (path.stem, path.suffix)
    n = 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not os.path.lexists(candidate):
            return candidate
        n += 1


def _count_files(path: Path) -> int:
    if not path.is_dir() or path.is_symlink():
        return 1
    return sum(len(files) + sum(1 for d in dirs if (Path(root) / d).is_symlink())
               for root, dirs, files in os.walk(path))


def _move(src: Path, dst: Path, replace: bool = False) -> None:
    """Move ``src`` para ``dst``; usa cópia se estiverem em sistemas de arquivos diferentes."""
    try:
        if replace:
            os.replace(src, dst)
        else:
            os.rename(src, dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    # Destino é um ponto de montagem diferente dentro da pasta de destino.
    if replace:
        tmp = free_name(dst.with_name(dst.name + ".descompactador-tmp"))
        shutil.move(src, tmp)
        os.replace(tmp, dst)
    else:
        shutil.move(src, dst)


class Merger:
    """Mescla áreas temporárias no destino, lembrando a política "aplicar a todos"."""

    def __init__(
        self,
        dest: Path,
        ask: AskCallback,
        cancel: threading.Event | None = None,
        policy: Action | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.dest = Path(dest)
        self.ask = ask
        self.cancel = cancel or threading.Event()
        self.policy = policy
        self.log = log or (lambda msg: None)

    def merge(self, staging: Path, source: str) -> MergeStats:
        stats = MergeStats()
        self._merge_dir(Path(staging), self.dest, Path(), source, stats)
        return stats

    def _merge_dir(self, src_dir: Path, dst_dir: Path, rel: Path, source: str, stats: MergeStats) -> None:
        with os.scandir(src_dir) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            if self.cancel.is_set():
                raise Cancelled()
            src = Path(entry.path)
            dst = dst_dir / entry.name
            rel_path = rel / entry.name
            src_is_dir = entry.is_dir(follow_symlinks=False)
            try:
                dst_st = os.lstat(dst)
            except FileNotFoundError:
                stats.added += _count_files(src)
                _move(src, dst)
                continue

            dst_is_dir = stat.S_ISDIR(dst_st.st_mode)
            if src_is_dir and dst_is_dir:
                self._merge_dir(src, dst, rel_path, source, stats)
                continue

            if (not src_is_dir and not dst_is_dir and entry.is_file(follow_symlinks=False)
                    and stat.S_ISREG(dst_st.st_mode)
                    and entry.stat(follow_symlinks=False).st_size == dst_st.st_size
                    and same_content(src, dst)):
                stats.identical += 1
                continue

            conflict = Conflict(rel_path, dst, src, source, dst_is_dir, src_is_dir)
            self._resolve(conflict, stats)

    def _decide(self, conflict: Conflict) -> Action:
        if self.policy is not None:
            return self.policy
        resolution = self.ask(conflict)
        if resolution.apply_to_all:
            self.policy = resolution.action
        return resolution.action

    def _resolve(self, conflict: Conflict, stats: MergeStats) -> None:
        action = self._decide(conflict)
        src, dst = conflict.incoming, conflict.existing

        if conflict.type_mismatch and action in (Action.OVERWRITE, Action.KEEP_NEWER):
            # Nunca substitui uma pasta por um arquivo (nem o contrário).
            action = Action.RENAME

        if action is Action.KEEP_NEWER:
            newer = os.lstat(src).st_mtime > os.lstat(dst).st_mtime
            action = Action.OVERWRITE if newer else Action.SKIP

        if action is Action.SKIP:
            stats.skipped += _count_files(src)
            self.log(f"Pulado (já existe): {conflict.rel_path}")
        elif action is Action.OVERWRITE:
            _move(src, dst, replace=True)
            stats.overwritten += 1
            self.log(f"Sobrescrito: {conflict.rel_path}")
        elif action is Action.RENAME:
            new_dst = free_name(dst, is_dir=conflict.incoming_is_dir)
            _move(src, new_dst)
            stats.renamed += _count_files(new_dst)
            self.log(f"Renomeado: {conflict.rel_path} -> {new_dst.name}")
