"""poorsdr.ui.state: RadioView y sus reducers (puro)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.ui import state  # noqa: E402
from poorsdr.ui.state import RadioView  # noqa: E402


class RadioViewTests(unittest.TestCase):
    def test_derived_fields(self):
        v = RadioView(frequency_hz=27_555_000, mode="USB", step_hz=1_000)
        self.assertEqual(v.freq_label, "27.555,00 MHz")
        self.assertEqual(v.band, "11m")
        self.assertEqual((v.parts.mhz, v.parts.khz, v.parts.chz), (27, 555, 0))
        self.assertEqual(v.cat_status_text, "sin CAT")

    def test_connected_text(self):
        self.assertEqual(RadioView(connected=True).cat_status_text, "CAT")

    def test_reducers_are_pure(self):
        v0 = RadioView()
        v1 = state.with_frequency(v0, 7_074_000)
        self.assertEqual(v0.frequency_hz, 27_555_000)  # inmutable
        self.assertEqual(v1.frequency_hz, 7_074_000)
        self.assertEqual(v1.band, "40m")

    def test_with_frequency_clamps_negative(self):
        self.assertEqual(state.with_frequency(RadioView(), -10).frequency_hz, 0)

    def test_with_mode_rejects_unknown(self):
        v = RadioView(mode="USB")
        self.assertEqual(state.with_mode(v, "cw").mode, "CW")
        self.assertEqual(state.with_mode(v, "ZZ").mode, "USB")  # se ignora

    def test_with_step_floor_1(self):
        self.assertEqual(state.with_step(RadioView(), 0).step_hz, 1)
        self.assertEqual(state.with_step(RadioView(), 2500).step_hz, 2500)

    def test_with_ptt_and_connected(self):
        self.assertTrue(state.with_ptt(RadioView(), 1).ptt)
        self.assertTrue(state.with_connected(RadioView(), "yes").connected)

    def test_from_config(self):
        from dataclasses import replace

        cfg = AppConfig()
        cfg = replace(
            cfg,
            cat=replace(cfg.cat, start_freq_hz=14_074_000, step_hz=500),
            ui=replace(cfg.ui, display_mode="lsb"),
        )
        v = state.from_config(cfg)
        self.assertEqual(v.frequency_hz, 14_074_000)
        self.assertEqual(v.mode, "LSB")
        self.assertEqual(v.step_hz, 500)
        self.assertEqual(v.band, "20m")


class TkImportSmokeTests(unittest.TestCase):
    def test_ui_modules_import_when_tk_present(self):
        try:
            import tkinter  # noqa: F401
        except Exception:
            self.skipTest("sin tkinter en este entorno")
        import poorsdr.ui.app  # noqa: F401
        import poorsdr.ui.panels.radio_panel  # noqa: F401
        import poorsdr.ui.widgets  # noqa: F401


if __name__ == "__main__":
    unittest.main()
