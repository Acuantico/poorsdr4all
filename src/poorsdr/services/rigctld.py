"""Servicio del proxy rigctld.

El endpoint rigctld (TCP, protocolo hamlib) es el "rig virtual" que consumen
WSJT-X / JTDX / N1MM / FreeDV / Libro de Guardia. Envuelve el
``RigCtldProxyServer`` heredado y aplica dos reglas del refactor:

- **Arranca siempre que esté habilitado**, aunque no haya CAT físico conectado
  (bug latente del proyecto original: el proxy solo se levantaba con la radio
  presente, y entonces esas apps no podían fijar frecuencia/modo/PTT).
- Se comunica por el :class:`~poorsdr.infra.events.EventBus`: cuando un cliente
  del proxy cambia algo, se publica ``radio.*`` y se aplica vía
  :class:`~poorsdr.services.radio.RadioService`; y a la inversa, los cambios de
  ``radio.*`` refrescan el estado cacheado del proxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from poorsdr.infra import paths
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import Event, EventBus
    from poorsdr.services.radio import RadioService

_RIG_NAME = "Kenwood TS-480"


def _default_server_factory(**kwargs: Any) -> Any:
    """Instancia el ``RigCtldProxyServer`` heredado (import perezoso)."""
    from rigctld_proxy import RigCtldProxyServer

    return RigCtldProxyServer(**kwargs)


class RigctldService(BaseService):
    name = "rigctld"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        radio: RadioService,
        *,
        server_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._radio = radio
        self._make_server = server_factory or _default_server_factory
        self._server: Any | None = None
        self._unsubs: list[Callable[[], None]] = []

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        if not self._cfg.rigctld.enabled:
            self._set_status(ServiceState.STOPPED, "deshabilitado")
            return
        self._set_status(ServiceState.STARTING)
        host = self._cfg.rigctld.host or "127.0.0.1"
        port = int(self._cfg.rigctld.port)
        try:
            self._server = self._make_server(
                cat=self._radio.controller,
                listen=host,
                port=port,
                rig_name=_RIG_NAME,
                set_frequency_cb=self._on_client_set_frequency,
                set_mode_cb=self._on_client_set_mode,
                set_ptt_cb=self._on_client_set_ptt,
                on_client_count_change_cb=self._on_client_count,
            )
            log_path = paths.log_dir() / "rigctld_proxy.log"
            if hasattr(self._server, "set_log_path"):
                self._server.set_log_path(str(log_path))
            self._server.start()
        except Exception as exc:  # noqa: BLE001
            self.log.exception("no se pudo arrancar el proxy rigctld en %s:%s", host, port)
            self._set_status(ServiceState.ERROR, str(exc))
            return

        self._sync_state_from_radio()
        self._unsubs = [
            self.bus.subscribe("radio.frequency", self._on_radio_frequency),
            self.bus.subscribe("radio.mode", self._on_radio_mode),
            self.bus.subscribe("radio.ptt", self._on_radio_ptt),
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
                self.log.debug("parada del proxy con excepción", exc_info=True)
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        old = self._cfg.rigctld
        self._cfg = cfg
        new = cfg.rigctld
        if (new.enabled, new.host, new.port) != (old.enabled, old.host, old.port):
            self.log.info("config rigctld cambiada; reiniciando el proxy")
            self.stop()
            self.start()
        elif self._server is not None:
            # el controlador CAT puede haberse recreado
            self._server.cat = self._radio.controller

    # ---- callbacks de clientes del proxy ----------------------------- #
    def _on_client_set_frequency(self, hz: int) -> None:
        self._radio.set_frequency(int(hz), source="rigctld")

    def _on_client_set_mode(self, mode: str) -> None:
        self._radio.set_mode(str(mode), source="rigctld")

    def _on_client_set_ptt(self, active: Any) -> None:
        self._radio.set_ptt(bool(int(active)), source="rigctld")

    def _on_client_count(self, count: int) -> None:
        self.bus.publish("rigctld.clients", count=int(count))

    # ---- reflejar radio.* en el estado cacheado del proxy ----------- #
    def _on_radio_frequency(self, ev: Event) -> None:
        if ev.get("source") != "rigctld":
            self._update_state("update_freq", int(ev["hz"]))

    def _on_radio_mode(self, ev: Event) -> None:
        if ev.get("source") != "rigctld":
            self._update_state("update_mode", str(ev["mode"]).upper())

    def _on_radio_ptt(self, ev: Event) -> None:
        if ev.get("source") != "rigctld":
            self._update_state("update_ptt", 1 if ev["active"] else 0)

    def _sync_state_from_radio(self) -> None:
        self._update_state("update_freq", int(self._radio.frequency_hz))
        self._update_state("update_mode", str(self._radio.mode).upper())
        self._update_state("update_ptt", 1 if self._radio.ptt else 0)

    def _update_state(self, method: str, value: Any) -> None:
        server = self._server
        state = getattr(server, "state", None)
        fn = getattr(state, method, None)
        if callable(fn):
            try:
                fn(value)
            except Exception:  # noqa: BLE001
                self.log.debug("%s(%r) en el estado del proxy falló", method, value, exc_info=True)


__all__ = ["RigctldService"]
