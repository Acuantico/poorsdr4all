import struct
import json
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
import poorsdr.viewers.waterfall as owrx_native

from poorsdr.viewers.waterfall import (
    AUDIO_OUTPUT_RATE,
    CLASSIC_THEME,
    ImaAdpcmDecoder,
    ImaAdpcmStreamDecoder,
    GtkNativeViewer,
    LinearPcm16Resampler,
    NATIVE_DECODER_PATH,
    NativeAdpcmDecoder,
    NativeViewer,
    build_palette,
    band_visible_range,
    bookmark_tune_target,
    decode_fft_payload,
    infer_band,
    levels_to_colors,
    merge_dial_bookmarks,
    nice_tick_step,
    parse_geometry,
    profile_palette,
)


class OwrxNativeProtocolTests(unittest.TestCase):
    def test_uncompressed_fft_is_little_endian_float32(self):
        raw = struct.pack("<3f", -42.5, -10.25, 3.0)
        np.testing.assert_allclose(decode_fft_payload(raw, "none"), [-42.5, -10.25, 3.0])

    def test_adpcm_decoder_matches_openwebrx_nibble_order(self):
        decoder = ImaAdpcmDecoder()
        decoded = decoder.decode(bytes([0x11, 0x72]))
        self.assertEqual(decoded.tolist(), [0, 1, 4, 15])

    def test_adpcm_fft_drops_csdr_padding(self):
        decoded = decode_fft_payload(bytes([0] * 8), "adpcm")
        self.assertEqual(decoded.dtype, np.float32)
        self.assertEqual(decoded.size, 6)

    def test_compiled_decoder_matches_reference_when_available(self):
        if not NATIVE_DECODER_PATH.is_file():
            self.skipTest("native decoder has not been built")
        payload = bytes(range(64))
        expected = ImaAdpcmDecoder().decode(payload)
        actual = NativeAdpcmDecoder().decode(payload)
        np.testing.assert_array_equal(actual, expected)

    def test_audio_adpcm_sync_can_span_websocket_packets(self):
        decoder = ImaAdpcmStreamDecoder()
        self.assertEqual(decoder.decode(b"SY").size, 0)
        decoded = decoder.decode(b"NC" + struct.pack("<hh", 0, 0) + bytes([0x11, 0x72]))
        self.assertEqual(decoded.tolist(), [0, 1, 4, 15])

    def test_audio_resampler_keeps_packet_boundary_continuity(self):
        resampler = LinearPcm16Resampler()
        first = resampler.process(np.asarray([0, 400], dtype=np.int16), 12_000, 48_000)
        second = resampler.process(np.asarray([800], dtype=np.int16), 12_000, 48_000)
        self.assertEqual(first.tolist(), [0, 0, 0, 0, 100, 200, 300, 400])
        self.assertEqual(second.tolist(), [500, 600, 700, 800])

    def test_stream_emits_uncompressed_audio_only_when_capture_is_enabled(self):
        stream = owrx_native.OpenWebRxStream("127.0.0.1", 8073)
        received = []
        stream.set_audio_callback(lambda pcm, rate, channels: received.append((pcm, rate, channels)))
        packet = bytes([2]) + struct.pack("<2h", 0, 400)
        stream._handle_binary(packet)
        self.assertEqual(received, [])
        stream.set_audio_capture(True)
        stream._handle_binary(packet)
        self.assertEqual(len(received), 1)
        pcm, rate, channels = received[0]
        self.assertEqual((rate, channels), (AUDIO_OUTPUT_RATE, 1))
        self.assertEqual(np.frombuffer(pcm, dtype="<i2").tolist(), [0, 0, 0, 0, 100, 200, 300, 400])

    def test_stream_decodes_synchronized_adpcm_audio(self):
        stream = owrx_native.OpenWebRxStream("127.0.0.1", 8073)
        stream.config["audio_compression"] = "adpcm"
        received = []
        stream.set_audio_callback(lambda pcm, rate, channels: received.append(pcm))
        stream.set_audio_capture(True)
        stream._handle_binary(bytes([2]) + b"SYNC" + struct.pack("<hh", 0, 0) + bytes([0x11]))
        self.assertEqual(len(received), 1)
        self.assertEqual(np.frombuffer(received[0], dtype="<i2").size, 8)


