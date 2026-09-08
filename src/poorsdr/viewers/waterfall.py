#!/usr/bin/env python3
"""Native, browser-free OpenWebRX spectrum/waterfall viewer for PoorSDR4All."""

from __future__ import annotations

import base64
import ctypes
import json
import math
import os
import queue
import re
import signal
import socket
import socketserver
import struct
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from poorsdr.i18n import t
from poorsdr.infra import paths as app_paths

# The minimal Raspberry Pi session has no accessibility bus.  Avoid starting
# an AT-SPI bridge for this small, dedicated viewer.
os.environ.setdefault("NO_AT_BRIDGE", "1")

try:
    import tkinter as tk
    from PIL import ImageTk
except ImportError:  # Protocol/render unit tests can run on headless build hosts.
    tk = None
    ImageTk = None

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    import cairo
except (ImportError, ValueError, AttributeError):
    Gdk = GLib = Gtk = cairo = None

def runtime_path(*rel: str) -> str:
    configured = os.environ.get("POORSDR_RUNTIME_DIR", "").strip()
    base = Path(configured).expanduser() if configured else app_paths.runtime_dir()
    return str(app_paths.ensure_dir(base).joinpath(*rel))


LOG_PATH = app_paths.ensure_dir(app_paths.log_dir()) / "owrx_native.log"
STATE_PATH = Path(os.environ.get("POORSDR_WATERFALL_STATE_PATH") or runtime_path("waterfall_state.json"))
WINDOW_EDIT_PATH = Path(runtime_path(".window_edit_mode"))
FFT_PAD_SAMPLES = 10
DEFAULT_THEME = (0x000000, 0x310000, 0x960000, 0xFF0000, 0xFF7800, 0xFFFF00)
#: Excepción única del tema Classic (back.png): la propia imagen de la
#: cascada (no solo el acento) usa este arcoíris fijo estilo SDR#/GQRX en vez
#: del waterfall_colors que mande el servidor OWRX. Espejo en
#: poorsdr.core.theme.CLASSIC_CASCADA_COLORS, salvo que build_palette()
#: reparte las paradas a posiciones equiespaciadas (no admite posiciones
#: explícitas): el negro se repite varias veces para que ocupe ~mitad de la
#: escala, igual que en la versión con posiciones — si no, ruido de fondo o
#: silencio ya se verían en azul/cian en vez de negro.
CLASSIC_THEME = (
    0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000,
    0x000030, 0x0000FF, 0x00FFFF, 0x00FF00, 0xFFFF00, 0xFF8000, 0xFF0000, 0xFFFFFF,
)
PROFILE_ACCENTS = {
    "back.png": "#7b8794",
    "back.jpg": "#f10a0a",
    "back0.jpg": "#ffd200",
    "back1.jpg": "#36f715",
    "back2.jpg": "#0314ec",
    "back3.jpg": "#dc12b0",
}
def _native_decoder_filename() -> str:
    if sys.platform.startswith("win"):
        return "poorsdr_fft_adpcm.dll"
    if sys.platform == "darwin":
        return "libpoorsdr_fft_adpcm.dylib"
    return "libpoorsdr_fft_adpcm.so"


NATIVE_DECODER_PATH = Path(runtime_path(_native_decoder_filename()))
AUDIO_SERVER_RATE = 12_000
AUDIO_OUTPUT_RATE = 48_000


def display_scale() -> float:
    try:
        return min(1.0, max(0.1, float(os.environ.get("POORSDR_DISPLAY_SCALE", "1") or 1)))
    except (TypeError, ValueError):
        return 1.0


def kiosk_mode() -> bool:
    """Modo pantalla fija sin bordes (pensado para paneles dedicados, p. ej.
    una Raspberry Pi con pantalla táctil): la ventana pierde la decoración
    de la ventana (barra de título, bordes de redimensionado) y solo se
    puede reposicionar/redimensionar creando el marcador
    ``WINDOW_EDIT_PATH``. Antes esto se activaba solo con
    ``display_scale() < 1.0`` — confirmado en real: eso hacía que la
    cascada, en cualquier pantalla más pequeña que la de referencia (no
    solo en un panel dedicado), se quedara sin bordes y sin forma de
    ajustarla a mano. Ahora es un interruptor aparte, explícito y
    desactivado por defecto: reescalar el contenido para que quepa en una
    pantalla pequeña no debe implicar perder el control normal de la
    ventana en un escritorio corriente.
    """
    return str(os.environ.get("POORSDR_WATERFALL_KIOSK", "") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def waterfall_fps() -> int:
    """Frecuencia de refresco del render.

    En escritorio la cascada puede ir fluida (~30 fps); en la Raspberry
    (display_scale < 1) se mantiene baja para ahorrar CPU. Override:
    POORSDR_WATERFALL_FPS.
    """
    env = os.environ.get("POORSDR_WATERFALL_FPS", "")
    if env.strip():
        try:
            return max(2, min(60, int(float(env))))
        except (TypeError, ValueError):
            pass
    return 30 if display_scale() >= 1.0 else 4


def log(message: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
    except Exception:
        pass


def parse_geometry(width: int, height: int) -> tuple[int, int, int, int]:
    scale = display_scale()
    min_width = max(220, int(round(520 * scale)))
    min_height = max(90, int(round(220 * scale)))
    candidates = [str(os.environ.get("OWRX_FORCE_GEOMETRY", "") or "").strip()]
    try:
        loaded = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            candidates.append(
                f"{int(loaded.get('width', 0))}x{int(loaded.get('height', 0))}"
                f"+{int(loaded.get('x', 0)):+d}+{int(loaded.get('y', 0)):+d}"
                .replace("++", "+")
            )
    except Exception:
        pass
    for value in candidates:
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", value)
        if match:
            w_raw, h_raw, x_raw, y_raw = match.groups()
            return max(min_width, int(w_raw)), max(min_height, int(h_raw)), int(x_raw), int(y_raw)
    return max(min_width, int(width or 900)), max(min_height, int(height or 420)), 0, 0


class ImaAdpcmDecoder:
    INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8)
    STEP_TABLE = (
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
        34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
        143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
        494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
        1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
        4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
        11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
        27086, 29794, 32767,
    )

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.step_index = 0
        self.predictor = 0
        self.step = 0

    def decode_nibble(self, nibble: int) -> int:
        nibble &= 0x0F
        self.step_index = min(88, max(0, self.step_index + self.INDEX_TABLE[nibble]))
        diff = self.step >> 3
        if nibble & 1:
            diff += self.step >> 2
        if nibble & 2:
            diff += self.step >> 1
        if nibble & 4:
            diff += self.step
        if nibble & 8:
            diff = -diff
        self.predictor = min(32767, max(-32768, self.predictor + diff))
        self.step = self.STEP_TABLE[self.step_index]
        return self.predictor

    def decode(self, data: bytes) -> np.ndarray:
        out = np.empty(len(data) * 2, dtype=np.int16)
        pos = 0
        for byte in data:
            out[pos] = self.decode_nibble(byte)
            out[pos + 1] = self.decode_nibble(byte >> 4)
            pos += 2
        return out


class NativeAdpcmDecoder:
    def __init__(self, path: Path = NATIVE_DECODER_PATH) -> None:
        self.library = ctypes.CDLL(str(path))
        self.function = self.library.poorsdr_fft_adpcm_decode
        self.function.argtypes = (
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int16), ctypes.c_size_t,
        )
        self.function.restype = ctypes.c_size_t

    def reset(self) -> None:
        return

    def decode(self, data: bytes) -> np.ndarray:
        source = np.frombuffer(data, dtype=np.uint8)
        output = np.empty(source.size * 2, dtype=np.int16)
        count = int(self.function(
            source.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)), source.size,
            output.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), output.size,
        ))
        return output[:count]


def create_adpcm_decoder():
    try:
        return NativeAdpcmDecoder()
    except Exception as exc:
        log(f"native ADPCM unavailable: {exc!r}")
        return ImaAdpcmDecoder()


class ImaAdpcmStreamDecoder:
    """Stateful OpenWebRX audio ADPCM decoder, including periodic SYNC frames."""

    def __init__(self) -> None:
        self.codec = ImaAdpcmDecoder()
        self.reset()

    def reset(self) -> None:
        self.codec.reset()
        self.phase = 0
        self.synchronized = 0
        self.sync_buffer = bytearray()
        self.sync_counter = 0

    def decode(self, data: bytes) -> np.ndarray:
        output = np.empty(len(data) * 2, dtype=np.int16)
        output_index = 0
        sync_word = b"SYNC"
        for value in data:
            if self.phase == 0:
                expected = sync_word[self.synchronized]
                self.synchronized += 1
                if value != expected:
                    self.synchronized = 0
                if self.synchronized == len(sync_word):
                    self.sync_buffer.clear()
                    self.phase = 1
            elif self.phase == 1:
                self.sync_buffer.append(value)
                if len(self.sync_buffer) == 4:
                    step_index, predictor = struct.unpack("<hh", self.sync_buffer)
                    self.codec.step_index = min(88, max(0, int(step_index)))
                    self.codec.predictor = min(32767, max(-32768, int(predictor)))
                    self.sync_counter = 1000
                    self.phase = 2
            else:
                output[output_index] = self.codec.decode_nibble(value & 0x0F)
                output[output_index + 1] = self.codec.decode_nibble(value >> 4)
                output_index += 2
                if self.sync_counter == 0:
                    self.synchronized = 0
                    self.phase = 0
                else:
                    self.sync_counter -= 1
        return output[:output_index]


class LinearPcm16Resampler:
    """Small streaming integer-ratio interpolator for OWRX voice audio."""

    def __init__(self) -> None:
        self.previous_sample: float | None = None

    def reset(self) -> None:
        self.previous_sample = None

    def process(self, samples: np.ndarray, input_rate: int, output_rate: int) -> np.ndarray:
        values = np.asarray(samples, dtype=np.float32)
        if values.size == 0:
            return np.zeros(0, dtype=np.int16)
        source_rate = max(1, int(input_rate))
        target_rate = max(1, int(output_rate))
        if source_rate == target_rate:
            self.previous_sample = float(values[-1])
            return np.clip(values, -32768, 32767).astype(np.int16)
        factor = target_rate // source_rate
        if factor < 1 or factor * source_rate != target_rate:
            raise ValueError(f"unsupported audio resampling ratio {source_rate}->{target_rate}")
        starts = np.empty(values.size, dtype=np.float32)
        starts[0] = values[0] if self.previous_sample is None else self.previous_sample
        if values.size > 1:
            starts[1:] = values[:-1]
        weights = np.arange(1, factor + 1, dtype=np.float32) / float(factor)
        expanded = starts[:, None] + (values - starts)[:, None] * weights[None, :]
        self.previous_sample = float(values[-1])
        return np.clip(expanded.reshape(-1), -32768, 32767).astype(np.int16)


def decode_fft_payload(payload: bytes, compression: str, decoder: ImaAdpcmDecoder | None = None) -> np.ndarray:
    if str(compression or "none").lower() == "adpcm":
        codec = decoder or ImaAdpcmDecoder()
        codec.reset()
        decoded = codec.decode(payload)
        if decoded.size <= FFT_PAD_SAMPLES:
            return np.zeros(0, dtype=np.float32)
        return decoded[FFT_PAD_SAMPLES:].astype(np.float32) / 100.0
    usable = len(payload) - (len(payload) % 4)
    if usable <= 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(payload[:usable], dtype="<f4").copy()


