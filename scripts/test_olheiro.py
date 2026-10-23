import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import olheiro  # noqa: E402


class TestOlheiro(unittest.TestCase):
    def test_citadas_por_ementa(self):
        por_numero = {("lei", "8078"): [("1990", "federal/leis-ordinarias/1990/lei-8078-1990-09-11.md")],
                      ("lcp", "101"): [("2000", "federal/leis-complementares/2000/lcp-101-2000-05-04.md")],
                      ("lei", "101"): [("1947", "federal/leis-ordinarias/1947/lei-101-1947-01-01.md")]}
        d = {"ementa": "Altera a Lei nº 8.078, de 11 de setembro de 1990, e a Lei Complementar nº 101, de 4 de maio de 2000."}
        self.assertEqual(olheiro.citadas(d, por_numero), [por_numero[("lei", "8078")][0][1], por_numero[("lcp", "101")][0][1]])
        # ano citado diferente não casa
        self.assertEqual(olheiro.citadas({"ementa": "Altera a Lei nº 8.078, de 1991."}, por_numero), [])

    def test_relevante_ignora_data_de_download_e_hashes(self):
        base = '---\ntitulo: "Lei X"\nrevogada: false\nbaixado_em: {}\nsha256_metadados_fonte: "{}"\n---\n# Lei X\n\nArt. 1º Texto.\n'
        with tempfile.TemporaryDirectory() as tmp:
            a, b, c = (os.path.join(tmp, n) for n in "abc")
            open(a, "w", encoding="utf-8").write(base.format("2026-01-01", "a" * 64))
            open(b, "w", encoding="utf-8").write(base.format("2026-10-23", "b" * 64))
            open(c, "w", encoding="utf-8").write(base.format("2026-10-23", "b" * 64).replace("Texto.", "Texto novo."))
            self.assertEqual(olheiro.relevante(a), olheiro.relevante(b))
            self.assertNotEqual(olheiro.relevante(a), olheiro.relevante(c))
            self.assertEqual(olheiro.sha_do_cabecalho(a), "a" * 64)


if __name__ == "__main__":
    unittest.main()
