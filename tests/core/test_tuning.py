"""core.tuning y core.bands: frecuencia, parseo, paso, inferencia de banda."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.core import bands, tuning  # noqa: E402


class SplitCombineTests(unittest.TestCase):
    def test_split_round_trips(self):
        for hz in (0, 27_555_000, 7_074_120, 28_074_990, 145_500_000):
            self.assertEqual(tuning.split_frequency(hz).hz, hz - hz % 10)

    def test_split_fields(self):
        p = tuning.split_frequency(27_555_120)
        self.assertEqual((p.mhz, p.khz, p.chz), (27, 555, 12))

    def test_combine_valid(self):
        self.assertEqual(tuning.combine_frequency(27, "555", "00"), 27_555_000)
        self.assertEqual(tuning.combine_frequency("7", "074", "12"), 7_074_120)

    def test_combine_invalid(self):
        self.assertIsNone(tuning.combine_frequency("", "5", "0"))
        self.assertIsNone(tuning.combine_frequency("a", "5", "0"))
        self.assertIsNone(tuning.combine_frequency(27, 1500, 0))  # khz > 999
        self.assertIsNone(tuning.combine_frequency(27, 5, 150))  # chz > 99

    def test_format(self):
        self.assertEqual(tuning.format_frequency(27_555_000), "27.555,00 MHz")
        self.assertEqual(tuning.format_frequency(7_074_120), "7.074,12 MHz")


class CoerceTests(unittest.TestCase):
    def test_int_and_digit_string(self):
        self.assertEqual(tuning.coerce_frequency(28_074_000), 28_074_000)
        self.assertEqual(tuning.coerce_frequency("28074000"), 28_074_000)

    def test_mhz_decimal(self):
        self.assertEqual(tuning.coerce_frequency("28.074"), 28_074_000)
        self.assertEqual(tuning.coerce_frequency("28,074"), 28_074_000)

    def test_extra_zeros_trimmed(self):
        self.assertEqual(tuning.coerce_frequency(280_740_000_000), 28_074_000)

    def test_out_of_range_and_junk_fall_back(self):
        self.assertEqual(tuning.coerce_frequency(None), tuning.FALLBACK_HZ)
        self.assertEqual(tuning.coerce_frequency(""), tuning.FALLBACK_HZ)
        self.assertEqual(tuning.coerce_frequency("hola"), tuning.FALLBACK_HZ)
        self.assertEqual(tuning.coerce_frequency(50), tuning.FALLBACK_HZ)  # < MIN_HZ

    def test_custom_fallback(self):
        self.assertEqual(tuning.coerce_frequency("x", fallback=7_074_000), 7_074_000)


class StepTests(unittest.TestCase):
    def test_khz_to_hz(self):
        self.assertEqual(tuning.step_khz_to_hz("0.5"), 500)
        self.assertEqual(tuning.step_khz_to_hz("10"), 10_000)
        self.assertIsNone(tuning.step_khz_to_hz("0"))
        self.assertIsNone(tuning.step_khz_to_hz("-3"))
        self.assertIsNone(tuning.step_khz_to_hz("abc"))

    def test_hz_to_khz_text(self):
        self.assertEqual(tuning.step_hz_to_khz_text(500), "0.5")
        self.assertEqual(tuning.step_hz_to_khz_text(10_000), "10")
        self.assertEqual(tuning.step_hz_to_khz_text(0), "0.001")

    def test_apply_step(self):
        self.assertEqual(tuning.apply_step(27_555_000, 500, +1), 27_555_500)
        self.assertEqual(tuning.apply_step(27_555_000, 500, -1), 27_554_500)
        self.assertEqual(tuning.apply_step(100, 500, -1), 0)  # no baja de 0


class BandTests(unittest.TestCase):
    def test_infer_nearest(self):
        self.assertEqual(bands.infer_band(7_074_000), "40m")
        self.assertEqual(bands.infer_band(27_555_000), "11m")
        self.assertEqual(bands.infer_band(28_074_000), "10m")
        self.assertEqual(bands.infer_band(14_000_000), "20m")

    def test_infer_empty_map(self):
        self.assertEqual(bands.infer_band(7_000_000, {}), "")

    def test_center_and_names(self):
        self.assertEqual(bands.band_center_hz("40m"), 7_074_000)
        self.assertIsNone(bands.band_center_hz("2m"))
        self.assertEqual(bands.band_names()[0], "160m")
        self.assertEqual(len(bands.band_names()), 10)

    def test_matches_legacy_min_criterion(self):
        # réplica del min(..., key=abs distancia) del legacy
        for hz in (1_000_000, 5_000_000, 9_000_000, 25_000_000, 30_000_000):
            expected = min(bands.BAND_MAP_HZ.items(), key=lambda it, h=hz: abs(it[1] - h))[0]
            self.assertEqual(bands.infer_band(hz), expected)


if __name__ == "__main__":
    unittest.main()
