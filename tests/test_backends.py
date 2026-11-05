import os
import tempfile
import threading
import unittest
from pathlib import Path

from descompactador.backends import (
    SevenZipBackend, TarBackend, Tools, UnarBackend, candidates, looks_like_rar, looks_like_tar,
)
from descompactador.errors import Cancelled, UnsupportedFormat, WrongPassword

from .helpers import (
    SEVENZIP, UNAR, make_7z, make_split_zip, make_tar, make_tree, make_zip, read_tree,
    requires_7z, requires_unar, requires_zip,
)

FILES = {
    "Fotos/a.txt": "conteúdo A",
    "Fotos/sub/ç ã é.txt": "acentos",
    "Fotos/grande.bin": os.urandom(200_000),
}


class BackendTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.src = make_tree(self.root / "src", FILES)
        self.out = self.root / "out"
        self.out.mkdir()
        self.cancel = threading.Event()
        self.progress = []
        self.logs = []

    def tearDown(self):
        self._tmp.cleanup()

    def extract(self, backend, archive, password=None):
        backend.extract(archive, self.out, password, self.progress.append, self.logs.append, self.cancel)

    def assertExtracted(self):
        self.assertEqual(read_tree(self.out), read_tree(self.src))


class TarBackendTest(BackendTestBase):
    def test_tar_gz(self):
        archive = make_tar(self.root / "a.tar.gz", self.src, "w:gz")
        self.extract(TarBackend(), archive)
        self.assertExtracted()
        self.assertAlmostEqual(self.progress[-1], 1.0)

    def test_tar_zst(self):
        archive = make_tar(self.root / "a.tar.zst", self.src, "w:zst")
        self.extract(TarBackend(), archive)
        self.assertExtracted()

    def test_membro_inseguro_e_ignorado(self):
        import io
        import tarfile
        archive = self.root / "mau.tar"
        with tarfile.open(archive, "w") as tf:
            data = b"pwned"
            info = tarfile.TarInfo("../fora.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            info = tarfile.TarInfo("ok.txt")
            info.size = 2
            tf.addfile(info, io.BytesIO(b"ok"))
        self.extract(TarBackend(), archive)
        self.assertFalse((self.root / "fora.txt").exists())
        self.assertEqual((self.out / "ok.txt").read_text(), "ok")
        self.assertTrue(any("../fora.txt" in msg for msg in self.logs))


@requires_7z
class SevenZipBackendTest(BackendTestBase):
    def backend(self):
        return SevenZipBackend(SEVENZIP)

    def test_zip(self):
        archive = make_zip(self.root / "a.zip", self.src)
        self.assertFalse(self.backend().probe(archive, self.cancel))
        self.extract(self.backend(), archive)
        self.assertExtracted()

    def test_7z_com_progresso(self):
        archive = make_7z(self.root / "a.7z", self.src)
        self.extract(self.backend(), archive)
        self.assertExtracted()

    def test_7z_dividido(self):
        make_7z(self.root / "d.7z", self.src, volume="64k")
        first = self.root / "d.7z.001"
        self.assertTrue((self.root / "d.7z.002").exists())
        self.extract(self.backend(), first)
        self.assertExtracted()

    @requires_zip
    def test_zip_dividido(self):
        archive = make_split_zip(self.root / "s.zip", self.src)
        self.assertTrue((self.root / "s.z01").exists())
        self.extract(self.backend(), archive)
        self.assertExtracted()

    def test_zip_com_senha(self):
        archive = make_7z(self.root / "p.zip", self.src, password="segredo", fmt="zip")
        self.assertTrue(self.backend().probe(archive, self.cancel))
        with self.assertRaises(WrongPassword):
            self.extract(self.backend(), archive, "errada")
        with self.assertRaises(WrongPassword):
            self.extract(self.backend(), archive, None)

    def test_zip_com_senha_correta(self):
        archive = make_7z(self.root / "p.zip", self.src, password="segredo", fmt="zip")
        self.extract(self.backend(), archive, "segredo")
        self.assertExtracted()

    def test_7z_cabecalho_criptografado(self):
        archive = make_7z(self.root / "h.7z", self.src, password="segredo", header_encrypt=True)
        self.assertTrue(self.backend().probe(archive, self.cancel))
        with self.assertRaises(WrongPassword):
            self.extract(self.backend(), archive, "errada")
        self.extract(self.backend(), archive, "segredo")
        self.assertExtracted()

    def test_formato_desconhecido(self):
        archive = self.root / "lixo.rar"
        archive.write_bytes(os.urandom(500))
        with self.assertRaises(UnsupportedFormat):
            self.backend().probe(archive, self.cancel)

    def test_cancelamento(self):
        archive = make_7z(self.root / "a.7z", self.src)
        self.cancel.set()
        with self.assertRaises(Cancelled):
            self.extract(self.backend(), archive)


@requires_unar
class UnarBackendTest(BackendTestBase):
    def backend(self):
        return UnarBackend(UNAR, Tools.detect().lsar)

    def test_zip_via_unar(self):
        archive = make_zip(self.root / "a.zip", self.src)
        backend = self.backend()
        self.assertFalse(backend.probe(archive, self.cancel))
        self.extract(backend, archive)
        self.assertExtracted()
        self.assertAlmostEqual(self.progress[-1], 1.0)

    @requires_7z
    def test_senha_via_unar(self):
        archive = make_7z(self.root / "p.zip", self.src, password="segredo", fmt="zip")
        backend = self.backend()
        self.assertTrue(backend.probe(archive, self.cancel))
        with self.assertRaises(WrongPassword):
            self.extract(backend, archive, "errada")
        for p in self.out.iterdir():
            import shutil
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        self.extract(backend, archive, "segredo")
        self.assertExtracted()

    def test_formato_desconhecido(self):
        archive = self.root / "lixo.bin"
        archive.write_bytes(os.urandom(500))
        with self.assertRaises(UnsupportedFormat):
            self.backend().probe(archive, self.cancel)


class SelecaoDeBackendTest(unittest.TestCase):
    def test_reconhecimento_por_nome(self):
        self.assertTrue(looks_like_tar(Path("x.tar.zst")))
        self.assertTrue(looks_like_tar(Path("x.tgz")))
        self.assertTrue(looks_like_rar(Path("x.part2.rar")))
        self.assertTrue(looks_like_rar(Path("x.r00")))

    def test_ordem(self):
        tools = Tools(sevenzip="/bin/7z", unar="/bin/unar", lsar="/bin/lsar")
        names = lambda p: [b.name for b in candidates(Path(p), tools)]
        self.assertEqual(names("/nao/existe/a.rar"), ["unar", "7z"])
        self.assertEqual(names("/nao/existe/a.zip"), ["7z", "unar"])
        self.assertEqual(names("/nao/existe/a.tar.xz"), ["tar"])


if __name__ == "__main__":
    unittest.main()
