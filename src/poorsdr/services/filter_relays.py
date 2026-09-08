"""Servicio de relés de filtros por WiFi.

Envuelve ``_legacy/filter_relays_wifi.py:BandRelayWifiController`` y le manda la
banda actual cada vez que cambia la frecuencia (evento ``radio.frequency``).
Portado de ``RadioCBApp._sync_filter_relays_for_frequency``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from poorsdr.core.bands import infer_band
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import Event, EventBus


class RelayControllerLike(Protocol):
    enabled: bool

    def apply_band(self, band: str, *, force: bool = ..., source: str = ...) -> bool: ...


def _default_controller_factory(cfg: AppConfig, log_fn: Callable[[str], None]) -> Any:
    from filter_relays_wifi import BandRelayWifiController

    return BandRelayWifiController.from_config(cfg.to_legacy(), log_fn=log_fn)


class FilterRelayService(BaseService):
    name = "filter-relays"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        controller_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._make_controller = controller_factory or _default_controller_factory
        self._controller: Any | None = None
        self._unsub: Callable[[], None] | None = None
        self._last_band = ""

    def start(self) -> None:
        if not self._cfg.relays.enabled:
            self._set_status(ServiceState.STOPPED, "deshabilitado")
            return
        try:
            self._controller = self._make_controller(self._cfg, self.log.info)
        except Exception as exc:  # noqa: BLE001
            self.log.exception("no se pudo crear el controlador de relés")
            self._set_status(ServiceState.ERROR, str(exc))
            return
        self._unsub = self.bus.subscribe("radio.frequency", self._on_frequency)
        self._set_status(ServiceState.RUNNING, self._cfg.relays.url or "sin URL")

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self._controller = None
        self._last_band = ""
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        old = self._cfg.relays
        self._cfg = cfg
        new = cfg.relays
        if (new.enabled, new.url, new.api_key, new.timeout_ms) != (
            old.enabled,
            old.url,
            old.api_key,
            old.timeout_ms,
        ) or new.band_groups != old.band_groups:
            self.log.info("config de relés cambiada; recreando el controlador")
            self.stop()
            self.start()

    def _on_frequency(self, ev: Event) -> None:
        ctrl = self._controller
        if ctrl is None or not getattr(ctrl, "enabled", False):
            return
        band = infer_band(int(ev.get("hz", 0) or 0))
        if not band or band == self._last_band:
            return
        self._last_band = band
        try:
            ctrl.apply_band(band, source="radio")
        except Exception:  # noqa: BLE001
            self.log.debug("apply_band(%s) falló", band, exc_info=True)


__all__ = ["FilterRelayService", "RelayControllerLike"]
