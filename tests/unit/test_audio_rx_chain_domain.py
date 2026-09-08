import unittest

from audio_rx_chain_domain import (
    rx_chain_gui,
    rx_chain_web,
    sdr_chain_light_gui,
    sdr_chain_light_web,
)


class AudioRxChainDomainTests(unittest.TestCase):
    def test_rx_chain_gui_flow(self):
        calls = []

        def mark(name, ret=b"x"):
            def _fn(*args, **kwargs):
                calls.append(name)
                return ret

            return _fn

        out = rx_chain_gui(
            b"in",
            1,
            48000,
            960,
            context="radio",
            volume=0.5,
            apply_output_boost=True,
            apply_user_gain=True,
            gain_mode="auto",
            web_rx_gain=1.0,
            rx_cleanup_fn=lambda d, ch, sr, ge: mark("cleanup", b"a")(d, ch, sr, ge),
            process_rx_ctx_fn=lambda ctx, d, sr, ch, fs: mark("dsp", b"b")(ctx, d, sr, ch, fs),
            apply_volume_fn=lambda d, v: mark("vol", b"c")(d, v),
            apply_auto_gain_fn=mark("auto", b"d"),
            apply_manual_gain_fn=mark("manual", b"e"),
            apply_gain_extra_rx_fn=mark("extra", b"f"),
            reinforce_pc_output_fn=mark("boost", b"g"),
        )
        self.assertEqual(b"g", out)
        self.assertEqual(["cleanup", "dsp", "vol", "auto", "extra", "boost"], calls)

    def test_rx_chain_web_manual_and_web_gain(self):
        calls = []

        def mark(name, ret=b"x"):
            def _fn(*args, **kwargs):
                calls.append(name)
                return ret

            return _fn

        out = rx_chain_web(
            b"in",
            1,
            48000,
            960,
            context="radio",
            volume=0.5,
            apply_user_gain=True,
            gain_mode="manual",
            web_rx_gain=1.2,
            rx_cleanup_fn=lambda d, ch, sr, ge: mark("cleanup", b"a")(d, ch, sr, ge),
            process_rx_ctx_fn=lambda ctx, d, sr, ch, fs: mark("dsp", b"b")(ctx, d, sr, ch, fs),
            apply_volume_fn=lambda d, v: mark("vol", b"c")(d, v),
            apply_auto_gain_fn=mark("auto", b"d"),
            apply_manual_gain_fn=mark("manual", b"e"),
            apply_factor_lineal_fn=lambda d, f: mark("web_gain", b"f")(d, f),
        )
        self.assertEqual(b"f", out)
        self.assertEqual(["cleanup", "dsp", "vol", "manual", "web_gain"], calls)

    def test_sdr_chain_light_gui_aplica_boost_si_no_es_uno(self):
        calls = []

        def mark(name, ret):
            def _fn(*args, **kwargs):
                calls.append(name)
                return ret

            return _fn

        out = sdr_chain_light_gui(
            b"in",
            0.5,
            output_post_gain=1.5,
            apply_volume_fn=lambda d, v: mark("vol", b"a")(d, v),
            apply_factor_lineal_fn=lambda d, g: mark("boost", b"b")(d, g),
        )
        self.assertEqual(b"b", out)
        self.assertEqual(["vol", "boost"], calls)

    def test_sdr_chain_light_gui_sin_boost_cuando_es_uno(self):
        calls = []

        def mark(name, ret):
            def _fn(*args, **kwargs):
                calls.append(name)
                return ret

            return _fn

        out = sdr_chain_light_gui(
            b"in",
            0.5,
            output_post_gain=1.0,
            apply_volume_fn=lambda d, v: mark("vol", b"a")(d, v),
            apply_factor_lineal_fn=lambda d, g: mark("boost", b"b")(d, g),
        )
        self.assertEqual(b"a", out)
        self.assertEqual(["vol"], calls)

    def test_sdr_chain_light_web_aplica_ganancia_web(self):
        calls = []

        def mark(name, ret):
            def _fn(*args, **kwargs):
                calls.append(name)
                return ret

            return _fn

        out = sdr_chain_light_web(
            b"in",
            0.5,
            web_rx_gain=1.2,
            apply_volume_fn=lambda d, v: mark("vol", b"a")(d, v),
            apply_factor_lineal_fn=lambda d, g: mark("web_gain", b"b")(d, g),
        )
        self.assertEqual(b"b", out)
        self.assertEqual(["vol", "web_gain"], calls)


if __name__ == "__main__":
    unittest.main()
