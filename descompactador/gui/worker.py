"""Thread que roda o motor e conversa com a GUI por sinais.

Perguntas (conflito, senha) são emitidas como sinais para a thread da GUI; a
thread de trabalho espera a resposta em um ``threading.Event``. Se a extração
for cancelada enquanto espera, a pergunta é tratada como "Cancelar tudo".
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..engine import Callbacks, Engine, JobResult
from ..errors import Cancelled
from ..merge import Action, Conflict, Resolution
from ..volumes import ArchiveSet


class _Bridge(Callbacks):
    def __init__(self, worker: ExtractWorker) -> None:
        self.worker = worker

    def on_conflict(self, conflict: Conflict) -> Resolution:
        answer = self.worker._ask(self.worker.conflict_requested, conflict)
        if answer is None:
            raise Cancelled()
        return answer

    def on_password(self, archive: ArchiveSet, attempt: int, error: str | None) -> str | None:
        answer = self.worker._ask(self.worker.password_requested, archive, attempt, error)
        if answer is None:
            raise Cancelled()
        choice, password = answer
        return password if choice == "ok" else None

    def on_progress(self, index: int, fraction: float, message: str) -> None:
        self.worker.progress.emit(index, fraction, message)

    def on_log(self, message: str) -> None:
        self.worker.log.emit(message)

    def on_job_done(self, index: int, result: JobResult) -> None:
        self.worker.job_done.emit(index, result)


class ExtractWorker(QThread):
    progress = Signal(int, float, str)
    log = Signal(str)
    job_done = Signal(int, object)
    conflict_requested = Signal(object)
    password_requested = Signal(object, int, object)

    def __init__(self, archives: list[ArchiveSet], dest: Path, policy: Action | None,
                 known_passwords: list[str], parent=None) -> None:
        super().__init__(parent)
        self.archives = archives
        self.dest = dest
        self.policy = policy
        self.known_passwords = known_passwords  # compartilhada com a janela: vale para a sessão toda
        self.cancel_event = threading.Event()
        self.results: list[JobResult] = []
        self.error: str | None = None
        self._answer = None
        self._answered = threading.Event()

    def run(self) -> None:
        engine = Engine(_Bridge(self), self.cancel_event, known_passwords=self.known_passwords)
        try:
            self.results = engine.run(self.archives, self.dest, self.policy)
        except Exception as exc:  # ex.: destino impossível de criar
            self.error = str(exc)

    def _ask(self, signal, *args):
        """Chamado na thread de trabalho: emite a pergunta e espera ``answer``."""
        self._answered.clear()
        self._answer = None
        signal.emit(*args)
        while not self._answered.wait(0.1):
            if self.cancel_event.is_set():
                return None
        return self._answer

    def answer(self, value) -> None:
        """Chamado na thread da GUI com a resposta (``None`` = cancelar tudo)."""
        self._answer = value
        self._answered.set()

    def request_cancel(self) -> None:
        self.cancel_event.set()
