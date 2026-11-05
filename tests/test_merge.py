import os
import tempfile
import threading
import unittest
from pathlib import Path

from descompactador.errors import Cancelled
from descompactador.merge import Action, Merger, Resolution, free_name


def write(path: Path, data: str, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class ScriptedAsk:
    """Responde aos conflitos com uma lista de resoluções e guarda o que foi perguntado."""

    def __init__(self, *resolutions: Resolution):
        self.resolutions = list(resolutions)
        self.asked = []

    def __call__(self, conflict):
        self.asked.append(conflict)
        return self.resolutions.pop(0)


class MergeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.dest = root / "dest"
        self.stage = root / "stage"
        self.dest.mkdir()
        self.stage.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def merge(self, ask=None, policy=None, cancel=None):
        ask = ask or ScriptedAsk()
        merger = Merger(self.dest, ask, cancel=cancel, policy=policy)
        return merger.merge(self.stage, "teste.zip"), ask

    def test_move_tudo_quando_destino_vazio(self):
        write(self.stage / "Fotos" / "a.jpg", "A")
        write(self.stage / "Fotos" / "sub" / "b.jpg", "B")
        write(self.stage / "solto.txt", "S")
        stats, ask = self.merge()
        self.assertEqual((self.dest / "Fotos" / "sub" / "b.jpg").read_text(), "B")
        self.assertEqual((self.dest / "solto.txt").read_text(), "S")
        self.assertEqual(stats.added, 3)
        self.assertEqual(ask.asked, [])

    def test_mescla_pasta_existente_sem_conflito(self):
        write(self.dest / "Fotos" / "velha.jpg", "V")
        write(self.stage / "Fotos" / "nova.jpg", "N")
        stats, ask = self.merge()
        self.assertEqual(sorted(p.name for p in (self.dest / "Fotos").iterdir()), ["nova.jpg", "velha.jpg"])
        self.assertEqual(stats.added, 1)
        self.assertEqual(ask.asked, [])

    def test_identicos_sao_pulados_sem_perguntar(self):
        write(self.dest / "Fotos" / "a.jpg", "MESMO")
        write(self.stage / "Fotos" / "a.jpg", "MESMO")
        stats, ask = self.merge()
        self.assertEqual(stats.identical, 1)
        self.assertEqual(ask.asked, [])

    def test_sobrescrever(self):
        write(self.dest / "a.txt", "velho")
        write(self.stage / "a.txt", "novo!")
        stats, ask = self.merge(ScriptedAsk(Resolution(Action.OVERWRITE)))
        self.assertEqual((self.dest / "a.txt").read_text(), "novo!")
        self.assertEqual(stats.overwritten, 1)
        self.assertEqual(ask.asked[0].rel_path, Path("a.txt"))
        self.assertEqual(ask.asked[0].source, "teste.zip")

    def test_pular(self):
        write(self.dest / "a.txt", "velho")
        write(self.stage / "a.txt", "novo!")
        stats, _ = self.merge(ScriptedAsk(Resolution(Action.SKIP)))
        self.assertEqual((self.dest / "a.txt").read_text(), "velho")
        self.assertEqual(stats.skipped, 1)

    def test_renomear_em_sequencia(self):
        write(self.dest / "a.txt", "0")
        write(self.dest / "a (1).txt", "1")
        write(self.stage / "a.txt", "2")
        stats, _ = self.merge(ScriptedAsk(Resolution(Action.RENAME)))
        self.assertEqual((self.dest / "a (2).txt").read_text(), "2")
        self.assertEqual((self.dest / "a.txt").read_text(), "0")
        self.assertEqual(stats.renamed, 1)

    def test_manter_mais_novo(self):
        write(self.dest / "novo_no_destino.txt", "destino", mtime=2_000_000_000)
        write(self.stage / "novo_no_destino.txt", "arquivo", mtime=1_000_000_000)
        write(self.dest / "velho_no_destino.txt", "destino", mtime=1_000_000_000)
        write(self.stage / "velho_no_destino.txt", "arquivo", mtime=2_000_000_000)
        stats, ask = self.merge(ScriptedAsk(Resolution(Action.KEEP_NEWER, apply_to_all=True)))
        self.assertEqual((self.dest / "novo_no_destino.txt").read_text(), "destino")
        self.assertEqual((self.dest / "velho_no_destino.txt").read_text(), "arquivo")
        self.assertEqual(len(ask.asked), 1)
        self.assertEqual((stats.overwritten, stats.skipped), (1, 1))

    def test_aplicar_a_todos_vale_para_proximas_mesclagens(self):
        write(self.dest / "a.txt", "1")
        write(self.dest / "b.txt", "1")
        write(self.stage / "a.txt", "22")
        write(self.stage / "b.txt", "22")
        ask = ScriptedAsk(Resolution(Action.OVERWRITE, apply_to_all=True))
        merger = Merger(self.dest, ask)
        merger.merge(self.stage, "um.zip")
        self.assertEqual(len(ask.asked), 1)
        self.assertEqual((self.dest / "b.txt").read_text(), "22")
        # Segunda mesclagem (outro arquivo compactado do mesmo lote): não pergunta de novo.
        write(self.stage / "a.txt", "333")
        merger.merge(self.stage, "dois.zip")
        self.assertEqual(len(ask.asked), 1)
        self.assertEqual((self.dest / "a.txt").read_text(), "333")

    def test_politica_fixa_nao_pergunta(self):
        write(self.dest / "a.txt", "1")
        write(self.stage / "a.txt", "22")
        stats, ask = self.merge(policy=Action.RENAME)
        self.assertEqual(ask.asked, [])
        self.assertTrue((self.dest / "a (1).txt").exists())

    def test_tipos_diferentes_sobrescrever_vira_renomear(self):
        write(self.dest / "coisa" / "dentro.txt", "pasta existente")
        write(self.stage / "coisa", "agora sou arquivo")
        stats, ask = self.merge(ScriptedAsk(Resolution(Action.OVERWRITE)))
        self.assertTrue(ask.asked[0].type_mismatch)
        self.assertEqual((self.dest / "coisa" / "dentro.txt").read_text(), "pasta existente")
        self.assertEqual((self.dest / "coisa (1)").read_text(), "agora sou arquivo")

    def test_pasta_renomeada_mantem_nome_com_ponto(self):
        write(self.dest / "Album.2024", "sou arquivo")
        write(self.stage / "Album.2024" / "f.jpg", "F")
        self.merge(ScriptedAsk(Resolution(Action.RENAME)))
        self.assertEqual((self.dest / "Album.2024 (1)" / "f.jpg").read_text(), "F")

    def test_symlink_no_destino_nao_e_seguido(self):
        fora = Path(self._tmp.name) / "fora"
        fora.mkdir()
        os.symlink(fora, self.dest / "Fotos")
        write(self.stage / "Fotos" / "a.jpg", "A")
        stats, ask = self.merge(ScriptedAsk(Resolution(Action.OVERWRITE)))
        self.assertEqual(list(fora.iterdir()), [])  # nada escrito através do link
        self.assertTrue((self.dest / "Fotos").is_symlink())
        self.assertEqual((self.dest / "Fotos (1)" / "a.jpg").read_text(), "A")

    def test_cancelamento(self):
        write(self.stage / "a.txt", "A")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.merge(cancel=cancel)


class FreeNameTest(unittest.TestCase):
    def test_formatos(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertEqual(free_name(d / "foto.jpg").name, "foto (1).jpg")
            self.assertEqual(free_name(d / ".bashrc").name, ".bashrc (1)")
            self.assertEqual(free_name(d / "Pasta.v2", is_dir=True).name, "Pasta.v2 (1)")


if __name__ == "__main__":
    unittest.main()
