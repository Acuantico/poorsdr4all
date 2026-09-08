"""Lógica pura de CAT: modos, tramas y parsers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.core import cat  # noqa: E402
from poorsdr.core.cat import frames  # noqa: E402
from poorsdr.core.cat.modes import cat_to_mode, mode_to_cat  # noqa: E402
from poorsdr.core.cat.parse import (  # noqa: E402
    parse_frequency,
    parse_if,
    parse_if_ptt,
    parse_mode,
)
from poorsdr.core.cat.profiles import (  # noqa: E402
    CUSTOM,
    GENERIC_TS480,
    apply_profile,
    profile_choices,
    resolve_profile,
)


class ModeMapTests(unittest.TestCase):
    def test_round_trip(self):
        for name in ("LSB", "USB", "CW", "FM", "AM", "DIGU"):
            self.assertEqual(cat_to_mode(mode_to_cat(name)), name)

    def test_unknown_mode_falls_back_to_usb(self):
        self.assertEqual(mode_to_cat("ZZZ"), mode_to_cat("USB"))
        self.assertEqual(mode_to_cat(None), mode_to_cat("USB"))

    def test_case_insensitive(self):
        self.assertEqual(mode_to_cat("usb"), 2)

    def test_cat_to_mode_bad_input(self):
        self.assertIsNone(cat_to_mode("x"))
        self.assertIsNone(cat_to_mode(None))
        self.assertIsNone(cat_to_mode(99))


class FrameTests(unittest.TestCase):
    def test_set_frequency_is_11_digits_terminated(self):
        self.assertEqual(frames.set_frequency(7074000), "FA00007074000;")
        self.assertEqual(frames.set_frequency(0), "FA00000000000;")

    def test_negative_frequency_clamped(self):
        self.assertEqual(frames.set_frequency(-5), "FA00000000000;")

    def test_set_mode(self):
        self.assertEqual(frames.set_mode("CW"), "MD3;")
        self.assertEqual(frames.set_mode("desconocido"), "MD2;")

    def test_ptt_and_queries(self):
        self.assertEqual(frames.set_ptt(True), "TX;")
        self.assertEqual(frames.set_ptt(False), "RX;")
        self.assertEqual(frames.query_if(), "IF;")
        self.assertEqual(frames.query_frequency(), "FA;")

    def test_reexport(self):
        self.assertIs(cat.frames, frames)


class ParseFrequencyTests(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(parse_frequency("FA00007074000;", "FA"), 7074000)

    def test_wrong_prefix_or_empty(self):
        self.assertIsNone(parse_frequency("MD2;", "FA"))
        self.assertIsNone(parse_frequency("", "FA"))
        self.assertIsNone(parse_frequency(None, "FA"))
        self.assertIsNone(parse_frequency("FA;", "FA"))


class ParseIfTests(unittest.TestCase):
    # IF...: 'IF' + 11 dígitos de frecuencia + relleno; el dígito de modo cae en
    # el índice 27 (0-based) para el layout TS-480 / uSDX.
    def _sample(self, freq: int, mode_digit: str) -> str:
        return "IF" + f"{freq:011d}" + "0" * 14 + mode_digit + "00;"

    def test_frequency_and_mode(self):
        freq, mode = parse_if(self._sample(14074000, "2"))
        self.assertEqual(freq, 14074000)
        self.assertEqual(mode, "USB")
        _f, mode_cw = parse_if(self._sample(7000000, "3"))
        self.assertEqual(mode_cw, "CW")

    def test_non_if(self):
        self.assertEqual(parse_if("FA1;"), (None, None))
        self.assertEqual(parse_if(None), (None, None))

    def test_parse_mode_helper(self):
        self.assertEqual(parse_mode("MD3;"), "CW")
        self.assertIsNone(parse_mode("MDX;"))
        self.assertIsNone(parse_mode(None))


class ParseIfPttTests(unittest.TestCase):
    def test_index_28_rx_and_tx(self):
        # PTT en el índice 28 (0-based): 'IF' + 26 chars + bit + resto
        rx = "IF" + "0" * 26 + "0" + "00000;"
        tx = "IF" + "0" * 26 + "1" + "00000;"
        self.assertIs(parse_if_ptt(rx), False)
        self.assertIs(parse_if_ptt(tx), True)

    def test_non_if_returns_none(self):
        self.assertIsNone(parse_if_ptt("MD2;"))
        self.assertIsNone(parse_if_ptt(None))
        self.assertIsNone(parse_if_ptt("IF"))


class RigProfileTests(unittest.TestCase):
    def test_unknown_or_empty_resolves_to_custom(self):
        self.assertIs(resolve_profile(None), CUSTOM)
        self.assertIs(resolve_profile(""), CUSTOM)
        self.assertIs(resolve_profile("no-existe"), CUSTOM)

    def test_custom_leaves_baud_untouched(self):
        self.assertEqual(apply_profile(19200, "custom"), 19200)
        self.assertEqual(apply_profile(19200, None), 19200)

    def test_named_profile_overrides_baud(self):
        self.assertEqual(apply_profile(19200, "generic-ts480"), GENERIC_TS480.baud)

    def test_trusdx_115200_profile(self):
        self.assertEqual(apply_profile(38400, "trusdx-115200"), 115200)

    def test_profile_choices_starts_with_custom(self):
        choices = profile_choices()
        self.assertEqual(choices[0], "custom")
        self.assertIn("generic-ts480", choices)
        self.assertIn("trusdx-115200", choices)


if __name__ == "__main__":
    unittest.main()
