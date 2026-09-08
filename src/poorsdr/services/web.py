"""Servicio del servidor web remoto (FastAPI / WebRTC).

Envuelve ``_legacy/webserver.py:WebServerController`` y cablea sus callbacks a
los servicios del refactor por el bus. Portado de
``WebControlMixin._init_web_server`` / ``_stop_web_server`` / ``toggle_web_server``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from poorsdr.core.bands import band_center_hz, band_names, infer_band
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus
    from poorsdr.services.audio import AudioService
    from poorsdr.services.radio import RadioService


def _default_controller_factory(callbacks: Any) -> Any:
    from webserver import WebServerController

    return WebServerController(callbacks)


def _make_callbacks(builder: dict[str, Callable[..., Any]]) -> Any:
    from webserver import WebCallbacks

    return WebCallbacks(**builder)


class WebServerService(BaseService):
    name = "web"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        radio: RadioService,
        audio: AudioService,
        *,
        controller_factory: Callable[[Any], Any] | None = None,
        callbacks_factory: Callable[[dict[str, Callable[..., Any]]], Any] | None = None,
        settle_delay_s: float = 0.18,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._radio = radio
        self._audio = audio
        self._make_controller = controller_factory or _default_controller_factory
        self._make_callbacks = callbacks_factory or _make_callbacks
        self._settle_delay_s = settle_delay_s
        self._controller: Any | None = None

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        # El botón WEB de la consola se pone en "ON" de forma optimista al
        # pulsarlo (ui.app._toggle_web) y confía en que este servicio
        # publique "web.status" para confirmar/corregir el estado real —
        # por eso se publica `running=False` en cada camino de fallo, no
        # solo al terminar con éxito: si no, el botón podría quedarse
        # mostrando "ON" aunque el servidor no llegara a escuchar.
        if not self._cfg.web.enabled:
            self.bus.publish("web.status", running=False)
            self._set_status(ServiceState.STOPPED, "deshabilitado")
            return
        if not (
            self._cfg.web.password_salt
            and self._cfg.web.password_hash
            and len(self._cfg.web.secret) >= 32
        ):
            self.bus.publish("web.status", running=False)
            self._set_status(
                ServiceState.ERROR,
                "configura una contraseña web antes de habilitar el servidor",
            )
            return
        self._set_status(ServiceState.STARTING)
        try:
            callbacks = self._make_callbacks(self._callback_map())
            self._controller = self._make_controller(callbacks)
            self._controller.start(self._cfg.to_legacy())
        except Exception as exc:  # noqa: BLE001 - dependencias web opcionales
            self.log.exception("no se pudo arrancar el servidor web")
            self._controller = None
            self.bus.publish("web.status", running=False)
            self._set_status(ServiceState.ERROR, str(exc))
            return
        if self._settle_delay_s:
            time.sleep(self._settle_delay_s)  # capturar fallos inmediatos (puerto en uso, etc.)
        if not self._running():
            self._controller = None
            self.bus.publish("web.status", running=False)
            self._set_status(ServiceState.ERROR, "el servidor no quedó a la escucha")
            return
        self.bus.publish("web.status", running=True)
        self._set_status(ServiceState.RUNNING, f"{self._cfg.web.host}:{self._cfg.web.port}")

    def stop(self) -> None:
        controller = self._controller
        self._controller = None
        if controller is not None:
            try:
                controller.stop()
            except Exception:  # noqa: BLE001
                self.log.debug("parada del servidor web con excepción", exc_info=True)
        self.bus.publish("web.status", running=False)
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        old = self._cfg.web
        self._cfg = cfg
        new = cfg.web
        keys = ("enabled", "host", "port", "allow_wan", "auto_https", "user")
        if any(getattr(new, k) != getattr(old, k) for k in keys):
            self.log.info("config del servidor web cambiada; reiniciando")
            self.stop()
            self.start()

    @property
    def running(self) -> bool:
        return self._running()

    def _running(self) -> bool:
        server = self._controller
        thread = getattr(server, "_thread", None) if server is not None else None
        return bool(thread is not None and thread.is_alive())

    # ---- callbacks (web → servicios) ------------------------------- #
    def _callback_map(self) -> dict[str, Callable[..., Any]]:
        return {
            "get_state": self._get_state,
            "set_frequency": lambda hz: self._radio.set_frequency(int(hz), source="web"),
            "set_mode": lambda m: self._radio.set_mode(str(m), source="web"),
            "set_band": self._set_band,
            "set_step": self._set_step,
            "set_ptt": self._set_ptt,
            "set_volumes": self._set_volumes,
            "toggle_audio": lambda on: self._audio.call(
                "habilitar_audio_para_radio", bool(on)
            ),
            "set_anr": lambda on: self._audio.set_anr(bool(on), source="web"),
            "set_anr_intensity": lambda n: self._audio.set_anr_intensity(int(n), source="web"),
        }

    def _get_state(self) -> dict[str, Any]:
        band = infer_band(self._radio.frequency_hz)
        return {
            "frequency_hz": int(self._radio.frequency_hz),
            "mode": str(self._radio.mode),
            "ptt": bool(self._radio.ptt),
            "band": band,
            "bands": band_names(),
            "radio_on": bool(self._radio.connected),
            "rx_volume": self._audio.web_rx_gain,
            "tx_volume": self._audio.web_tx_gain,
            "anr_enabled": self._audio.anr_enabled,
            "anr_intensity": self._audio.anr_intensity,
            "anr_available": True,
            "step_khz": self._radio.step_hz / 1000.0,
        }

    def _set_band(self, band: str) -> None:
        center = band_center_hz(str(band))
        if center is not None:
            self._radio.set_frequency(center, source="web")

    def _set_step(self, khz: Any) -> None:
        # Comparte el mismo estado que la consola (`RadioService.step_hz`,
        # igual que frecuencia/modo/PTT) en vez de guardar su propia copia:
        # así, cambiar el paso desde cualquiera de las dos interfaces se
        # refleja en la otra. `RadioService.set_step` publica `radio.step`,
        # que la consola escucha para reflejar el cambio.
        try:
            value = float(khz)
        except (TypeError, ValueError):
            return
        if value > 0:
            self._radio.set_step(max(1, int(round(value * 1000))), source="web")

    def _set_ptt(self, active: Any) -> None:
        on = bool(active)
        (self._audio.start_tx if on else self._audio.stop_tx)()
        self._radio.set_ptt(on, source="web")

    def _set_volumes(self, rx: Any, tx: Any) -> None:
        # El panel web manda 0.0-1.0 (min/max del <input type="range">), la
        # misma escala que WEB_RX_GAIN/WEB_TX_GAIN: la ganancia real del
        # audio que se manda/recibe por WebRTC. No es lo mismo que
        # rx_volume/tx_volume (el dial de la consola, ruta de audio local
        # del PC), que no tiene ningún efecto sobre lo que oye el navegador.
        self._audio.set_web_rx_gain(float(rx))
        self._audio.set_web_tx_gain(float(tx))


__all__ = ["WebServerService"]
