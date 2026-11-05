"""Janela principal: lista de arquivos, destino, política de conflito e progresso."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engine import JobResult, Status, summarize
from ..merge import Action, Conflict
from ..volumes import ArchiveSet, group_archives
from .dialogs import ConflictDialog, PasswordDialog, human_size
from .worker import ExtractWorker

FILE_FILTER = (
    "Arquivos compactados (*.zip *.7z *.rar *.tar *.tar.* *.tgz *.tbz *.tbz2 *.txz *.tzst "
    "*.gz *.bz2 *.xz *.zst *.lzma *.iso *.cab *.001 *.r[0-9][0-9] *.z[0-9][0-9]);;"
    "Todos os arquivos (*)"
)

POLICIES = [
    ("Perguntar", None),
    ("Sobrescrever", Action.OVERWRITE),
    ("Manter o mais novo", Action.KEEP_NEWER),
    ("Renomear o novo", Action.RENAME),
    ("Pular o novo", Action.SKIP),
]

COL_NAME, COL_SIZE, COL_STATUS = range(3)
_STATUS_COLORS = {Status.OK: "#2e7d32", Status.ERROR: "#c62828"}


def _job_status_text(result: JobResult) -> str:
    if result.status is Status.OK:
        s = result.stats
        parts = [f"{s.added} novo(s)"]
        if s.overwritten:
            parts.append(f"{s.overwritten} sobrescrito(s)")
        if s.renamed:
            parts.append(f"{s.renamed} renomeado(s)")
        if s.skipped:
            parts.append(f"{s.skipped} pulado(s)")
        if s.identical:
            parts.append(f"{s.identical} idêntico(s)")
        return "OK: " + ", ".join(parts)
    if result.status is Status.ERROR:
        return f"Erro: {result.message}"
    return result.message


class MainWindow(QMainWindow):
    def __init__(self, initial_files: list[str]) -> None:
        super().__init__()
        self.setWindowTitle("Descompactador")
        self.setAcceptDrops(True)
        self.resize(760, 520)

        self.archives: list[ArchiveSet] = []
        self.worker: ExtractWorker | None = None
        self.known_passwords: list[str] = []
        self._dest_from_user = False

        # Lista de arquivos
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Arquivo", "Tamanho", "Situação"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.tree.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_STATUS, 260)
        header.setStretchLastSection(False)

        self.add_btn = QPushButton(QIcon.fromTheme("list-add"), "Adicionar…")
        self.add_btn.clicked.connect(self.choose_files)
        self.remove_btn = QPushButton(QIcon.fromTheme("list-remove"), "Remover")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton(QIcon.fromTheme("edit-clear-list"), "Limpar")
        self.clear_btn.clicked.connect(self.clear)
        list_buttons = QHBoxLayout()
        for b in (self.add_btn, self.remove_btn, self.clear_btn):
            list_buttons.addWidget(b)
        list_buttons.addStretch()
        list_buttons.addWidget(QLabel("Arraste arquivos para cá"))

        # Destino e política
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Pasta onde tudo será extraído")
        self.dest_edit.textEdited.connect(self._on_dest_edited)
        self.dest_btn = QPushButton(QIcon.fromTheme("folder-open"), "Escolher…")
        self.dest_btn.clicked.connect(self.choose_dest)
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Destino:"))
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(self.dest_btn)

        self.policy_combo = QComboBox()
        for label, action in POLICIES:
            self.policy_combo.addItem(label, action)
        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("Se um arquivo já existir:"))
        policy_row.addWidget(self.policy_combo)
        policy_row.addStretch()

        # Progresso e log
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("")
        self.status_label = QLabel("Adicione os arquivos compactados.")

        self.log_toggle = QToolButton()
        self.log_toggle.setText("Detalhes")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.toggled.connect(self._toggle_log)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setVisible(False)

        self.extract_btn = QPushButton(QIcon.fromTheme("archive-extract"), "Extrair")
        self.extract_btn.setDefault(True)
        self.extract_btn.clicked.connect(self._on_extract_clicked)
        close_btn = QPushButton(QIcon.fromTheme("window-close"), "Fechar")
        close_btn.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(self.log_toggle)
        bottom.addStretch()
        bottom.addWidget(self.extract_btn)
        bottom.addWidget(close_btn)

        layout = QVBoxLayout()
        layout.addWidget(self.tree, 3)
        layout.addLayout(list_buttons)
        layout.addLayout(dest_row)
        layout.addLayout(policy_row)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        layout.addWidget(self.log_view, 2)
        layout.addLayout(bottom)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self._editing_widgets = [self.add_btn, self.remove_btn, self.clear_btn, self.dest_edit,
                                 self.dest_btn, self.policy_combo]
        if initial_files:
            self.add_files(initial_files)
        self._update_buttons()

    # ---- lista de arquivos ----------------------------------------------------------

    def add_files(self, paths: list[str | Path]) -> None:
        files = [Path(p) for p in paths if Path(p).is_file()]
        if not files:
            return
        # Reagrupa tudo: uma parte nova de um conjunto já listado não vira item novo.
        self.archives = group_archives([a.first for a in self.archives] + files)
        self._rebuild_tree()
        if not self._dest_from_user and self.archives:
            self.dest_edit.setText(str(self.archives[0].first.parent))

    def _rebuild_tree(self) -> None:
        self.tree.clear()
        for archive in self.archives:
            item = QTreeWidgetItem([archive.display_name, human_size(archive.total_size), "Aguardando"])
            item.setIcon(COL_NAME, QIcon.fromTheme("application-x-archive"))
            item.setToolTip(COL_NAME, "\n".join(str(v) for v in archive.volumes))
            item.setData(COL_NAME, Qt.ItemDataRole.UserRole, archive)
            if archive.missing_first:
                item.setText(COL_STATUS, "Volume inicial ausente")
                item.setForeground(COL_STATUS, QBrush(QColor(_STATUS_COLORS[Status.ERROR])))
            self.tree.addTopLevelItem(item)
        self._update_buttons()

    def choose_files(self) -> None:
        start = self.dest_edit.text() or str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(self, "Escolher arquivos compactados", start, FILE_FILTER)
        self.add_files(files)

    def remove_selected(self) -> None:
        selected = {id(item.data(COL_NAME, Qt.ItemDataRole.UserRole)) for item in self.tree.selectedItems()}
        self.archives = [a for a in self.archives if id(a) not in selected]
        self._rebuild_tree()

    def clear(self) -> None:
        self.archives = []
        self._rebuild_tree()
        self.progress.setValue(0)
        self.status_label.setText("Adicione os arquivos compactados.")

    def dragEnterEvent(self, event) -> None:
        if self.worker is None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.add_files([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    # ---- destino ----------------------------------------------------------------------

    def _on_dest_edited(self, text: str) -> None:
        self._dest_from_user = bool(text)

    def choose_dest(self) -> None:
        start = self.dest_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Pasta de destino", start)
        if folder:
            self.dest_edit.setText(folder)
            self._dest_from_user = True

    def _validated_dest(self) -> Path | None:
        text = self.dest_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "Destino", "Escolha a pasta de destino.")
            return None
        dest = Path(os.path.expanduser(text))
        if dest.exists() and not dest.is_dir():
            QMessageBox.warning(self, "Destino", f"{dest} não é uma pasta.")
            return None
        if not dest.exists():
            answer = QMessageBox.question(self, "Destino", f"A pasta {dest} não existe. Criar?")
            if answer != QMessageBox.StandardButton.Yes:
                return None
        elif not os.access(dest, os.W_OK | os.X_OK):
            QMessageBox.warning(self, "Destino", f"Sem permissão de escrita em {dest}.")
            return None
        return dest

    # ---- extração ---------------------------------------------------------------------

    def _on_extract_clicked(self) -> None:
        if self.worker is not None:
            self.worker.request_cancel()
            self.extract_btn.setEnabled(False)
            self.status_label.setText("Cancelando…")
            return
        runnable = [a for a in self.archives if not a.missing_first]
        if not runnable:
            return
        dest = self._validated_dest()
        if dest is None:
            return

        self.log_view.clear()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if not item.data(COL_NAME, Qt.ItemDataRole.UserRole).missing_first:
                item.setText(COL_STATUS, "Aguardando")
                item.setForeground(COL_STATUS, QBrush())
        self._runnable = runnable
        self.worker = ExtractWorker(runnable, dest, self.policy_combo.currentData(), self.known_passwords, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._append_log)
        self.worker.job_done.connect(self._on_job_done)
        self.worker.conflict_requested.connect(self._ask_conflict)
        self.worker.password_requested.connect(self._ask_password)
        self.worker.finished.connect(self._on_finished)
        self._set_running(True)
        self._append_log(f"Destino: {dest}")
        self.worker.start()

    def _set_running(self, running: bool) -> None:
        for w in self._editing_widgets:
            w.setEnabled(not running)
        self.extract_btn.setEnabled(True)
        self.extract_btn.setText("Cancelar" if running else "Extrair")
        self.extract_btn.setIcon(QIcon.fromTheme("process-stop" if running else "archive-extract"))
        self.progress.setFormat("%p%" if running else "")
        self._update_buttons()

    def _item_for_job(self, index: int) -> QTreeWidgetItem | None:
        archive = self._runnable[index]
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(COL_NAME, Qt.ItemDataRole.UserRole) is archive:
                return item
        return None

    def _on_progress(self, index: int, fraction: float, message: str) -> None:
        total = len(self._runnable)
        self.progress.setValue(int((index + fraction) / total * 1000))
        name = self._runnable[index].first.name
        self.status_label.setText(f"{message} {name} ({index + 1} de {total})")
        item = self._item_for_job(index)
        if item is not None:
            text = f"{message} {fraction:.0%}" if message == "Extraindo" else f"{message}…"
            item.setText(COL_STATUS, text)

    def _on_job_done(self, index: int, result: JobResult) -> None:
        item = self._item_for_job(index)
        if item is not None:
            item.setText(COL_STATUS, _job_status_text(result))
            item.setToolTip(COL_STATUS, _job_status_text(result))
            color = _STATUS_COLORS.get(result.status)
            item.setForeground(COL_STATUS, QBrush(QColor(color)) if color else QBrush(Qt.GlobalColor.gray))

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _ask_conflict(self, conflict: Conflict) -> None:
        if self.worker is None:
            return
        dialog = ConflictDialog(conflict, self)
        dialog.exec()
        if self.worker is not None:
            self.worker.answer(dialog.resolution)

    def _ask_password(self, archive: ArchiveSet, attempt: int, error: str | None) -> None:
        if self.worker is None:
            return
        dialog = PasswordDialog(archive.first.name, error, self)
        dialog.exec()
        if self.worker is not None:
            self.worker.answer(None if dialog.choice == "cancel" else (dialog.choice, dialog.password))

    def _on_finished(self) -> None:
        worker, self.worker = self.worker, None
        self._set_running(False)
        if worker.error:
            self.status_label.setText(f"Erro: {worker.error}")
            QMessageBox.critical(self, "Erro", worker.error)
            return
        summary = summarize(worker.results)
        self.progress.setValue(1000)
        self.status_label.setText(summary.replace("\n", " "))
        self._append_log(summary)
        failed = any(r.status is Status.ERROR for r in worker.results)
        box = QMessageBox.warning if failed else QMessageBox.information
        box(self, "Concluído", summary)

    def _update_buttons(self) -> None:
        idle = self.worker is None
        has_items = bool(self.archives)
        self.remove_btn.setEnabled(idle and has_items)
        self.clear_btn.setEnabled(idle and has_items)
        if idle:
            self.extract_btn.setEnabled(any(not a.missing_first for a in self.archives))

    def _toggle_log(self, shown: bool) -> None:
        self.log_view.setVisible(shown)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            answer = QMessageBox.question(self, "Extração em andamento",
                                          "Cancelar a extração e fechar?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.request_cancel()
            self.worker.wait()
        event.accept()


def _to_path(arg: str) -> str:
    return QUrl(arg).toLocalFile() if arg.startswith("file://") else arg


def run(argv: list[str]) -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("descompactador")
    app.setApplicationDisplayName("Descompactador")
    app.setDesktopFileName("descompactador")
    app.setWindowIcon(QIcon.fromTheme("archive-extract"))
    window = MainWindow([_to_path(a) for a in argv])
    window.show()
    return app.exec()
