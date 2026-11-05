"""Diálogos de conflito de arquivo e de senha."""

from __future__ import annotations

import html
import os
import stat
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ..merge import Action, Conflict, Resolution


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""


def describe(path: Path) -> tuple[str, float | None]:
    """Descrição curta de um item e seu mtime (None para pastas/links)."""
    try:
        st = os.lstat(path)
    except OSError:
        return "inacessível", None
    if stat.S_ISDIR(st.st_mode):
        return "pasta", None
    if stat.S_ISLNK(st.st_mode):
        return f"link simbólico → {os.readlink(path)}", None
    date = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
    return f"{human_size(st.st_size)}, modificado em {date}", st.st_mtime


class ConflictDialog(QDialog):
    """Pergunta o que fazer com um item que já existe no destino."""

    def __init__(self, conflict: Conflict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Arquivo já existe")
        self.resolution: Resolution | None = None

        title = QLabel(f"<b>{html.escape(str(conflict.rel_path))}</b> já existe no destino.")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        existing, existing_mtime = describe(conflict.existing)
        incoming, incoming_mtime = describe(conflict.incoming)
        if existing_mtime is not None and incoming_mtime is not None and existing_mtime != incoming_mtime:
            if incoming_mtime > existing_mtime:
                incoming += "  (mais novo)"
            else:
                existing += "  (mais novo)"

        grid = QGridLayout()
        grid.addWidget(QLabel("Existente:"), 0, 0)
        grid.addWidget(QLabel(existing), 0, 1)
        grid.addWidget(QLabel(f"Novo (de {html.escape(conflict.source)}):"), 1, 0)
        grid.addWidget(QLabel(incoming), 1, 1)
        grid.setColumnStretch(1, 1)

        self.apply_all = QCheckBox("Aplicar a todos os conflitos restantes")

        buttons = QHBoxLayout()
        for label, action, icon in (
            ("Sobrescrever", Action.OVERWRITE, "document-save"),
            ("Manter o mais novo", Action.KEEP_NEWER, "view-calendar-day"),
            ("Renomear", Action.RENAME, "edit-rename"),
            ("Pular", Action.SKIP, "go-next-skip"),
        ):
            button = QPushButton(QIcon.fromTheme(icon), label)
            button.clicked.connect(lambda _=False, a=action: self._choose(a))
            if conflict.type_mismatch and action in (Action.OVERWRITE, Action.KEEP_NEWER):
                button.setEnabled(False)
            if action is Action.RENAME:
                button.setDefault(True)
            buttons.addWidget(button)
        buttons.addStretch()
        cancel = QPushButton(QIcon.fromTheme("dialog-cancel"), "Cancelar tudo")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(grid)
        if conflict.type_mismatch:
            note = QLabel("Um deles é pasta e o outro não: o item novo só pode ser renomeado ou pulado.")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addWidget(self.apply_all)
        layout.addLayout(buttons)

    def _choose(self, action: Action) -> None:
        self.resolution = Resolution(action, self.apply_all.isChecked())
        self.accept()


class PasswordDialog(QDialog):
    """Pede a senha de um arquivo protegido. ``choice`` fica em 'ok', 'skip' ou 'cancel'."""

    def __init__(self, archive_name: str, error: str | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Senha necessária")
        self.choice = "cancel"

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{html.escape(archive_name)}</b> está protegido por senha."))
        if error:
            warn = QLabel(f"{html.escape(error)}. Tente novamente.")
            warn.setStyleSheet("color: #d9534f;")
            layout.addWidget(warn)

        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setPlaceholderText("Senha")
        layout.addWidget(self.field)

        show = QCheckBox("Mostrar senha")
        show.toggled.connect(lambda on: self.field.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        layout.addWidget(show)

        buttons = QHBoxLayout()
        ok = QPushButton(QIcon.fromTheme("archive-extract"), "Extrair")
        ok.setDefault(True)
        ok.setEnabled(False)
        self.field.textChanged.connect(lambda text: ok.setEnabled(bool(text)))
        ok.clicked.connect(lambda: self._finish("ok"))
        skip = QPushButton(QIcon.fromTheme("go-next-skip"), "Pular este arquivo")
        skip.clicked.connect(lambda: self._finish("skip"))
        cancel = QPushButton(QIcon.fromTheme("dialog-cancel"), "Cancelar tudo")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(skip)
        buttons.addStretch()
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.resize(420, self.sizeHint().height())

    @property
    def password(self) -> str:
        return self.field.text()

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()