class OwrxNativeRenderTests(unittest.TestCase):
    def test_bookmark_tune_target_prefers_explicit_underlying_mode(self):
        target = bookmark_tune_target({
            "frequency": 7_080_000,
            "modulation": "rtty170",
            "underlying": "lsb",
            "source": "dial_frequencies",
        })
        self.assertEqual((7_080_000, "LSB"), target)

    def test_bookmark_tune_target_uses_usb_for_digital_dial_marker(self):
        self.assertEqual(
            (14_074_000, "USB"),
            bookmark_tune_target({
                "frequency": 14_074_000,
                "modulation": "ft8",
                "source": "dial_frequencies",
            }),
        )

    def test_bookmark_tune_target_normalizes_nfm(self):
        self.assertEqual(
            (145_500_000, "FM"),
            bookmark_tune_target({"frequency": 145_500_000, "modulation": "nfm"}),
        )

    def test_palette_interpolates_integer_rgb_anchors(self):
        palette = build_palette([0x000000, 0xFF0000, 0xFFFF00], 5)
        self.assertEqual(palette[0].tolist(), [0, 0, 0])
        self.assertEqual(palette[-1].tolist(), [255, 255, 0])

    def test_levels_clip_and_map_to_palette(self):
        palette = build_palette([0x000000, 0xFFFFFF], 256)
        colors = levels_to_colors(np.asarray([-100.0, -50.0, 0.0]), -100.0, 0.0, palette)
        self.assertEqual(colors[0].tolist(), [0, 0, 0])
        self.assertEqual(colors[-1].tolist(), [255, 255, 255])
        self.assertTrue(120 <= int(colors[1][0]) <= 135)

    def test_tick_step_is_125_decade(self):
        self.assertEqual(nice_tick_step(1_000_000, 1000), 200_000)

    def test_band_inference_covers_poorsdr_hf_profiles(self):
        self.assertEqual(infer_band(7_074_000), "40m")
        self.assertEqual(infer_band(14_074_000), "20m")
        self.assertEqual(infer_band(144_300_000), "")

    def test_40m_base_view_uses_band_edges(self):
        low, high = band_visible_range(7_105_000, 1_000_000, "40m")
        self.assertEqual((low, high), (7_000_000, 7_200_000))

    def test_zoom_has_gentle_steps_and_can_pan_inside_band(self):
        low, high = band_visible_range(7_105_000, 1_000_000, "40m", 1.25, 7_080_000)
        self.assertEqual(high - low, 160_000)
        self.assertEqual((low, high), (7_000_000, 7_160_000))
        low, high = band_visible_range(7_105_000, 1_000_000, "40m", 2.0, 7_150_000)
        self.assertEqual((low, high), (7_100_000, 7_200_000))

    def test_digital_markers_survive_following_bookmark_message(self):
        stream = owrx_native.OpenWebRxStream("127.0.0.1", 8073)
        stream._handle_text(json.dumps({
            "type": "dial_frequencies",
            "value": [{"frequency": 7_074_000, "mode": "ft8"}],
        }))
        stream._handle_text(json.dumps({
            "type": "bookmarks",
            "value": [{"frequency": 7_100_000, "name": "Personal"}],
        }))
        self.assertEqual([item["name"] for item in stream.bookmarks], ["FT8", "Personal"])

    def test_digital_modes_at_same_frequency_are_grouped(self):
        merged = merge_dial_bookmarks([
            {"frequency": 7_078_000, "mode": "jt9", "source": "dial_frequencies"},
            {"frequency": 7_078_000, "mode": "js8", "source": "dial_frequencies"},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "JT9 · JS8")

    def test_profile_palette_follows_background_accent(self):
        red = profile_palette("back.jpg")
        blue = profile_palette("back2.jpg")
        green = profile_palette("/tmp/back1.jpg")
        self.assertGreater(int(red[145][0]), int(red[145][2]))
        self.assertGreater(int(blue[145][2]), int(blue[145][0]))
        self.assertGreater(int(green[145][1]), int(green[145][0]))
        for palette in (red, blue, green):
            self.assertEqual(palette[-1].tolist(), [255, 255, 0])

    def test_profile_palette_classic_uses_fixed_rainbow_not_accent(self):
        # Excepción única del tema Classic: negro -> ... -> blanco fijo, no
        # el degradado derivado del acento plateado (quedaría deslucido).
        classic = profile_palette("back.png")
        classic_from_path = profile_palette("/tmp/back.png")
        self.assertEqual(classic[0].tolist(), [0, 0, 0])
        self.assertEqual(classic[-1].tolist(), [255, 255, 255])
        self.assertEqual(classic.tolist(), build_palette(CLASSIC_THEME).tolist())
        self.assertEqual(classic.tolist(), classic_from_path.tolist())

    def test_viewlock_state_writes_are_atomic(self):
        old_path = owrx_native.STATE_PATH
        try:
            with tempfile.TemporaryDirectory() as directory:
                owrx_native.STATE_PATH = Path(directory) / "state.json"
                owrx_native.STATE_PATH.write_text("", encoding="utf-8")
                viewer = object.__new__(GtkNativeViewer)
                viewer.state_lock = threading.Lock()
                viewer.viewlock_prefs = {"40m": {"zoom": 4.0, "center": 7_100_000}}
                threads = [threading.Thread(target=viewer._save_viewlock_state) for _ in range(12)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                loaded = json.loads(owrx_native.STATE_PATH.read_text(encoding="utf-8"))
                self.assertEqual(loaded["viewlock_prefs"]["40m"]["zoom"], 4.0)
        finally:
            owrx_native.STATE_PATH = old_path

    def test_classic_theme_is_black_to_white(self):
        # Excepción única del tema Classic: negro -> ... -> blanco, estilo
        # SDR#/GQRX, sin importar el acento del tema.
        palette = build_palette(CLASSIC_THEME, 5)
        self.assertEqual(palette[0].tolist(), [0, 0, 0])
        self.assertEqual(palette[-1].tolist(), [255, 255, 255])

    def test_refresh_profile_palette_follows_config_file(self):
        import os

        viewer = object.__new__(NativeViewer)
        viewer.profile_background = ""
        viewer.profile_config_mtime = -1.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"Imagen_Fondo": "back.png"}), encoding="utf-8")
            old_env = os.environ.get("OWRX_CONFIG_PATH")
            os.environ["OWRX_CONFIG_PATH"] = str(path)
            try:
                viewer._refresh_profile_palette()
                self.assertEqual(viewer.profile_background, "back.png")

                # el tema cambia pero el mtime se deja igual a propósito: no
                # debe refrescar (evita releer el fichero en cada frame).
                mtime = path.stat().st_mtime
                path.write_text(json.dumps({"Imagen_Fondo": "back2.jpg"}), encoding="utf-8")
                os.utime(path, (mtime, mtime))
                viewer._refresh_profile_palette()
                self.assertEqual(viewer.profile_background, "back.png")

                # y si el mtime sí avanza, la siguiente lectura coge el nuevo tema
                os.utime(path, (mtime + 5, mtime + 5))
                viewer._refresh_profile_palette()
                self.assertEqual(viewer.profile_background, "back2.jpg")
            finally:
                if old_env is None:
                    os.environ.pop("OWRX_CONFIG_PATH", None)
                else:
                    os.environ["OWRX_CONFIG_PATH"] = old_env

    def test_refresh_profile_palette_without_env_is_a_noop(self):
        import os

        viewer = object.__new__(NativeViewer)
        viewer.profile_background = "back.jpg"
        viewer.profile_config_mtime = -1.0
        old_env = os.environ.pop("OWRX_CONFIG_PATH", None)
        try:
            viewer._refresh_profile_palette()
            self.assertEqual(viewer.profile_background, "back.jpg")  # sin cambios
        finally:
            if old_env is not None:
                os.environ["OWRX_CONFIG_PATH"] = old_env

    def test_geometry_uses_forced_value(self):
        old = __import__("os").environ.get("OWRX_FORCE_GEOMETRY")
        try:
            __import__("os").environ["OWRX_FORCE_GEOMETRY"] = "900x240+12+34"
            self.assertEqual(parse_geometry(1, 1), (900, 240, 12, 34))
        finally:
            if old is None:
                __import__("os").environ.pop("OWRX_FORCE_GEOMETRY", None)
            else:
                __import__("os").environ["OWRX_FORCE_GEOMETRY"] = old

    def test_geometry_falls_back_to_last_saved_window(self):
        old_path = owrx_native.STATE_PATH
        old_forced = __import__("os").environ.pop("OWRX_FORCE_GEOMETRY", None)
        try:
            with tempfile.TemporaryDirectory() as directory:
                owrx_native.STATE_PATH = Path(directory) / "state.json"
                owrx_native.STATE_PATH.write_text(
                    json.dumps({"width": 1100, "height": 310, "x": 45, "y": 520}),
                    encoding="utf-8",
                )
                self.assertEqual(parse_geometry(1, 1), (1100, 310, 45, 520))
        finally:
            owrx_native.STATE_PATH = old_path
            if old_forced is not None:
                __import__("os").environ["OWRX_FORCE_GEOMETRY"] = old_forced


if __name__ == "__main__":
    unittest.main()
