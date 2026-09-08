"""Servidor de control de los visores OWRX (cascada / digi) + canal de comandos.

Los visores (``owrx_native.py`` / ``owrx_digi.py``) abren su propio WebSocket a
OpenWebRX, decodifican audio y FFT, y se lo mandan a PoorSDR por un socket TCP
local (líneas JSON). Este servicio:

- **recibe** de ellos ``audio_chunk`` (→ pipeline de audio, altavoz + cascada) y
  ``tune`` (sintonía inversa desde la cascada);
- **envía** hacia ellos ``profile`` (perfil SDR al cambiar de banda), ``tune`` y
  ``step``, conectándose al puerto que el visor deja a la escucha.

Sustituye el núcleo de ``RadioCBApp._start_owrx_control_server`` /
``_on_owrx_control_message`` / ``_send_owrx_profile_for_band`` /
``_send_owrx_viewer_command``.
"""

from __future__ import annotations

import base64
import json
import socket
import socketserver
import threading
from typing import TYPE_CHECKING, Any

from poorsdr.core.bands import infer_band
from poorsdr.core.cat.modes import DEFAULT_MODE
from poorsdr.core.owrx.process import (
    normalize_incoming_tune_mode,
    parse_incoming_tune_frequency,
)
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import Event, EventBus


def resolve_profile(cfg: AppConfig, band: str) -> str:
    """Nombre del perfil OWRX para ``band``: mapa explícito → ``<hint> <band>`` → ``band``."""
    profiles = cfg.owrx.band_profiles or {}
    if band in profiles and str(profiles[band]).strip():
        return str(profiles[band]).strip()
    hint = (cfg.owrx.sdr_hint or "").strip()
    return f"{hint} {band}".strip() if hint else band


