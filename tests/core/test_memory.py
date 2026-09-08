"""core.memory: modelo y validación de memorias de frecuencia (puro)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.core import memory as m  # noqa: E402
from poorsdr.core.memory import MemoryEntry  # noqa: E402


class CoerceTests(unittest.TestCase):
    def test_ok(self):
        e = m.coerce_entry({"name": " CQ ", "hz": "7074000", "mode": "usb", "band": "40m"})
        self.assertEqual(e, MemoryEntry(name="CQ", hz=7074000, mode="USB", band="40m"))

    def test_bad_mode_and_band_fall_back(self):
        e = m.coerce_entry({"name": "x", "hz": 1, "mode": "ZZ", "band": "2m"})
        self.assertEqual(e.mode, "AM")
        self.assertEqual(e.band, "")

    def test_rejects_no_name_or_bad_hz(self):
        self.assertIsNone(m.coerce_entry({"name": "", "hz": 1}))
        self.assertIsNone(m.coerce_entry({"name": "a", "hz": "no"}))


class NormalizeTests(unittest.TestCase):
    def test_filters_junk(self):
        raw = [
            {"name": "a", "hz": 1000000},
            "no soy dict",
            {"name": "", "hz": 2},
            {"name": "b", "hz": "x"},
            {"name": "c", "hz": 27555000, "mode": "lsb", "band": "11m"},
        ]
        out = m.normalize_entries(raw)
        self.assertEqual([e.name for e in out], ["a", "c"])
        self.assertEqual(out[1].mode, "LSB")

    def test_non_list_is_empty(self):
        self.assertEqual(m.normalize_entries({"x": 1}), [])
        self.assertEqual(m.normalize_entries(None), [])


class ParseFreqTests(unittest.TestCase):
    def test_seven_digits(self):
        self.assertEqual(m.parse_memory_frequency("2755500", default_hz=0), 27555000)
        self.assertEqual(m.parse_memory_frequency("2.755.500", default_hz=0), 27555000)

    def test_empty_returns_default(self):
        self.assertEqual(m.parse_memory_frequency("", default_hz=14074000), 14074000)
        self.assertEqual(m.parse_memory_frequency("   ", default_hz=7), 7)

    def test_wrong_length_is_none(self):
        self.assertIsNone(m.parse_memory_frequency("123", default_hz=0))
        self.assertIsNone(m.parse_memory_frequency("123456789", default_hz=0))


class MutationTests(unittest.TestCase):
    def test_upsert_replaces_by_name_ci(self):
        a = MemoryEntry("Casa", 1)
        b = MemoryEntry("casa", 2)
        out = m.upsert([a], b)
        self.assertEqual(out, [b])

    def test_upsert_appends_new(self):
        a = MemoryEntry("a", 1)
        b = MemoryEntry("b", 2)
        self.assertEqual(m.upsert([a], b), [a, b])

    def test_remove_at(self):
        xs = [MemoryEntry("a", 1), MemoryEntry("b", 2)]
        self.assertEqual(m.remove_at(xs, 0), [xs[1]])
        self.assertEqual(m.remove_at(xs, 9), xs)  # fuera de rango: sin cambios

    def test_to_json_round_trip(self):
        xs = [MemoryEntry("a", 1, "FM", "40m")]
        self.assertEqual(m.normalize_entries(m.to_json_list(xs)), xs)


if __name__ == "__main__":
    unittest.main()
