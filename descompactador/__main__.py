"""Ponto de entrada: ``python3 -m descompactador [arquivos...]`` abre a janela."""

import sys


def main() -> int:
    from .gui.main_window import run

    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