def build_palette(theme=None, size: int = 256) -> np.ndarray:
    anchors = list(theme or DEFAULT_THEME)
    rgb: list[tuple[int, int, int]] = []
    for value in anchors:
        try:
            if isinstance(value, (list, tuple)) and len(value) >= 3:
                rgb.append(tuple(max(0, min(255, int(v))) for v in value[:3]))
            else:
                number = int(value)
                rgb.append(((number >> 16) & 255, (number >> 8) & 255, number & 255))
        except Exception:
            continue
    if len(rgb) < 2:
        rgb = [(0, 0, 0), (255, 255, 255)]
    src = np.linspace(0.0, 1.0, len(rgb))
    dst = np.linspace(0.0, 1.0, max(2, int(size)))
    arr = np.asarray(rgb, dtype=np.float32)
    return np.stack([np.interp(dst, src, arr[:, channel]) for channel in range(3)], axis=1).astype(np.uint8)


def levels_to_colors(values: np.ndarray, minimum: float, maximum: float, palette: np.ndarray) -> np.ndarray:
    span = max(1e-6, float(maximum) - float(minimum))
    normalized = np.clip((np.asarray(values, dtype=np.float32) - float(minimum)) / span, 0.0, 1.0)
    indexes = np.asarray(normalized * (len(palette) - 1), dtype=np.int32)
    return palette[indexes]


def nice_tick_step(span_hz: float, width: int) -> float:
    target = max(2.0, float(width) / 145.0)
    raw = max(1.0, float(span_hz) / target)
    power = 10.0 ** math.floor(math.log10(raw))
    fraction = raw / power
    factor = 1.0 if fraction <= 1.0 else 2.0 if fraction <= 2.0 else 5.0 if fraction <= 5.0 else 10.0
    return factor * power


BAND_LIMITS = {
    "160m": (1_810_000.0, 2_000_000.0),
    "80m": (3_500_000.0, 3_800_000.0),
    "60m": (5_351_500.0, 5_366_500.0),
    "40m": (7_000_000.0, 7_200_000.0),
    "30m": (10_100_000.0, 10_150_000.0),
    "20m": (14_000_000.0, 14_350_000.0),
    "17m": (18_068_000.0, 18_168_000.0),
    "15m": (21_000_000.0, 21_450_000.0),
    # PoorSDR también usa la zona extendida de 11 m para sus perfiles.
    "11m": (26_965_000.0, 27_860_000.0),
    "10m": (28_000_000.0, 29_700_000.0),
}


def infer_band(freq_hz: float) -> str:
    value = float(freq_hz or 0)
    return next((band for band, (low, high) in BAND_LIMITS.items() if low <= value < high), "")


def band_visible_range(
    center_hz: float, sample_rate: float, band: str, zoom: float = 1.0,
    view_center_hz: float = 0.0,
) -> tuple[float, float]:
    """Return a zoomed range constrained to the selected band and receiver data."""
    receiver_low = float(center_hz) - max(1.0, float(sample_rate)) / 2.0
    receiver_high = float(center_hz) + max(1.0, float(sample_rate)) / 2.0
    desired_low, desired_high = BAND_LIMITS.get(band, (receiver_low, receiver_high))
    base_low = max(receiver_low, desired_low)
    base_high = min(receiver_high, desired_high)
    if base_high <= base_low:
        base_low, base_high = receiver_low, receiver_high
    span = (base_high - base_low) / max(1.0, float(zoom))
    view_center = float(view_center_hz or ((base_low + base_high) / 2.0))
    half = span / 2.0
    # El desplazamiento (arrastre) puede salir de los limites de la banda, pero
    # nunca de los datos que entrega el receptor.
    lo_bound = min(base_low, receiver_low + half)
    hi_bound = max(base_high, receiver_high - half)
    view_center = min(hi_bound, max(lo_bound, view_center))
    return view_center - half, view_center + half


def merge_dial_bookmarks(bookmarks: list[dict]) -> list[dict]:
    """Merge digital-mode markers sharing a dial frequency into one flag."""
    result: list[dict] = []
    grouped: dict[int, dict] = {}
    for bookmark in bookmarks:
        if str(bookmark.get("source") or "") != "dial_frequencies":
            result.append(bookmark)
            continue
        try:
            frequency = int(float(bookmark.get("frequency", bookmark.get("freq", 0)) or 0))
        except (TypeError, ValueError):
            continue
        mode = str(bookmark.get("name") or bookmark.get("mode") or bookmark.get("modulation") or "DIGI").upper()
        if frequency not in grouped:
            grouped[frequency] = dict(bookmark, frequency=frequency, name=mode)
            result.append(grouped[frequency])
        else:
            names = grouped[frequency]["name"].split(" · ")
            if mode not in names:
                grouped[frequency]["name"] += f" · {mode}"
    return result


def bookmark_tune_target(bookmark: dict, fallback_mode: str = "USB") -> tuple[int, str]:
    """Resolve the exact dial frequency and PoorSDR mode for a marker."""
    try:
        frequency = int(float(bookmark.get("frequency", bookmark.get("freq", 0)) or 0))
    except (AttributeError, TypeError, ValueError):
        frequency = 0
    underlying = bookmark.get("underlying", "") if isinstance(bookmark, dict) else ""
    if isinstance(underlying, (list, tuple)):
        underlying = next((value for value in underlying if value), "")
    candidates = [
        underlying,
        bookmark.get("modulation", "") if isinstance(bookmark, dict) else "",
        bookmark.get("mode", "") if isinstance(bookmark, dict) else "",
        bookmark.get("name", "") if isinstance(bookmark, dict) else "",
    ]
    for candidate in candidates:
        value = str(candidate or "").strip().upper()
        if value == "NFM" or value == "FM":
            return frequency, "FM"
        if value in ("AM", "USB", "LSB"):
            return frequency, value
        if "LSB" in value:
            return frequency, "LSB"
        if "USB" in value:
            return frequency, "USB"
        if value in ("SSB", "PHONE"):
            return frequency, "LSB" if frequency and frequency < 10_000_000 else "USB"
    # OpenWebRX digital dial-frequency markers (FT8, FT4, WSPR, JS8,
    # RTTY, PSK, CW...) are conventionally tuned using an upper sideband
    # receiver. An explicit underlying mode above always takes precedence.
    if str(bookmark.get("source", "") if isinstance(bookmark, dict) else "") == "dial_frequencies":
        return frequency, "USB"
    joined = " ".join(str(value or "").upper() for value in candidates)
    if any(token in joined for token in (
        "CW", "FT8", "FT4", "WSPR", "JS8", "JT9", "JT65", "FST4",
        "Q65", "RTTY", "PSK", "SITOR", "DIGI",
    )):
        return frequency, "USB"
    normalized_fallback = str(fallback_mode or "USB").upper()
    return frequency, normalized_fallback if normalized_fallback in ("AM", "FM", "USB", "LSB") else "USB"


def profile_accent(background_name: str) -> tuple[int, int, int]:
    value = PROFILE_ACCENTS.get(Path(str(background_name or "")).name, PROFILE_ACCENTS["back.jpg"])
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def profile_palette(background_name: str) -> np.ndarray:
    """Build a black -> theme accent -> yellow waterfall palette.

    Excepción única del tema Classic (back.png): arcoíris fijo estilo
    SDR#/GQRX en vez del degradado derivado del acento — en Classic el
    acento es un plateado apagado que quedaría deslucido en la cascada.
    """
    if Path(str(background_name or "")).name == "back.png":
        return build_palette(CLASSIC_THEME)
    accent = profile_accent(background_name)

    def rgb(scale: float) -> int:
        channels = [min(255, round(channel * scale)) for channel in accent]
        return (channels[0] << 16) | (channels[1] << 8) | channels[2]

    # The penultimate anchor blends the theme with yellow.  The highest
    # intensities always finish in yellow, as in a classic SDR waterfall.
    blend = tuple(round(channel * 0.52 + yellow * 0.48) for channel, yellow in zip(accent, (255, 255, 0)))
    blend_rgb = (blend[0] << 16) | (blend[1] << 8) | blend[2]
    return build_palette((0x000000, rgb(0.14), rgb(0.38), rgb(0.72), rgb(1.0), blend_rgb, 0xFFFF00))


class OpenWebRxStream:
    def __init__(self, host: str, port: int, lang: str = "es") -> None:
        self.host = host
        self.port = int(port)
        self._lang = lang
        self.stop_event = threading.Event()
        self.commands: "queue.Queue[dict]" = queue.Queue(maxsize=128)
        self.lock = threading.Lock()
        self.latest_fft: np.ndarray | None = None
        self.fft_sequence = 0
        self.config: dict = {}
        self.profiles: list[dict] = []
        self.bookmarks: list[dict] = []
        self.server_bookmarks: list[dict] = []
        self.dial_frequencies: list[dict] = []
        self.bands: list[dict] = []
        self.status = t("waterfall_connecting", self._lang)
        self._thread: threading.Thread | None = None
        self._decoder = create_adpcm_decoder()
        self._audio_decoders = {2: ImaAdpcmStreamDecoder(), 4: ImaAdpcmStreamDecoder()}
        self._audio_resamplers = {2: LinearPcm16Resampler(), 4: LinearPcm16Resampler()}
        self._audio_capture_enabled = False
        self._audio_callback = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="owrx_native_stream")
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def send(self, payload: dict) -> None:
        try:
            self.commands.put_nowait(dict(payload))
        except queue.Full:
            try:
                self.commands.get_nowait()
                self.commands.put_nowait(dict(payload))
            except Exception:
                pass

    def set_audio_capture(self, enabled: bool) -> None:
        with self.lock:
            self._audio_capture_enabled = bool(enabled)

    def set_audio_callback(self, callback) -> None:
        with self.lock:
            self._audio_callback = callback

    def snapshot(self) -> tuple[np.ndarray | None, int, dict, list[dict], list[dict], list[dict], str]:
        with self.lock:
            return (
                self.latest_fft,
                self.fft_sequence,
                dict(self.config),
                list(self.profiles),
                list(self.bookmarks),
                list(self.bands),
                self.status,
            )

    def _set_status(self, value: str) -> None:
        with self.lock:
            self.status = value

    def _handle_text(self, raw: str) -> None:
        if not raw or raw.startswith("CLIENT DE SERVER"):
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        kind = str(payload.get("type") or "")
        value = payload.get("value")
        with self.lock:
            if kind in ("config", "update") and isinstance(value, dict):
                self.config.update(value)
            elif kind == "profiles" and isinstance(value, list):
                self.profiles = [item for item in value if isinstance(item, dict)]
            elif kind in ("bookmarks", "dial_frequencies") and isinstance(value, list):
                if kind == "bookmarks":
                    self.server_bookmarks = [dict(item, source=str(item.get("source") or "server"))
                                             for item in value if isinstance(item, dict)]
                else:
                    self.dial_frequencies = [
                        dict(
                            item,
                            name=str(item.get("mode") or item.get("name") or "DIGI").upper(),
                            modulation=str(item.get("mode") or item.get("modulation") or ""),
                            source="dial_frequencies",
                        )
                        for item in value if isinstance(item, dict)
                    ]
                # These messages arrive independently and in either order.
                # Keep both sets instead of allowing the last one to erase the other.
                self.bookmarks = merge_dial_bookmarks(self.dial_frequencies) + self.server_bookmarks
            elif kind == "bands" and isinstance(value, list):
                self.bands = [item for item in value if isinstance(item, dict)]
            elif kind in ("sdr_error", "backoff", "log_message"):
                self.status = str(value or kind)

    def _handle_binary(self, raw: bytes) -> None:
        if not raw:
            return
        packet_type = int(raw[0])
        if packet_type in (2, 4):
            self._handle_audio(packet_type, raw[1:])
            return
        if packet_type != 1:
            return
        with self.lock:
            compression = str(self.config.get("fft_compression", "none") or "none")
            expected_size = int(self.config.get("fft_size", 0) or 0)
        values = decode_fft_payload(raw[1:], compression, self._decoder)
        # OpenWebRX+'s ADPCM decoder yields two samples per compressed byte;
        # its canvases consume exactly fft_size values and clip the padding/tail.
        if expected_size > 0 and values.size > expected_size:
            values = values[:expected_size]
        if values.size:
            with self.lock:
                self.latest_fft = values
                self.fft_sequence += 1
                self.status = t("waterfall_connected", self._lang)

    def _handle_audio(self, packet_type: int, payload: bytes) -> None:
        with self.lock:
            compression = str(self.config.get("audio_compression", "none") or "none").lower()
            capture_enabled = bool(self._audio_capture_enabled)
            callback = self._audio_callback
        if compression == "adpcm":
            samples = self._audio_decoders[packet_type].decode(payload)
        else:
            usable = len(payload) - (len(payload) % 2)
            samples = np.frombuffer(payload[:usable], dtype="<i2").copy() if usable else np.zeros(0, dtype=np.int16)
        if samples.size == 0 or not capture_enabled or callback is None:
            return
        try:
            converted = self._audio_resamplers[packet_type].process(
                samples, AUDIO_SERVER_RATE, AUDIO_OUTPUT_RATE
            )
            if converted.size:
                callback(converted.astype("<i2", copy=False).tobytes(), AUDIO_OUTPUT_RATE, 1)
        except Exception as exc:
            log(f"audio packet error type={packet_type}: {exc!r}")

    def _run(self) -> None:
        from websockets.sync.client import connect

        ws_url = f"ws://{self.host}:{self.port}/ws/"
        while not self.stop_event.is_set():
            try:
                self._set_status(t("waterfall_connecting", self._lang))
                with connect(
                    ws_url, origin=None, open_timeout=4, close_timeout=1,
                    ping_interval=None, max_size=8 * 1024 * 1024,
                ) as ws:
                    for decoder in self._audio_decoders.values():
                        decoder.reset()
                    for resampler in self._audio_resamplers.values():
                        resampler.reset()
                    ws.send("SERVER DE CLIENT client=PoorSDR4All-native type=receiver")
                    ws.send(json.dumps({"type": "connectionproperties", "params": {
                        "output_rate": AUDIO_SERVER_RATE,
                        "hd_output_rate": AUDIO_SERVER_RATE,
                    }}))
                    self._set_status(t("waterfall_waiting_fft", self._lang))
                    while not self.stop_event.is_set():
                        while True:
                            try:
                                ws.send(json.dumps(self.commands.get_nowait()))
                            except queue.Empty:
                                break
                        try:
                            raw = ws.recv(timeout=0.18)
                        except TimeoutError:
                            continue
                        if isinstance(raw, str):
                            self._handle_text(raw)
                        elif isinstance(raw, (bytes, bytearray)):
                            self._handle_binary(bytes(raw))
            except Exception as exc:
                self._set_status(
                    t("waterfall_reconnecting", self._lang).format(error=type(exc).__name__)
                )
                log(f"stream reconnect {exc!r}")
                self.stop_event.wait(1.2)


