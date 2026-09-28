"""poorsdr_rtty_power.contest: reglas CQ WW RTTY (trabajados, intercambio, bandas)."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr_rtty_power.contest import (  # noqa: E402
    CALL_RE,
    WORKED_WINDOW_SEC,
    Exchange,
    WorkedLog,
    contest_window_start,
    cq_answer,
    cq_caller,
    exchange_to_send,
    find_reply_exchange,
    is_calling_cq,
    is_contest_band,
    parse_exchange,
    reply_text,
    report_text,
    responder_step,
    split_exchange,
)


def _ts(*args: int) -> float:
    return datetime(*args, tzinfo=UTC).timestamp()


FRIDAY_TEST = _ts(2026, 9, 25, 20, 0)
CONTEST_START = _ts(2026, 9, 26, 0, 0)  # CQ WW RTTY 2026: sábado 26 00:00 UTC
SATURDAY = _ts(2026, 9, 26, 10, 0)
SUNDAY_LATE = _ts(2026, 9, 27, 23, 30)


class ContestWindowTests(unittest.TestCase):
    def test_weekend_window_starts_saturday_0000_utc(self):
        self.assertEqual(contest_window_start(SATURDAY), CONTEST_START)
        self.assertEqual(contest_window_start(SUNDAY_LATE), CONTEST_START)

    def test_a_friday_test_qso_is_not_a_dupe_in_the_contest(self):
        log = WorkedLog()
        log.add("K1XYZ", "40m", timestamp=FRIDAY_TEST)
        self.assertTrue(log.is_worked("K1XYZ", "40m", now=FRIDAY_TEST + 60))  # el viernes sí
        self.assertFalse(log.is_worked("K1XYZ", "40m", now=SATURDAY))  # en el concurso no

    def test_a_saturday_qso_is_still_a_dupe_on_sunday_night(self):
        log = WorkedLog()
        log.add("K1XYZ", "40m", timestamp=SATURDAY)
        self.assertTrue(log.is_worked("K1XYZ", "40m", now=SUNDAY_LATE))

    def test_weekday_window_is_48_hours(self):
        monday = _ts(2026, 9, 28, 12, 0)
        self.assertEqual(contest_window_start(monday), monday - WORKED_WINDOW_SEC)


class WorkedLogTests(unittest.TestCase):
    def test_worked_is_per_band(self):
        log = WorkedLog()
        log.add("k1xyz", "40M", timestamp=SATURDAY)
        self.assertTrue(log.is_worked("K1XYZ", "40m", now=SATURDAY + 1))
        self.assertFalse(log.is_worked("K1XYZ", "20m", now=SATURDAY + 1))
        self.assertFalse(log.is_worked("EA1ABC", "40m", now=SATURDAY + 1))

    def test_json_round_trip(self):
        log = WorkedLog()
        log.add("K1XYZ", "40m", timestamp=SATURDAY)
        restored = WorkedLog.from_json(log.to_json(now=SATURDAY + 10))
        self.assertTrue(restored.is_worked("K1XYZ", "40m", now=SATURDAY + 20))

    def test_corrupt_json_is_ignored(self):
        self.assertEqual(WorkedLog.from_json({"x": 1}).entries, [])
        self.assertEqual(WorkedLog.from_json([{"call": "A1AA"}]).entries, [])


class ExchangeTests(unittest.TestCase):
    def test_dx_exchange(self):
        self.assertEqual(parse_exchange("EA1ABC 599 14 14 TU"), Exchange("599", "14"))

    def test_usa_exchange_with_state(self):
        self.assertEqual(parse_exchange("TU 599 05 05 MA MA"), Exchange("599", "05", "MA"))

    def test_canada_exchange_with_province(self):
        self.assertEqual(parse_exchange("599 04 ON ON"), Exchange("599", "04", "ON"))

    def test_de_before_a_callsign_is_not_delaware(self):
        self.assertEqual(parse_exchange("599 05 DE K1XYZ"), Exchange("599", "05"))

    def test_state_only_counts_for_north_american_zones(self):
        # "OK" tras una zona europea no es Oklahoma.
        self.assertEqual(parse_exchange("599 14 OK"), Exchange("599", "14"))

    def test_invalid_zone_is_ignored(self):
        self.assertIsNone(parse_exchange("599 55"))

    def test_last_exchange_wins(self):
        self.assertEqual(parse_exchange("599 14 14 ... 599 05 05"), Exchange("599", "05"))

    def test_split_hand_typed_fields(self):
        self.assertEqual(split_exchange("599 14 14"), Exchange("599", "14"))
        self.assertEqual(split_exchange("599 05 ma"), Exchange("599", "05", "MA"))
        self.assertEqual(split_exchange("14"), Exchange("", "14"))

    def test_exchange_to_send_repeats_the_zone(self):
        self.assertEqual(exchange_to_send("14"), "599 14 14")
        self.assertEqual(exchange_to_send(""), "599")

    def test_contest_bands(self):
        for band in ("80m", "40M", "20m", "15m", "10m"):
            self.assertTrue(is_contest_band(band))
        for band in ("160m", "30m", "17m", "12m", ""):
            self.assertFalse(is_contest_band(band))


class ReplyTextTests(unittest.TestCase):
    def test_normal_qso_report_has_both_calls(self):
        self.assertEqual(report_text("lz3nd", "ea0xxx"), "LZ3ND DE EA0XXX 599 599")

    def test_reply_without_zone_is_a_normal_report(self):
        # Bug real: con Exchange = "599" se enviaba solo "LZ3ND 599".
        self.assertEqual(reply_text("LZ3ND", "EA0XXX", "599"), "LZ3ND DE EA0XXX 599 599")
        self.assertEqual(reply_text("LZ3ND", "EA0XXX", ""), "LZ3ND DE EA0XXX 599 599")

    def test_reply_with_zone_is_the_short_contest_exchange(self):
        self.assertEqual(reply_text("LZ3ND", "EA0XXX", "599 14 14"), "LZ3ND 599 14 14")


class ResponderPhaseTests(unittest.TestCase):
    def _step(self, phase, exchange="599", calling_cq=True):
        return responder_step(phase, call="LZ3ND", my_call="EA0XXX", exchange=exchange, calling_cq=calling_cq)

    def test_normal_qso_answering_a_cq(self):
        self.assertEqual(self._step("none"), ("EA0XXX EA0XXX", "called"))
        self.assertEqual(self._step("called"), ("LZ3ND DE EA0XXX 599 599", "report_tx"))
        self.assertEqual(self._step("report_tx"), ("TU 73 LZ3ND DE EA0XXX SK", "done"))

    def test_contest_qso_answering_a_cq(self):
        self.assertEqual(self._step("none", "599 14 14"), ("EA0XXX EA0XXX", "called"))
        self.assertEqual(self._step("called", "599 14 14"), ("LZ3ND 599 14 14", "report_tx"))
        self.assertEqual(self._step("report_tx", "599 14 14"), ("TU", "done"))

    def test_station_that_called_me_gets_my_report_first(self):
        self.assertEqual(self._step("none", calling_cq=False), ("LZ3ND DE EA0XXX 599 599", "report_tx"))


class ReplyExchangeTests(unittest.TestCase):
    """Tras responder a un CQ: ¿me ha dado ya su intercambio?"""

    def test_reply_to_me_with_exchange(self):
        self.assertEqual(find_reply_exchange("EA1ABC 599 15 15", "EA1ABC"), Exchange("599", "15"))

    def test_reply_with_state_and_glued_garbage(self):
        self.assertEqual(
            find_reply_exchange("XQEA1ABCEA1ABC 599 05 05 MA MA", "ea1abc"), Exchange("599", "05", "MA")
        )

    def test_normal_qso_report_without_zone(self):
        # Bug real: en un QSO normal solo llega "599 599" (sin zona) y el
        # reporte automático nunca saltaba.
        self.assertEqual(find_reply_exchange("EA0XXX DE LZ3ND UR 599 599 K", "EA0XXX"), Exchange("599", ""))

    def test_contest_waits_for_the_zone(self):
        # Bug real (IB9R): en concurso saltaba con "EA0XXX 599" antes de su zona.
        self.assertIsNone(find_reply_exchange("EA0XXX 599", "EA0XXX", require_zone=True))
        self.assertEqual(
            find_reply_exchange("EA0XXX 599 15 15", "EA0XXX", require_zone=True), Exchange("599", "15")
        )

    def test_reply_to_another_station_is_ignored(self):
        self.assertIsNone(find_reply_exchange("DL1ZZZ 599 15 15", "EA1ABC"))

    def test_mangled_call_is_not_trusted(self):
        self.assertIsNone(find_reply_exchange("EA1ABD 599 15 15", "EA1ABC"))

    def test_my_call_without_exchange_yet(self):
        self.assertIsNone(find_reply_exchange("EA1ABC EA1A", "EA1ABC"))


class CqDetectionTests(unittest.TestCase):
    TEXT = "EA1ABC 599 14 14\nCQ TEST DE K1XYZ K1XYZ\n"

    def _start(self, call, nth=0):
        return [m.start() for m in CALL_RE.finditer(self.TEXT) if m.group(0) == call][nth]

    def test_call_after_cq_is_calling_cq(self):
        self.assertTrue(is_calling_cq(self.TEXT, self._start("K1XYZ")))
        self.assertTrue(is_calling_cq(self.TEXT, self._start("K1XYZ", 1)))

    def test_call_not_preceded_by_cq_is_not(self):
        self.assertFalse(is_calling_cq(self.TEXT, self._start("EA1ABC")))

    def _calling(self, text, call, nth=0):
        m = [m for m in CALL_RE.finditer(text) if m.group(0) == call][nth]
        return is_calling_cq(text, m.start(), m.end())

    def test_contest_call_formats_without_cq(self):
        # En concurso muchos no mandan "CQ": estos formatos también llaman.
        self.assertTrue(self._calling("TEST K1XYZ K1XYZ", "K1XYZ", 1))
        self.assertTrue(self._calling("K1XYZ K1XYZ TEST", "K1XYZ", 0))
        self.assertTrue(self._calling("TU K1XYZ TEST", "K1XYZ"))
        self.assertTrue(self._calling("QRZ DE K1XYZ", "K1XYZ"))

    def test_cq_split_over_two_lines(self):
        self.assertTrue(self._calling("CQ TEST CQ TEST\nDE K1XYZ K1XYZ K1XYZ", "K1XYZ", 2))

    def test_garbled_cq_still_counts_if_test_is_there(self):
        self.assertTrue(self._calling("CW TEST DE K1XYZ K1XYZ", "K1XYZ"))

    def test_real_off_air_cq_with_glued_garbage(self):
        # Texto real del panel (YT3X llamando CQ, 2026-09-25): el CQ llega
        # pegado a basura y el indicativo repetido llega pegado a sí mismo.
        text = "VTFEMCQ YT3YT3X YT3X TFLGHCQ YT3X YT3XYTMKPV 3V\n"
        self.assertTrue(self._calling(text, "YT3X", 0))
        self.assertTrue(self._calling(text, "YT3X", 1))
        self.assertEqual(cq_caller(text), "YT3X")

    def test_runner_closing_tu_call_is_a_new_call(self):
        # Caso real (CN3A, 2026-09-26): cierra con W9EXL y vuelve a llamar
        # con "TU CN3A", sin CQ ni TEST.
        text = "W9EXL 599 33\nW9EXL TU CN3A\nN HWBMLDA\n"
        self.assertTrue(self._calling(text, "CN3A"))
        self.assertFalse(self._calling(text, "W9EXL", 1))  # W9EXL no llama
        self.assertEqual(cq_caller(text), "CN3A")

    def test_tu_before_an_exchange_is_not_a_call(self):
        self.assertFalse(self._calling("DL1ZZZ TU 599 14 14 CN3A", "DL1ZZZ"))

    def test_the_next_line_cq_of_another_station_does_not_count(self):
        self.assertFalse(self._calling("DL1ZZZ 599 14 14\nCQ TEST DE K1XYZ", "DL1ZZZ"))

    def test_a_station_answering_a_cq_is_not_calling(self):
        self.assertFalse(self._calling("CQ TEST DE K1XYZ K1XYZ\nDL1ZZZ DL1ZZZ", "DL1ZZZ"))

    def test_cq_caller_understands_test_after_the_call(self):
        self.assertEqual(cq_caller("DL1ZZZ 599 14\nK1XYZ K1XYZ TEST"), "K1XYZ")

    def test_cq_caller_is_the_station_of_the_last_cq(self):
        text = "CQ TEST DE W1AW W1AW\nEA1ABC EA1ABC\nCQ TEST DE K1XYZ K1XYZ"
        self.assertEqual(cq_caller(text), "K1XYZ")

    def test_cq_caller_skips_my_own_call(self):
        self.assertEqual(cq_caller("CQ TEST DE EA1ABC EA1ABC", my_call="ea1abc"), None)

    def test_answer_is_my_call_twice(self):
        self.assertEqual(cq_answer("ea1abc"), "EA1ABC EA1ABC")


if __name__ == "__main__":
    unittest.main()
