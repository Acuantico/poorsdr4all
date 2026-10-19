"""El alto mínimo de la cascada debe poder ser bajo (pantallas bajas) y coherente en todos los sitios."""
import os
import unittest
from unittest import mock

from poorsdr.viewers import waterfall


class AltoMinimoTests(unittest.TestCase):
    def test_minimo_a_escala_uno(self):
        self.assertEqual(waterfall.min_window_size(1.0), (520, 110))

    def test_el_minimo_nunca_supera_los_220_antiguos(self):
        self.assertLess(waterfall.min_window_size(1.0)[1], 220)

    def test_minimo_escala_con_la_pantalla_pero_con_suelo(self):
        self.assertEqual(waterfall.min_window_size(0.5), (260, 90))
        self.assertEqual(waterfall.min_window_size(0.1), (220, 90))

    def test_una_geometria_guardada_baja_se_respeta(self):
        with mock.patch.dict(os.environ, {"OWRX_FORCE_GEOMETRY": "900x130+0+0"}):
            self.assertEqual(waterfall.parse_geometry(1, 1)[:2], (900, 130))

    def test_una_geometria_mas_baja_que_el_minimo_se_sube_al_minimo(self):
        with mock.patch.dict(os.environ, {"OWRX_FORCE_GEOMETRY": "900x50+0+0"}):
            self.assertEqual(waterfall.parse_geometry(1, 1)[:2], (900, 110))


if __name__ == "__main__":
    unittest.main()
