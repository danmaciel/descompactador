"""Agrupamento de arquivos multivolume.

Transforma a seleção do usuário numa lista de ``ArchiveSet``: cada conjunto é
uma tarefa de extração, identificada pelo volume que deve ser passado ao
extrator (``first``). Selecionar qualquer parte de um conjunto, ou todas elas,
gera um único ``ArchiveSet``.

Convenções reconhecidas:
  * ``nome.part1.rar``, ``nome.part2.rar`` ...       -> ``nome.part1.rar``
  * ``nome.rar``, ``nome.r00``, ``nome.r01`` ...     -> ``nome.rar``
  * ``nome.7z.001``, ``nome.7z.002`` ...             -> ``nome.7z.001``
  * ``nome.zip``, ``nome.z01``, ``nome.z02`` ...     -> ``nome.zip``
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_RAR_PART = re.compile(r"^(?P<base>.+)\.part(?P<num>\d+)\.rar$", re.IGNORECASE)
_NUMBERED = re.compile(r"^(?P<base>.+)\.(?P<num>\d{3})$")
_RAR_OLD = re.compile(r"^(?P<base>.+)\.r(?P<num>\d{2,3})$", re.IGNORECASE)
_ZIP_SPLIT = re.compile(r"^(?P<base>.+)\.z(?P<num>\d{2,3})$", re.IGNORECASE)
_RAR = re.compile(r"^(?P<base>.+)\.rar$", re.IGNORECASE)
_ZIP = re.compile(r"^(?P<base>.+)\.zip$", re.IGNORECASE)


@dataclass
class ArchiveSet:
    """Um arquivo compactado lógico, possivelmente dividido em volumes."""

    first: Path
    volumes: list[Path] = field(default_factory=list)
    missing_first: bool = False

    def __post_init__(self) -> None:
        if not self.volumes:
            self.volumes = [self.first]

    @property
    def is_multivolume(self) -> bool:
        return len(self.volumes) > 1

    @property
    def display_name(self) -> str:
        extra = len(self.volumes) - 1
        if self.missing_first:
            return f"{self.first.name} (volume inicial ausente)"
        if extra > 0:
            return f"{self.first.name} (+{extra} volume{'s' if extra > 1 else ''})"
        return self.first.name

    @property
    def total_size(self) -> int:
        total = 0
        for vol in self.volumes:
            try:
                total += vol.stat().st_size
            except OSError:
                pass
        return total


def _siblings(directory: Path, cache: dict[Path, list[str]]) -> list[str]:
    if directory not in cache:
        try:
            cache[directory] = [e.name for e in os.scandir(directory) if e.is_file()]
        except OSError:
            cache[directory] = []
    return cache[directory]


def _collect(directory: Path, names: list[str], pattern: re.Pattern, base: str) -> list[tuple[int, Path]]:
    """Volumes no diretório que casam com ``pattern`` e têm a mesma base."""
    found = []
    for name in names:
        m = pattern.match(name)
        if m and m.group("base").casefold() == base.casefold():
            found.append((int(m.group("num")), directory / name))
    return sorted(found)


def _find_named(directory: Path, names: list[str], wanted: str) -> Path | None:
    for name in names:
        if name.casefold() == wanted.casefold():
            return directory / name
    return None


def _classify(path: Path, cache: dict[Path, list[str]]) -> tuple[tuple, ArchiveSet]:
    """Devolve (chave do conjunto, conjunto) para um caminho selecionado."""
    directory = path.parent
    name = path.name

    m = _RAR_PART.match(name)
    if m:
        base = m.group("base")
        vols = _collect(directory, _siblings(directory, cache), _RAR_PART, base)
        if not vols:
            vols = [(int(m.group("num")), path)]
        first_num, first = vols[0]
        key = (directory, base.casefold(), "rar-part")
        return key, ArchiveSet(first, [p for _, p in vols], missing_first=first_num != 1)

    m = _NUMBERED.match(name)
    if m:
        base = m.group("base")
        vols = _collect(directory, _siblings(directory, cache), _NUMBERED, base)
        if not vols:
            vols = [(int(m.group("num")), path)]
        first_num, first = vols[0]
        key = (directory, base.casefold(), "numbered")
        return key, ArchiveSet(first, [p for _, p in vols], missing_first=first_num != 1)

    for part_re, main_re, ext, kind in (
        (_RAR_OLD, _RAR, ".rar", "rar-old"),
        (_ZIP_SPLIT, _ZIP, ".zip", "zip-split"),
    ):
        m = part_re.match(name) or main_re.match(name)
        if not m:
            continue
        base = m.group("base")
        names = _siblings(directory, cache)
        parts = [p for _, p in _collect(directory, names, part_re, base)]
        main = _find_named(directory, names, base + ext)
        if main is None and part_re.match(name):
            # Só temos as partes: o volume principal não está na pasta.
            vols = parts or [path]
            return (directory, base.casefold(), kind), ArchiveSet(vols[0], vols, missing_first=True)
        # Em zip dividido o .zip é o último volume, mas é por ele que se abre.
        main = main or path
        return (directory, base.casefold(), kind), ArchiveSet(main, [main, *parts])

    return (path,), ArchiveSet(path)


def group_archives(paths: list[Path | str]) -> list[ArchiveSet]:
    """Agrupa os caminhos em conjuntos, preservando a ordem da primeira aparição."""
    cache: dict[Path, list[str]] = {}
    groups: dict[tuple, ArchiveSet] = {}
    for raw in paths:
        path = Path(raw).absolute()
        key, archive_set = _classify(path, cache)
        if key not in groups:
            groups[key] = archive_set
    return list(groups.values())
