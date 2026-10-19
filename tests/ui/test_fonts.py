"""Fuente LED: siempre 7LED (incluida en el paquete, sin modificar y con su readme); nunca DSEG7."""
from __future__ import annotations

import hashlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_SIN_TK = False
try:  # entornos de prueba sin Tk: aquí solo se usa la lógica de ficheros
    import tkinter.font  # noqa: F401
except ImportError:  # pragma: no cover
    _SIN_TK = True
    _tk = types.ModuleType("tkinter")
    _tk.font = types.ModuleType("tkinter.font")  # type: ignore[attr-defined]
    sys.modules.update({"tkinter": _tk, "tkinter.font": _tk.font})  # type: ignore[arg-type]

from poorsdr.ui import fonts  # noqa: E402

if _SIN_TK:  # no dejar un tkinter falso en memoria: otras pruebas comprueban si Tk existe de verdad
    sys.modules.pop("tkinter", None)
    sys.modules.pop("tkinter.font", None)

TTF_SHA256 = "5101231624f1cd19b037f1c0617f13553e6e82a648702ae945b9351d43eab6eb"  # el fichero original de dafont, sin modificar (lo exige la licencia del autor)


class FuenteLedTests(unittest.TestCase):
    def test_7led_va_primera_y_dseg_no_aparece(self):
        self.assertEqual(fonts._LED_CANDIDATES[0], "7LED")
        self.assertFalse(any("dseg" in c.lower() for c in fonts._LED_CANDIDATES))

    def test_la_fuente_esta_en_el_paquete_sin_modificar(self):
        ttf = fonts._FONTS_DIR / "7LED.ttf"
        self.assertTrue(ttf.is_file())
        self.assertEqual(hashlib.sha256(ttf.read_bytes()).hexdigest(), TTF_SHA256)

    def test_el_readme_del_autor_viaja_con_la_fuente(self):
        readme = fonts._FONTS_DIR / "7LED-readme.txt"
        self.assertTrue(readme.is_file())
        self.assertIn("FREEWARE", readme.read_text(encoding="latin-1"))

    def test_no_quedan_fuentes_dseg_en_el_paquete(self):
        self.assertEqual(list(fonts._FONTS_DIR.glob("DSEG*")), [])

    def test_linux_copia_fuente_y_readme(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d, mock.patch.object(fonts.Path, "home", return_value=Path(d)), \
                mock.patch.object(fonts.platform, "system", return_value="Linux"), \
                mock.patch.object(fonts.shutil, "which", return_value=None):
            self.assertEqual(fonts.install_led_font(), "7LED")
            destino = Path(d) / ".local" / "share" / "fonts" / "poorsdr4all"
            self.assertTrue((destino / "7LED.ttf").is_file())
            self.assertTrue((destino / "7LED-readme.txt").is_file())

    def test_windows_la_registra_para_el_proceso(self):
        with mock.patch.object(fonts.platform, "system", return_value="Windows"), \
                mock.patch.object(fonts, "_register_windows", return_value=True) as reg:
            self.assertEqual(fonts.install_led_font(), "7LED")
            self.assertEqual(reg.call_args.args[0].name, "7LED.ttf")

    def test_windows_si_falla_el_registro_no_se_anuncia(self):
        with mock.patch.object(fonts.platform, "system", return_value="Windows"), \
                mock.patch.object(fonts, "_register_windows", return_value=False):
            self.assertEqual(fonts.install_led_font(), "")

    def test_sin_el_fichero_devuelve_vacio(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d, mock.patch.object(fonts, "_FONTS_DIR", Path(d)):
            self.assertEqual(fonts.install_led_font(), "")


if __name__ == "__main__":
    unittest.main()
