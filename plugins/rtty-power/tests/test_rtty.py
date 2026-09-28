"""poorsdr_rtty_power.rtty: codec Baudot/ITA2 y tonos FSK (puro)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr_rtty_power.rtty import (  # noqa: E402
    RttyDemodulator,
    band_from_freq_hz,
    build_qso_adif,
    build_wsjtx_logged_adif_packet,
    decode_baudot_to_text,
    encode_text_to_baudot,
    find_signal_candidates,
    generate_fsk_samples,
)


class BaudotCodecTests(unittest.TestCase):
    def test_round_trip_letters_and_space(self):
        text = "CQ CQ DE EA1ABC EA1ABC"
        codes = encode_text_to_baudot(text)
        self.assertEqual(decode_baudot_to_text(codes), text)

    def test_round_trip_switches_to_figures_and_back(self):
        text = "599 001 TU"
        codes = encode_text_to_baudot(text)
        self.assertEqual(decode_baudot_to_text(codes), text)

    def test_lowercase_is_accepted_on_encode(self):
        codes = encode_text_to_baudot("ea1abc")
        self.assertEqual(decode_baudot_to_text(codes), "EA1ABC")

    def test_figures_after_a_space_resend_figs_for_uos_receivers(self):
        codes = encode_text_to_baudot("599 14")
        space = codes.index(4)
        self.assertEqual(codes[space + 1], 27)  # FIGS otra vez antes de "14"

    def test_transmission_starts_with_an_explicit_shift(self):
        self.assertEqual(encode_text_to_baudot("CQ")[0], 31)  # LTRS
        self.assertEqual(encode_text_to_baudot("599")[0], 27)  # FIGS

    def test_unrepresentable_chars_are_dropped_not_crashed(self):
        codes = encode_text_to_baudot("A€B")
        self.assertEqual(decode_baudot_to_text(codes), "AB")


def _with_tail(audio, sample_rate):
    """El audio del uSDX nunca se corta en seco: el último carácter se
    confirma ~30 ms después de su bit de parada (retardo de los filtros).
    Los tests añaden esa cola igual que la tendría la señal real."""
    return np.concatenate([audio, np.zeros(sample_rate // 5, dtype=np.float32)])


class FskRoundTripTests(unittest.TestCase):
    def test_tone_generation_decodes_back_to_the_same_text(self):
        text = "CQ TEST EA1ABC EA1ABC 599 14"
        sample_rate = 8000
        audio = generate_fsk_samples(
            text, sample_rate=sample_rate, center_hz=1500.0, idle_marks=4
        )
        self.assertGreater(audio.size, 0)

        decoder = RttyDemodulator(sample_rate=sample_rate, center_hz=1500.0)
        recovered = decoder.feed(_with_tail(audio, sample_rate))
        self.assertIn(text, recovered)

    def test_feed_can_be_called_in_small_chunks(self):
        text = "TEST DE EA1ABC"
        sample_rate = 8000
        audio = _with_tail(
            generate_fsk_samples(text, sample_rate=sample_rate, center_hz=1200.0), sample_rate
        )

        decoder = RttyDemodulator(sample_rate=sample_rate, center_hz=1200.0)
        chunk = 512
        collected = ""
        for start in range(0, audio.size, chunk):
            collected += decoder.feed(audio[start : start + chunk])
        self.assertIn(text, collected)

    def test_first_character_after_preamble_is_not_corrupted(self):
        # El decodificador anterior perdía o corrompía el primer carácter
        # tras cualquier silencio/preámbulo ("CQ" -> "VQ") según la
        # alineación entre la frecuencia de muestreo y el largo del
        # preámbulo: se barren todas las combinaciones habituales.
        text = "CQ TEST"
        for sample_rate in (8000, 12000, 16000, 24000, 32000, 44100, 48000):
            for idle_marks in range(0, 17):
                with self.subTest(sample_rate=sample_rate, idle_marks=idle_marks):
                    audio = generate_fsk_samples(
                        text, sample_rate=sample_rate, center_hz=1500.0, idle_marks=idle_marks
                    )
                    decoder = RttyDemodulator(sample_rate=sample_rate, center_hz=1500.0)
                    self.assertIn(text, decoder.feed(_with_tail(audio, sample_rate)))

    def test_long_message_stays_aligned(self):
        # Un mensaje largo seguido no debe ir perdiendo la alineación
        # carácter a carácter (le pasó al decodificador anterior).
        text = "CQ TEST DE EA1ABC EA1ABC K " * 5
        audio = generate_fsk_samples(text, sample_rate=48000, center_hz=1500.0, idle_marks=6)
        decoder = RttyDemodulator(sample_rate=48000, center_hz=1500.0)
        self.assertEqual(decoder.feed(_with_tail(audio, 48000)), text)


def _noisy(audio, snr_db, seed=0):
    """Ruido blanco a ``snr_db`` (potencia de señal frente a ruido en 2500 Hz)
    sobre audio a 48 kHz, como en scripts/rtty_bench.py."""
    rng = np.random.default_rng(seed)
    power = float(np.mean(audio.astype(np.float64) ** 2))
    sigma2 = power * 48000 / (5000.0 * 10 ** (snr_db / 10))
    return (audio + rng.normal(0, np.sqrt(sigma2), audio.size)).astype(np.float32)


class ContestRobustnessTests(unittest.TestCase):
    """Lo que de verdad importa en un concurso. Cada caso reproduce un
    escenario de scripts/rtty_bench.py donde el decodificador anterior
    fallaba (25-85 % de caracteres erróneos)."""

    TEXT = "CQ TEST DE EA1ABC EA1ABC TEST\nEA1ABC 599 14 14 DE K1XYZ\n"

    def _decode(self, audio, **kwargs):
        dec = RttyDemodulator(sample_rate=48000, center_hz=1500.0, **kwargs)
        return "".join(dec.feed(audio[i : i + 4320]) for i in range(0, audio.size, 4320))

    def _signal(self, **kwargs):
        pad = np.zeros(48000, dtype=np.float32)
        body = generate_fsk_samples(
            self.TEXT, sample_rate=48000, center_hz=1500.0, amplitude=0.25, idle_marks=6, **kwargs
        )
        return np.concatenate([pad, body, pad])

    def test_exchange_numbers_survive_a_receiver_with_uos(self):
        # Bug real de TX: tras el espacio de "599 14" no se reenviaba FIGS y
        # un receptor con UOS (MMTTY/N1MM por defecto) leía "599 QR".
        self.assertIn("599 14 14", self._decode(self._signal(), uos=True))

    def test_decodes_with_noise_at_minus_3_db(self):
        self.assertIn(self.TEXT, self._decode(_noisy(self._signal(), -3)))

    def test_reverse_polarity_is_decoded_when_asked(self):
        audio = _noisy(self._signal(shift_hz=-170.0), 5)
        self.assertIn(self.TEXT, self._decode(audio, reverse=True))

    def test_strong_neighbour_350_hz_away_does_not_break_the_copy(self):
        other = generate_fsk_samples(
            "RYRYRY CQ CQ DE W1AW W1AW K " * 8, sample_rate=48000, center_hz=1850.0, amplitude=1.0
        )
        audio = _noisy(self._signal(), 0)  # SNR respecto a NUESTRA señal
        self.assertIn(self.TEXT, self._decode(audio + other[: audio.size]))

    def test_little_garbage_from_pure_noise(self):
        noise = np.random.default_rng(3).normal(0, 0.05, 48000 * 30).astype(np.float32)
        self.assertLess(len(self._decode(noise).strip()), 30)  # < 1 carácter/s


class SignalScannerTests(unittest.TestCase):
    def test_finds_the_center_of_a_synthetic_signal(self):
        sample_rate = 8000
        audio = generate_fsk_samples(
            "CQ CQ CQ DE EA1ABC EA1ABC EA1ABC K",
            sample_rate=sample_rate,
            center_hz=1700.0,
        )
        candidates = find_signal_candidates(audio[:4096], sample_rate)
        self.assertTrue(candidates, "no candidate signal found")
        closest = min(candidates, key=lambda c: abs(c - 1700.0))
        self.assertLess(abs(closest - 1700.0), 60.0)


class BandFromFreqTests(unittest.TestCase):
    def test_known_hf_bands(self):
        self.assertEqual(band_from_freq_hz(14_090_000.0), "20m")
        self.assertEqual(band_from_freq_hz(7_045_000.0), "40m")

    def test_unknown_frequency_returns_empty(self):
        self.assertEqual(band_from_freq_hz(1_000.0), "")


class QsoAdifTests(unittest.TestCase):
    def test_contains_expected_fields(self):
        adif = build_qso_adif(
            call="ea1abc",
            band="20m",
            freq_hz=14_090_000.0,
            rst_sent="599",
            rst_recv="599",
            zone_sent="14",
            zone_recv="5",
            timestamp_utc="2026-09-20T10:30:15",
        )
        self.assertIn("<CALL:6>EA1ABC ", adif)
        self.assertIn("<QSO_DATE:8>20260920 ", adif)
        self.assertIn("<TIME_ON:6>103015 ", adif)
        self.assertIn("<BAND:3>20M ", adif)
        self.assertIn("<MODE:4>RTTY ", adif)
        self.assertIn("<STX_STRING:2>14 ", adif)
        self.assertIn("<STX:2>14 ", adif)
        self.assertIn("<SRX_STRING:1>5 ", adif)
        self.assertIn("<SRX:1>5 ", adif)
        self.assertTrue(adif.endswith("<EOR>\n"))

    def test_omits_empty_optional_fields(self):
        adif = build_qso_adif(
            call="EA1ABC", band="", freq_hz=14_090_000.0, rst_sent="599", rst_recv="599"
        )
        self.assertNotIn("STX", adif)
        self.assertNotIn("SRX", adif)
        self.assertNotIn("BAND", adif)


class WsjtxUdpPacketTests(unittest.TestCase):
    @staticmethod
    def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
        return int.from_bytes(data[offset : offset + 4], byteorder="big"), offset + 4

    @staticmethod
    def _read_qbytearray_utf8(data: bytes, offset: int) -> tuple[str, int]:
        length, offset = WsjtxUdpPacketTests._read_u32(data, offset)
        end = offset + length
        return data[offset:end].decode("utf-8"), end

    def _extract_logged_adif(self, payload: bytes) -> str | None:
        # Réplica deliberada de
        # ``Libro-Guardia.py::_extract_wsjtx_logged_adif`` (NMN1M) -- si esto
        # decodifica el paquete, el importador real de WSJT-X UDP de NMN1M
        # también debería hacerlo.
        offset = 0
        magic, offset = self._read_u32(payload, offset)
        if magic != 0xADBCCBDA:
            return None
        _schema, offset = self._read_u32(payload, offset)
        msg_type, offset = self._read_u32(payload, offset)
        if msg_type != 12:
            return None
        _sender_id, offset = self._read_qbytearray_utf8(payload, offset)
        adif_text, _offset = self._read_qbytearray_utf8(payload, offset)
        return adif_text

    def test_round_trips_through_nmn1m_style_decoder(self):
        adif = build_qso_adif(
            call="EA1ABC", band="20m", freq_hz=14_090_000.0, rst_sent="599", rst_recv="599", zone_sent="14"
        )
        packet = build_wsjtx_logged_adif_packet(adif, client_id="PoorSDR4All-RTTY")
        recovered = self._extract_logged_adif(packet)
        self.assertEqual(recovered, adif)

    def test_wrong_magic_is_rejected_like_the_real_parser(self):
        packet = build_wsjtx_logged_adif_packet("<EOR>\n")
        corrupted = b"\x00\x00\x00\x00" + packet[4:]
        self.assertIsNone(self._extract_logged_adif(corrupted))


if __name__ == "__main__":
    unittest.main()
