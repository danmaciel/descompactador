import os
import tempfile
import threading
import unittest
from pathlib import Path

from descompactador.engine import STAGING_PREFIX, Callbacks, Engine, Status, summarize
from descompactador.errors import Cancelled
from descompactador.merge import Action, Resolution
from descompactador.volumes import group_archives

from .helpers import make_7z, make_tar, make_tree, make_zip, read_tree, requires_7z


class FakeCallbacks(Callbacks):
    def __init__(self, conflicts=(), passwords=()):
        self.conflicts = list(conflicts)
        self.passwords = list(passwords)
        self.asked_conflicts = []
        self.asked_passwords = []
        self.done = []
        self.logs = []

    def on_conflict(self, conflict):
        self.asked_conflicts.append(conflict)
        answer = self.conflicts.pop(0)
        if answer is Cancelled:
            raise Cancelled()
        return answer

    def on_password(self, archive, attempt, error):
        self.asked_passwords.append((archive.first.name, attempt, error))
        return self.passwords.pop(0)

    def on_log(self, message):
        self.logs.append(message)

    def on_job_done(self, index, result):
        self.done.append((index, result.status))


@requires_7z
class EngineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dest = self.root / "Destino"

    def tearDown(self):
        self._tmp.cleanup()

    def src(self, name, files):
        return make_tree(self.root / "src" / name, files)

    def run_engine(self, paths, callbacks, policy=None, known=None):
        engine = Engine(callbacks, known_passwords=known)
        results = engine.run(group_archives(paths), self.dest, policy)
        leftovers = [p for p in self.dest.iterdir() if p.name.startswith(STAGING_PREFIX)]
        self.assertEqual(leftovers, [], "área temporária não foi apagada")
        return results, engine

    def test_mescla_varios_formatos_na_mesma_pasta(self):
        a = make_zip(self.root / "a.zip", self.src("a", {"Fotos/1.jpg": "um", "Fotos/capa.jpg": "capa A"}))
        b = make_7z(self.root / "b.7z", self.src("b", {"Fotos/2.jpg": "dois", "Fotos/capa.jpg": "capa B"}))
        c = make_tar(self.root / "c.tar.zst", self.src("c", {"Fotos/3/x.jpg": "três", "leia.txt": "oi"}), "w:zst")
        (self.dest / "Fotos").mkdir(parents=True)
        (self.dest / "Fotos" / "ja_existia.jpg").write_text("antigo")

        cb = FakeCallbacks(conflicts=[Resolution(Action.RENAME)])
        results, _ = self.run_engine([a, b, c], cb)

        self.assertEqual([r.status for r in results], [Status.OK] * 3)
        self.assertEqual(read_tree(self.dest), {
            "Fotos/1.jpg": b"um",
            "Fotos/2.jpg": b"dois",
            "Fotos/3/x.jpg": "três".encode(),
            "Fotos/capa (1).jpg": b"capa B",
            "Fotos/capa.jpg": b"capa A",
            "Fotos/ja_existia.jpg": b"antigo",
            "leia.txt": b"oi",
        })
        self.assertEqual(len(cb.asked_conflicts), 1)
        self.assertEqual(cb.asked_conflicts[0].source, "b.7z")
        self.assertEqual(cb.done, [(0, Status.OK), (1, Status.OK), (2, Status.OK)])
        self.assertIn("1 renomeado(s)", summarize(results))

    def test_rodar_de_novo_nao_pergunta_nada(self):
        a = make_zip(self.root / "a.zip", self.src("a", {"Fotos/1.jpg": "um"}))
        self.run_engine([a], FakeCallbacks())
        results, _ = self.run_engine([a], FakeCallbacks())
        self.assertEqual(results[0].stats.identical, 1)

    def test_senha_errada_depois_certa_e_cache(self):
        files = {"Doc/segredo.txt": "x" * 1000}
        p1 = make_7z(self.root / "p1.7z", self.src("p1", files), password="abc", header_encrypt=True)
        p2 = make_7z(self.root / "p2.zip", self.src("p2", {"Doc/outro.txt": "y"}), password="abc", fmt="zip")
        cb = FakeCallbacks(passwords=["errada", "abc"])
        results, engine = self.run_engine([p1, p2], cb)

        self.assertEqual([r.status for r in results], [Status.OK, Status.OK])
        # Primeira pergunta sem erro; segunda avisa que a senha estava errada; p2 usou o cache.
        self.assertEqual(cb.asked_passwords, [("p1.7z", 0, None), ("p1.7z", 1, "Senha incorreta")])
        self.assertEqual(engine.known_passwords, ["abc"])
        self.assertEqual(sorted(read_tree(self.dest)), ["Doc/outro.txt", "Doc/segredo.txt"])

    def test_pular_arquivo_sem_senha(self):
        p = make_7z(self.root / "p.7z", self.src("p", {"a.txt": "a"}), password="abc")
        ok = make_zip(self.root / "ok.zip", self.src("ok", {"b.txt": "b"}))
        cb = FakeCallbacks(passwords=[None])
        results, _ = self.run_engine([p, ok], cb)
        self.assertEqual([r.status for r in results], [Status.SKIPPED, Status.OK])
        self.assertEqual(read_tree(self.dest), {"b.txt": b"b"})

    def test_cancelar_no_conflito_cancela_o_resto(self):
        a = make_zip(self.root / "a.zip", self.src("a", {"x.txt": "1"}))
        b = make_zip(self.root / "b.zip", self.src("b", {"x.txt": "2"}))
        c = make_zip(self.root / "c.zip", self.src("c", {"y.txt": "3"}))
        cb = FakeCallbacks(conflicts=[Cancelled])
        results, _ = self.run_engine([a, b, c], cb)
        self.assertEqual([r.status for r in results], [Status.OK, Status.CANCELLED, Status.CANCELLED])
        self.assertEqual(read_tree(self.dest), {"x.txt": b"1"})

    def test_cancelar_durante_extracao(self):
        big = self.src("big", {f"f{i}.bin": os.urandom(2_000_000) for i in range(20)})
        archive = make_7z(self.root / "big.7z", big)
        cancel = threading.Event()

        class CancelOnProgress(FakeCallbacks):
            def on_progress(self, index, fraction, message):
                if message == "Extraindo":
                    cancel.set()

        engine = Engine(CancelOnProgress(), cancel=cancel)
        results = engine.run(group_archives([archive]), self.dest)
        self.assertEqual(results[0].status, Status.CANCELLED)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_multivolume_e_erros(self):
        make_7z(self.root / "vol.7z", self.src("vol", {"v/big.bin": os.urandom(150_000)}), volume="64k")
        (self.root / "orfao.part2.rar").write_bytes(b"x")
        lixo = self.root / "lixo.zip"
        lixo.write_bytes(os.urandom(300))
        results, _ = self.run_engine(
            [self.root / "vol.7z.002", self.root / "orfao.part2.rar", lixo, self.root / "vol.7z.001"],
            FakeCallbacks(),
        )
        self.assertEqual([r.status for r in results], [Status.OK, Status.ERROR, Status.ERROR])
        self.assertEqual(results[1].message, "Volume inicial não encontrado")
        self.assertIn("Formato não reconhecido", results[2].message)
        self.assertTrue((self.dest / "v" / "big.bin").is_file())

    def test_politica_fixa(self):
        a = make_zip(self.root / "a.zip", self.src("a", {"x.txt": "1"}))
        b = make_zip(self.root / "b.zip", self.src("b", {"x.txt": "22"}))
        cb = FakeCallbacks()
        self.run_engine([a, b], cb, policy=Action.OVERWRITE)
        self.assertEqual(cb.asked_conflicts, [])
        self.assertEqual((self.dest / "x.txt").read_text(), "22")

    def test_rar_sem_unar_explica_o_que_instalar(self):
        from descompactador.backends import Tools
        fake_rar = self.root / "x.rar"
        fake_rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + os.urandom(100))
        engine = Engine(FakeCallbacks(), tools=Tools(sevenzip=Tools.detect().sevenzip, unar=None, lsar=None))
        results = engine.run(group_archives([fake_rar]), self.dest)
        self.assertEqual(results[0].status, Status.ERROR)
        self.assertIn("instale o pacote 'unar'", results[0].message)


if __name__ == "__main__":
    unittest.main()
