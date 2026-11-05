"""Geração de arquivos compactados de teste em diretórios temporários."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import unittest
import zipfile
from pathlib import Path

SEVENZIP = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")
UNAR = shutil.which("unar")
ZIP = shutil.which("zip")

requires_7z = unittest.skipUnless(SEVENZIP, "7z não instalado")
requires_unar = unittest.skipUnless(UNAR, "unar não instalado")
requires_zip = unittest.skipUnless(ZIP, "zip não instalado")


def make_tree(root: Path, files: dict[str, str | bytes]) -> Path:
    """Cria ``root`` com os arquivos dados (caminho relativo -> conteúdo)."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
    return root


def _top_level(src: Path) -> list[str]:
    return sorted(os.listdir(src))


def make_zip(archive: Path, src: Path) -> Path:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            zf.write(path, path.relative_to(src))
    return archive


def make_tar(archive: Path, src: Path, mode: str = "w:gz") -> Path:
    with tarfile.open(archive, mode) as tf:
        for name in _top_level(src):
            tf.add(src / name, arcname=name)
    return archive


def make_7z(archive: Path, src: Path, password: str | None = None, header_encrypt: bool = False,
            volume: str | None = None, fmt: str = "7z") -> Path:
    cmd = [SEVENZIP, "a", "-bd", "-bso0", "-bsp0", f"-t{fmt}"]
    if password:
        cmd.append(f"-p{password}")
    if header_encrypt:
        cmd.append("-mhe=on")
    if volume:
        cmd.append(f"-v{volume}")
    cmd += [str(archive), *_top_level(src)]
    subprocess.run(cmd, cwd=src, check=True, stdin=subprocess.DEVNULL)
    return archive


def make_split_zip(archive: Path, src: Path, size: str = "64k") -> Path:
    subprocess.run([ZIP, "-q", "-r", "-s", size, str(archive), *_top_level(src)],
                   cwd=src, check=True, stdin=subprocess.DEVNULL)
    return archive


def read_tree(root: Path) -> dict[str, bytes]:
    """Conteúdo de todos os arquivos sob ``root`` (caminho relativo -> bytes)."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
