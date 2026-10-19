"""poorsdr.ui.layout: overrides de posiciones del modo EDIT."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.ui import layout  # noqa: E402


class LayoutOverridesTests(unittest.TestCase):
    def test_round_trip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "layout.json"
            with mock.patch.object(layout, "_overrides_path", return_value=path):
                self.assertEqual(layout.load_overrides(), {})
                layout.save_overrides(
                    {"ptt_button": {"x": 10, "y": 20, "anchor": "nw", "width": 240}}
                )
                got = layout.load_overrides()
        self.assertEqual(got["ptt_button"]["x"], 10)
        self.assertEqual(got["ptt_button"]["width"], 240)

    def test_bad_file_returns_empty(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "layout.json"
            path.write_text("{ not json", encoding="utf-8")
            with mock.patch.object(layout, "_overrides_path", return_value=path):
                self.assertEqual(layout.load_overrides(), {})

    def test_non_dict_entries_dropped(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "layout.json"
            path.write_text('{"a": {"x": 1, "y": 2}, "b": 5}', encoding="utf-8")
            with mock.patch.object(layout, "_overrides_path", return_value=path):
                got = layout.load_overrides()
        self.assertEqual(set(got), {"a"})


if __name__ == "__main__":
    unittest.main()


class BotonesDeFabricaNoSeSolapanTests(unittest.TestCase):
    """Columna de la derecha: Log -> Mem -> primer plugin (RTTY...). Antes el segundo plugin caía sobre Mem."""

    ALTO_BOTON = 32  # alto aproximado de un botón de la consola
    ALTO_VENTANA = 760  # WINDOW_H de main_window

    def _pos(self, nombre):
        d = layout.LAYOUT_DEFAULTS[nombre]
        return d["x"], d["y"]

    def test_orden_vertical_y_separacion_suficiente(self):
        ys = [self._pos(n)[1] for n in ("log_button", "mem_button", "plugin_button_1")]
        self.assertEqual(ys, sorted(ys))
        for a, b in zip(ys, ys[1:], strict=False):
            self.assertGreaterEqual(b - a, self.ALTO_BOTON)

    def test_caben_en_la_ventana(self):
        self.assertLessEqual(self._pos("plugin_button_1")[1] + self.ALTO_BOTON, self.ALTO_VENTANA)

    def test_misma_columna(self):
        xs = [self._pos(n)[0] for n in ("log_button", "mem_button", "plugin_button_1")]
        self.assertLessEqual(max(xs) - min(xs), 3)
