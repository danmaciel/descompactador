import tempfile
import unittest
from pathlib import Path

from descompactador.volumes import group_archives


class GroupArchivesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def touch(self, *names):
        for name in names:
            (self.dir / name).write_bytes(b"x")
        return [self.dir / n for n in names]

    def test_arquivos_simples_viram_um_conjunto_cada(self):
        paths = self.touch("a.zip", "b.7z", "c.tar.gz")
        sets = group_archives(paths)
        self.assertEqual([s.first.name for s in sets], ["a.zip", "b.7z", "c.tar.gz"])
        self.assertTrue(all(not s.is_multivolume for s in sets))

    def test_rar_partN_agrupa_e_escolhe_part1(self):
        paths = self.touch("x.part1.rar", "x.part2.rar", "x.part3.rar")
        sets = group_archives([paths[2], paths[0]])
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].first.name, "x.part1.rar")
        self.assertEqual(len(sets[0].volumes), 3)
        self.assertFalse(sets[0].missing_first)
        self.assertEqual(sets[0].display_name, "x.part1.rar (+2 volumes)")

    def test_rar_part01_com_zeros(self):
        self.touch("y.part01.rar", "y.part02.rar")
        sets = group_archives([self.dir / "y.part02.rar"])
        self.assertEqual(sets[0].first.name, "y.part01.rar")

    def test_rar_part_sem_volume_inicial(self):
        self.touch("z.part2.rar", "z.part3.rar")
        sets = group_archives([self.dir / "z.part3.rar"])
        self.assertTrue(sets[0].missing_first)

    def test_numerado_001(self):
        self.touch("d.7z.001", "d.7z.002", "d.7z.003")
        sets = group_archives([self.dir / "d.7z.002", self.dir / "d.7z.003"])
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].first.name, "d.7z.001")
        self.assertEqual(len(sets[0].volumes), 3)

    def test_numerado_sem_001(self):
        self.touch("e.zip.002")
        sets = group_archives([self.dir / "e.zip.002"])
        self.assertTrue(sets[0].missing_first)

    def test_rar_antigo_r00(self):
        self.touch("f.rar", "f.r00", "f.r01")
        sets = group_archives([self.dir / "f.r01", self.dir / "f.rar"])
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].first.name, "f.rar")
        self.assertEqual(len(sets[0].volumes), 3)

    def test_r00_sem_rar_principal(self):
        self.touch("g.r00", "g.r01")
        sets = group_archives([self.dir / "g.r00"])
        self.assertTrue(sets[0].missing_first)

    def test_zip_dividido(self):
        self.touch("h.zip", "h.z01", "h.z02")
        sets = group_archives([self.dir / "h.z02", self.dir / "h.z01", self.dir / "h.zip"])
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].first.name, "h.zip")
        self.assertEqual(len(sets[0].volumes), 3)

    def test_rar_unico_sem_partes(self):
        self.touch("i.rar")
        sets = group_archives([self.dir / "i.rar"])
        self.assertEqual(sets[0].volumes, [self.dir / "i.rar"])

    def test_maiusculas(self):
        self.touch("J.PART1.RAR", "J.PART2.RAR")
        sets = group_archives([self.dir / "J.PART2.RAR"])
        self.assertEqual(sets[0].first.name, "J.PART1.RAR")

    def test_ordem_preservada_e_sem_duplicatas(self):
        self.touch("b.zip", "a.zip")
        sets = group_archives([self.dir / "b.zip", self.dir / "a.zip", self.dir / "b.zip"])
        self.assertEqual([s.first.name for s in sets], ["b.zip", "a.zip"])


if __name__ == "__main__":
    unittest.main()
