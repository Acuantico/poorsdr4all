"""core.autocall: perfiles y validación (puro)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.core import autocall as ac  # noqa: E402


class ParsersTests(unittest.TestCase):
    def test_repeats(self):
        self.assertEqual(ac.parse_repeats("10"), 10)
        self.assertEqual(ac.parse_repeats(3), 3)
        self.assertIsNone(ac.parse_repeats(0))
        self.assertIsNone(ac.parse_repeats(-1))
        self.assertIsNone(ac.parse_repeats("x"))

    def test_interval(self):
        self.assertEqual(ac.parse_interval("5"), 5.0)
        self.assertEqual(ac.parse_interval(-2), 0.0)
        self.assertIsNone(ac.parse_interval("nope"))


class ProfileTests(unittest.TestCase):
    def test_from_dict(self):
        p = ac.profile_from_dict({"Audio": " /x/cq.wav ", "Intervalo": "5", "Repeticiones": "10"})
        self.assertEqual(p, ac.AutocallProfile(audio="/x/cq.wav", repeats=10, interval=5.0))

    def test_from_dict_defaults_and_reject(self):
        self.assertIsNone(ac.profile_from_dict({"Audio": ""}))
        p = ac.profile_from_dict({"Audio": "a.wav", "Repeticiones": "0"})
        self.assertEqual(p.repeats, 1)  # 0 → default 1

    def test_profiles_from_config_list(self):
        cfg = {
            "AutoCallProfiles": [
                {"Audio": "a.wav", "Intervalo": "0", "Repeticiones": "1"},
                {},
                {"Audio": "b.wav", "Intervalo": "3", "Repeticiones": "2"},
            ]
        }
        out = ac.profiles_from_config(cfg)
        self.assertEqual([p.audio for p in out], ["a.wav", "b.wav"])

    def test_profiles_from_config_legacy_fields(self):
        cfg = {"Audio_Llamada_Automatica": "cq.wav", "Repeticiones": "4", "Intervalo": "2"}
        out = ac.profiles_from_config(cfg)
        self.assertEqual(out, [ac.AutocallProfile(audio="cq.wav", repeats=4, interval=2.0)])

    def test_valid_property(self):
        self.assertTrue(ac.AutocallProfile("a.wav", 1).valid)
        self.assertFalse(ac.AutocallProfile("", 1).valid)


class SlotsAndButtonsTests(unittest.TestCase):
    def test_slots_keep_position_of_invalid(self):
        cfg = {
            "AutoCallProfiles": [
                {"Audio": "a.wav", "Nombre": "CQ DX"},
                {"Audio": ""},
                {"Audio": "c.wav"},
            ]
        }
        slots = ac.slots_from_config(cfg)
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0].title, "CQ DX")
        self.assertFalse(slots[1].valid)
        self.assertEqual(slots[2].audio, "c.wav")

    def test_slots_capped_at_limit(self):
        cfg = {"AutoCallProfiles": [{"Audio": f"{i}.wav"} for i in range(20)]}
        self.assertEqual(len(ac.slots_from_config(cfg)), ac.MACRO_LIMIT)

    def test_button_targets_defaults_and_clamps(self):
        self.assertEqual(ac.button_targets({}), [0, 1, 2, 3])
        self.assertEqual(ac.button_targets({"AutoCallButtons": [2, -1]}), [2, -1, 2, 3])
        self.assertEqual(ac.button_targets({"AutoCallButtons": ["x", 5, 1, 0, 9]}), [-1, 5, 1, 0])


if __name__ == "__main__":
    unittest.main()
