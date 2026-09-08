import unittest

try:
    import numpy as np
    from audio_signal_domain import (
        apply_volume,
        convert_channels,
        generate_sine_chunk,
        prepare_tx_radio_audio,
    )
    _HAS_NUMPY = True
except ModuleNotFoundError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy no disponible en este entorno")
class AudioSignalDomainTests(unittest.TestCase):
    def test_convert_channels_stereo_to_mono(self):
        samples = np.array([1000, -1000, 2000, -2000], dtype=np.int16)
        out = convert_channels(samples.tobytes(), 2, 1)
        mono = np.frombuffer(out, dtype=np.int16)
        self.assertEqual(2, mono.size)
        self.assertEqual(0, int(mono[0]))

    def test_apply_volume(self):
        samples = np.array([1000, -1000], dtype=np.int16)
        out = apply_volume(samples.tobytes(), 0.5)
        scaled = np.frombuffer(out, dtype=np.int16)
        self.assertEqual(500, int(scaled[0]))
        self.assertEqual(-500, int(scaled[1]))

    def test_apply_volume_saturates_instead_of_wrapping(self):
        samples = np.array([30000, -30000], dtype=np.int16)
        out = apply_volume(samples.tobytes(), 2.0)
        scaled = np.frombuffer(out, dtype=np.int16)
        self.assertEqual(32767, int(scaled[0]))
        self.assertEqual(-32768, int(scaled[1]))

    def test_apply_volume_rejects_non_finite_gain(self):
        samples = np.array([1000, -1000], dtype=np.int16)
        out = apply_volume(samples.tobytes(), float("nan"))
        self.assertEqual([0, 0], np.frombuffer(out, dtype=np.int16).tolist())

    def test_generate_sine_chunk_fase_avanza_modulo_2pi(self):
        # 1000 Hz a 48000 Hz en 480 muestras = exactamente 10 ciclos: la fase
        # vuelve al mismo ángulo (0 y 2π son el mismo punto del círculo; el
        # redondeo de punto flotante puede dar cualquiera de los dos).
        freq, rate, frame = 1000.0, 48000, 480
        step = (2.0 * np.pi * freq) / rate
        _, new_phase = generate_sine_chunk(0.0, step, frame, 0.5)
        self.assertGreaterEqual(new_phase, 0.0)
        self.assertLess(new_phase, 2.0 * np.pi)
        self.assertAlmostEqual(np.sin(new_phase), 0.0, places=3)
        self.assertAlmostEqual(np.cos(new_phase), 1.0, places=3)

    def test_generate_sine_chunk_amplitud_pico(self):
        freq, rate, frame = 1000.0, 48000, 480
        step = (2.0 * np.pi * freq) / rate
        chunk, _ = generate_sine_chunk(0.0, step, frame, 0.3)
        self.assertAlmostEqual(float(np.max(np.abs(chunk))), 0.3, delta=0.01)

    def test_generate_sine_chunk_frecuencia_por_cruces_por_cero(self):
        freq, rate, frame = 1000.0, 48000, 4800  # 100 ms -> ~100 ciclos
        step = (2.0 * np.pi * freq) / rate
        chunk, _ = generate_sine_chunk(0.0, step, frame, 1.0)
        signs = np.sign(chunk)
        crossings = int(np.sum(np.abs(np.diff(signs)) > 0))
        expected = 2 * freq * (frame / rate)  # 200 cruces
        self.assertAlmostEqual(crossings, expected, delta=4)

    def test_prepare_tx_radio_audio_uses_channel_0(self):
        # Frames: [ch0, ch1]
        samples = np.array([100, 900, 200, 800], dtype=np.int16)
        out, channels = prepare_tx_radio_audio(samples.tobytes(), 2, 1)
        mono = np.frombuffer(out, dtype=np.int16)
        self.assertEqual(1, channels)
        self.assertEqual([100, 200], mono.tolist())


if __name__ == "__main__":
    unittest.main()
