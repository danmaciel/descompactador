"""Teste de fumaça da janela, sem tela (QT_QPA_PLATFORM=offscreen)."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # pragma: no cover
    QApplication = None

from descompactador.merge import Action, Resolution

from .helpers import make_7z, make_tree, make_zip, read_tree, requires_7z


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
@requires_7z
class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def wait_worker(self, window, timeout=30):
        deadline = time.monotonic() + timeout
        while window.worker is not None:
            self.app.processEvents()
            time.sleep(0.01)
            self.assertLess(time.monotonic(), deadline, "extração não terminou")

    def test_extracao_completa_pela_janela(self):
        from descompactador.gui import main_window
        from descompactador.gui.dialogs import ConflictDialog, PasswordDialog

        a = make_zip(self.root / "a.zip", make_tree(self.root / "sa", {"Fotos/x.jpg": "A", "Fotos/a.jpg": "1"}))
        b = make_zip(self.root / "b.zip", make_tree(self.root / "sb", {"Fotos/x.jpg": "B", "Fotos/b.jpg": "2"}))
        c = make_7z(self.root / "c.7z", make_tree(self.root / "sc", {"Fotos/c.jpg": "3"}), password="abc")
        make_7z(self.root / "d.7z", make_tree(self.root / "sd", {"Fotos/d.jpg": "4"}), volume="1k")
        dest = self.root / "Destino"

        asked = {"conflict": 0, "password": 0}

        def fake_conflict_exec(dialog):
            asked["conflict"] += 1
            dialog.resolution = Resolution(Action.RENAME, apply_to_all=True)
            return 1

        def fake_password_exec(dialog):
            asked["password"] += 1
            dialog.field.setText("abc")
            dialog.choice = "ok"
            return 1

        with mock.patch.object(ConflictDialog, "exec", fake_conflict_exec), \
             mock.patch.object(PasswordDialog, "exec", fake_password_exec), \
             mock.patch.object(QMessageBox, "information") as info, \
             mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            window = main_window.MainWindow([str(a), str(b), str(c), str(self.root / "d.7z.001")])
            self.assertEqual(window.tree.topLevelItemCount(), 4)
            self.assertEqual(window.dest_edit.text(), str(self.root))
            window.dest_edit.setText(str(dest))
            window._on_extract_clicked()
            self.wait_worker(window)

        self.assertEqual(asked, {"conflict": 1, "password": 1})
        info.assert_called_once()
        self.assertEqual(read_tree(dest), {
            "Fotos/a.jpg": b"1", "Fotos/b.jpg": b"2", "Fotos/c.jpg": b"3", "Fotos/d.jpg": b"4",
            "Fotos/x.jpg": b"A", "Fotos/x (1).jpg": b"B",
        })
        statuses = [window.tree.topLevelItem(i).text(2) for i in range(4)]
        self.assertTrue(all(s.startswith("OK") for s in statuses), statuses)
        self.assertEqual(window.extract_btn.text(), "Extrair")
        window.close()


if __name__ == "__main__":
    unittest.main()
