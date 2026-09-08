#!/usr/bin/env python3
"""Native OpenWebRX+ digital decoder panel for PoorSDR4All."""

from __future__ import annotations

import base64
from collections import deque
from datetime import datetime, timezone
import json
import os
import queue
import re
import signal
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from poorsdr.i18n import t
from poorsdr.infra import paths as app_paths

os.environ.setdefault("NO_AT_BRIDGE", "1")

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango
except (ImportError, ValueError, AttributeError):
    Gdk = GdkPixbuf = GLib = Gtk = Pango = None

from poorsdr.viewers.waterfall import (
    ImaAdpcmDecoder,
    OpenWebRxStream,
    PROFILE_ACCENTS,
    decode_fft_payload,
)
def runtime_path(*rel: str) -> str:
    configured = os.environ.get("POORSDR_RUNTIME_DIR", "").strip()
    base = Path(configured).expanduser() if configured else app_paths.runtime_dir()
    return str(app_paths.ensure_dir(base).joinpath(*rel))


LOG_PATH = app_paths.ensure_dir(app_paths.log_dir()) / "owrx_digi.log"
STATE_PATH = Path(os.environ.get("POORSDR_DIGI_STATE_PATH") or runtime_path("digi_state.json"))
WINDOW_EDIT_PATH = Path(runtime_path(".window_edit_mode"))


def display_scale() -> float:
    try:
        return min(1.0, max(0.1, float(os.environ.get("POORSDR_DISPLAY_SCALE", "1") or 1)))
    except (TypeError, ValueError):
        return 1.0


def selected_theme_accent(config_path: str = "") -> str:
    """Return the PoorSDR accent associated with the selected background."""
    background = "back.jpg"
    try:
        path = Path(config_path or os.environ.get("OWRX_CONFIG_PATH") or "")
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            background = str(loaded.get("Imagen_Fondo") or background)
    except Exception:
        pass
    return PROFILE_ACCENTS.get(Path(background).name, PROFILE_ACCENTS["back.jpg"])


