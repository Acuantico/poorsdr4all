import unittest

from audio_config_domain import as_bool, clamp, normalize_anr_config


class AudioConfigDomainTests(unittest.TestCase):
    def test_as_bool(self):
        self.assertTrue(as_bool("true"))
        self.assertTrue(as_bool("1"))
        self.assertFalse(as_bool("false"))
        self.assertFalse(as_bool("", default=False))
        self.assertTrue(as_bool("unexpected", default=True))

    def test_clamp(self):
        self.assertEqual(5.0, clamp(5, 1, 10))
        self.assertEqual(1.0, clamp("bad", 1, 10))
        self.assertEqual(10.0, clamp(99, 1, 10))

    def test_normalize_anr_config_updates_and_persists(self):
        config = {
            "DSPFilters": {"anr": {"enabled": "false", "intensity": "9"}},
            "ANR_Enabled": True,
            "ANR_Intensity": 3,
        }
        calls = {"persist": 0}

        def persist():
            calls["persist"] += 1

        changed = normalize_anr_config(config, persist_callback=persist)

        self.assertTrue(changed)
        self.assertFalse(config["ANR_Enabled"])
        self.assertEqual(9, config["ANR_Intensity"])
        self.assertEqual(1, calls["persist"])

    def test_normalize_anr_config_no_change(self):
        config = {
            "DSPFilters": {"anr": {"enabled": True, "intensity": 3}},
            "ANR_Enabled": True,
            "ANR_Intensity": 3,
        }
        calls = {"persist": 0}

        def persist():
            calls["persist"] += 1

        changed = normalize_anr_config(config, persist_callback=persist)

        self.assertFalse(changed)
        self.assertEqual(0, calls["persist"])


if __name__ == "__main__":
    unittest.main()
