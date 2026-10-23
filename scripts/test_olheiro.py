import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import olheiro  # noqa: E402
import olheiro_estados  # noqa: E402


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

    def test_janela_estadual_acima_do_maior_publicado(self):
        ce = olheiro_estados.argumentos("CE", ["estaduais/CE/leis-ordinarias/1974/lei-9853-1974-id9535.md",
                                              "estaduais/CE/leis-ordinarias/2026/lei-19000-2026-id12990.md"])
        self.assertEqual(ce[0], "ce.py")
        self.assertTrue(ce[1].startswith("12991,") and ce[1].endswith(str(12990 + olheiro_estados.JANELA)))
        ma = olheiro_estados.argumentos("MA", ["estaduais/MA/leis-ordinarias/2026/lei-13400-2026.md",
                                              "estaduais/MA/leis-complementares/2026/lc-280-2026.md"])[1].split(",")
        self.assertIn("LEI_13401", ma)
        self.assertIn("LC_281", ma)
        self.assertIn("EC_1", ma)  # nenhum EC publicado: janela começa do 1
        self.assertNotIn("LEI_13400", ma)


if __name__ == "__main__":
    unittest.main()