def accent_rgb(accent: str) -> tuple[float, float, float]:
    """Convert a CSS accent into Cairo's normalized RGB components."""
    try:
        value = str(accent).lstrip("#")
        if len(value) != 6:
            raise ValueError
        return tuple(int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
    except (TypeError, ValueError):
        return accent_rgb(PROFILE_ACCENTS["back.jpg"])


def log(message: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
    except Exception:
        pass


def parse_geometry(width: int, height: int) -> tuple[int, int, int, int]:
    scale = display_scale()
    min_width = max(300, int(round(720 * scale)))
    min_height = max(180, int(round(440 * scale)))
    candidates = [str(os.environ.get("OWRX_FORCE_GEOMETRY", "") or "").strip()]
    try:
        loaded = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            candidates.append(
                f"{int(loaded.get('width', 0))}x{int(loaded.get('height', 0))}"
                f"+{int(loaded.get('x', 0))}+{int(loaded.get('y', 0))}"
            )
    except Exception:
        pass
    for value in candidates:
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", value)
        if match:
            w, h, x, y = (int(part) for part in match.groups())
            return max(min_width, w), max(min_height, h), x, y
    return max(min_width, int(width or 980)), max(min_height, int(height or 620)), 0, 0


def available_digital_modes(modes: list[dict]) -> list[dict]:
    """Return the decoder list already filtered by OpenWebRX+ features."""
    values = [dict(mode) for mode in modes if isinstance(mode, dict) and mode.get("type") == "digimode"]
    return sorted(values, key=lambda mode: str(mode.get("name") or mode.get("modulation") or "").casefold())


def decoder_params(mode: dict, frequency: int, center_frequency: int, preferred_underlying: str = "") -> dict:
    underlying = [str(value).lower() for value in mode.get("underlying", []) if value]
    preferred = str(preferred_underlying or "").lower()
    primary = preferred if preferred in underlying else (underlying[0] if underlying else "usb")
    bandpass = mode.get("bandpass") if isinstance(mode.get("bandpass"), dict) else None
    if bandpass:
        low_cut = bandpass.get("low_cut")
        high_cut = bandpass.get("high_cut")
    else:
        low_cut, high_cut = {
            "usb": (150, 2750), "lsb": (-2750, -150), "nfm": (-4000, 4000),
            "empty": (None, None),
        }.get(primary, (150, 2750))
    return {
        "offset_freq": int(frequency) - int(center_frequency),
        "mod": primary,
        "secondary_mod": str(mode.get("modulation") or ""),
        "secondary_offset_freq": 0,
        "squelch_level": -150,
        "low_cut": low_cut,
        "high_cut": high_cut,
    }


# Modos que entregan una TRAMA completa por mensaje (una línea con marca de tiempo).
_WSJT_MODES = {
    "FT8", "FT4", "JT65", "JT9", "JT4", "WSPR", "FST4", "FST4W", "Q65", "JS8", "MSK144",
}
_PAGE_MODES = {"POCSAG", "FLEX"}
_PACKET_MODES = {"APRS", "AX.25", "AX25", "PACKET"}


def _decoder_stamp(timestamp) -> str:
    try:
        numeric = float(timestamp)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, timezone.utc).strftime("%H:%M:%S")
    except Exception:
        return str(timestamp or "").strip()


def format_decoder_message(message) -> str:
    """Formatea UNA trama (dict) segun su familia de modo.

    Los modos de texto en flujo (PSK31/RTTY/CW/Navtex...) NO pasan por aqui:
    su texto crudo se inserta tal cual en _append_message.
    """
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return str(message)

    stamp = _decoder_stamp(message.get("timestamp"))
    mode = str(message.get("mode") or "").strip()
    mu = mode.upper()

    # --- WSJT (FT8/FT4/JT65/WSPR/JS8/...) ---
    if mu in _WSJT_MODES or (message.get("msg") is not None and message.get("db") is not None):
        parts = [stamp, (mu or "WSJT")]
        db = message.get("db")
        if db not in (None, ""):
            try:
                parts.append(f"{int(round(float(db))):>4} dB")
            except (TypeError, ValueError):
                parts.append(f"{db} dB")
        dt = message.get("dt")
        if dt not in (None, ""):
            try:
                parts.append(f"DT{float(dt):+.1f}")
            except (TypeError, ValueError):
                parts.append(f"DT {dt}")
        freq = message.get("freq")
        if freq not in (None, ""):
            try:
                parts.append(f"{int(freq):>4}Hz")
            except (TypeError, ValueError):
                parts.append(str(freq))
        msg = str(message.get("msg") or "").strip()
        if msg:
            parts.append(msg)
        return "  ".join(p for p in parts if str(p).strip())

    # --- Buscapersonas (POCSAG/FLEX) ---
    if mu in _PAGE_MODES or (message.get("address") is not None and message.get("message") is not None):
        parts = [stamp, (mu or "PAGE")]
        addr = message.get("address")
        if addr not in (None, ""):
            parts.append(f"[{addr}]")
        fn = message.get("function")
        if fn not in (None, ""):
            parts.append(f"f{fn}")
        body = str(message.get("message") or message.get("text") or "").strip()
        if body:
            parts.append(body)
        return "  ".join(p for p in parts if str(p).strip())

    # --- Paquete / APRS ---
    if mu in _PACKET_MODES or message.get("source") is not None:
        src = str(message.get("source") or message.get("address") or "").strip()
        body = str(
            message.get("comment") or message.get("message")
            or message.get("data") or message.get("text") or ""
        ).strip()
        head = f"{src}:" if src else ""
        return "  ".join(p for p in [stamp, (mu or "PACKET"), head, body] if str(p).strip())

    # --- Otros con texto/mensaje sueltos ---
    if message.get("text") is not None:
        return "  ".join(p for p in [stamp, mu, str(message.get("text") or "").strip()] if str(p).strip())
    if message.get("message") is not None:
        return "  ".join(p for p in [stamp, mu, str(message.get("message") or "").strip()] if str(p).strip())

    compact = {key: value for key, value in message.items() if key not in ("pixels", "color")}
    return json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))


