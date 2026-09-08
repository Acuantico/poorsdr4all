import unittest

try:
    import numpy as np
    from audio_rx_domain import apply_rx_frontend, highpass, rx_cleanup
    _HAS_NUMPY = True
except ModuleNotFoundError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy no disponible en este entorno")
class AudioRxDomainTests(unittest.TestCase):
    def test_highpass_keeps_shape(self):
        state = {"prev_x": None, "prev_y": None}
        samples = np.zeros((10, 1), dtype=np.float32)
        out = highpass(samples, 80.0, 48000, state)
        self.assertEqual(samples.shape, out.shape)

    def test_rx_cleanup_returns_pcm_bytes(self):
        state = {"prev_x": None, "prev_y": None}
        samples = (np.sin(np.linspace(0, 2 * np.pi, 960)) * 12000).astype(np.int16)
        out = rx_cleanup(
            samples.tobytes(),
            1,
            48000,
            gate_enabled=True,
            rx_hpf_cutoff=80.0,
            rx_gate_threshold=0.0,
            rx_hpf_state=state,
        )
        out_arr = np.frombuffer(out, dtype=np.int16)
        self.assertEqual(samples.size, out_arr.size)

    def test_apply_rx_frontend_applies_attenuation_callback(self):
        samples = np.array([1000, -1000], dtype=np.int16).tobytes()

        def attenuate(data: bytes) -> bytes:
            arr = np.frombuffer(data, dtype=np.int16).copy()
            arr //= 2
            return arr.tobytes()

        out = apply_rx_frontend(
            samples,
            rx_capture_gain=1.0,
            rx_hum_reduction=False,
            attenuate_input_radio=attenuate,
        )
        out_arr = np.frombuffer(out, dtype=np.int16)
        self.assertEqual([500, -500], out_arr.tolist())


if __name__ == "__main__":
    unittest.main()
