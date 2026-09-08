import unittest

from audio_tx_gate_domain import (
    reset_tx_gate_state,
    tx_output_signal_is_ready,
    tx_source_is_easyeffects,
    tx_use_external_dsp_passthrough,
)


class AudioTxGateDomainTests(unittest.TestCase):
    def test_tx_source_is_easyeffects(self):
        self.assertTrue(tx_source_is_easyeffects("easyeffects_source"))
        self.assertFalse(tx_source_is_easyeffects("alsa_input.usb"))

    def test_tx_use_external_dsp_passthrough(self):
        self.assertTrue(
            tx_use_external_dsp_passthrough(
                "mic",
                "easyeffects_source",
                injected_present=False,
                external_dsp_bypass=True,
            )
        )
        self.assertFalse(
            tx_use_external_dsp_passthrough(
                "radio",
                "easyeffects_source",
                injected_present=False,
                external_dsp_bypass=True,
            )
        )
        self.assertFalse(
            tx_use_external_dsp_passthrough(
                "mic",
                "easyeffects_source",
                injected_present=True,
                external_dsp_bypass=True,
            )
        )

    def test_reset_tx_gate_state(self):
        gate = {
            "env": 1.0,
            "hold_until": 2.0,
            "voice_until": 3.0,
            "noise_rms": 0.5,
            "noise_peak": 0.6,
            "start_ts": 0.0,
        }
        hpf = {"x_prev": [1], "y_prev": [2]}
        lpf = {"y_prev": [3]}
        reset_tx_gate_state(gate, hpf, lpf, monotonic=lambda: 42.0)
        self.assertEqual(0.0, gate["env"])
        self.assertEqual(0.0, gate["hold_until"])
        self.assertEqual(0.0, gate["voice_until"])
        self.assertEqual(0.0, gate["noise_rms"])
        self.assertEqual(0.0, gate["noise_peak"])
        self.assertEqual(42.0, gate["start_ts"])
        self.assertIsNone(hpf["x_prev"])
        self.assertIsNone(hpf["y_prev"])
        self.assertIsNone(lpf["y_prev"])

    def test_tx_output_signal_requires_recent_audio_after_ptt(self):
        self.assertTrue(tx_output_signal_is_ready(0.25, 10.1, 10.0, 10.2))
        self.assertFalse(tx_output_signal_is_ready(0.25, 9.9, 10.0, 10.2))
        self.assertFalse(tx_output_signal_is_ready(0.25, 10.0, 9.0, 11.0))
        self.assertFalse(tx_output_signal_is_ready(0.001, 11.0, 10.0, 11.0))


if __name__ == "__main__":
    unittest.main()