def is_image_decoder_message(message) -> bool:
    """Identify SSTV/Fax image data and their non-displayable control events."""
    if not isinstance(message, dict):
        return False
    mode = str(message.get("mode") or "").strip().upper()
    try:
        has_dimensions = int(message.get("width", 0) or 0) > 0 and int(message.get("height", 0) or 0) > 0
    except (TypeError, ValueError):
        has_dimensions = False
    return (
        mode in ("SSTV", "FAX")
        or message.get("pixels") is not None
        or has_dimensions
    )


class DigitalStream(OpenWebRxStream):
    def __init__(self, host: str, port: int, lang: str = "es") -> None:
        super().__init__(host, port, lang)
        self.modes: list[dict] = []
        self.messages: deque[tuple[int, object]] = deque(maxlen=1000)
        self.message_sequence = 0
        self.secondary_fft: np.ndarray | None = None
        self.secondary_fft_sequence = 0
        self._secondary_decoder = ImaAdpcmDecoder()
        self._seen_text_types: set[str] = set()
        self._seen_binary_types: set[int] = set()

    def _handle_text(self, raw: str) -> None:
        super()._handle_text(raw)
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        kind = str(payload.get("type") or "")
        value = payload.get("value")
        if kind and kind not in self._seen_text_types:
            self._seen_text_types.add(kind)
            log(f"received type={kind}")
        with self.lock:
            if kind == "modes" and isinstance(value, list):
                self.modes = available_digital_modes(value)
                log(f"modes available={len(self.modes)}")
            elif kind == "secondary_config" and isinstance(value, dict):
                self.config.update(value)
            elif kind == "secondary_demod":
                self.message_sequence += 1
                self.messages.append((self.message_sequence, value))
                if self.message_sequence <= 5 or self.message_sequence % 200 == 0:
                    log(f"secondary_demod #{self.message_sequence} {type(value).__name__}: {repr(value)[:280]}")
            elif kind == "demodulator_error":
                self.status = str(value or t("digi_decoder_error", self._lang))

    def _handle_binary(self, raw: bytes) -> None:
        if raw and raw[0] not in self._seen_binary_types:
            self._seen_binary_types.add(raw[0])
            log(f"received binary type={raw[0]} bytes={len(raw) - 1}")
        if raw and raw[0] == 3:
            with self.lock:
                compression = str(self.config.get("fft_compression", "none") or "none")
                expected = int(self.config.get("secondary_fft_size", 0) or 0)
            values = decode_fft_payload(raw[1:], compression, self._secondary_decoder)
            if expected > 0 and values.size > expected:
                values = values[:expected]
            if values.size:
                with self.lock:
                    self.secondary_fft = values
                    self.secondary_fft_sequence += 1
            return
        # The Digi panel does not draw the main receiver FFT. Ignoring frame
        # type 1 avoids decoding thousands of unused samples on the Pi.

    def digi_snapshot(self) -> tuple[list[dict], list[tuple[int, object]], np.ndarray | None, int, dict, str]:
        with self.lock:
            return (
                list(self.modes), list(self.messages), self.secondary_fft,
                self.secondary_fft_sequence, dict(self.config), self.status,
            )