class SpiderStream:
    def __init__(self, host: str) -> None:
        self.host = host
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.spots: list[dict] = []
        # Segundos que un spot permanece visible antes de caducar (configurable
        # desde Ajustes → Spots; por defecto 10 min, como el original).
        self.retention_sec = 600

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="owrx_native_spider").start()

    def stop(self) -> None:
        self.stop_event.set()

    def snapshot(self) -> list[dict]:
        cutoff = int(time.time()) - max(30, int(self.retention_sec or 600))
        with self.lock:
            self.spots = [spot for spot in self.spots if int(spot.get("time", 0) or 0) >= cutoff]
            return list(self.spots)

    def _accept(self, item) -> None:
        if not isinstance(item, dict):
            return
        try:
            freq = int(round(float(item.get("freq", 0))))
        except Exception:
            return
        call = str(item.get("call", "") or "").upper().strip()
        if freq <= 0 or not call:
            return
        spot = {
            "freq": freq,
            "call": call[:12],
            "mode": str(item.get("mode", "") or "").upper(),
            # Hora de RECEPCION: el 'time' del feed puede venir desfasado varias
            # horas y snapshot() descartaria el spot al instante.
            "time": int(time.time()),
        }
        with self.lock:
            for old in reversed(self.spots):
                if old.get("call") == call and abs(int(old.get("freq", 0)) - freq) <= 120:
                    old.update(spot)
                    break
            else:
                self.spots.append(spot)
            if len(self.spots) > 1200:
                del self.spots[:-1200]

    def _handle(self, raw) -> None:
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if isinstance(payload, list):
            values = payload
        elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
            values = payload["data"]
        elif isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            values = [payload["data"]]
        elif isinstance(payload, dict) and isinstance(payload.get("spot"), dict):
            values = [payload["spot"]]
        else:
            values = [payload]
        for item in values:
            self._accept(item)
        n = getattr(self, "_ingest_count", 0) + 1
        self._ingest_count = n
        if n % 500 == 0:
            log(f"spider ingest #{n} buffered={len(self.spots)}")

    def _run(self) -> None:
        from websockets.sync.client import connect

        # Native Raspberry Pi installs expose spiderd directly on 7373.  Keep
        # 17373 as the legacy Docker mapping fallback.
        urls = [f"ws://{self.host}:7373/spots", f"ws://{self.host}:17373/spots"]
        while not self.stop_event.is_set():
            for url in urls:
                if self.stop_event.is_set():
                    return
                try:
                    with connect(
                        url, origin=None, open_timeout=2, close_timeout=1,
                        ping_interval=None, max_size=2 * 1024 * 1024,
                    ) as ws:
                        log(f"spider connected {url}")
                        while not self.stop_event.is_set():
                            try:
                                raw = ws.recv(timeout=1.0)
                            except TimeoutError:
                                continue
                            except TypeError:
                                # websockets < 13 no acepta recv(timeout=...)
                                raw = ws.recv()
                            self._handle(raw)
                except Exception as exc:
                    log(f"spider ws error url={url} err={exc!r}")
                    continue
            self.stop_event.wait(2.0)


