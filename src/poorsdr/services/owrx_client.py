"""Servicio del cliente WebSocket de OpenWebRX+.

Envuelve el ``OwrxClient`` heredado (WebSocket, decodificación FFT nativa, audio
IMA-ADPCM) y lo alimenta desde el :class:`~poorsdr.infra.events.EventBus`: cuando
la radio cambia de frecuencia/modo o cambia la banda/perfil, se lo reenvía al
backend OWRX. Así el visor de cascada sigue a la app sin *reach-ins*.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import Event, EventBus


class OwrxClientLike(Protocol):
    enabled: bool

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def send_frequency(self, hz: int) -> None: ...

    def send_mode(self, mode: str) -> None: ...

    def send_profile(self, profile: str) -> None: ...


def _default_client_factory(cfg: AppConfig) -> OwrxClientLike | None:
    try:
        from owrx_client import OwrxClient
    except Exception:  # noqa: BLE001 - sin _legacy: sin cliente OWRX
        return None
    return OwrxClient.from_config(cfg.to_legacy())


class OwrxClientService(BaseService):
    name = "owrx-client"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        client_factory: Callable[[AppConfig], OwrxClientLike | None] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._make_client = client_factory or _default_client_factory
        self._client: OwrxClientLike | None = None
        self._unsubs: list[Callable[[], None]] = []

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        cfg = self._cfg
        if not cfg.owrx.enabled or not (cfg.owrx.host or "").strip():
            self._set_status(ServiceState.STOPPED, "deshabilitado")
            return
        self._set_status(ServiceState.STARTING)
        try:
            self._client = self._make_client(cfg)
            if self._client is not None:
                self._client.start()
        except Exception as exc:  # noqa: BLE001
            self.log.exception("no se pudo arrancar el cliente OWRX")
            self._set_status(ServiceState.ERROR, str(exc))
            return

        self._unsubs = [
            self.bus.subscribe("radio.frequency", self._on_frequency),
            self.bus.subscribe("radio.mode", self._on_mode),
            self.bus.subscribe("owrx.band", self._on_band),
        ]
        self._set_status(ServiceState.RUNNING)
        self.bus.publish("owrx.status", component="client", ready=self._client is not None)

    def stop(self) -> None:
        for cancel in self._unsubs:
            cancel()
        self._unsubs = []
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.stop()
            except Exception:  # noqa: BLE001
                self.log.debug("parada del cliente OWRX con excepción", exc_info=True)
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        old = self._cfg.owrx
        self._cfg = cfg
        new = cfg.owrx
        if (new.enabled, new.host, new.port, new.key) != (old.enabled, old.host, old.port, old.key):
            self.log.info("config del cliente OWRX cambiada; reconectando")
            self.stop()
            self.start()

    # ---- reenvío de eventos al backend ----------------------------- #
    def _on_frequency(self, ev: Event) -> None:
        self._forward(lambda c: c.send_frequency(int(ev["hz"])))

    def _on_mode(self, ev: Event) -> None:
        self._forward(lambda c: c.send_mode(str(ev["mode"])))

    def _on_band(self, ev: Event) -> None:
        profile = ev.get("profile")
        if profile:
            self._forward(lambda c: c.send_profile(str(profile)))

    def _forward(self, action: Callable[[OwrxClientLike], Any]) -> None:
        client = self._client
        if client is None or not getattr(client, "enabled", False):
            return
        try:
            action(client)
        except Exception:  # noqa: BLE001
            self.log.debug("reenvío al cliente OWRX falló", exc_info=True)


__all__ = ["OwrxClientLike", "OwrxClientService"]