class DigiWindow:
    def __init__(
        self, stream: DigitalStream, width: int, height: int, x: int, y: int,
        command_port: int, control_host: str, control_port: int,
    ) -> None:
        self.stream = stream
        self._lang = getattr(stream, "_lang", "es")
        self.command_port = int(command_port)
        self.control_host = control_host
        self.control_port = int(control_port)
        self.stop_event = threading.Event()
        self.pending_commands: "queue.Queue[dict]" = queue.Queue(maxsize=128)
        self.server = None
        self.mode_map: dict[str, dict] = {}
        self.modes_signature = ""
        self.selected_mode = self._load_saved_decoder()
        self.tuned_frequency = 0
        self.preferred_underlying = "usb"
        self.deferred_profile: dict | None = None
        self.last_dsp_signature = None
        self.last_message_sequence = 0
        self.last_fft_sequence = 0
        self.fft_values: np.ndarray | None = None
        self.image_rgb: np.ndarray | None = None
        self.image_label = ""
        self.last_geometry_save = time.monotonic()
        self.geometry_save_source = 0
        self.restore_target_x = int(x)
        self.restore_target_y = int(y)
        self.restoring_geometry = True
        self.last_theme_check = 0.0
        self.has_decoder_output = False
        self.accent = selected_theme_accent()
        self.theme_provider = None
        self.display_scale = display_scale()
        self.window_edit_enabled = WINDOW_EDIT_PATH.exists()
        if self.display_scale < 1.0 and self.window_edit_enabled:
            original = (int(width), int(height), int(x), int(y))
            screen_height = int(Gdk.Screen.get_default().get_height())
            adjusted_y = max(26, min(int(y) + 26, screen_height - int(height)))
            adjusted = (int(width), int(height), int(x), adjusted_y)
            self.window_edit_original_geometry = original
            self.window_edit_adjusted_geometry = adjusted
            self.restore_target_y = adjusted_y

        def scaled(value: int, minimum: int = 1) -> int:
            return max(minimum, int(round(value * self.display_scale)))

        self.window = Gtk.Window(title="Digi")
        self.window.set_name("digi-window")
        if self.display_scale < 1.0:
            # PoorSDR's Digi toggle is the window close control in compact
            # mode, leaving the whole rectangle available to the decoder.
            self.window.set_decorated(self.window_edit_enabled)
        self.window.set_default_size(width, height)
        self.window.move(self.restore_target_x, self.restore_target_y)
        self.window.set_size_request(scaled(720, 300), scaled(440, 180))
        self.window.connect("delete-event", self._on_delete)
        self.window.connect("configure-event", self._on_configure)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=scaled(6))
        outer.set_name("digi-root")
        outer.set_border_width(scaled(8))
        self.window.add(outer)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=scaled(8))
        header.set_name("digi-header")
        outer.pack_start(header, False, False, 0)
        header.pack_start(Gtk.Label(label=t("digi_decoder_label", self._lang)), False, False, 0)
        self.selector = Gtk.ComboBoxText()
        self.selector.set_hexpand(False)
        self.selector.set_size_request(scaled(220, 90), -1)
        self.selector.set_wrap_width(2)
        self.selector.connect("changed", self._on_decoder_changed)
        header.pack_start(self.selector, False, False, 0)
        clear = Gtk.Button(label=t("digi_clear", self._lang))
        clear.connect("clicked", self._on_clear)
        header.pack_start(clear, False, False, 0)

        self.frequency_label = Gtk.Label(label="—")
        self.frequency_label.set_xalign(0)
        header.pack_start(self.frequency_label, False, False, 0)
        self.status_label = Gtk.Label(label=t("waterfall_connecting", self._lang))
        self.status_label.set_name("digi-status")
        self.status_label.set_xalign(0)
        outer.pack_start(self.status_label, False, False, 0)

        self.visual = Gtk.DrawingArea()
        self.visual.set_name("digi-visual")
        self.visual.set_size_request(-1, scaled(150, 60))
        self.visual.connect("draw", self._draw_visual)
        outer.pack_start(self.visual, False, True, 0)

        output_title = Gtk.Label(label=t("digi_output_title", self._lang))
        output_title.set_name("digi-output-title")
        output_title.set_xalign(0)
        outer.pack_start(output_title, False, False, scaled(2))

        scroll = Gtk.ScrolledWindow()
        scroll.set_name("digi-output")
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.text = Gtk.TextView()
        self.text.set_editable(False)
        self.text.set_cursor_visible(False)
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.buffer = self.text.get_buffer()
        self.buffer.set_text(
            t("digi_waiting_frames", self._lang) + t("digi_ft8_note", self._lang)
        )
        scroll.add(self.text)
        outer.pack_start(scroll, True, True, 0)

        self._apply_theme()

        self._start_command_server()
        self.stream.start()
        GLib.timeout_add(40, self._process_commands)
        GLib.timeout_add(180, self._tick)
        self.window.show_all()
        GLib.timeout_add(80, self._restore_window_position, 3)

    def _restore_window_position(self, attempts_left: int) -> bool:
        try:
            # Labwc/Xwayland may ignore the move issued before the GTK window
            # is mapped and apply its own cascade offset.  Once mapped,
            # repeating the saved absolute position uses the correct desktop
            # coordinate system.  Compensating with the observed delta would
            # instead request negative coordinates near a screen edge, which
            # the compositor clamps and causes the position to drift.
            self.window.move(self.restore_target_x, self.restore_target_y)
        except Exception:
            pass
        if attempts_left > 1:
            GLib.timeout_add(120, self._restore_window_position, attempts_left - 1)
        else:
            self.restoring_geometry = False
            GLib.timeout_add(180, self._save_geometry_after_configure)
        return False

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

    def _apply_theme(self) -> None:
        accent = self.accent
        scale = self.display_scale
        px = lambda value, minimum=1: max(minimum, int(round(value * scale)))
        font = lambda value, minimum=8: max(minimum, int(round(value * scale)))
        css = f"""
        #digi-window, #digi-root {{
            background-color: #050607;
            color: #e8edf2;
            font-size: {font(10)}pt;
        }}
        #digi-window label {{ color: #e8edf2; }}
        #digi-header {{
            background-color: #090c0f;
            border-bottom: {px(1)}px solid {accent};
            padding: {px(5)}px;
        }}
        #digi-window button, #digi-window combobox button {{
            background-image: none;
            background-color: #11161b;
            color: #f3f6f8;
            border: {px(1)}px solid {accent};
            border-radius: {px(3)}px;
            padding: {px(5)}px {px(9)}px;
        }}
        #digi-window button:hover, #digi-window combobox button:hover {{
            background-color: {accent};
            color: #050607;
        }}
        menu, menuitem, menuitem label {{
            background-color: #0b0e12;
            color: #f3f6f8;
        }}
        menuitem:hover, menuitem:hover label {{
            background-color: {accent};
            color: #050607;
        }}
        #digi-status {{ color: {accent}; padding: {px(2)}px {px(4)}px; }}
        #digi-output-title {{
            color: {accent};
            font-weight: bold;
            font-size: {font(12)}pt;
            padding-top: {px(3)}px;
        }}
        #digi-visual {{
            background-color: #06080a;
            border: {px(1)}px solid #27303a;
        }}
        #digi-output {{ border: {px(1)}px solid {accent}; }}
        #digi-output textview, #digi-output textview text {{
            background-color: #050607;
            color: #e8edf2;
            font-family: monospace;
            font-size: {font(11)}pt;
        }}
        #digi-output textview selection {{
            background-color: {accent};
            color: #050607;
        }}
        #digi-window scrollbar, #digi-window scrollbar trough {{ background-color: #090c0f; }}
        #digi-window scrollbar slider {{ background-color: {accent}; min-width: {px(8)}px; min-height: {px(8)}px; }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen is not None:
            if self.theme_provider is not None:
                Gtk.StyleContext.remove_provider_for_screen(screen, self.theme_provider)
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            self.theme_provider = provider

    @staticmethod
    def _load_saved_decoder() -> str:
        try:
            loaded = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
            return str(loaded.get("decoder") or "") if isinstance(loaded, dict) else ""
        except Exception:
            return ""

    def _start_command_server(self) -> None:
        if not self.command_port:
            return
        owner = self

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
                        owner.pending_commands.put_nowait(payload)
                except Exception:
                    pass

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", self.command_port), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="owrx_digi_commands").start()

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
                requested = str(command.get("mode") or "").lower()
                if requested == "fm":
                    requested = "nfm"
                if requested in ("usb", "lsb", "nfm"):
                    self.preferred_underlying = requested
                self.last_dsp_signature = None
                log(f"command tune={self.tuned_frequency} preferred={self.preferred_underlying}")
            elif kind == "profile":
                self.deferred_profile = dict(command)
            elif kind == "decoder":
                self._select_decoder(str(command.get("decoder") or ""))
        return True

    def _select_profile(self, command: dict, profiles: list[dict]) -> bool:
        target = str(command.get("profile") or "").casefold().strip()
        sdr_hint = str(command.get("sdr") or "").casefold().strip()
        candidates = profiles
        if sdr_hint:
            hinted = [item for item in profiles if sdr_hint in str(item.get("id", "")).casefold()]
            if hinted:
                candidates = hinted
        match = next((item for item in candidates if target and target in f"{item.get('id', '')} {item.get('name', '')}".casefold()), None)
        if not match and target:
            m = re.search(r"\d+\s*c?m", target)
            tok = m.group(0).replace(" ", "") if m else ""
            if tok:
                match = next(
                    (item for item in candidates
                     if re.search(r"(?<![0-9a-z])" + re.escape(tok) + r"(?![0-9a-z])",
                                  str(item.get("name", "")).casefold())),
                    None,
                )
        if not match:
            return False
        params = {"profile": str(match.get("id") or "")}
        if command.get("key"):
            params["key"] = str(command["key"])
        self.stream.send({"type": "selectprofile", "params": params})
        self.last_dsp_signature = None
        return True

    def _apply_decoder(self, config: dict) -> None:
        mode = self.mode_map.get(self.selected_mode)
        center = int(config.get("center_freq", 0) or 0)
        if not mode or not center or not self.tuned_frequency:
            return
        params = decoder_params(mode, self.tuned_frequency, center, self.preferred_underlying)
        signature = (center, self.tuned_frequency, self.selected_mode, repr(params))
        if signature == self.last_dsp_signature:
            return
        self.last_dsp_signature = signature
        # OpenWebRX's own client configures the secondary demodulator before
        # starting it.  WSJT modes in particular need those parameters when
        # their interval-aligned audio chopper is created.
        self.stream.send({"type": "dspcontrol", "params": params})
        self.stream.send({"type": "dspcontrol", "action": "start"})
        log(f"decoder={self.selected_mode} freq={self.tuned_frequency} center={center} mod={params['mod']}")

    def _select_decoder(self, modulation: str) -> None:
        if modulation not in self.mode_map:
            return
        self.selected_mode = modulation
        self.last_dsp_signature = None
        self.image_rgb = None
        self.image_label = ""
        if self.selector.get_active_id() != modulation:
            self.selector.set_active_id(modulation)

    def _on_decoder_changed(self, selector) -> None:
        selected = str(selector.get_active_id() or "")
        if selected:
            self._select_decoder(selected)

    def _is_stream_text(self, message) -> bool:
        """True para modos de TEXTO EN FLUJO (PSK31/RTTY/CW/Navtex/SITOR/DSC/
        MFSK...): OWRX manda el texto crudo (str) o {'text': ...} sin marca de
        tiempo ni SNR, a menudo carácter a carácter."""
        if isinstance(message, str):
            return True
        if not isinstance(message, dict):
            return False
        if message.get("text") is None:
            return False
        # Si trae metadatos de trama (msg/db/dt/address/source) NO es flujo.
        if any(message.get(k) is not None for k in ("msg", "db", "dt", "address", "source")):
            return False
        mu = str(message.get("mode") or "").strip().upper()
        return mu not in _WSJT_MODES | _PAGE_MODES | _PACKET_MODES

    def _buffer_write(self, text: str, newline: bool) -> None:
        if not text:
            return
        if not self.has_decoder_output:
            self.buffer.set_text("")
            self.has_decoder_output = True
        self.buffer.insert(self.buffer.get_end_iter(), text + ("\n" if newline else ""))
        if self.buffer.get_line_count() > 1000:
            start = self.buffer.get_start_iter()
            cutoff = self.buffer.get_iter_at_line(self.buffer.get_line_count() - 800)
            self.buffer.delete(start, cutoff)
        mark = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        self.text.scroll_mark_onscreen(mark)

    def _append_message(self, message) -> None:
        # Imágenes (SSTV / FAX): a la vista de imagen; los eventos de control se ignoran.
        if is_image_decoder_message(message):
            if (
                message.get("pixels") is not None
                or (message.get("width") and message.get("height"))
            ):
                self._update_image(message)
            return

        # Texto en flujo -> tal cual, sin salto de línea añadido.
        if self._is_stream_text(message):
            raw = message if isinstance(message, str) else str(message.get("text") or "")
            self._buffer_write(raw, newline=False)
            return

        # Trama (FT8/FT4/WSPR/JS8/Pocsag/APRS...) -> una línea con formato propio.
        line = format_decoder_message(message)
        if line:
            self._buffer_write(line, newline=True)

    @staticmethod
    def _decode_fax_rle(data: bytes) -> bytes:
        out = bytearray()
        index = 0
        while index < len(data):
            count = data[index]
            if count < 128:
                end = index + count + 2
                out.extend(data[index + 1:end])
                index = end
            else:
                if index + 1 >= len(data):
                    break
                out.extend(bytes([data[index + 1]]) * (count - 128 + 2))
                index += 2
        return bytes(out)

    def _update_image(self, message: dict) -> None:
        try:
            width = int(message.get("width", 0) or 0)
            height = int(message.get("height", 0) or 0)
            if width <= 0 or height <= 0:
                return
            if self.image_rgb is None or self.image_rgb.shape[:2] != (height, width):
                self.image_rgb = np.zeros((height, width, 3), dtype=np.uint8)
                mode = str(message.get("sstvMode") or message.get("faxMode") or message.get("mode") or "Imagen")
                self.image_label = f"{mode}  {width}×{height}"
            if message.get("pixels") is None or message.get("line") is None:
                self.visual.queue_draw()
                return
            line = int(message.get("line", -1))
            if not 0 <= line < height:
                return
            raw = base64.b64decode(str(message.get("pixels") or ""))
            if message.get("rle"):
                raw = self._decode_fax_rle(raw)
            depth = int(message.get("depth", 24) or 24)
            if depth == 8 and len(raw) >= width:
                gray = np.frombuffer(raw[:width], dtype=np.uint8)
                self.image_rgb[line, :, :] = gray[:, None]
            elif len(raw) >= width * 3:
                bgr = np.frombuffer(raw[:width * 3], dtype=np.uint8).reshape(width, 3)
                self.image_rgb[line] = bgr[:, ::-1]
            self.visual.queue_draw()
        except Exception as exc:
            log(f"image error {exc!r}")

    def _draw_visual(self, area, ctx) -> bool:
        allocation = area.get_allocation()
        width, height = max(1, allocation.width), max(1, allocation.height)
        ctx.set_source_rgb(0.025, 0.03, 0.04)
        ctx.paint()
        if self.image_rgb is not None:
            image = self.image_rgb
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
                GLib.Bytes.new(image.tobytes()), GdkPixbuf.Colorspace.RGB, False, 8,
                int(image.shape[1]), int(image.shape[0]), int(image.shape[1] * 3),
            )
            scale = min(width / image.shape[1], height / image.shape[0])
            ctx.save()
            ctx.translate((width - image.shape[1] * scale) / 2, 0)
            ctx.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
            ctx.paint()
            ctx.restore()
            return False
        values = self.fft_values
        if values is None or not values.size:
            return False
        finite = np.nan_to_num(values.astype(np.float32), nan=-120.0, posinf=0.0, neginf=-120.0)
        minimum, maximum = float(np.percentile(finite, 5)), float(np.percentile(finite, 98))
        if maximum <= minimum:
            maximum = minimum + 1.0
        positions = np.linspace(0, finite.size - 1, width)
        samples = np.interp(positions, np.arange(finite.size), finite)
        ctx.set_source_rgb(*accent_rgb(self.accent))
        ctx.set_line_width(1.2)
        for index, value in enumerate(samples):
            y = height - 4 - np.clip((value - minimum) / (maximum - minimum), 0.0, 1.0) * (height - 8)
            if index == 0:
                ctx.move_to(0, y)
            else:
                ctx.line_to(index, y)
        ctx.stroke()
        return False

    def _tick(self) -> bool:
        if self.stop_event.is_set():
            return False
        if self.display_scale < 1.0:
            window_edit_enabled = WINDOW_EDIT_PATH.exists()
            if window_edit_enabled != self.window_edit_enabled:
                self._set_window_edit_mode(window_edit_enabled)
        modes, messages, fft, fft_sequence, config, status = self.stream.digi_snapshot()
        _main_fft, _seq, _cfg, profiles, _marks, _bands, _main_status = self.stream.snapshot()
        signature = repr([(mode.get("modulation"), mode.get("name")) for mode in modes])
        if signature != self.modes_signature:
            previous = self.selected_mode
            self.modes_signature = signature
            self.mode_map = {str(mode.get("modulation") or ""): mode for mode in modes}
            self.selector.remove_all()
            for mode in modes:
                self.selector.append(str(mode.get("modulation") or ""), str(mode.get("name") or mode.get("modulation") or ""))
            target = previous if previous in self.mode_map else ("ft8" if "ft8" in self.mode_map else next(iter(self.mode_map), ""))
            if target:
                self._select_decoder(target)
        if self.deferred_profile and self._select_profile(self.deferred_profile, profiles):
            self.deferred_profile = None
        self._apply_decoder(config)
        for sequence, message in messages:
            if sequence > self.last_message_sequence:
                self.last_message_sequence = sequence
                self._append_message(message)
        if fft_sequence != self.last_fft_sequence:
            self.last_fft_sequence = fft_sequence
            self.fft_values = fft
            self.visual.queue_draw()
        decoder_name = str(self.mode_map.get(self.selected_mode, {}).get("name") or self.selected_mode or "—")
        waiting = "" if self.has_decoder_output else " · esperando tramas"
        self.status_label.set_text(
            f"{status} · {decoder_name} activo{waiting} · {len(modes)} decodificadores disponibles"
        )
        if self.tuned_frequency:
            self.frequency_label.set_text(f"{self.tuned_frequency / 1_000_000:.6f} MHz")
        now = time.monotonic()
        if now - self.last_theme_check >= 1.0:
            self.last_theme_check = now
            current_accent = selected_theme_accent()
            if current_accent != self.accent:
                self.accent = current_accent
                self._apply_theme()
                self.visual.queue_draw()
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

    def _on_clear(self, _button) -> None:
        self.has_decoder_output = False
        self.buffer.set_text(t("digi_waiting_new_frames", self._lang))
        self.image_rgb = None
        self.image_label = ""
        self.visual.queue_draw()

    def _on_configure(self, *_args) -> bool:
        if self.restoring_geometry:
            return False
        if self.geometry_save_source:
            try:
                GLib.source_remove(self.geometry_save_source)
            except Exception:
                pass
        self.geometry_save_source = GLib.timeout_add(150, self._save_geometry_after_configure)
        return False

    def _save_geometry_after_configure(self) -> bool:
        self.geometry_save_source = 0
        self._save_geometry()
        return False

    def _save_geometry(self) -> None:
        try:
            width, height = self.window.get_size()
            x, y = self._client_position()
            data = {"width": int(width), "height": int(height), "x": int(x), "y": int(y),
                    "decoder": self.selected_mode}
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = STATE_PATH.with_name(f".{STATE_PATH.name}.tmp-{os.getpid()}")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, STATE_PATH)
        except Exception:
            pass

    def _on_delete(self, *_args) -> bool:
        self.close()
        return True

    def close(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self._save_geometry()
        # Stop the selected secondary decoder immediately. Closing Digi must
        # also stop WSJT/JS8 jobs; no decoder is meant to remain in the
        # background after the panel has been switched off.
        self.stream.send({"type": "dspcontrol", "action": "stop"})
        self.stream.stop()
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
        except Exception:
            pass
        Gtk.main_quit()


def main() -> int:
    if Gtk is None:
        print("OWRX_DIGI_ERROR: GTK3/PyGObject no está disponible", file=sys.stderr)
        return 3
    if len(sys.argv) < 4:
        print("Usage: owrx_digi.py <url> <width> <height> [port] [control_host] [control_port]", file=sys.stderr)
        return 2
    parsed = urlparse(sys.argv[1])
    width, height, x, y = parse_geometry(int(sys.argv[2]), int(sys.argv[3]))
    command_port = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else 0
    control_host = sys.argv[5] if len(sys.argv) > 5 else "127.0.0.1"
    control_port = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] else 0
    lang = os.environ.get("POORSDR_UI_LANG", "es") or "es"
    stream = DigitalStream(parsed.hostname or "127.0.0.1", parsed.port or 8073, lang)
    window = DigiWindow(stream, width, height, x, y, command_port, control_host, control_port)
    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(window.close))
    signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(window.close))
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
