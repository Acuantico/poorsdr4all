"""Selector de la cascada de OWRX: ancho impuesto por el filtro del uSDX (panel RTTY)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.viewers.waterfall import passband_cuts  # noqa: E402


class PassbandCutsTests(unittest.TestCase):
    def test_default_cuts_without_imposed_width(self):
        self.assertEqual(passband_cuts("LSB", None), (-2750, -150))
        self.assertEqual(passband_cuts("usb", None), (150, 2750))

    def test_usdx_500_filter_in_lsb_is_mirrored_below_the_dial(self):
        # Audio 500-1000 Hz en LSB = de -1000 a -500 Hz respecto al dial.
        self.assertEqual(passband_cuts("LSB", (500.0, 1000.0)), (-1000, -500))

    def test_usdx_filter_in_usb_is_used_as_is(self):
        self.assertEqual(passband_cuts("USB", (600.0, 950.0)), (600, 950))

    def test_other_modes_keep_their_own_width(self):
        self.assertEqual(passband_cuts("AM", (500.0, 1000.0)), (-4000, 4000))
        self.assertEqual(passband_cuts("nfm", (500.0, 1000.0)), (-4000, 4000))


if __name__ == "__main__":
    unittest.main()
