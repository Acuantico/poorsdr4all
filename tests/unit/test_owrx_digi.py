import unittest

from poorsdr.viewers.digi import (
    DigiWindow,
    accent_rgb,
    available_digital_modes,
    decoder_params,
    format_decoder_message,
    is_image_decoder_message,
    selected_theme_accent,
)


class OwrxDigiTests(unittest.TestCase):
    def test_available_modes_uses_server_filtered_digimodes(self):
        modes = [
            {"type": "analog", "modulation": "usb", "name": "USB"},
            {"type": "digimode", "modulation": "rtty170", "name": "RTTY"},
            {"type": "digimode", "modulation": "ft8", "name": "FT8"},
        ]
        self.assertEqual(["ft8", "rtty170"], [m["modulation"] for m in available_digital_modes(modes)])

    def test_decoder_params_selects_supported_underlying_and_frequency(self):
        mode = {
            "modulation": "rtty170",
            "underlying": ["usb", "lsb"],
            "bandpass": {"low_cut": 100, "high_cut": 2500},
        }
        params = decoder_params(mode, 7_074_000, 7_100_000, "lsb")
        self.assertEqual("rtty170", params["secondary_mod"])
        self.assertEqual("lsb", params["mod"])
        self.assertEqual(-26_000, params["offset_freq"])
        self.assertEqual((100, 2500), (params["low_cut"], params["high_cut"]))

    def test_decoder_params_uses_mode_default(self):
        params = decoder_params({"modulation": "page", "underlying": ["nfm"]}, 145_500_000, 145_000_000)
        self.assertEqual("nfm", params["mod"])
        self.assertEqual((-4000, 4000), (params["low_cut"], params["high_cut"]))

    def test_format_wsjt_message(self):
        line = format_decoder_message({"mode": "FT8", "db": -12, "dt": 0.2, "freq": 14075000, "msg": "CQ EA1ABC"})
        self.assertIn("FT8", line)
        self.assertIn("-12 dB", line)
        self.assertIn("CQ EA1ABC", line)

    def test_sstv_control_messages_are_classified_as_image_only(self):
        self.assertTrue(is_image_decoder_message({"mode": "SSTV", "message": "SSTV VIS 124 OK"}))
        self.assertTrue(is_image_decoder_message({
            "mode": "SSTV", "width": 320, "height": 256, "sstvMode": "Scottie 1",
        }))
        self.assertFalse(is_image_decoder_message({"mode": "FT8", "msg": "CQ EA1ABC"}))

    def test_selected_theme_accent_follows_poorsdr_background(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({"Imagen_Fondo": "/tmp/back2.jpg"}), encoding="utf-8")
            self.assertEqual("#0314ec", selected_theme_accent(str(path)))

    def test_accent_rgb_is_ready_for_cairo(self):
        self.assertEqual((30 / 255, 144 / 255, 1.0), accent_rgb("#1e90ff"))

    def test_decode_fax_rle(self):
        # literal run of three bytes, followed by four repeated bytes
        encoded = bytes([2, 1, 2, 3, 130, 9])
        self.assertEqual(bytes([1, 2, 3, 9, 9, 9, 9]), DigiWindow._decode_fax_rle(encoded))


if __name__ == "__main__":
    unittest.main()
