import unittest

try:
    import numpy as np
    from audio_diag_domain import (
        rx_meter_ballistics,
        tx_diag_gate_snapshot,
        tx_diag_metrics,
    )
    _HAS_NUMPY = True
except ModuleNotFoundError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy no disponible en este entorno")
class AudioDiagDomainTests(unittest.TestCase):
    def test_tx_diag_metrics_empty(self):
        self.assertEqual("empty=1", tx_diag_metrics(b"", 1, 48000))

    def test_tx_diag_metrics_contains_core_fields(self):
        samples = (np.sin(np.linspace(0, 2 * np.pi, 960)) * 12000).astype(np.int16)
        metrics = tx_diag_metrics(samples.tobytes(), 1, 48000)
        self.assertIn("rms=", metrics)
        self.assertIn("peak=", metrics)
        self.assertIn("sr=48000", metrics)

    def test_rx_meter_ballistics_sin_datos_devuelve_none(self):
        self.assertIsNone(rx_meter_ballistics(b"", 1, -80.0))

    def test_rx_meter_ballistics_tono_nivel_conocido(self):
        # Amplitud constante 328 ≈ -40 dBFS (20*log10(328/32768)).
        data = np.full(960, 328, dtype=np.int16).tobytes()
        dbfs = rx_meter_ballistics(data, 1, -40.0)  # ya en el nivel objetivo
        self.assertAlmostEqual(dbfs, -40.0, delta=0.5)

    def test_rx_meter_ballistics_ataque_mas_rapido_que_liberacion(self):
        # Nota: ``prev_dbfs`` no puede ser 0.0 exacto (el código original lo
        # trata como "sin valor previo" vía ``prev_dbfs or -120.0`` — mismo
        # comportamiento que tenía inline, se conserva tal cual).
        # Subida (tono fuerte, ~0 dBFS, desde -60): ataque, alpha=0.30.
        fuerte = np.full(960, 32767, dtype=np.int16).tobytes()
        subida = rx_meter_ballistics(fuerte, 1, -60.0)
        frac_subida = abs(subida - (-60.0)) / 60.0
        # Bajada (tono flojo, ~-40 dBFS, desde -1): liberación, alpha=0.10.
        flojo = np.full(960, 328, dtype=np.int16).tobytes()
        bajada = rx_meter_ballistics(flojo, 1, -1.0)
        frac_bajada = abs(bajada - (-1.0)) / 39.0
        self.assertAlmostEqual(frac_subida, 0.30, delta=0.02)
        self.assertAlmostEqual(frac_bajada, 0.10, delta=0.02)
        self.assertGreater(frac_subida, frac_bajada)

    def test_tx_diag_gate_snapshot(self):
        state = {
            "env": 0.4,
            "hold_until": 12.0,
            "voice_until": 14.0,
            "noise_rms": 0.01,
            "noise_peak": 0.03,
        }
        snap = tx_diag_gate_snapshot(state, now=10.0)
        self.assertIn("env=0.4000", snap)
        self.assertIn("hold_left=2.000", snap)
        self.assertIn("voice_left=4.000", snap)


if __name__ == "__main__":
    unittest.main()
