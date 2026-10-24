"""tx_playback: temporización exacta, vaciado de pacat y decodificadores (WAV propio, ffmpeg, PyAV)."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

from poorsdr.services.tx_playback import (  # noqa: E402
    UnsupportedAudio,
    decode_wav,
    open_source,
    play_through_pacat,
    play_through_stream,
    precise_wait,
)


class _Sink(io.BytesIO):
    """BytesIO que conserva lo escrito aunque se cierre (como una tubería ya vaciada)."""

    def __init__(self):
        super().__init__()
        self.data = b""

    def write(self, b):
        self.data += bytes(b)
        return super().write(b)

    def flush(self):
        pass


class _Player:
    """pacat simulado."""

    def __init__(self, *, drains: bool = True):
        self.stdin = _Sink()
        self._drains = drains
        self.terminated = False
        self.waited = False
        self.stdin_closed_at_wait: bool | None = None
        self._rc: int | None = None

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        self.waited = True
        self.stdin_closed_at_wait = self.stdin.closed
        if not self._drains:
            raise subprocess.TimeoutExpired("pacat", timeout)
        self._rc = 0
        return 0

    def terminate(self):
        self.terminated = True
        self._rc = -15


class _Src:
    """Decodificador simulado: entrega ``data`` por bloques."""

    def __init__(self, data: bytes):
        self._d = io.BytesIO(data)
        self.closed = False

    def read(self, n):
        return self._d.read(n)

    def close(self):
        self.closed = True


def _factory(src):
    return lambda path, rate, channels, **_kw: src


_KW = dict(sink="sink", rate=48000, channels=1, latency_ms=20)


def _popen(player):
    return lambda cmd, **_kw: player


class PlayThroughPacatTests(unittest.TestCase):
    def test_espera_a_que_pacat_vacie_en_vez_de_matarlo(self):
        # Regresión: el módulo heredado hacía terminate() justo tras escribir y
        # se perdía el final (~0,6 s) que aún estaba en la tubería.
        audio = b"\x01\x00" * 10_000
        pl = _Player()
        ok = play_through_pacat(
            "a.wav", popen=_popen(pl), source_factory=_factory(_Src(audio)), **_KW
        )
        self.assertTrue(ok)
        self.assertEqual(pl.stdin.data, audio)      # todo el audio se entregó
        self.assertTrue(pl.waited)                   # se esperó a que vaciara
        self.assertTrue(pl.stdin_closed_at_wait)     # ...tras cerrar la entrada (EOF)
        self.assertFalse(pl.terminated)              # y no se mató

    def test_on_ready_se_llama_antes_de_escribir_la_primera_muestra(self):
        pl = _Player()
        seen = {}

        def on_ready():
            seen["written_before"] = pl.stdin.data
            return True

        play_through_pacat(
            "a.wav", on_ready=on_ready, popen=_popen(pl),
            source_factory=_factory(_Src(b"\x01\x00" * 100)), **_KW,
        )
        self.assertEqual(seen["written_before"], b"")

    def test_on_ready_false_no_emite_nada(self):
        pl = _Player()
        ok = play_through_pacat(
            "a.wav", on_ready=lambda: False, popen=_popen(pl),
            source_factory=_factory(_Src(b"\x01\x00" * 100)), **_KW,
        )
        self.assertFalse(ok)
        self.assertEqual(pl.stdin.data, b"")

    def test_archivo_no_decodificable_devuelve_false_sin_lanzar_pacat(self):
        launched = []

        def popen(cmd, **_kw):
            launched.append(cmd[0])
            return _Player()

        self.assertFalse(play_through_pacat(
            "mal.wav", popen=popen, source_factory=lambda *a, **k: None, **_KW))
        self.assertEqual(launched, [])

    def test_stop_corta_y_mata_el_reproductor(self):
        pl = _Player(drains=False)
        src = _Src(b"\x01\x00" * 50_000)
        ok = play_through_pacat(
            "a.wav", stop_checker=lambda: True, popen=_popen(pl),
            source_factory=_factory(src), **_KW,
        )
        self.assertTrue(ok)
        self.assertEqual(pl.stdin.data, b"")
        self.assertTrue(pl.terminated)
        self.assertTrue(src.closed)


class _Stream:
    def __init__(self):
        self.data = b""
        self.stopped = self.closed = False

    def write(self, b):
        self.data += bytes(b)

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


class PlayThroughStreamTests(unittest.TestCase):
    _kw = dict(rate=48000, channels=1)

    def test_escribe_todo_y_cierra_el_stream(self):
        audio = b"\x02\x00" * 5_000
        st = _Stream()
        ok = play_through_stream(
            "a.wav", open_stream=lambda: st, source_factory=_factory(_Src(audio)), **self._kw
        )
        self.assertTrue(ok)
        self.assertEqual(st.data, audio)
        self.assertTrue(st.stopped and st.closed)

    def test_on_ready_antes_de_la_primera_muestra(self):
        st = _Stream()
        seen = {}

        def on_ready():
            seen["antes"] = st.data
            return True

        play_through_stream(
            "a.wav", open_stream=lambda: st, on_ready=on_ready,
            source_factory=_factory(_Src(b"\x01\x00" * 50)), **self._kw,
        )
        self.assertEqual(seen["antes"], b"")

    def test_sin_dispositivo_configurado_devuelve_false(self):
        ok = play_through_stream(
            "a.wav", open_stream=lambda: None,
            source_factory=_factory(_Src(b"\x01\x00" * 50)), **self._kw,
        )
        self.assertFalse(ok)


def _write_wav(path, *, rate=8000, channels=1, width=2, seconds=0.5, freq=440.0):
    n = int(rate * seconds)
    t = np.arange(n) / rate
    x = np.sin(2 * np.pi * freq * t) * 0.5
    if width == 1:
        data = ((x * 127) + 128).astype(np.uint8)
    elif width == 2:
        data = (x * 32767).astype("<i2")
    elif width == 4:
        data = (x * 2147483647).astype("<i4")
    elif width == 3:
        v = (x * 8388607).astype(np.int32)
        data = np.stack([(v >> 0) & 255, (v >> 8) & 255, (v >> 16) & 255], axis=1).astype(np.uint8)
    frames = np.repeat(data.reshape(n, -1), channels, axis=1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(frames.tobytes())


class DecodeWavTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _read_all(self, src):
        out = b""
        while True:
            c = src.read(4096)
            if not c:
                return out
            out += c

    def test_longitud_y_formato_tras_convertir_frecuencia_y_canales(self):
        p = self.dir / "a.wav"
        _write_wav(p, rate=8000, channels=1, seconds=0.5)
        pcm = self._read_all(decode_wav(str(p), 48000, 2))
        self.assertEqual(len(pcm), int(48000 * 0.5) * 2 * 2)   # s16 estéreo
        a = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2)
        self.assertTrue(np.array_equal(a[:, 0], a[:, 1]))      # mono duplicado
        self.assertGreater(int(np.abs(a).max()), 10_000)       # hay señal, no silencio

    def test_estereo_a_mono_promedia(self):
        p = self.dir / "s.wav"
        _write_wav(p, rate=48000, channels=2, seconds=0.2)
        pcm = self._read_all(decode_wav(str(p), 48000, 1))
        self.assertEqual(len(pcm), int(48000 * 0.2) * 2)

    def test_anchuras_8_24_y_32_bits(self):
        for width in (1, 3, 4):
            with self.subTest(width=width):
                p = self.dir / f"w{width}.wav"
                _write_wav(p, rate=16000, width=width, seconds=0.25)
                pcm = self._read_all(decode_wav(str(p), 16000, 1))
                a = np.frombuffer(pcm, dtype="<i2")
                self.assertEqual(len(a), 4000)
                self.assertGreater(int(np.abs(a).max()), 10_000)

    def test_mantiene_la_frecuencia_del_tono(self):
        p = self.dir / "f.wav"
        _write_wav(p, rate=8000, seconds=1.0, freq=500.0)
        a = np.frombuffer(self._read_all(decode_wav(str(p), 48000, 1)), dtype="<i2").astype(float)
        spec = np.abs(np.fft.rfft(a))
        peak_hz = np.argmax(spec) * 48000 / len(a)
        self.assertAlmostEqual(peak_hz, 500.0, delta=2.0)

    def test_no_wav_lanza_unsupported(self):
        p = self.dir / "x.wav"
        p.write_bytes(b"ID3\x03\x00" + b"\x00" * 100)    # no es RIFF/WAVE
        with self.assertRaises(UnsupportedAudio):
            decode_wav(str(p), 48000, 1)

    def test_wav_float_lanza_unsupported(self):
        # WAVE_FORMAT_IEEE_FLOAT (3): ``wave`` no lo soporta → se debe probar otro decodificador.
        p = self.dir / "float.wav"
        data = np.zeros(100, dtype="<f4").tobytes()
        hdr = (b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
               + (3).to_bytes(2, "little") + (1).to_bytes(2, "little") + (8000).to_bytes(4, "little")
               + (32000).to_bytes(4, "little") + (4).to_bytes(2, "little") + (32).to_bytes(2, "little")
               + b"data" + len(data).to_bytes(4, "little"))
        p.write_bytes(hdr + data)
        with self.assertRaises(UnsupportedAudio):
            decode_wav(str(p), 8000, 1)


class OpenSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_wav_no_necesita_ffmpeg(self):
        p = self.dir / "a.wav"
        _write_wav(p)
        called = []
        src = open_source(str(p), 8000, 1, ffmpeg="no-existe-ffmpeg",
                          popen=lambda *a, **k: called.append(1))
        self.assertIsNotNone(src)
        self.assertEqual(called, [])                      # ni se intentó lanzar ffmpeg
        self.assertTrue(src.read(100))

    def test_archivo_inexistente_devuelve_none(self):
        self.assertIsNone(open_source(str(self.dir / "no.wav"), 8000, 1))

    def test_no_wav_usa_ffmpeg_si_existe(self):
        p = self.dir / "a.mp3"
        p.write_bytes(b"ID3" + b"\x00" * 50)
        fake_ffmpeg = self.dir / "ffmpeg"
        fake_ffmpeg.write_text("#!/bin/sh\n")
        launched = []

        class _P:
            stdout = io.BytesIO(b"\x01\x00" * 10)
            stdin = None

            def poll(self):
                return 0

        def popen(cmd, **_kw):
            launched.append(cmd[0])
            return _P()

        src = open_source(str(p), 8000, 1, ffmpeg=str(fake_ffmpeg), popen=popen)
        self.assertIsNotNone(src)
        self.assertEqual(launched, [str(fake_ffmpeg)])

    def test_sin_ffmpeg_ni_pyav_devuelve_none(self):
        p = self.dir / "a.mp3"
        p.write_bytes(b"ID3" + b"\x00" * 50)
        saved = sys.modules.get("av", ...)
        sys.modules["av"] = None            # fuerza ImportError al hacer ``import av``
        try:
            self.assertIsNone(open_source(str(p), 8000, 1, ffmpeg="no-existe-ffmpeg"))
        finally:
            if saved is ...:
                sys.modules.pop("av", None)
            else:
                sys.modules["av"] = saved


@unittest.skipUnless(importlib.util.find_spec("av"), "PyAV no instalado")
class AvFallbackTests(unittest.TestCase):
    """El respaldo sin ffmpeg: PyAV decodifica un mp3 de verdad."""

    def test_mp3_sin_ffmpeg_se_decodifica_con_pyav(self):
        import av

        with tempfile.TemporaryDirectory() as d:
            mp3 = Path(d) / "tono.mp3"
            rate, n = 44100, 44100  # 1 s
            t = np.arange(n) / rate
            pcm = (np.sin(2 * np.pi * 600 * t) * 0.5 * 32767).astype("<i2").reshape(1, -1)
            out = av.open(str(mp3), "w")
            stream = out.add_stream("libmp3lame", rate=rate)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
            frame.sample_rate = rate
            for packet in stream.encode(frame):
                out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
            out.close()

            src = open_source(str(mp3), 48000, 1, ffmpeg="no-existe-ffmpeg")
            self.assertIsNotNone(src)
            data = b""
            while True:
                c = src.read(4096)
                if not c:
                    break
                data += c
            src.close()
        a = np.frombuffer(data, dtype="<i2").astype(float)
        self.assertGreater(len(a), 40_000)                       # ~1 s a 48 kHz
        peak_hz = np.argmax(np.abs(np.fft.rfft(a))) * 48000 / len(a)
        self.assertAlmostEqual(peak_hz, 600.0, delta=5.0)


class PreciseWaitTests(unittest.TestCase):
    def test_precision_submilimetrica_razonable(self):
        for target in (0.05, 0.2):
            t0 = time.perf_counter()
            self.assertTrue(precise_wait(target, lambda: False))
            elapsed = time.perf_counter() - t0
            self.assertGreaterEqual(elapsed, target)
            self.assertLess(elapsed - target, 0.05)   # nunca antes; tarde solo si la máquina va muy cargada

    def test_cancelada_devuelve_false_enseguida(self):
        t0 = time.perf_counter()
        self.assertFalse(precise_wait(5.0, lambda: True))
        self.assertLess(time.perf_counter() - t0, 0.05)

    def test_cero_no_espera(self):
        self.assertTrue(precise_wait(0.0, lambda: False))


if __name__ == "__main__":
    unittest.main()