class NativeViewer:
    def __init__(
        self,
        root: tk.Tk,
        stream: OpenWebRxStream,
        spider: SpiderStream,
        width: int,
        height: int,
        x: int,
        y: int,
        command_port: int,
        control_host: str,
        control_port: int,
    ) -> None:
        self.root = root
        self.stream = stream
        self.spider = spider
        self.command_port = int(command_port)
        self.control_host = control_host
        self.control_port = int(control_port)
        self.stop_event = threading.Event()
        self.pending_commands: "queue.Queue[dict]" = queue.Queue(maxsize=128)
        self.outbound: "queue.Queue[dict | None]" = queue.Queue(maxsize=128)
        self.server = None
        self.width = width
        self.height = height
        self.last_fft_sequence = -1
        self.waterfall: np.ndarray | None = None
        self.spectrum_smooth: np.ndarray | None = None
        self.palette = build_palette()
        self.palette_signature = ""
        self.profile_background = ""
        self.profile_config_mtime = -1.0
        self.photo = None
        self.tuned_frequency = 0
        self.mode = "USB"
        self.step_hz = 1000
        self.zoom = 1.0
        self.zoom_center = 0.0
        self.spots_enabled = True
        self.spot_modes = {"CW", "DIGI", "SSB"}
        self.last_geometry_save = 0.0
        self.drag_start_x: float | None = None
        self.drag_start_center = 0.0
        self.drag_start_span = 0.0
        self.drag_moved = False
        self.deferred_profile: dict | None = None
        self.last_tune_signature = None
        self._last_smeter_emit = 0.0

        root.title("Waterfall")
        edit_at_start = WINDOW_EDIT_PATH.exists()
        if kiosk_mode():
            root.overrideredirect(not edit_at_start)
            if edit_at_start:
                screen_height = int(root.winfo_screenheight())
                y = max(26, min(int(y) + 26, screen_height - int(height)))
        root.configure(bg="#08090b")
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(520, 220)
        self.canvas = tk.Canvas(root, bg="#08090b", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind(
            "<Button-4>",
            lambda event: self._zoom_at(event.x, 1) if int(getattr(event, "state", 0)) & 0x4 else self._tune_step(1),
        )
        self.canvas.bind(
            "<Button-5>",
            lambda event: self._zoom_at(event.x, -1) if int(getattr(event, "state", 0)) & 0x4 else self._tune_step(-1),
        )
        root.bind("<KeyPress>", self._on_key)
        root.protocol("WM_DELETE_WINDOW", self.close)
        signal.signal(signal.SIGTERM, lambda *_: root.after(0, self.close))
        signal.signal(signal.SIGINT, lambda *_: root.after(0, self.close))

        self._start_command_server()
        if self.control_host and self.control_port:
            threading.Thread(target=self._send_control_loop, daemon=True, name="owrx_native_control").start()
        self.stream.set_audio_callback(self._emit_audio_chunk)
        self.stream.start()
        self.spider.start()
        root.after(30, self._process_commands)
        root.after(80, self._render)

    def _start_command_server(self) -> None:
        if not self.command_port:
            return
        viewer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                data = b""
                self.request.settimeout(0.5)
                try:
                    while b"\n" not in data and len(data) < 1024 * 1024:
                        part = self.request.recv(65536)
                        if not part:
                            break
                        data += part
                except Exception:
                    pass
                try:
                    payload = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
                    if isinstance(payload, dict):
                        viewer.pending_commands.put_nowait(payload)
                except Exception:
                    pass

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", self.command_port), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="owrx_native_commands").start()

    def _send_control_loop(self) -> None:
        sock = None
        while not self.stop_event.is_set():
            try:
                if sock is None:
                    sock = socket.create_connection((self.control_host, self.control_port), timeout=1.0)
                    sock.settimeout(2.0)
                try:
                    payload = self.outbound.get(timeout=0.5)
                except queue.Empty:
                    continue
                if payload is None:
                    break
                sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            except Exception:
                try:
                    if sock:
                        sock.close()
                except Exception:
                    pass
                sock = None
                self.stop_event.wait(0.5)
        try:
            if sock:
                sock.close()
        except Exception:
            pass

    def _emit(self, payload: dict) -> None:
        try:
            self.outbound.put_nowait(payload)
        except queue.Full:
            pass

    def _emit_audio_chunk(self, pcm: bytes, sample_rate: int, channels: int) -> None:
        if not pcm or self.stop_event.is_set():
            return
        self._emit({
            "type": "audio_chunk",
            "pcm": base64.b64encode(pcm).decode("ascii"),
            "sample_rate": int(sample_rate),
            "channels": int(channels),
        })

    def _process_commands(self) -> None:
        if self.stop_event.is_set():
            return
        while True:
            try:
                command = self.pending_commands.get_nowait()
            except queue.Empty:
                break
            kind = str(command.get("type") or "")
            if kind == "close":
                self.close()
                return
            if kind == "tune":
                if command.get("frequency") is not None:
                    self.tuned_frequency = int(float(command["frequency"]))
                if command.get("mode"):
                    self.mode = str(command["mode"]).upper()
                self._send_tune_to_stream()
                # PoorSDR holds reverse tuning during startup until the viewer
                # confirms the requested value.  The browser bridge did this
                # through report_tune; the native viewer must do the same.
                self._emit({
                    "type": "tune", "frequency": self.tuned_frequency,
                    "modulation": self.mode.lower(), "view_mode": "owrx",
                })
            elif kind == "step":
                self.step_hz = max(1, int(command.get("step_hz") or 1))
            elif kind == "profile":
                if not self._select_profile(command):
                    self.deferred_profile = command
            elif kind == "spots":
                self.spots_enabled = bool(command.get("enabled")) and not bool(command.get("off"))
                modes = command.get("modes")
                if isinstance(modes, list):
                    self.spot_modes = {str(mode).upper() for mode in modes}
                if command.get("retention_sec") is not None:
                    self.spider.retention_sec = max(30, int(command.get("retention_sec") or 600))
            elif kind == "audio_capture":
                self.stream.set_audio_capture(bool(command.get("enabled")))
        if self.deferred_profile and self._select_profile(self.deferred_profile):
            self.deferred_profile = None
        self.root.after(30, self._process_commands)

    def _select_profile(self, command: dict) -> bool:
        target = str(command.get("profile") or "").lower().strip()
        sdr_hint = str(command.get("sdr") or "").lower().strip()
        _fft, _seq, _cfg, profiles, _marks, _bands, _status = self.stream.snapshot()
        candidates = profiles
        if sdr_hint:
            hinted = [p for p in profiles if sdr_hint in str(p.get("id", "")).lower()]
            if hinted:
                candidates = hinted
        match = next(
            (p for p in candidates if target and target in f"{p.get('id', '')} {p.get('name', '')}".lower()),
            None,
        )
        if not match and target:
            # Reserva: emparejar por el token de banda del objetivo ("RTL 80m",
            # "RTL-3 160m" -> "80m" / "160m") contra el nombre del perfil.
            m = re.search(r"\d+\s*c?m", target)
            tok = m.group(0).replace(" ", "") if m else ""
            if tok:
                match = next(
                    (p for p in candidates
                     if re.search(r"(?<![0-9a-z])" + re.escape(tok) + r"(?![0-9a-z])",
                                  str(p.get("name", "")).lower())),
                    None,
                )
        if not match:
            return False
        params = {"profile": str(match.get("id") or "")}
        if command.get("key"):
            params["key"] = str(command["key"])
        self.stream.send({"type": "selectprofile", "params": params})
        self.zoom = 1.0
        # A new profile changes center_freq.  Force the desired app frequency
        # to be sent again when the new profile configuration arrives.
        self.last_tune_signature = None
        return True

    def _send_tune_to_stream(self) -> None:
        _fft, _seq, config, _profiles, _marks, _bands, _status = self.stream.snapshot()
        center = int(config.get("center_freq", 0) or 0)
        params = {}
        if self.tuned_frequency and center:
            params["offset_freq"] = int(self.tuned_frequency - center)
        mod = self.mode.lower()
        if mod == "fm":
            mod = "nfm"
        if mod in ("am", "nfm", "usb", "lsb", "cw"):
            params["mod"] = mod
            cuts = {
                "am": (-4000, 4000), "nfm": (-4000, 4000),
                "usb": (150, 2750), "lsb": (-2750, -150),
                "cw": (300, 700),
            }[mod]
            params["low_cut"], params["high_cut"] = cuts
        if params:
            signature = (center, self.tuned_frequency, self.mode)
            if signature == self.last_tune_signature:
                return
            self.last_tune_signature = signature
            self.stream.send({"type": "dspcontrol", "action": "start"})
            self.stream.send({"type": "dspcontrol", "params": params})

    def _refresh_profile_palette(self) -> None:
        """Detecta si el tema de PoorSDR (consola) cambió a/desde Classic.

        El visor es un proceso aparte: no le llega ningún evento cuando
        cambias de tema en Ajustes, así que vigila el mismo config.json (por
        mtime) que usa la consola. Solo importa para saber si toca forzar el
        arcoíris fijo de Classic; el resto de temas siguen dejando que
        ``waterfall_colors`` (el que manda el propio servidor OWRX) pinte la
        cascada, igual que siempre.
        """
        path = Path(os.environ.get("OWRX_CONFIG_PATH") or "")
        if not path.is_file():
            return
        try:
            mtime = path.stat().st_mtime
            if mtime == self.profile_config_mtime:
                return
            self.profile_config_mtime = mtime
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            self.profile_background = Path(str(loaded.get("Imagen_Fondo") or "back.jpg")).name
        except Exception:
            pass

    def _visible_range(self, config: dict) -> tuple[float, float]:
        center = float(config.get("center_freq", 0) or 0)
        bandwidth = max(1.0, float(config.get("samp_rate", 1) or 1))
        band = infer_band(self.tuned_frequency) or infer_band(center)
        return band_visible_range(center, bandwidth, band, self.zoom, self.zoom_center)

    def _frequency_at(self, x: int, config: dict) -> int:
        low, high = self._visible_range(config)
        return int(round(low + (max(0, min(self.width - 1, x)) / max(1, self.width - 1)) * (high - low)))

    def _on_click(self, event) -> None:
        _fft, _seq, config, _profiles, _marks, _bands, _status = self.stream.snapshot()
        frequency = self._frequency_at(event.x, config)
        step = max(1, int(self.step_hz))
        frequency = int(round(frequency / step) * step)
        self.tuned_frequency = frequency
        self._send_tune_to_stream()
        self._emit({"type": "tune", "frequency": frequency, "modulation": self.mode.lower(), "view_mode": "owrx", "user": True})

    def _on_wheel(self, event) -> None:
        direction = 1 if getattr(event, "delta", 0) > 0 else -1
        if int(getattr(event, "state", 0)) & 0x4:  # Ctrl -> zoom
            self._zoom_at(event.x, direction)
        else:
            self._tune_step(direction)

    def _tune_step(self, direction: int) -> None:
        step = max(1, int(getattr(self, "step_hz", 0) or 0) or 1000)
        base = int(self.tuned_frequency or 0)
        if base <= 0:
            _f, _s, config, *_rest = self.stream.snapshot()
            base = int(config.get("center_freq", 0) or 0)
        new_freq = int(round((base + direction * step) / step) * step)
        if new_freq == int(self.tuned_frequency or 0):
            return
        self.tuned_frequency = new_freq
        self.last_tune_signature = None
        self._send_tune_to_stream()
        self._emit({
            "type": "tune", "frequency": new_freq,
            "modulation": self.mode.lower(), "view_mode": "owrx", "user": True,
        })

    def _zoom_at(self, x: int, direction: int) -> None:
        _fft, _seq, config, _profiles, _marks, _bands, _status = self.stream.snapshot()
        focus = self._frequency_at(x, config)
        levels = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0)
        current = min(range(len(levels)), key=lambda index: abs(levels[index] - self.zoom))
        current = max(0, min(len(levels) - 1, current + (1 if direction > 0 else -1)))
        self.zoom = levels[current]
        self.zoom_center = float(focus)

    def _on_key(self, event) -> None:
        key = str(event.keysym or event.char or "")
        mods = []
        if event.state & 0x4:
            mods.append("Ctrl")
        if event.state & 0x8:
            mods.append("Alt")
        if event.state & 0x1:
            mods.append("Shift")
        mapped = "+".join(mods + [key]) if mods else key
        self._emit({"type": "hotkey", "key": mapped})

    def _resample_fft(self, fft: np.ndarray, config: dict, width: int) -> np.ndarray:
        if fft.size == 0:
            return np.zeros(width, dtype=np.float32)
        center = float(config.get("center_freq", 0) or 0)
        bandwidth = max(1.0, float(config.get("samp_rate", 1) or 1))
        low, high = self._visible_range(config)
        start_ratio = np.clip((low - (center - bandwidth / 2.0)) / bandwidth, 0.0, 1.0)
        end_ratio = np.clip((high - (center - bandwidth / 2.0)) / bandwidth, 0.0, 1.0)
        positions = np.linspace(start_ratio * (fft.size - 1), end_ratio * (fft.size - 1), width)
        return np.interp(positions, np.arange(fft.size), fft).astype(np.float32)

    def _update_smeter(self, values: np.ndarray, config: dict) -> None:
        """Calcula el nivel dBFS dentro de la banda de paso sintonizada y lo
        manda a PoorSDR (throttled) como S-metro: el µSDX no lo da por CAT,
        pero OWRX ya tiene esta señal calculada para pintar el espectro.
        """
        now = time.monotonic()
        if now - self._last_smeter_emit < 0.15 or values.size == 0 or not self.tuned_frequency:
            return
        low, high = self._visible_range(config)
        span = max(1.0, high - low)
        cuts = {
            "AM": (-4000, 4000), "FM": (-4000, 4000),
            "USB": (150, 2750), "LSB": (-2750, -150), "CW": (300, 700),
        }.get(self.mode, (-1000, 1000))
        x1 = int((self.tuned_frequency + cuts[0] - low) / span * self.width)
        x2 = int((self.tuned_frequency + cuts[1] - low) / span * self.width)
        x1, x2 = sorted((max(0, min(values.size - 1, x1)), max(0, min(values.size - 1, x2))))
        window = values[x1 : x2 + 1]
        if window.size == 0:
            return
        self._last_smeter_emit = now
        # El dBFS en bruto: PoorSDR autocalibra la escala siguiendo el "suelo"
        # real de la banda (poorsdr.core.smeter.NoiseFloorTracker), así que
        # aquí no hace falta mandar ningún rango calibrado.
        self._emit({"type": "smeter", "dbfs": round(float(np.percentile(window, 90.0)), 1)})

    def _draw_scale(self, image: Image.Image, draw: ImageDraw.ImageDraw, config: dict, scale_h: int) -> None:
        low, high = self._visible_range(config)
        span = max(1.0, high - low)
        step = nice_tick_step(span, self.width)
        first = math.ceil(low / step) * step
        font = ImageFont.load_default()
        value = first
        while value <= high + 0.5 * step:
            x = int(round((value - low) / span * max(1, self.width - 1)))
            draw.line((x, scale_h - 10, x, scale_h - 1), fill=(155, 164, 174))
            label = f"{value / 1_000_000:.3f}"
            box = draw.textbbox((0, 0), label, font=font)
            draw.text((x - (box[2] - box[0]) // 2, 3), label, fill=(220, 224, 230), font=font)
            value += step
        draw.line((0, scale_h - 1, self.width, scale_h - 1), fill=(96, 100, 108))

    def _draw_spectrum(self, image: Image.Image, draw: ImageDraw.ImageDraw, values: np.ndarray, top: int, height: int) -> None:
        if values.size == 0 or height <= 2:
            return
        minimum = float(np.percentile(values, 87.0))
        maximum = float(np.percentile(values, 99.7))
        if maximum <= minimum + 0.1:
            maximum = minimum + 1.0
        normalized = np.clip((values - minimum) / (maximum - minimum), 0.0, 1.0)
        normalized = np.where(normalized < 0.28, normalized * 1.32,
            np.where(normalized < 0.72, 0.37 + (normalized - 0.28) * 0.62, 0.64 + (normalized - 0.72) * 1.18))
        normalized = np.clip(normalized, 0.0, 1.0) ** 1.02
        if self.spectrum_smooth is None or self.spectrum_smooth.size != values.size:
            self.spectrum_smooth = normalized.copy()
        else:
            self.spectrum_smooth = self.spectrum_smooth * 0.72 + normalized * 0.28
        ys = top + height - 2 - self.spectrum_smooth * (height - 4)
        points = [(x, int(ys[x])) for x in range(min(self.width, ys.size))]
        if not points:
            return
        # Excepción Classic: relleno azul marino (a juego con el arcoíris fijo
        # de la cascada) en vez del rojo oscuro del resto de temas.
        fill = (6, 20, 40) if self.profile_background == "back.png" else (70, 10, 3)
        draw.polygon([(0, top + height - 1)] + points + [(points[-1][0], top + height - 1)], fill=fill)
        draw.line(points, fill=(255, 194, 0), width=1)

    def _draw_passband(self, draw: ImageDraw.ImageDraw, config: dict, top: int, bottom: int) -> None:
        if not self.tuned_frequency:
            return
        low, high = self._visible_range(config)
        span = max(1.0, high - low)
        cuts = {
            "AM": (-4000, 4000), "FM": (-4000, 4000),
            "USB": (150, 2750), "LSB": (-2750, -150), "CW": (300, 700),
        }.get(self.mode, (-1000, 1000))
        x1 = int((self.tuned_frequency + cuts[0] - low) / span * self.width)
        x2 = int((self.tuned_frequency + cuts[1] - low) / span * self.width)
        cursor = int((self.tuned_frequency - low) / span * self.width)
        if x2 >= 0 and x1 <= self.width:
            draw.rectangle((max(0, x1), top, min(self.width - 1, x2), bottom), fill=(38, 92, 120))
        if 0 <= cursor < self.width:
            draw.line((cursor, top, cursor, bottom), fill=(255, 230, 80), width=1)

    @staticmethod
    def _spot_class(mode: str) -> str:
        value = str(mode or "").upper()
        if "CW" in value:
            return "CW"
        if value in ("USB", "LSB", "SSB", "PHONE", "AM", "FM"):
            return "SSB"
        return "DIGI"

    def _draw_spots(self, draw: ImageDraw.ImageDraw, config: dict, top: int, bottom: int) -> None:
        if not self.spots_enabled:
            return
        low, high = self._visible_range(config)
        span = max(1.0, high - low)
        spots = self.spider.snapshot()
        lanes: list[list[tuple[int, int]]] = [[] for _ in range(7)]
        font = ImageFont.load_default()
        colors = {"CW": (46, 220, 90), "SSB": (255, 215, 40), "DIGI": (180, 100, 255)}
        for spot in sorted(spots, key=lambda value: int(value.get("freq", 0))):
            freq = int(spot.get("freq", 0) or 0)
            category = self._spot_class(str(spot.get("mode", "")))
            if category not in self.spot_modes or not (low <= freq <= high):
                continue
            x = int((freq - low) / span * self.width)
            label = str(spot.get("call", ""))[:12]
            box = draw.textbbox((0, 0), label, font=font)
            label_w = box[2] - box[0] + 9
            left = max(1, min(self.width - label_w - 1, x))
            lane = next((i for i, used in enumerate(lanes) if all(left > end + 4 or left + label_w < start - 4 for start, end in used)), None)
            if lane is None:
                continue
            lanes[lane].append((left, left + label_w))
            y = top + 3 + lane * 15
            if y + 13 >= bottom:
                continue
            draw.rounded_rectangle((left, y, left + label_w, y + 13), radius=3, fill=(10, 12, 16), outline=(92, 98, 108))
            draw.rectangle((left, y, left + 3, y + 13), fill=colors[category])
            draw.text((left + 6, y + 1), label, fill=(234, 242, 255), font=font)

    def _render(self) -> None:
        if self.stop_event.is_set():
            return
        self.width = max(1, int(self.canvas.winfo_width()))
        self.height = max(1, int(self.canvas.winfo_height()))
        fft, sequence, config, _profiles, _bookmarks, _bands, status = self.stream.snapshot()
        if self.tuned_frequency and int(config.get("center_freq", 0) or 0):
            self._send_tune_to_stream()
        scale_h = 27
        spectrum_h = max(44, min(76, int(self.height * 0.29)))
        waterfall_top = scale_h + spectrum_h
        waterfall_h = max(1, self.height - waterfall_top)
        if fft is not None and fft.size:
            values = self._resample_fft(fft, config, self.width)
        else:
            values = np.zeros(self.width, dtype=np.float32)
        self._update_smeter(values, config)

        self._refresh_profile_palette()
        is_classic = self.profile_background == "back.png"
        theme = config.get("waterfall_colors")
        signature = f"classic:{is_classic}|{theme!r}"
        if signature != self.palette_signature:
            self.palette = build_palette(CLASSIC_THEME if is_classic else (theme or DEFAULT_THEME))
            self.palette_signature = signature
        levels = config.get("waterfall_levels") if isinstance(config.get("waterfall_levels"), dict) else {}
        minimum = float(levels.get("min", -60.0) or -60.0)
        maximum = float(levels.get("max", -10.0) or -10.0)
        if maximum <= minimum:
            maximum = minimum + 1.0
        if self.waterfall is None or self.waterfall.shape != (waterfall_h, self.width, 3):
            self.waterfall = np.zeros((waterfall_h, self.width, 3), dtype=np.uint8)
        if sequence != self.last_fft_sequence and fft is not None:
            self.waterfall[1:] = self.waterfall[:-1]
            self.waterfall[0] = levels_to_colors(values, minimum, maximum, self.palette)
            self.last_fft_sequence = sequence

        image = Image.new("RGB", (self.width, self.height), (8, 9, 11))
        draw = ImageDraw.Draw(image)
        self._draw_scale(image, draw, config, scale_h)
        self._draw_spectrum(image, draw, values, scale_h, spectrum_h)
        if self.waterfall is not None:
            image.paste(Image.fromarray(self.waterfall, mode="RGB"), (0, waterfall_top))
        draw = ImageDraw.Draw(image, "RGB")
        self._draw_passband(draw, config, scale_h, self.height - 1)
        self._draw_spots(draw, config, waterfall_top, self.height - 1)
        if not sequence:
            draw.text((10, waterfall_top + 10), status, fill=(225, 225, 225), font=ImageFont.load_default())
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfigure(self.image_item, image=self.photo)
        now = time.monotonic()
        if now - self.last_geometry_save >= 1.0:
            self.last_geometry_save = now
            self._save_geometry()
        self.root.after(max(15, int(round(1000.0 / waterfall_fps()))), self._render)

    def _save_geometry(self) -> None:
        try:
            data = {}
            if STATE_PATH.is_file():
                loaded = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            data.update({
                "width": int(self.root.winfo_width()), "height": int(self.root.winfo_height()),
                "x": int(self.root.winfo_x()), "y": int(self.root.winfo_y()),
            })
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def close(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self._save_geometry()
        self.stream.stop()
        self.spider.stop()
        try:
            self.outbound.put_nowait(None)
        except Exception:
            pass


class GtkNativeViewer:
    """Low-copy GTK/Cairo renderer used on Raspberry Pi."""

    def __init__(
        self, stream: OpenWebRxStream, spider: SpiderStream, width: int, height: int,
        x: int, y: int, command_port: int, control_host: str, control_port: int,
    ) -> None:
        self.stream = stream
        self.spider = spider
        self.command_port = int(command_port)
        self.control_host = control_host
        self.control_port = int(control_port)
        self.stop_event = threading.Event()
        self.pending_commands: "queue.Queue[dict]" = queue.Queue(maxsize=128)
        self.outbound: "queue.Queue[dict | None]" = queue.Queue(maxsize=128)
        self.server = None
        self.display_scale = display_scale()
        self.actual_width = int(width)
        self.actual_height = int(height)
        self.width = max(1, int(round(self.actual_width / self.display_scale)))
        self.height = max(1, int(round(self.actual_height / self.display_scale)))
        self.x = int(x)
        self.y = int(y)
        self.last_fft_sequence = -1
        self.values = np.zeros(self.width, dtype=np.float32)
        self.config: dict = {}
        self.bookmarks: list[dict] = []
        self.status = "Conectando…"
        self.waterfall: np.ndarray | None = None
        self.spectrum_smooth: np.ndarray | None = None
        self.palette = build_palette()
        self.palette_signature = ""
        self.tuned_frequency = 0
        self.mode = "USB"
        self.step_hz = 1000
        self.zoom = 1.0
        self.zoom_center = 0.0
        self.current_band = ""
        self._last_smeter_emit = 0.0
        self.state_lock = threading.Lock()
        self.viewlock_prefs: dict[str, dict] = self._load_viewlock_prefs()
        self.control_rects: dict[str, tuple[float, float, float, float]] = {}
        self.bookmark_rects: list[tuple[float, float, float, float, dict]] = []
        self.profile_background = ""
        self.profile_config_mtime = -1.0
        self.spots_enabled = True
        self.spot_modes = {"CW", "DIGI", "SSB"}
        self.deferred_profile: dict | None = None
        self.last_tune_signature = None
        self.last_geometry_save = 0.0

        self.window = Gtk.Window(title="Waterfall")
        self.kiosk_mode = kiosk_mode()
        self.window_edit_enabled = WINDOW_EDIT_PATH.exists()
        launch_y = int(y)
        if self.kiosk_mode and self.window_edit_enabled:
            screen_height = int(Gdk.Screen.get_default().get_height())
            launch_y = max(26, min(int(y) + 26, screen_height - int(height)))
            self.window_edit_original_geometry = (int(width), int(height), int(x), int(y))
            self.window_edit_adjusted_geometry = (int(width), int(height), int(x), launch_y)
        if self.kiosk_mode:
            # OWRX is itself the open/close control for the native waterfall.
            self.window.set_decorated(self.window_edit_enabled)
        self.window.set_default_size(width, height)
        self.window.move(x, launch_y)
        self.window.set_size_request(
            max(220, int(round(520 * self.display_scale))),
            max(90, int(round(220 * self.display_scale))),
        )
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK
        )
        self.window.add(self.area)
        self.area.connect("draw", self._on_draw)
        self.area.connect("button-press-event", self._on_click)
        self.area.connect("button-release-event", self._on_release)
        self.area.connect("motion-notify-event", self._on_motion)
        self.area.connect("scroll-event", self._on_scroll)
        self.window.connect("key-press-event", self._on_key)
        self.window.connect("delete-event", self._on_delete)
        self.window.connect("configure-event", self._on_configure)

        self._start_command_server()
        if self.control_host and self.control_port:
            threading.Thread(target=self._send_control_loop, daemon=True, name="owrx_native_control").start()
        self.stream.set_audio_callback(self._emit_audio_chunk)
        self.stream.start()
        self.spider.start()
        GLib.timeout_add(30, self._process_commands)
        self._tick_interval_ms = max(8, int(round(1000.0 / waterfall_fps())))
        GLib.timeout_add(self._tick_interval_ms, self._tick)
        self.window.show_all()

    @staticmethod
    def _load_viewlock_prefs() -> dict[str, dict]:
        try:
            loaded = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
            prefs = loaded.get("viewlock_prefs") if isinstance(loaded, dict) else None
            return {str(key): dict(value) for key, value in prefs.items() if isinstance(value, dict)} if isinstance(prefs, dict) else {}
        except Exception:
            return {}

    def _save_viewlock_state(self) -> None:
        try:
            with self.state_lock:
                data = {}
                if STATE_PATH.is_file():
                    try:
                        loaded = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
                        if isinstance(loaded, dict):
                            data.update(loaded)
                    except (OSError, ValueError):
                        pass
                data["viewlock_prefs"] = self.viewlock_prefs
                self._write_state_atomic(data)
        except Exception:
            pass

    @staticmethod
    def _write_state_atomic(data: dict) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_PATH.with_name(f".{STATE_PATH.name}.tmp-{os.getpid()}")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, STATE_PATH)

    def _save_current_band_view(self) -> None:
        band = self.current_band or infer_band(self.tuned_frequency or self.config.get("center_freq", 0))
        if not band or band not in self.viewlock_prefs:
            return
        self.viewlock_prefs[band] = {
            "zoom": float(self.zoom), "center": float(self.zoom_center),
            "freq": int(self.tuned_frequency or 0), "ts": int(time.time() * 1000),
        }
        self._save_viewlock_state()

    def _toggle_viewlock(self) -> None:
        band = self.current_band or infer_band(self.tuned_frequency or self.config.get("center_freq", 0))
        if not band:
            return
        if band in self.viewlock_prefs:
            del self.viewlock_prefs[band]
            self._save_viewlock_state()
        else:
            self.viewlock_prefs[band] = {}
            self._save_current_band_view()
        self.area.queue_draw()

    def _apply_band_view(self, band: str) -> None:
        pref = self.viewlock_prefs.get(band)
        if not isinstance(pref, dict):
            return
        try:
            zoom = float(pref.get("zoom", 0) or 0)
            center = float(pref.get("center", 0) or 0)
            # Compatibility with state written by the former browser viewer.
            if zoom <= 0 and int(pref.get("zoom_level", -1) or -1) >= 0:
                zoom = min(16.0, 2.0 ** min(4, int(pref["zoom_level"])))
            if zoom > 0:
                self.zoom = min(16.0, max(1.0, zoom))
            if center > 0:
                self.zoom_center = center
            elif float(pref.get("freq", 0) or 0) > 0:
                self.zoom_center = float(pref["freq"])
        except (TypeError, ValueError):
            pass

    def _refresh_profile_palette(self) -> None:
        path = Path(os.environ.get("OWRX_CONFIG_PATH") or "")
        if not path.is_file():
            return
        try:
            mtime = path.stat().st_mtime
            if mtime == self.profile_config_mtime:
                return
            self.profile_config_mtime = mtime
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            background = Path(str(loaded.get("Imagen_Fondo") or "back.jpg")).name
            if background != self.profile_background:
                self.profile_background = background
                self.palette = profile_palette(background)
                self.palette_signature = f"profile:{background}"
                self.waterfall = None
        except Exception:
            pass

    def _start_command_server(self) -> None:
        if not self.command_port:
            return
        viewer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                data = b""
                self.request.settimeout(0.5)
                try:
                    while b"\n" not in data and len(data) < 1024 * 1024:
                        part = self.request.recv(65536)
                        if not part:
                            break
                        data += part
                except Exception:
                    pass
                try:
                    payload = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
                    if isinstance(payload, dict):
                        viewer.pending_commands.put_nowait(payload)
                except Exception:
                    pass

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", self.command_port), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="owrx_native_commands").start()

    def _send_control_loop(self) -> None:
        sock = None
        while not self.stop_event.is_set():
            try:
                if sock is None:
                    sock = socket.create_connection((self.control_host, self.control_port), timeout=1.0)
                try:
                    payload = self.outbound.get(timeout=0.5)
                except queue.Empty:
                    continue
                if payload is None:
                    break
                sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            except Exception:
                try:
                    if sock:
                        sock.close()
                except Exception:
                    pass
                sock = None
                self.stop_event.wait(0.5)
        try:
            if sock:
                sock.close()
        except Exception:
            pass

    def _emit(self, payload: dict) -> None:
        try:
            self.outbound.put_nowait(payload)
        except queue.Full:
            pass

    def _emit_audio_chunk(self, pcm: bytes, sample_rate: int, channels: int) -> None:
        if not pcm or self.stop_event.is_set():
            return
        self._emit({
            "type": "audio_chunk",
            "pcm": base64.b64encode(pcm).decode("ascii"),
            "sample_rate": int(sample_rate),
            "channels": int(channels),
        })

    def _process_commands(self) -> bool:
        if self.stop_event.is_set():
            return False
        while True:
            try:
                command = self.pending_commands.get_nowait()
            except queue.Empty:
                break
            kind = str(command.get("type") or "")
            if kind == "close":
                self.close()
                return False
            if kind == "tune":
                if command.get("frequency") is not None:
                    self.tuned_frequency = int(float(command["frequency"]))
                if command.get("mode"):
                    self.mode = str(command["mode"]).upper()
                self._send_tune_to_stream()
                self._emit({
                    "type": "tune", "frequency": self.tuned_frequency,
                    "modulation": self.mode.lower(), "view_mode": "owrx",
                })
            elif kind == "step":
                self.step_hz = max(1, int(command.get("step_hz") or 1))
            elif kind == "profile":
                if not self._select_profile(command):
                    self.deferred_profile = command
            elif kind == "spots":
                self.spots_enabled = bool(command.get("enabled")) and not bool(command.get("off"))
                if isinstance(command.get("modes"), list):
                    self.spot_modes = {str(value).upper() for value in command["modes"]}
                if command.get("retention_sec") is not None:
                    self.spider.retention_sec = max(30, int(command.get("retention_sec") or 600))
                log(f"spots cmd enabled={self.spots_enabled} modes={sorted(self.spot_modes)} "
                    f"retention={self.spider.retention_sec}s buffered={len(self.spider.snapshot())}")
            elif kind == "audio_capture":
                self.stream.set_audio_capture(bool(command.get("enabled")))
        if self.deferred_profile and self._select_profile(self.deferred_profile):
            self.deferred_profile = None
        return True

    def _select_profile(self, command: dict) -> bool:
        target = str(command.get("profile") or "").lower().strip()
        sdr_hint = str(command.get("sdr") or "").lower().strip()
        _fft, _seq, _config, profiles, _marks, _bands, _status = self.stream.snapshot()
        candidates = profiles
        if sdr_hint:
            hinted = [item for item in profiles if sdr_hint in str(item.get("id", "")).lower()]
            if hinted:
                candidates = hinted
        match = next((item for item in candidates if target and target in f"{item.get('id', '')} {item.get('name', '')}".lower()), None)
        if not match:
            return False
        params = {"profile": str(match.get("id") or "")}
        if command.get("key"):
            params["key"] = str(command["key"])
        self.stream.send({"type": "selectprofile", "params": params})
        if self.current_band not in self.viewlock_prefs:
            self.zoom = 1.0
        self.last_tune_signature = None
        return True

    def _send_tune_to_stream(self) -> None:
        center = int(self.config.get("center_freq", 0) or 0)
        params = {}
        if self.tuned_frequency and center:
            params["offset_freq"] = int(self.tuned_frequency - center)
        mod = self.mode.lower()
        if mod == "fm":
            mod = "nfm"
        if mod in ("am", "nfm", "usb", "lsb", "cw"):
            params["mod"] = mod
            params["low_cut"], params["high_cut"] = {
                "am": (-4000, 4000), "nfm": (-4000, 4000),
                "usb": (150, 2750), "lsb": (-2750, -150),
                "cw": (300, 700),
            }[mod]
        if not params:
            return
        signature = (center, self.tuned_frequency, self.mode)
        if signature == self.last_tune_signature:
            return
        self.last_tune_signature = signature
        self.stream.send({"type": "dspcontrol", "action": "start"})
        self.stream.send({"type": "dspcontrol", "params": params})

    def _visible_range(self) -> tuple[float, float]:
        center = float(self.config.get("center_freq", 0) or 0)
        bandwidth = max(1.0, float(self.config.get("samp_rate", 1) or 1))
        band = self.current_band or infer_band(self.tuned_frequency) or infer_band(center)
        return band_visible_range(center, bandwidth, band, self.zoom, self.zoom_center)

    def _frequency_at(self, x: float) -> int:
        low, high = self._visible_range()
        return int(round(low + np.clip(float(x) / max(1, self.width - 1), 0.0, 1.0) * (high - low)))

    def _resample_fft(self, fft: np.ndarray) -> np.ndarray:
        if fft.size == 0:
            return np.zeros(self.width, dtype=np.float32)
        center = float(self.config.get("center_freq", 0) or 0)
        bandwidth = max(1.0, float(self.config.get("samp_rate", 1) or 1))
        low, high = self._visible_range()
        start = np.clip((low - (center - bandwidth / 2.0)) / bandwidth, 0.0, 1.0)
        end = np.clip((high - (center - bandwidth / 2.0)) / bandwidth, 0.0, 1.0)
        positions = np.linspace(start * (fft.size - 1), end * (fft.size - 1), self.width)
        return np.interp(positions, np.arange(fft.size), fft).astype(np.float32)

    def _update_smeter(self, values: np.ndarray) -> None:
        """Igual que en el visor Tk: nivel dBFS de la banda de paso, throttled."""
        now = time.monotonic()
        if now - self._last_smeter_emit < 0.15 or values.size == 0 or not self.tuned_frequency:
            return
        low, high = self._visible_range()
        span = max(1.0, high - low)
        cuts = {
            "AM": (-4000, 4000), "FM": (-4000, 4000),
            "USB": (150, 2750), "LSB": (-2750, -150), "CW": (300, 700),
        }.get(self.mode, (-1000, 1000))
        x1 = int((self.tuned_frequency + cuts[0] - low) / span * self.width)
        x2 = int((self.tuned_frequency + cuts[1] - low) / span * self.width)
        x1, x2 = sorted((max(0, min(values.size - 1, x1)), max(0, min(values.size - 1, x2))))
        window = values[x1 : x2 + 1]
        if window.size == 0:
            return
        self._last_smeter_emit = now
        self._emit({"type": "smeter", "dbfs": round(float(np.percentile(window, 90.0)), 1)})

    def _tick(self) -> bool:
        if self.stop_event.is_set():
            return False
        if self.kiosk_mode:
            window_edit_enabled = WINDOW_EDIT_PATH.exists()
            if window_edit_enabled != self.window_edit_enabled:
                self._set_window_edit_mode(window_edit_enabled)
        fft, sequence, self.config, _profiles, self.bookmarks, _bands, self.status = self.stream.snapshot()
        self._refresh_profile_palette()
        center = float(self.config.get("center_freq", 0) or 0)
        band = infer_band(self.tuned_frequency) or infer_band(center)
        if band and band != self.current_band:
            self.current_band = band
            self.zoom = 1.0
            limits = BAND_LIMITS.get(band)
            self.zoom_center = sum(limits) / 2.0 if limits else center
            self._apply_band_view(band)
        if self.tuned_frequency and int(self.config.get("center_freq", 0) or 0):
            self._send_tune_to_stream()
        scale_h = 27
        spectrum_h = max(44, min(76, int(self.height * 0.29)))
        waterfall_h = max(1, self.height - scale_h - spectrum_h)
        if fft is not None and fft.size:
            self.values = self._resample_fft(fft)
        elif self.values.size != self.width:
            self.values = np.zeros(self.width, dtype=np.float32)
        self._update_smeter(self.values)
        if not self.palette_signature.startswith("profile:"):
            self.palette = profile_palette(self.profile_background or "back.jpg")
            self.palette_signature = f"profile:{self.profile_background or 'back.jpg'}"
        if self.waterfall is None or self.waterfall.shape != (waterfall_h, self.width, 4):
            self.waterfall = np.zeros((waterfall_h, self.width, 4), dtype=np.uint8)
        row_added = False
        if sequence != self.last_fft_sequence and fft is not None:
            levels = self.config.get("waterfall_levels") if isinstance(self.config.get("waterfall_levels"), dict) else {}
            minimum = float(levels.get("min", -60.0) or -60.0)
            maximum = max(minimum + 1.0, float(levels.get("max", -10.0) or -10.0))
            rgb = levels_to_colors(self.values, minimum, maximum, self.palette)
            self.waterfall[1:] = self.waterfall[:-1]
            self.waterfall[0, :, :3] = rgb[:, ::-1]  # Cairo RGB24 is B,G,R,x on little-endian ARM.
            self.last_fft_sequence = sequence
            row_added = True
        # Redibujar por cada fila FFT nueva (cascada fluida) y, si no llegan
        # FFTs, al menos unas pocas veces por segundo (spots/estado).
        self._ticks_since_draw = getattr(self, "_ticks_since_draw", 999) + 1
        min_draw_ticks = max(1, int(round(waterfall_fps() / 6.0)))
        if row_added or self._ticks_since_draw >= min_draw_ticks:
            self._ticks_since_draw = 0
            self.area.queue_draw()
        now = time.monotonic()
        if now - self.last_geometry_save >= 1.0:
            self.last_geometry_save = now
            self._save_geometry()
        return True

    def _set_window_edit_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.window_edit_enabled:
            return
        try:
            width, height = self.window.get_size()
            x, y = self._client_position()
            self.window.unmaximize()
            self.window_edit_enabled = enabled
            self.window.set_decorated(enabled)
            current = (int(width), int(height), int(x), int(y))
            if enabled:
                screen_height = int(Gdk.Screen.get_default().get_height())
                target_y = max(26, min(int(y) + 26, screen_height - int(height)))
                target = (int(width), int(height), int(x), target_y)
                self.window_edit_original_geometry = current
                self.window_edit_adjusted_geometry = target
            elif current == getattr(self, "window_edit_adjusted_geometry", None):
                target = getattr(self, "window_edit_original_geometry", current)
            else:
                target = (int(width), int(height), int(x), max(0, int(y) - 26))

            def apply_geometry() -> bool:
                target_width, target_height, target_x, target_y = target
                self.window.resize(target_width, target_height)
                self.window.move(target_x, target_y)
                return False

            GLib.timeout_add(60, apply_geometry)
        except Exception:
            self.window_edit_enabled = enabled

    def _client_position(self) -> tuple[int, int]:
        # window.get_position() devuelve la esquina del MARCO decorado, que es
        # justo lo que interpreta window.move(): guardar con esa referencia evita
        # que la ventana descienda la altura de la barra de título en cada ciclo.
        try:
            pos = self.window.get_position()
            if pos and (int(pos[0]) or int(pos[1])):
                return int(pos[0]), int(pos[1])
        except Exception:
            pass
        try:
            native_window = self.window.get_window()
            if native_window is not None:
                origin = native_window.get_origin()
                if isinstance(origin, tuple) and len(origin) >= 2:
                    return int(origin[-2]), int(origin[-1])
        except Exception:
            pass
        return 0, 0

    def _on_draw(self, _area, ctx) -> bool:
        scale_x = self.actual_width / max(1.0, float(self.width))
        scale_y = self.actual_height / max(1.0, float(self.height))
        ctx.scale(scale_x, scale_y)
        ctx.set_source_rgb(0.03, 0.035, 0.045)
        ctx.paint()
        scale_h = 27
        spectrum_h = max(44, min(76, int(self.height * 0.29)))
        waterfall_top = scale_h + spectrum_h
        low, high = self._visible_range()
        span = max(1.0, high - low)

        ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(16)
        step = nice_tick_step(span, self.width)
        value = math.ceil(low / step) * step
        while value <= high + step * 0.5:
            x = (value - low) / span * max(1, self.width - 1)
            ctx.set_source_rgb(0.6, 0.64, 0.68)
            ctx.move_to(x, scale_h - 10)
            ctx.line_to(x, scale_h - 1)
            ctx.stroke()
            label = f"{value / 1_000_000:.3f}"
            ext = ctx.text_extents(label)
            ctx.set_source_rgb(0.86, 0.88, 0.91)
            ctx.move_to(x - ext.width / 2.0, 17)
            ctx.show_text(label)
            value += step
        ctx.set_source_rgb(0.38, 0.4, 0.43)
        ctx.move_to(0, scale_h - 0.5)
        ctx.line_to(self.width, scale_h - 0.5)
        ctx.stroke()

        values = self.values
        if values.size:
            minimum = float(np.percentile(values, 87.0))
            maximum = max(minimum + 0.1, float(np.percentile(values, 99.7)))
            normalized = np.clip((values - minimum) / (maximum - minimum), 0.0, 1.0)
            normalized = np.where(normalized < 0.28, normalized * 1.32,
                np.where(normalized < 0.72, 0.37 + (normalized - 0.28) * 0.62, 0.64 + (normalized - 0.72) * 1.18))
            normalized = np.clip(normalized, 0.0, 1.0) ** 1.02
            if self.spectrum_smooth is None or self.spectrum_smooth.size != values.size:
                self.spectrum_smooth = normalized.copy()
            else:
                self.spectrum_smooth *= 0.72
                self.spectrum_smooth += normalized * 0.28
            ys = scale_h + spectrum_h - 2 - self.spectrum_smooth * (spectrum_h - 4)
            ctx.move_to(0, scale_h + spectrum_h - 1)
            point_step = max(1, self.width // 640)
            for x in range(0, len(ys), point_step):
                y = ys[x]
                ctx.line_to(x, float(y))
            ctx.line_to(self.width - 1, scale_h + spectrum_h - 1)
            ctx.close_path()
            accent = np.asarray(profile_accent(self.profile_background or "back.jpg"), dtype=np.float32) / 255.0
            if self.profile_background == "back.png":
                # Excepción Classic: relleno azul marino a juego con el
                # arcoíris fijo de la cascada, en vez del plateado del tema.
                ctx.set_source_rgba(6 / 255.0, 20 / 255.0, 40 / 255.0, 0.78)
            else:
                ctx.set_source_rgba(float(accent[0] * 0.32), float(accent[1] * 0.32), float(accent[2] * 0.32), 0.78)
            ctx.fill_preserve()
            ctx.set_source_rgb(float(accent[0]), float(accent[1]), float(accent[2]))
            ctx.set_line_width(1.0)
            ctx.stroke()

        if self.waterfall is not None:
            surface = cairo.ImageSurface.create_for_data(
                self.waterfall, cairo.FORMAT_RGB24, self.width, self.waterfall.shape[0], self.waterfall.strides[0]
            )
            ctx.set_source_surface(surface, 0, waterfall_top)
            ctx.paint()

        # High-contrast boundary requested by the PoorSDR layout: FFT above,
        # time waterfall below.
        ctx.set_dash([])
        ctx.set_line_width(1.0)
        ctx.set_source_rgb(1.0, 1.0, 1.0)
        ctx.move_to(0, waterfall_top + 0.5)
        ctx.line_to(self.width, waterfall_top + 0.5)
        ctx.stroke()

        self._draw_passband(ctx, low, span, scale_h, self.height)
        self.bookmark_rects.clear()
        self._draw_bookmarks(ctx, low, span, scale_h, waterfall_top)
        self._draw_spots(ctx, low, span, waterfall_top, self.height)
        self._draw_view_controls(ctx)
        # Draw it last so spectrum fill, cursor and overlays cannot tint it.
        ctx.set_dash([])
        ctx.set_line_width(2.0)
        ctx.set_source_rgb(1.0, 1.0, 1.0)
        ctx.move_to(0, waterfall_top + 0.5)
        ctx.line_to(self.width, waterfall_top + 0.5)
        ctx.stroke()
        if self.last_fft_sequence <= 0:
            ctx.set_source_rgb(0.9, 0.9, 0.9)
            ctx.move_to(10, waterfall_top + 18)
            ctx.show_text(self.status)
        # The tuned-frequency selector is the topmost overlay. Spots and
        # bookmark labels must never hide the active tuning position.
        self._draw_tuning_cursor(ctx, low, span, scale_h, self.height)
        return False

    def _draw_passband(self, ctx, low: float, span: float, top: int, bottom: int) -> None:
        if not self.tuned_frequency:
            return
        cuts = {"AM": (-4000, 4000), "FM": (-4000, 4000), "USB": (150, 2750), "LSB": (-2750, -150), "CW": (300, 700)}.get(self.mode, (-1000, 1000))
        x1 = (self.tuned_frequency + cuts[0] - low) / span * self.width
        x2 = (self.tuned_frequency + cuts[1] - low) / span * self.width
        if x2 >= 0 and x1 <= self.width:
            ctx.set_source_rgba(0.14, 0.52, 0.68, 0.22)
            ctx.rectangle(max(0, x1), top, min(self.width, x2) - max(0, x1), bottom - top)
            ctx.fill()

    def _draw_tuning_cursor(self, ctx, low: float, span: float, top: int, bottom: int) -> None:
        if not self.tuned_frequency:
            return
        cursor = (self.tuned_frequency - low) / span * self.width
        if not 0 <= cursor < self.width:
            return
        ctx.set_dash([])
        ctx.set_line_width(2.0)
        ctx.set_source_rgb(1.0, 0.9, 0.3)
        ctx.move_to(cursor, top)
        ctx.line_to(cursor, bottom)
        ctx.stroke()

    @staticmethod
    def _spot_class(mode: str) -> str:
        value = str(mode or "").upper()
        if "CW" in value:
            return "CW"
        if value in ("USB", "LSB", "SSB", "PHONE", "AM", "FM"):
            return "SSB"
        return "DIGI"

    def _draw_spots(self, ctx, low: float, span: float, top: int, bottom: int) -> None:
        if not self.spots_enabled:
            return
        lanes: list[list[tuple[float, float]]] = [[] for _ in range(7)]
        colors = {"CW": (0.18, 0.86, 0.35), "SSB": (1.0, 0.84, 0.16), "DIGI": (0.71, 0.39, 1.0)}
        ctx.set_font_size(17)
        for spot in sorted(self.spider.snapshot(), key=lambda item: int(item.get("freq", 0))):
            freq = int(spot.get("freq", 0) or 0)
            category = self._spot_class(str(spot.get("mode", "")))
            if category not in self.spot_modes or not (low <= freq <= low + span):
                continue
            x = (freq - low) / span * self.width
            label = str(spot.get("call", ""))[:12]
            ext = ctx.text_extents(label)
            label_w = ext.width + 11
            left = max(1.0, min(self.width - label_w - 1, x))
            lane = next((i for i, used in enumerate(lanes) if all(left > end + 4 or left + label_w < start - 4 for start, end in used)), None)
            if lane is None:
                continue
            lanes[lane].append((left, left + label_w))
            y = top + 3 + lane * 20
            if y + 18 >= bottom:
                continue
            ctx.set_source_rgba(0.04, 0.05, 0.07, 0.94)
            ctx.rectangle(left, y, label_w, 18)
            ctx.fill()
            ctx.set_source_rgb(*colors[category])
            ctx.rectangle(left, y, 3, 18)
            ctx.fill()
            ctx.set_source_rgb(0.92, 0.95, 1.0)
            ctx.move_to(left + 6, y + 14)
            ctx.show_text(label)

    def _draw_view_controls(self, ctx) -> None:
        size, gap, top = 27.0, 4.0, 3.0
        labels = (("lock", "F"), ("in", "+"), ("out", "−"))
        total = len(labels) * size + (len(labels) - 1) * gap
        left = max(2.0, self.width - total - 7.0)
        locked = bool(self.current_band and self.current_band in self.viewlock_prefs)
        self.control_rects = {}
        ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(16)
        for index, (name, label) in enumerate(labels):
            x = left + index * (size + gap)
            self.control_rects[name] = (x, top, size, size - 3)
            if name == "lock" and locked:
                ctx.set_source_rgba(0.10, 0.46, 0.20, 0.97)
            else:
                ctx.set_source_rgba(0.08, 0.095, 0.12, 0.96)
            ctx.rectangle(x, top, size, size - 3)
            ctx.fill_preserve()
            if name == "lock" and locked:
                ctx.set_source_rgb(0.45, 1.0, 0.62)
            else:
                ctx.set_source_rgb(0.74, 0.78, 0.84)
            ctx.set_line_width(1.0)
            ctx.stroke()
            ext = ctx.text_extents(label)
            ctx.move_to(x + (size - ext.width) / 2.0 - ext.x_bearing, top + 17)
            ctx.show_text(label)

    def _draw_bookmarks(self, ctx, low: float, span: float, top: int, bottom: int) -> None:
        """Draw bookmarks as cyan spectrum flags, visually unlike DX spots."""
        lanes: list[list[tuple[float, float]]] = [[] for _ in range(6)]
        source_colors = {
            "local": (1.0, 0.25, 0.18),
            "server": (0.95, 0.58, 0.18),
            "dial_frequencies": (0.25, 0.76, 1.0),
        }
        ctx.set_font_size(14)
        drawn_freqs: list[int] = []
        # Dial frequencies go first so live/server bookmarks cannot hide the
        # permanent FT8, FT4, WSPR, JS8, etc. reference flags.
        for bookmark in sorted(self.bookmarks, key=lambda item: str(item.get("source")) != "dial_frequencies"):
            try:
                freq = int(float(bookmark.get("frequency", bookmark.get("freq", 0)) or 0))
            except (TypeError, ValueError):
                continue
            if not (low <= freq <= low + span):
                continue
            # Evitar marcadores duplicados en la misma frecuencia (p.ej. un
            # dial_frequency de OWRX y un bookmark de servidor con la misma).
            if any(abs(freq - seen) <= 120 for seen in drawn_freqs):
                continue
            drawn_freqs.append(freq)
            label = str(bookmark.get("name") or bookmark.get("description") or f"{freq / 1000:.1f}")[:18]
            ext = ctx.text_extents(label)
            label_w = max(13.0, ext.width + 10)
            x = (freq - low) / span * self.width
            left = max(1.0, min(self.width - label_w - 1, x - label_w / 2))
            lane = next((i for i, used in enumerate(lanes)
                         if all(left > end + 3 or left + label_w < start - 3 for start, end in used)), None)
            if lane is None:
                continue
            lanes[lane].append((left, left + label_w))
            y = top + 4 + lane * 20
            if y + 18 >= bottom:
                continue
            source = str(bookmark.get("source") or "local")
            color = source_colors.get(source, (0.95, 0.58, 0.18))
            # Flag pole and triangular pointer identify a stored frequency;
            # spots remain filled labels inside the waterfall.
            ctx.set_source_rgba(*color, 0.72)
            ctx.set_dash([3.0, 4.0])
            ctx.move_to(x, y + 12)
            ctx.line_to(x, bottom)
            ctx.stroke()
            ctx.set_dash([])
            ctx.move_to(x - 4, y + 18)
            ctx.line_to(x + 4, y + 18)
            ctx.line_to(x, y + 23)
            ctx.close_path()
            ctx.fill()
            ctx.set_source_rgba(0.025, 0.035, 0.05, 0.84)
            ctx.rectangle(left, y, label_w, 18)
            ctx.fill_preserve()
            ctx.set_source_rgb(*color)
            ctx.set_line_width(1.0)
            ctx.stroke()
            ctx.set_source_rgb(*color)
            ctx.move_to(left + 5, y + 14)
            ctx.show_text(label)
            self.bookmark_rects.append((left, y, label_w, 23.0, bookmark))

    def _bookmark_at(self, x: float, y: float) -> dict | None:
        for left, top, width, height, bookmark in reversed(self.bookmark_rects):
            if left <= x <= left + width and top <= y <= top + height:
                return bookmark
        return None

    def _tune_bookmark(self, bookmark: dict) -> None:
        frequency, mode = bookmark_tune_target(bookmark, self.mode)
        if frequency <= 0:
            return
        self.tuned_frequency = frequency
        self.mode = mode
        self.last_tune_signature = None
        self._send_tune_to_stream()
        self._emit({
            "type": "tune", "frequency": frequency,
            "modulation": mode.lower(), "view_mode": "owrx", "user": True,
        })
        log(f"bookmark tune frequency={frequency} mode={mode}")

    def _on_click(self, _widget, event) -> bool:
        if event.button != 1:
            return False
        event_x = float(event.x) * self.width / max(1, self.actual_width)
        event_y = float(event.y) * self.height / max(1, self.actual_height)
        for action, (x, y, width, height) in self.control_rects.items():
            if x <= event_x <= x + width and y <= event_y <= y + height:
                self.drag_start_x = None
                if action == "lock":
                    self._toggle_viewlock()
                elif action == "in":
                    self._change_zoom(1)
                elif action == "out":
                    self._change_zoom(-1)
                return True
        bookmark = self._bookmark_at(event_x, event_y)
        if bookmark is not None:
            self.drag_start_x = None
            self.drag_moved = False
            self._tune_bookmark(bookmark)
            return True
        low, high = self._visible_range()
        self.drag_start_x = event_x
        self.drag_start_center = (low + high) / 2.0
        self.drag_start_span = high - low
        self.drag_start_freq = int(self.tuned_frequency or round((low + high) / 2.0))
        self.drag_moved = False
        return True

    def _on_motion(self, _widget, event) -> bool:
        event_x = float(event.x) * self.width / max(1, self.actual_width)
        event_y = float(event.y) * self.height / max(1, self.actual_height)
        if not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            area_window = self.area.get_window()
            if area_window is not None:
                display = Gdk.Display.get_default()
                cursor = Gdk.Cursor.new_from_name(display, "pointer") if self._bookmark_at(event_x, event_y) else None
                area_window.set_cursor(cursor)
            return False
        if self.drag_start_x is None or not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        delta_x = event_x - self.drag_start_x
        if not self.drag_moved and abs(delta_x) < 3.0:
            return True
        self.drag_moved = True
        # Arrastre = desplazar la vista de la cascada (pan). Puede salir de los
        # limites de la banda pero no de los datos del receptor.
        span_hz = float(self.drag_start_span or 0.0)
        center = float(self.config.get("center_freq", 0) or 0)
        bandwidth = max(1.0, float(self.config.get("samp_rate", 1) or 1))
        rx_low = center - bandwidth / 2.0
        rx_high = center + bandwidth / 2.0
        half = span_hz / 2.0
        candidate = self.drag_start_center - delta_x * span_hz / max(1, self.width - 1)
        self.zoom_center = min(rx_high - half, max(rx_low + half, candidate))
        self.waterfall = None
        self.area.queue_draw()
        return True

    def _on_release(self, _widget, event) -> bool:
        if event.button != 1 or self.drag_start_x is None:
            return False
        was_drag = self.drag_moved
        self.drag_start_x = None
        self.drag_moved = False
        if was_drag:
            self._save_current_band_view()
            return True
        event_x = float(event.x) * self.width / max(1, self.actual_width)
        frequency = self._frequency_at(event_x)
        step = max(1, self.step_hz)
        self.tuned_frequency = int(round(frequency / step) * step)
        self._send_tune_to_stream()
        self._emit({"type": "tune", "frequency": self.tuned_frequency, "modulation": self.mode.lower(), "view_mode": "owrx", "user": True})
        return True

    def _change_zoom(self, direction: int, focus: float | None = None) -> None:
        levels = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0)
        current = min(range(len(levels)), key=lambda index: abs(levels[index] - self.zoom))
        self.zoom = levels[max(0, min(len(levels) - 1, current + (1 if direction > 0 else -1)))]
        if focus is None:
            low, high = self._visible_range()
            candidate = float(self.tuned_frequency or 0)
            focus = candidate if low <= candidate <= high else (low + high) / 2.0
        self.zoom_center = float(focus)
        self.waterfall = None
        self._save_current_band_view()
        self.area.queue_draw()

    def _on_scroll(self, _widget, event) -> bool:
        # La rueda SOLO cambia la frecuencia (el zoom se hace con los botones +/-).
        if event.direction == Gdk.ScrollDirection.UP:
            self._tune_step(1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self._tune_step(-1)
        return True

    def _tune_step(self, direction: int) -> None:
        step = max(1, int(self.step_hz or 0) or 1000)
        base = int(self.tuned_frequency or 0)
        if base <= 0:
            low, high = self._visible_range()
            base = int((low + high) / 2.0)
        new_freq = int(round((base + direction * step) / step) * step)
        if new_freq == int(self.tuned_frequency or 0):
            return
        self.tuned_frequency = new_freq
        self.last_tune_signature = None
        self._send_tune_to_stream()
        self._emit({
            "type": "tune", "frequency": new_freq,
            "modulation": self.mode.lower(), "view_mode": "owrx", "user": True,
        })

    def _on_key(self, _widget, event) -> bool:
        key = Gdk.keyval_name(event.keyval) or ""
        mods = []
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            mods.append("Ctrl")
        if event.state & Gdk.ModifierType.MOD1_MASK:
            mods.append("Alt")
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            mods.append("Shift")
        self._emit({"type": "hotkey", "key": "+".join(mods + [key]) if mods else key})
        return False

    def _on_configure(self, _widget, event) -> bool:
        self.actual_width = max(1, int(event.width))
        self.actual_height = max(1, int(event.height))
        self.width = max(1, int(round(self.actual_width / self.display_scale)))
        self.height = max(1, int(round(self.actual_height / self.display_scale)))
        self.x = int(event.x)
        self.y = int(event.y)
        return False

    def _on_delete(self, *_args) -> bool:
        self.close()
        return True

    def _save_geometry(self) -> None:
        try:
            width, height = self.window.get_size()
            x, y = self._client_position()
            with self.state_lock:
                data = {}
                if STATE_PATH.is_file():
                    try:
                        loaded = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
                        if isinstance(loaded, dict):
                            data.update(loaded)
                    except (OSError, ValueError):
                        pass
                data.update({"width": int(width), "height": int(height), "x": int(x), "y": int(y)})
                data["viewlock_prefs"] = self.viewlock_prefs
                self._write_state_atomic(data)
        except Exception:
            pass

    def close(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self._save_geometry()
        self.stream.stop()
        self.spider.stop()
        try:
            self.outbound.put_nowait(None)
        except Exception:
            pass
        if self.server:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        Gtk.main_quit()


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: owrx_native.py <url> <width> <height> [port] [control_host] [control_port]", file=sys.stderr)
        return 1
    parsed = urlparse(str(sys.argv[1]))
    host = parsed.hostname or "127.0.0.1"
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    width, height, x, y = parse_geometry(int(sys.argv[2]), int(sys.argv[3]))
    command_port = int(sys.argv[4]) if len(sys.argv) >= 5 and sys.argv[4] else 0
    control_host = str(sys.argv[5]) if len(sys.argv) >= 6 and sys.argv[5] else ""
    control_port = int(sys.argv[6]) if len(sys.argv) >= 7 and sys.argv[6] else 0
    lang = os.environ.get("POORSDR_UI_LANG", "es") or "es"
    log(f"startup endpoint={host}:{port} geometry={width}x{height}+{x}+{y}")
    if Gtk is not None and cairo is not None:
        viewer = GtkNativeViewer(OpenWebRxStream(host, port, lang), SpiderStream(host), width, height, x, y, command_port, control_host, control_port)
        signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(viewer.close))
        signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(viewer.close))
        Gtk.main()
    elif tk is not None and ImageTk is not None:
        root = tk.Tk()
        NativeViewer(root, OpenWebRxStream(host, port, lang), SpiderStream(host), width, height, x, y, command_port, control_host, control_port)
        root.mainloop()
    else:
        print("OWRX_NATIVE_ERROR: Python no dispone de GTK/Cairo ni Tk/ImageTk", file=sys.stderr)
        return 1
    log("exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