class OwrxControlService(BaseService):
    name = "owrx-control"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        audio_push: Callable[[bytes, int, int], None] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._audio_push = audio_push or (lambda _d, _r, _c: None)
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._clients: set[Any] = set()
        self._clients_lock = threading.Lock()
        self._unsubs: list[Callable[[], None]] = []
        self._viewer_ports: dict[str, int] = {}  # "waterfall" / "digi" → puerto
        self._last_band = infer_band(int(cfg.cat.start_freq_hz))
        self._step_hz = max(1, int(cfg.cat.step_hz))
        # Frecuencia/modo actuales del equipo: se siembran de la config al
        # arrancar (igual que RadioService) y se mantienen al día por el bus.
        # Sin esto, un visor que se abre a media sesión solo recibe el
        # perfil de banda y arranca centrado en él, no donde está sintonizado
        # de verdad el equipo.
        self._last_freq_hz = int(cfg.cat.start_freq_hz)
        self._last_mode = (cfg.ui.display_mode or DEFAULT_MODE).upper()

    @property
    def port(self) -> int:
        return int(self._server.server_address[1]) if self._server is not None else 0

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        if self._server is not None:
            return
        service = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(inner) -> None:  # noqa: N805
                service._register(inner.request)
                service._on_client_connected()
                buf = b""
                try:
                    while True:
                        chunk = inner.request.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        while b"\n" in buf:
                            line, _, buf = buf.partition(b"\n")
                            service._handle_line(line)
                finally:
                    service._unregister(inner.request)

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.05) if self._server else None,
            name="owrx-control",
            daemon=True,
        )
        self._thread.start()
        self._unsubs = [
            self.bus.subscribe("radio.frequency", self._on_radio_frequency),
            self.bus.subscribe("radio.mode", self._on_radio_mode),
        ]
        self._set_status(ServiceState.RUNNING, f"127.0.0.1:{self.port}")

    def stop(self) -> None:
        for cancel in self._unsubs:
            cancel()
        self._unsubs = []
        server = self._server
        self._server = None
        if server is not None:
            with self._clients_lock:
                self._clients.clear()
            try:
                server.shutdown()
                server.server_close()
            except Exception:  # noqa: BLE001
                self.log.debug("cierre del servidor de control con excepción", exc_info=True)
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        old_src = self._cfg.audio.rx_source
        old_spots = self._cfg.owrx.spots
        old_step = self._step_hz
        self._cfg = cfg
        self._step_hz = max(1, int(cfg.cat.step_hz))
        if cfg.audio.rx_source != old_src:
            self._send_audio_capture()
        if cfg.owrx.spots != old_spots:
            self._send_spots()
        if self._step_hz != old_step:
            self._send_step()

    # ---- API: puerto del visor + envío de comandos ---------------- #
    def set_viewer_port(self, kind: str, port: int) -> None:
        """Registra el puerto a la escucha de un visor (``kind`` = waterfall|digi)."""
        self._viewer_ports[kind] = int(port)
        self._push_profile_and_tune(force=True)
        self._send_step()
        self._send_spots()
        self._send_audio_capture()

    def _send_audio_capture(self) -> None:
        """Le dice al visor si debe decodificar y reenviar el audio (modo SDR).

        Va por el puerto de comandos del visor: el socket que el visor abre
        *hacia* este servicio es de solo escritura (el visor no lo lee).
        """
        self._send_to_viewers(
            {"type": "audio_capture", "enabled": self._cfg.audio.rx_source == "sdr"}
        )

    def set_step(self, step_hz: int) -> None:
        """Fija el paso de sintonía (Hz) que usará la rueda del ratón en los visores."""
        self._step_hz = max(1, int(step_hz))
        self._send_step()

    def _send_step(self) -> None:
        self._send_to_viewers({"type": "step", "step_hz": self._step_hz})

    def _send_spots(self) -> None:
        """Envía a los visores el estado de spots con el contrato del original.

        ``modes`` es la lista de tipos a pintar (``CW`` / ``DIGI`` / ``SSB``);
        ``enabled`` ya incorpora "fuera de banda" (``off`` lo desactiva todo).
        """
        s = self._cfg.owrx.spots
        modes: list[str] = []
        if s.filter_cw:
            modes.append("CW")
        if s.filter_digi:
            modes.append("DIGI")
        if s.filter_ssb:
            modes.append("SSB")
        self._send_to_viewers(
            {
                "type": "spots",
                "enabled": bool(s.enabled) and not bool(s.filter_off),
                "off": bool(s.filter_off),
                "modes": modes,
                "retention_sec": max(60, int(s.retention_min) * 60),
            }
        )

    def clear_viewer_port(self, kind: str) -> None:
        self._viewer_ports.pop(kind, None)

    def _send_to_viewers(self, payload: dict[str, Any]) -> None:
        message = (json.dumps(payload) + "\n").encode("utf-8")
        for port in list(self._viewer_ports.values()):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3) as sock:
                    sock.sendall(message)
            except OSError:
                self.log.debug("no se pudo mandar %s al visor :%s", payload.get("type"), port)

    def _push_profile_and_tune(self, *, force: bool = False) -> None:
        if not self._viewer_ports:
            return
        band = self._last_band
        profile = resolve_profile(self._cfg, band)
        payload: dict[str, Any] = {"type": "profile", "profile": profile}
        hint = (self._cfg.owrx.sdr_hint or "").strip()
        if hint:
            payload["sdr"] = hint
        key = (self._cfg.owrx.key or "").strip()
        if key:
            payload["key"] = key
        self._send_to_viewers(payload)
        # El perfil por sí solo no sintoniza nada: el visor necesita también
        # la frecuencia/modo reales del equipo, si no arranca centrado en el
        # perfil en vez de donde está sintonizada la radio.
        self._send_to_viewers({
            "type": "tune", "frequency": self._last_freq_hz, "mode": self._last_mode,
        })

    # ---- clientes (conexiones entrantes de los visores) ------------ #
    def _register(self, conn: Any) -> None:
        with self._clients_lock:
            self._clients.add(conn)

    def _unregister(self, conn: Any) -> None:
        with self._clients_lock:
            self._clients.discard(conn)

    def _on_client_connected(self) -> None:
        self.bus.publish("owrx.status", component="viewer", ready=True)
        # El visor ya tiene su servidor de comandos a la escucha (acaba de
        # conectarse de vuelta): reenvía todo por ahí, porque el envío de
        # ``set_viewer_port`` ocurre antes de que el visor arranque.
        self._push_profile_and_tune(force=True)
        self._send_step()
        self._send_spots()
        self._send_audio_capture()

    # ---- mensajes entrantes -------------------------------------- #
    def _handle_line(self, line: bytes) -> None:
        try:
            payload = json.loads(line.decode("utf-8", "ignore"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(payload, dict):
            return
        kind = str(payload.get("type") or "")
        if kind == "audio_chunk":
            self._handle_audio_chunk(payload)
        elif kind == "tune":
            self._handle_tune(payload)
        elif kind == "smeter":
            self._handle_smeter(payload)
        elif kind == "client_connected":
            self.bus.publish("owrx.status", component="viewer", ready=True)

    def _handle_audio_chunk(self, payload: dict[str, Any]) -> None:
        if self._cfg.audio.rx_source != "sdr":
            return
        pcm_b64 = payload.get("pcm")
        if not pcm_b64:
            return
        try:
            data = base64.b64decode(pcm_b64)
        except (ValueError, TypeError):
            return
        rate = int(payload.get("sample_rate") or 48000)
        channels = int(payload.get("channels") or 2)
        try:
            self._audio_push(data, rate, channels)
        except Exception:  # noqa: BLE001
            self.log.debug("push de audio OWRX falló", exc_info=True)

    def _handle_tune(self, payload: dict[str, Any]) -> None:
        freq = parse_incoming_tune_frequency(payload.get("frequency") or payload.get("freq"))
        if freq is None:
            return
        mode = normalize_incoming_tune_mode(payload.get("mode") or payload.get("modulation") or "")
        self.bus.publish("owrx.tune", hz=int(freq), mode=mode, source="owrx")

    def _handle_smeter(self, payload: dict[str, Any]) -> None:
        raw = payload.get("dbfs")
        if raw is None:
            return
        try:
            dbfs = float(raw)
        except (TypeError, ValueError):
            return
        self.bus.publish("owrx.smeter", dbfs=dbfs)

    # ---- eventos del bus (consola → visores) -------------------- #
    def _on_radio_frequency(self, ev: Event) -> None:
        hz = int(ev["hz"])
        self._last_freq_hz = hz
        band = infer_band(hz)
        if band != self._last_band:
            self._last_band = band
            self._push_profile_and_tune(force=True)
        if ev.get("source") != "owrx":
            self._send_to_viewers({"type": "tune", "frequency": hz})

    def _on_radio_mode(self, ev: Event) -> None:
        mode = str(ev["mode"])
        self._last_mode = mode.upper()
        if ev.get("source") != "owrx":
            self._send_to_viewers({"type": "tune", "mode": mode})


__all__ = ["OwrxControlService", "resolve_profile"]
