"""Servicio de radio: control CAT del transceptor y estado de frecuencia/modo/PTT.

Envuelve el ``CatController`` heredado (``_legacy/cat.py``, E/S por serie) y le
añade:
- **arranque tolerante**: si no hay puerto CAT o la radio no responde, el
  servicio arranca igualmente en estado ``RUNNING`` pero ``connected == False``
  (los consumidores como el proxy rigctld o WSJT-X siguen funcionando).
- **eventos de bus**: publica ``radio.frequency`` / ``radio.mode`` / ``radio.ptt``
  / ``radio.status`` en vez de que otros subsistemas lean atributos ajenos.
- **reconfiguración en caliente**: si cambia el puerto/baudios, recrea el
  controlador.

La lógica pura de tramas y parsers vive en :mod:`poorsdr.core.cat`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from poorsdr.core.cat.modes import DEFAULT_MODE
from poorsdr.core.cat.profiles import apply_profile
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus


class CatLike(Protocol):
    """Interfaz mínima del controlador CAT que usa el servicio."""

    def is_connected(self) -> bool: ...

    def set_frequency_hz(self, hz: int) -> None: ...

    def set_mode(self, mode: str) -> None: ...

    def set_ptt(self, active: bool) -> None: ...

    def get_state(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


def resolve_legacy_cat_config(cfg: AppConfig) -> dict[str, Any]:
    """``cfg.to_legacy()`` con el perfil de radio (``cfg.cat.rig_profile``) ya
    aplicado sobre ``CAT_BAUD``.

    Con el perfil ``"custom"`` (valor por defecto) no cambia nada: respeta lo
    que haya en Ajustes. Con un perfil con nombre (p. ej. ``"trusdx-115200"``),
    sustituye ese valor por la plantilla del perfil — ver
    :mod:`poorsdr.core.cat.profiles`. Pura: sin IO, testeable sin CAT físico.
    """
    legacy = cfg.to_legacy()
    legacy["CAT_BAUD"] = apply_profile(
        int(legacy.get("CAT_BAUD", 38400)),
        legacy.get("CAT_RIG_PROFILE"),
    )
    return legacy


def _default_controller_factory(cfg: AppConfig) -> CatLike | None:
    """Construye el ``CatController`` heredado a partir de la config tipada.

    Import perezoso: ``_vendor`` solo está en ``sys.path`` cuando arranca
    ``poorsdr.app`` (o los tests lo inyectan).
    """
    try:
        from cat import CatController
    except Exception:  # noqa: BLE001 - sin _legacy disponible: sin CAT físico
        return None
    return CatController.from_config(resolve_legacy_cat_config(cfg))


class RadioService(BaseService):
    name = "radio"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        controller_factory: Callable[[AppConfig], CatLike | None] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._make_controller = controller_factory or _default_controller_factory
        self._controller: CatLike | None = None
        self.frequency_hz: int = int(cfg.cat.start_freq_hz)
        self.mode: str = (cfg.ui.display_mode or DEFAULT_MODE).upper()
        self.ptt: bool = False
        self.step_hz: int = max(1, int(cfg.cat.step_hz))

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        self._set_status(ServiceState.STARTING)
        try:
            self._controller = self._make_controller(self._cfg)
        except Exception as exc:  # noqa: BLE001 - nunca abortar por CAT
            self.log.warning("no se pudo crear el controlador CAT: %s", exc)
            self._controller = None
        self._publish_status()
        if self.connected:
            self._read_and_publish_state()
        self._set_status(ServiceState.RUNNING, "" if self.connected else "sin CAT físico")

    def stop(self) -> None:
        ctrl = self._controller
        self._controller = None
        if ctrl is not None:
            try:
                ctrl.close()
            except Exception:  # noqa: BLE001
                self.log.debug("cierre de CAT con excepción", exc_info=True)
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        relevant = ("port", "baud", "rig_profile")
        changed = any(getattr(cfg.cat, k) != getattr(self._cfg.cat, k) for k in relevant)
        # El paso de sintonía no es un valor de hardware (no hay comando CAT
        # para "paso"), pero sí es estado compartido entre la consola y el
        # panel web (igual que frecuencia/modo/PTT). `_set_step` de la
        # consola ya pasa por este mismo `reconfigure` (vía
        # `ctx.reconfigure`), así que basta con detectar el cambio aquí y
        # publicarlo — sin tocar el controlador CAT.
        new_step = max(1, int(cfg.cat.step_hz))
        if new_step != self.step_hz:
            self.step_hz = new_step
            self.bus.publish("radio.step", hz=self.step_hz, source="app")
        self._cfg = cfg
        if changed:
            self.log.info("config CAT cambiada; recreando el controlador")
            self.stop()
            self.start()

    def set_step(self, hz: int, *, source: str = "app") -> None:
        """Paso de sintonía (Hz) — ver el comentario en ``reconfigure``."""
        self.step_hz = max(1, int(hz))
        self.bus.publish("radio.step", hz=self.step_hz, source=source)

    # ---- comandos ----------------------------------------------------- #
    @property
    def controller(self) -> CatLike | None:
        """Controlador CAT subyacente (lo consume el proxy rigctld para lecturas)."""
        return self._controller

    @property
    def connected(self) -> bool:
        return bool(self._controller is not None and self._controller.is_connected())

    def set_frequency(self, hz: int, *, source: str = "app") -> None:
        self.frequency_hz = max(0, int(hz))
        ctrl = self._live_controller()
        if ctrl is not None:
            self._safe(lambda: ctrl.set_frequency_hz(self.frequency_hz))
        self.bus.publish("radio.frequency", hz=self.frequency_hz, source=source)

    def set_mode(self, mode: str, *, source: str = "app") -> None:
        self.mode = (mode or DEFAULT_MODE).upper()
        ctrl = self._live_controller()
        if ctrl is not None:
            self._safe(lambda: ctrl.set_mode(self.mode))
        self.bus.publish("radio.mode", mode=self.mode, source=source)

    def set_ptt(self, active: bool, *, source: str = "app") -> None:
        self.ptt = bool(active)
        ctrl = self._live_controller()
        if ctrl is not None:
            self._safe(lambda: ctrl.set_ptt(self.ptt))
        self.bus.publish("radio.ptt", active=self.ptt, source=source)

    def _live_controller(self) -> CatLike | None:
        ctrl = self._controller
        if ctrl is not None and ctrl.is_connected():
            return ctrl
        return None

    def read_state(self) -> dict[str, Any]:
        """Relee frecuencia/modo de la radio si hay CAT; sincroniza el estado."""
        if self.connected:
            self._read_and_publish_state()
        return {"frequency_hz": self.frequency_hz, "mode": self.mode, "ptt": self.ptt}

    # ---- internos --------------------------------------------------- #
    def _read_and_publish_state(self) -> None:
        ctrl = self._live_controller()
        if ctrl is None:
            return
        try:
            state = ctrl.get_state()
        except Exception:  # noqa: BLE001
            self.log.debug("get_state CAT falló", exc_info=True)
            return
        freq = state.get("frequency_hz")
        mode = state.get("mode")
        if isinstance(freq, int) and freq > 0 and freq != self.frequency_hz:
            self.frequency_hz = freq
            self.bus.publish("radio.frequency", hz=freq, source="cat")
        if isinstance(mode, str) and mode and mode.upper() != self.mode:
            self.mode = mode.upper()
            self.bus.publish("radio.mode", mode=self.mode, source="cat")

    def _publish_status(self) -> None:
        self.bus.publish("radio.status", connected=self.connected)

    def _safe(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - un fallo de serie no debe propagarse
            self.log.warning("comando CAT falló", exc_info=True)


__all__ = ["CatLike", "RadioService", "resolve_legacy_cat_config"]
