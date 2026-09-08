"""Servicio del emulador TS-480 para N1MM / log-software por TCP.

Envuelve ``_legacy/ts480_emulator.py:TS480TcpServer`` y lo mantiene sincronizado
con el estado de la radio a través del bus (``radio.frequency`` / ``radio.mode``
/ ``radio.ptt``). Portado de ``RadioCBApp._init_ts480_server`` /
``_update_n1m_state``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from poorsdr.infra import paths
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import Event, EventBus


def _default_server_factory(host: str, port: int) -> Any:
    from ts480_emulator import TS480TcpServer

    return TS480TcpServer(host, port)


class N1mService(BaseService):
    name = "n1m"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        server_factory: Callable[[str, int], Any] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._make_server = server_factory or _default_server_factory
        self._server: Any | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._freq = int(cfg.cat.start_freq_hz)
        self._mode = (cfg.ui.display_mode or "USB").upper()
        self._ptt = False

    def start(self) -> None:
        if not self._cfg.n1m.enabled:
            self._set_status(ServiceState.STOPPED, "deshabilitado")
            return
        self._set_status(ServiceState.STARTING)
        host = self._cfg.n1m.host or "127.0.0.1"
        port = int(self._cfg.n1m.port)
        try:
            self._server = self._make_server(host, port)
            if hasattr(self._server, "set_log_path"):
                self._server.set_log_path(str(paths.log_dir() / "ts480_tcp.log"))
            ok = self._server.start()
        except Exception as exc:  # noqa: BLE001
            self.log.exception("no se pudo arrancar el emulador TS-480 en %s:%s", host, port)
            self._set_status(ServiceState.ERROR, str(exc))
            return
        if ok is False:
            self._set_status(ServiceState.ERROR, "el puerto TCP no quedó a la escucha")
            return
        self._push_state()
        self._unsubs = [
            self.bus.subscribe("radio.frequency", self._on_frequency),
            self.bus.subscribe("radio.mode", self._on_mode),
            self.bus.subscribe("radio.ptt", self._on_ptt),
        ]
        self._set_status(ServiceState.RUNNING, f"{host}:{port}")

    def stop(self) -> None:
        for cancel in self._unsubs:
            cancel()
        self._unsubs = []
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.stop()
            except Exception:  # noqa: BLE001
                self.log.debug("parada del emulador con excepción", exc_info=True)
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        old = self._cfg.n1m
        self._cfg = cfg
        new = cfg.n1m
        if (new.enabled, new.host, new.port) != (old.enabled, old.host, old.port):
            self.log.info("config N1M cambiada; reiniciando el emulador")
            self.stop()
            self.start()

    # ---- sincronización desde el bus ------------------------------- #
    def _on_frequency(self, ev: Event) -> None:
        self._freq = int(ev["hz"])
        self._push_state()

    def _on_mode(self, ev: Event) -> None:
        self._mode = str(ev["mode"]).upper()
        self._push_state()

    def _on_ptt(self, ev: Event) -> None:
        self._ptt = bool(ev["active"])
        self._push_state()

    def _push_state(self) -> None:
        server = self._server
        if server is None:
            return
        try:
            server.set_state(freq=self._freq, mode=self._mode, ptt=self._ptt)
        except Exception:  # noqa: BLE001
            self.log.debug("set_state del emulador falló", exc_info=True)


__all__ = ["N1mService"]
