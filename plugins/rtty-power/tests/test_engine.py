"""poorsdr_rtty_power.engine: motor RTTY (RX multi-señal + TX + watchdog de PTT)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402
from poorsdr_rtty_power.engine import (  # noqa: E402
    AFC_SEARCH_HALF_HZ,
    ANALYSIS_WINDOW_SAMPLES,
    TX_TAIL_SEC,
    TX_WATCHDOG_SEC,
    RttyEngine,
    RttySignal,
)
from poorsdr_rtty_power.rtty import RttyDemodulator, generate_fsk_samples  # noqa: E402

SAMPLE_RATE = 8000


class FakeAudioModule:
    def __init__(self) -> None:
        self._queue: list[np.ndarray] = []
        self.injected: list[tuple[np.ndarray, int]] = []
        self.digi_inject_active = False
        self.digi_inject_history: list[bool] = []

    def push(self, samples: np.ndarray) -> None:
        self._queue.append(samples)

    def pop_rx_raw_chunk_digi(self):
        if not self._queue:
            return None
        return self._queue.pop(0)

    def inject_tx_audio(self, samples: np.ndarray, sample_rate: int) -> None:
        self.injected.append((samples, sample_rate))

    def clear_tx_inject_buffer(self) -> None:
        self.injected.clear()

    def set_tx_digi_inject_active(self, enabled: bool) -> None:
        self.digi_inject_active = enabled
        self.digi_inject_history.append(enabled)


class FakeAudioService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start_tx(self) -> None:
        self.calls.append("start_tx")

    def stop_tx(self) -> None:
        self.calls.append("stop_tx")


class FakeRadio:
    def __init__(self, mode: str = "USB") -> None:
        self.mode = mode
        self.ptt_calls: list[bool] = []

    def set_ptt(self, active: bool, *, source: str = "app") -> None:
        self.ptt_calls.append(active)


class RttyEngineRxTests(unittest.TestCase):
    def test_tick_decodes_a_synthetic_signal_end_to_end(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)

        tone = generate_fsk_samples(
            "CQ CQ DE EA1ABC", sample_rate=SAMPLE_RATE, center_hz=1500.0
        )
        # Trocea la señal para simular que llega en varias pasadas de _tick_.
        chunk = 1024
        for start in range(0, tone.size, chunk):
            audio.push(tone[start : start + chunk])
            engine.tick()
            engine._last_scan = 0.0  # fuerza re-escaneo en cada trozo del test

        combined = "".join(sig.text for sig in engine.signals.values())
        self.assertIn("EA1ABC", combined)

    def test_analysis_window_stays_bounded_after_a_big_backlog(self):
        # Bug real: tras un atasco de la UI llegaba de golpe un bloque de
        # varios segundos; find_signal_candidates sobre todo el bloque
        # tardaba segundos y congelaba la ventana (ni se cerraba).
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        audio.push(np.zeros(SAMPLE_RATE * 5, dtype=np.float32))
        engine.tick()
        self.assertEqual(engine.last_samples.size, ANALYSIS_WINDOW_SAMPLES)

    def test_stale_signals_are_dropped(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.signals[1] = RttySignal(
            center_hz=1234.0,
            decoder=RttyDemodulator(sample_rate=SAMPLE_RATE, center_hz=1234.0),
            last_seen=time.monotonic() - 999.0,
        )
        audio.push(np.zeros(64, dtype=np.float32))
        engine.tick()
        self.assertNotIn(1, engine.signals)


class RttyEngineLockAndScanTests(unittest.TestCase):
    def test_locked_signal_survives_past_the_stale_timeout(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        key = engine.lock_signal(1500.0)
        engine.signals[key].last_seen = time.monotonic() - 999.0
        audio.push(np.zeros(64, dtype=np.float32))
        engine.tick()
        self.assertIn(key, engine.signals)

    def test_clicking_the_same_station_again_reuses_its_decoder(self):
        # Bug real: 4 clics sobre la misma estación (1912/1922/1927/1932 Hz)
        # dejaban 4 decodificadores enganchados leyendo lo mismo.
        engine = RttyEngine(audio_module=FakeAudioModule(), radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        keys = {engine.lock_signal(hz) for hz in (1912.0, 1922.0, 1927.0, 1932.0)}
        self.assertEqual(len(keys), 1)
        self.assertEqual(len(engine.signals), 1)
        self.assertEqual(next(iter(engine.signals.values())).center_hz, 1932.0)  # la última sintonía

    def test_a_different_station_nearby_gets_its_own_decoder(self):
        engine = RttyEngine(audio_module=FakeAudioModule(), radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.lock_signal(1500.0)
        engine.lock_signal(1800.0)
        self.assertEqual(len(engine.signals), 2)

    def test_auto_scan_only_looks_inside_the_usdx_filter(self):
        # Con el filtro de 500 del uSDX (550-950 Hz) una señal en 1800 Hz
        # no pasa por la radio: el auto-scan no debe buscar ahí.
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.scan_range_hz = (500.0, 1000.0)
        tone = generate_fsk_samples("CQ CQ DE EA1ABC EA1ABC", sample_rate=SAMPLE_RATE, center_hz=1800.0)
        for start in range(0, tone.size, 1024):
            audio.push(tone[start : start + 1024])
            engine._last_scan = 0.0
            engine.tick()
        self.assertEqual(engine.signals, {})

    def test_auto_scan_disabled_does_not_add_new_signals(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False
        tone = generate_fsk_samples("CQ CQ DE EA1ABC", sample_rate=SAMPLE_RATE, center_hz=1500.0)
        audio.push(tone)
        engine.tick()
        self.assertEqual(engine.signals, {})


class RttyEngineAfcTests(unittest.TestCase):
    """AFC = ajuste extrafino de la señal que el OPERADOR ya sintonizó (clic
    o "Enganchar"), nunca un buscador de señal: debe pulir la imprecisión
    normal de un clic, y NO debe ir hacia otra estación más fuerte."""

    @staticmethod
    def _run(engine, audio, tone):
        chunk = int(SAMPLE_RATE * 0.4)
        for start in range(0, tone.size, chunk):
            audio.push(tone[start : start + chunk])
            engine._last_afc = 0.0  # fuerza el AFC en cada trozo del test
            engine.tick()

    def test_afc_fine_tunes_a_slightly_off_lock_to_the_real_peak(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False

        real_center = 1560.0
        approx_center = 1540.0  # 20 Hz de error -- la imprecisión típica de un clic
        key = engine.lock_signal(approx_center)
        text = "CQ TEST DE EA1ABC EA1ABC CQ TEST DE EA1ABC EA1ABC PSE K"
        tone = generate_fsk_samples(
            text, sample_rate=SAMPLE_RATE, center_hz=real_center, shift_hz=170.0, idle_marks=20
        )
        # Cola tras el último carácter: el audio real nunca se corta en seco.
        tone = np.concatenate([tone, np.zeros(SAMPLE_RATE // 5, dtype=np.float32)])
        self._run(engine, audio, tone)

        sig = engine.signals[key]
        self.assertLess(
            abs(sig.center_hz - real_center),
            5.0,
            f"el AFC no afinó: quedó en {sig.center_hz}, el real es {real_center}",
        )
        self.assertIn(text, sig.text)

    def test_afc_does_not_get_stuck_at_the_initial_lock(self):
        # Bug real: escoger "el candidato más cercano al centro actual" (en
        # vez del de más energía) casi siempre encuentra un candidato falso
        # (ruido/lóbulos laterales) pegado justo donde ya está el centro, y
        # el AFC no se movía ni un Hz por mucho que se dejara correr.
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False

        approx_center = 1540.0
        key = engine.lock_signal(approx_center)
        tone = generate_fsk_samples(
            "CQ TEST DE EA1ABC EA1ABC CQ TEST DE EA1ABC EA1ABC PSE K",
            sample_rate=SAMPLE_RATE, center_hz=1560.0, shift_hz=170.0, idle_marks=20,
        )
        self._run(engine, audio, tone)

        self.assertNotEqual(engine.signals[key].center_hz, approx_center)

    def test_afc_does_not_chase_a_stronger_neighbouring_signal(self):
        # El operador sintonizó la estación débil de 1560 Hz; hay otra
        # mucho más fuerte a 1650 Hz (pileup). El AFC NO debe irse hacia
        # ella -- solo afina lo que el operador eligió.
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False

        key = engine.lock_signal(1540.0)
        weak = generate_fsk_samples(
            "CQ TEST DE EA1ABC EA1ABC CQ TEST DE EA1ABC EA1ABC PSE K",
            sample_rate=SAMPLE_RATE, center_hz=1560.0, shift_hz=170.0, idle_marks=20, amplitude=0.5,
        )
        strong = generate_fsk_samples(
            "VVV VVV VVV VVV VVV VVV VVV VVV",
            sample_rate=SAMPLE_RATE, center_hz=1650.0, shift_hz=170.0, idle_marks=20, amplitude=2.5,
        )
        n = min(weak.size, strong.size)
        self._run(engine, audio, weak[:n] + strong[:n])

        self.assertGreater(
            abs(engine.signals[key].center_hz - 1650.0),
            30.0,
            "el AFC se fue hacia la señal vecina más fuerte en vez de quedarse en la sintonizada",
        )

    def test_afc_disabled_leaves_the_locked_signal_where_the_operator_put_it(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False
        engine.afc = False
        key = engine.lock_signal(1540.0)
        tone = generate_fsk_samples(
            "CQ TEST DE EA1ABC EA1ABC CQ TEST DE EA1ABC EA1ABC PSE K",
            sample_rate=SAMPLE_RATE, center_hz=1560.0, shift_hz=170.0, idle_marks=20,
        )
        self._run(engine, audio, tone)

        self.assertEqual(engine.signals[key].center_hz, 1540.0)

    def test_afc_holds_the_tuning_while_the_correspondent_is_silent(self):
        # Bug real: cuando el corresponsal paraba de transmitir, el AFC
        # seguía "corrigiendo" hacia el ruido y desintonizaba la estación.
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False
        key = engine.lock_signal(1560.0)
        rng = np.random.default_rng(0)
        self._run(engine, audio, rng.normal(0, 0.05, SAMPLE_RATE * 10).astype(np.float32))

        self.assertEqual(engine.signals[key].center_hz, 1560.0)

    def test_afc_never_moves_further_than_the_band_from_the_operator_tuning(self):
        # Nuestra estación callada y otra a +60 Hz transmitiendo: el centro
        # no puede salir de ±AFC_SEARCH_HALF_HZ de donde sintonizó el operador.
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False
        key = engine.lock_signal(1560.0)
        other = generate_fsk_samples(
            "CQ CQ DE EC3ZZZ EC3ZZZ K CQ CQ DE EC3ZZZ EC3ZZZ K",
            sample_rate=SAMPLE_RATE, center_hz=1620.0, shift_hz=170.0, idle_marks=10,
        )
        self._run(engine, audio, other)

        self.assertLessEqual(abs(engine.signals[key].center_hz - 1560.0), AFC_SEARCH_HALF_HZ)

    def test_afc_leaves_unlocked_auto_detected_signals_alone(self):
        # Solo lo que el operador enganchó a mano: una señal que solo ha
        # detectado el auto-scan (sin enganchar) no se toca.
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False
        engine.signals[154] = RttySignal(
            center_hz=1540.0,
            decoder=RttyDemodulator(sample_rate=SAMPLE_RATE, center_hz=1540.0),
        )
        tone = generate_fsk_samples(
            "CQ TEST DE EA1ABC EA1ABC CQ TEST DE EA1ABC EA1ABC PSE K",
            sample_rate=SAMPLE_RATE, center_hz=1560.0, shift_hz=170.0, idle_marks=20,
        )
        self._run(engine, audio, tone)

        self.assertEqual(engine.signals[154].center_hz, 1540.0)


class RttyEnginePolarityTests(unittest.TestCase):
    """En LSB el audio sale invertido respecto a la RF: mark (RF alta) es el
    tono de audio grave. Sin seguir el modo del equipo, en LSB no se
    decodificaba nada y lo transmitido le llegaba invertido a los demás."""

    @staticmethod
    def _decode_locked(engine, audio, tone):
        key = engine.lock_signal(1500.0)
        tone = np.concatenate([tone, np.zeros(SAMPLE_RATE // 5, dtype=np.float32)])
        for start in range(0, tone.size, 1024):
            audio.push(tone[start : start + 1024])
            engine.tick()
        return engine.signals[key].text

    def test_lsb_receives_with_mark_as_the_low_audio_tone(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio("LSB"), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False
        # Estación normal oída en LSB: mark (RF alta) llega como tono grave.
        tone = generate_fsk_samples("CQ DE EA1ABC K", sample_rate=SAMPLE_RATE, center_hz=1500.0,
                                    shift_hz=-170.0)
        self.assertIn("CQ DE EA1ABC K", self._decode_locked(engine, audio, tone))

    def test_manual_rev_decodes_an_upside_down_station(self):
        audio = FakeAudioModule()
        engine = RttyEngine(audio_module=audio, radio=FakeRadio("USB"), sample_rate=SAMPLE_RATE)
        engine.auto_scan = False
        engine.rx_reverse = True
        tone = generate_fsk_samples("CQ DE EA1ABC K", sample_rate=SAMPLE_RATE, center_hz=1500.0,
                                    shift_hz=-170.0)
        self.assertIn("CQ DE EA1ABC K", self._decode_locked(engine, audio, tone))

    def test_tx_follows_the_sideband_but_not_the_manual_rev(self):
        expected_lsb = generate_fsk_samples("TEST", sample_rate=SAMPLE_RATE, center_hz=1500.0,
                                            shift_hz=-170.0)
        expected_usb = generate_fsk_samples("TEST", sample_rate=SAMPLE_RATE, center_hz=1500.0,
                                            shift_hz=170.0)
        for mode, rev, expected in (("LSB", False, expected_lsb), ("USB", True, expected_usb)):
            with self.subTest(mode=mode, rev=rev):
                audio = FakeAudioModule()
                engine = RttyEngine(audio_module=audio, radio=FakeRadio(mode), sample_rate=SAMPLE_RATE)
                engine.rx_reverse = rev
                engine.send_text("TEST", center_hz=1500.0)
                np.testing.assert_allclose(audio.injected[0][0], expected, atol=1e-6)


class RttyEngineTxTimingTests(unittest.TestCase):
    def _engine(self):
        audio = FakeAudioModule()
        radio = FakeRadio()
        return audio, radio, RttyEngine(audio_module=audio, radio=radio, sample_rate=SAMPLE_RATE)

    def test_ptt_is_held_past_the_end_of_the_audio(self):
        # Bug real: el PTT caía justo al final teórico del audio y se comía
        # el final del mensaje (el número del intercambio).
        audio, _radio, engine = self._engine()
        before = time.monotonic()
        engine.send_text("EA1ABC 599 14", center_hz=1500.0)
        duration = audio.injected[0][0].size / SAMPLE_RATE
        self.assertGreaterEqual(engine._tx_release_at, before + duration + TX_TAIL_SEC)

    def test_long_free_text_is_not_cut_by_the_watchdog(self):
        # Bug real: watchdog fijo de 8 s cortaba textos de más de ~45 letras.
        audio, _radio, engine = self._engine()
        before = time.monotonic()
        engine.send_text("THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG " * 3, center_hz=1500.0)
        duration = audio.injected[0][0].size / SAMPLE_RATE
        self.assertGreater(duration, 8.0)
        self.assertGreaterEqual(engine._tx_deadline, before + duration + TX_TAIL_SEC + TX_WATCHDOG_SEC)

    def test_a_second_macro_is_chained_after_the_first(self):
        audio, radio, engine = self._engine()
        before = time.monotonic()
        engine.send_text("CQ TEST DE EA1ABC", center_hz=1500.0)
        engine.send_text("EA1ABC 599 14", center_hz=1500.0)
        total = sum(a.size for a, _r in audio.injected) / SAMPLE_RATE
        self.assertGreaterEqual(engine._tx_release_at, before + total + TX_TAIL_SEC)

    def test_ptt_waits_while_audio_is_still_queued(self):
        # Medido en el equipo real: el audio empieza a sonar hasta ~0.5 s
        # después del PTT; soltarlo por reloj cortaba el último carácter.
        audio, radio, engine = self._engine()
        pending = {"n": 4800}
        audio.tx_inject_pending_samples = lambda: pending["n"]
        engine.send_text("CQ TEST DE EA1ABC", center_hz=1500.0)
        engine._tx_release_at = time.monotonic() - 0.01  # "ya debería haber acabado"
        audio.push(np.zeros(1, dtype=np.float32))
        engine.tick()
        self.assertEqual(radio.ptt_calls, [True])  # aún suena: no se suelta
        pending["n"] = 0
        engine._tx_release_at = time.monotonic() - 0.01  # pasó el margen tras vaciarse
        audio.push(np.zeros(1, dtype=np.float32))
        engine.tick()
        self.assertEqual(radio.ptt_calls, [True, False])

    def test_escape_abort_drops_ptt_and_flushes_queued_audio(self):
        audio, radio, engine = self._engine()
        engine.send_text("CQ TEST DE EA1ABC EA1ABC", center_hz=1500.0)
        engine.abort_tx()
        self.assertEqual(radio.ptt_calls, [True, False])
        self.assertEqual(audio.injected, [])
        self.assertFalse(engine.transmitting)


class RttyEngineTxTests(unittest.TestCase):
    def test_send_text_arms_ptt_and_injects_audio(self):
        audio = FakeAudioModule()
        radio = FakeRadio()
        engine = RttyEngine(audio_module=audio, radio=radio, sample_rate=SAMPLE_RATE)

        ok = engine.send_text("TEST", center_hz=1500.0)
        self.assertTrue(ok)
        self.assertEqual(radio.ptt_calls, [True])
        self.assertEqual(len(audio.injected), 1)
        samples, rate = audio.injected[0]
        self.assertEqual(rate, SAMPLE_RATE)
        self.assertGreater(samples.size, 0)

    def test_watchdog_releases_ptt_after_message_duration(self):
        audio = FakeAudioModule()
        radio = FakeRadio()
        engine = RttyEngine(audio_module=audio, radio=radio, sample_rate=SAMPLE_RATE)
        engine.send_text("T", center_hz=1500.0)
        self.assertEqual(radio.ptt_calls, [True])

        # Simula que ya pasó el tiempo de la propia duración del mensaje.
        engine._tx_release_at = time.monotonic() - 0.01
        audio.push(np.zeros(1, dtype=np.float32))
        engine.tick()
        self.assertEqual(radio.ptt_calls, [True, False])

    def test_watchdog_forces_ptt_off_if_deadline_exceeded(self):
        audio = FakeAudioModule()
        radio = FakeRadio()
        engine = RttyEngine(audio_module=audio, radio=radio, sample_rate=SAMPLE_RATE)
        engine._tx_deadline = time.monotonic() - 0.01
        engine._tx_release_at = time.monotonic() + 999.0  # aún "en curso"
        audio.push(np.zeros(1, dtype=np.float32))
        engine.tick()
        self.assertEqual(radio.ptt_calls, [False])

    def test_send_text_activates_tx_audio_before_arming_ptt(self):
        # Bug real: send_text() armaba el PTT pero nunca pasaba el pipeline
        # de audio a modo TX -- la radio transmitía sin nada que modulara.
        audio = FakeAudioModule()
        radio = FakeRadio()
        audio_service = FakeAudioService()
        engine = RttyEngine(
            audio_module=audio, radio=radio, audio_service=audio_service, sample_rate=SAMPLE_RATE
        )
        engine.send_text("TEST", center_hz=1500.0)
        self.assertEqual(audio_service.calls, ["start_tx"])
        self.assertEqual(radio.ptt_calls, [True])

        engine._tx_release_at = time.monotonic() - 0.01
        audio.push(np.zeros(1, dtype=np.float32))
        engine.tick()
        self.assertEqual(audio_service.calls, ["start_tx", "stop_tx"])
        self.assertEqual(radio.ptt_calls, [True, False])

    def test_send_text_enables_digi_inject_flag_around_transmission(self):
        # Bug real: la radio armaba el PTT (y hasta el pipeline pasaba a modo
        # TX) pero no salía modulación, porque el bucle TX nativo descarta
        # cualquier chunk de inject_tx_audio() salvo en remoto/WebRTC o con
        # el tono de prueba -- faltaba activar el equivalente para RTTY.
        audio = FakeAudioModule()
        radio = FakeRadio()
        audio_service = FakeAudioService()
        engine = RttyEngine(
            audio_module=audio, radio=radio, audio_service=audio_service, sample_rate=SAMPLE_RATE
        )
        engine.send_text("TEST", center_hz=1500.0)
        self.assertTrue(audio.digi_inject_active)

        engine._tx_release_at = time.monotonic() - 0.01
        audio.push(np.zeros(1, dtype=np.float32))
        engine.tick()
        self.assertFalse(audio.digi_inject_active)
        self.assertEqual(audio.digi_inject_history, [True, False])

    def test_send_text_with_no_injector_returns_false(self):
        class NoInjectAudio:
            def pop_rx_raw_chunk_digi(self):
                return None

        engine = RttyEngine(audio_module=NoInjectAudio(), radio=FakeRadio(), sample_rate=SAMPLE_RATE)
        self.assertFalse(engine.send_text("TEST"))


if __name__ == "__main__":
    unittest.main()
