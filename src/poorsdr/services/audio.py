"""Servicio de audio.

Fachada estrecha sobre el módulo procedimental ``_legacy/audio.py`` (4559 líneas,
187 funciones, singleton vía ``app_globals.audio``). No reimplementa el DSP:
le da un **dueño del ciclo de vida** y un hueco en el ``ServiceManager``, y expone
el módulo para que la UI llame a sus funciones operativas (igual que
``RadioService.controller``).

La descomposición profunda de ``audio.py`` en ``poorsdr.core.audio`` (los
``audio_*_domain`` ya son el punto de partida) es un trabajo posterior.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus

#: Funciones que el servicio invoca sobre el módulo si existen (tolerante).
_LIFECYCLE_STOP = ("detener_rx_tx", "desactivar_audio")


def _default_module_factory() -> Any:
    """Importa el módulo ``audio`` heredado y lo publica en ``app_globals``."""
    import audio  # requiere numpy + pyaudio

    try:
        from gui_app import app_globals

        app_globals.audio = audio
    except Exception:  # noqa: BLE001 - app_globals es opcional fuera del legacy
        pass
    return audio


class AudioService(BaseService):
    name = "audio"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        module_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._make_module = module_factory or _default_module_factory
        self._module: Any | None = None
        # Último volumen pedido desde el dial (0-100). Se reaplica a la ruta
        # correcta cada vez que cambia la fuente RX; si no, la ruta recién
        # activada se queda a 0 hasta que alguien toca el dial.
        self._rx_volume = 25.0
        self._tx_volume = 100.0
        # Ganancia del audio remoto por WebRTC (0.0-1.0 lineal), aparte de
        # rx_volume/tx_volume: esos son el dial de la CONSOLA (ruta de audio
        # local del PC); el panel web tiene su propio control porque, con el
        # remoto activo, la ruta local queda anulada (ver _remote_mode en
        # _vendor/audio.py) y mover el dial de la consola no tendría sentido
        # ni efecto en lo que oye el navegador.
        self._web_rx_gain = 1.0
        self._web_tx_gain = 1.0

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        self._set_status(ServiceState.STARTING)
        try:
            self._module = self._make_module()
        except Exception as exc:  # noqa: BLE001 - sin audio: la app sigue
            self.log.warning("no se pudo cargar el subsistema de audio: %s", exc)
            self._module = None
            self._set_status(ServiceState.ERROR, str(exc))
            self.bus.publish("audio.status", ready=False)
            return
        # Arranca el pipeline de RX (captura + reproducción). En modo SDR el
        # audio llega por OwrxControlService → push_owrx_audio_chunk.
        self.call("habilitar_audio_en_modo", "rx")
        self._apply_rx_source()
        self._apply_anr()
        self._set_status(ServiceState.RUNNING)
        self.bus.publish("audio.status", ready=True)

    def stop(self) -> None:
        mod = self._module
        self._module = None
        if mod is not None:
            for fn_name in _LIFECYCLE_STOP:
                fn = getattr(mod, fn_name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:  # noqa: BLE001
                        self.log.debug("%s() falló al parar audio", fn_name, exc_info=True)
        self._set_status(ServiceState.STOPPED)
        self.bus.publish("audio.status", ready=False)

    def reconfigure(self, cfg: AppConfig) -> None:
        old = self._cfg
        self._cfg = cfg
        if cfg.audio.rx_source != old.audio.rx_source:
            self._apply_rx_source()
        if (cfg.dsp.anr_enabled, cfg.dsp.anr_intensity) != (old.dsp.anr_enabled, old.dsp.anr_intensity):
            self._apply_anr()
            if cfg.dsp.anr_enabled and not old.dsp.anr_enabled:
                # Desactivar y reactivar el ANR es la forma de "resetearlo" si
                # su estado interno queda degradado tras una señal muy fuerte
                # (ver reset_anr): no hace falta un control aparte para eso.
                self.reset_anr()
        if _device_selection(cfg.audio) != _device_selection(old.audio):
            self.log.info("cambio de dispositivos de audio: requiere reiniciar el servicio")
            self.bus.publish("audio.status", ready=True, needs_restart=True)

    # ---- API ------------------------------------------------------- #
    @property
    def module(self) -> Any | None:
        """Módulo ``audio`` heredado (para que la UI llame a sus funciones)."""
        return self._module

    @property
    def anr_enabled(self) -> bool:
        return bool(self._cfg.dsp.anr_enabled)

    @property
    def anr_intensity(self) -> int:
        return int(self._cfg.dsp.anr_intensity)

    def call(self, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        """Invoca ``fn_name`` en el módulo si existe; si no, devuelve ``None``."""
        mod = self._module
        fn = getattr(mod, fn_name, None) if mod is not None else None
        if not callable(fn):
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            self.log.warning("audio.%s(...) falló", fn_name, exc_info=True)
            return None

    def push_owrx_chunk(self, data: bytes, sample_rate: int, channels: int) -> None:
        """Inyecta un bloque de audio de OWRX en el pipeline de RX (modo SDR)."""
        self.call("push_owrx_audio_chunk", data, sample_rate, channels)

    def set_rx_volume(self, value: float, *, source: str = "app") -> None:
        """Volumen de recepción (0-100), aplicado a la ruta correcta según la fuente."""
        self._rx_volume = max(0.0, float(value))
        self._apply_rx_volume()
        self._publish_volume(source=source)

    def set_tx_volume(self, value: float, *, source: str = "app") -> None:
        """Volumen de transmisión (0-100, ganancia del micrófono)."""
        self._tx_volume = max(0.0, float(value))
        self.call("set_volumen_tx", self._tx_volume)
        self._publish_volume(source=source)

    def _publish_volume(self, *, source: str = "app") -> None:
        self.bus.publish("audio.volume", rx=self._rx_volume, tx=self._tx_volume, source=source)

    @property
    def rx_volume(self) -> float:
        return self._rx_volume

    @property
    def tx_volume(self) -> float:
        return self._tx_volume

    def set_web_rx_gain(self, value: float) -> None:
        """Ganancia (0.0-1.0) del audio RX que se manda al navegador por
        WebRTC. No toca ``rx_volume`` (el dial de la consola) ni publica
        ``audio.volume``: son rutas de audio independientes."""
        self._web_rx_gain = max(0.0, min(1.0, float(value)))
        self.call("set_web_rx_gain", self._web_rx_gain)

    def set_web_tx_gain(self, value: float) -> None:
        """Igual que :meth:`set_web_rx_gain`, para el micrófono del navegador."""
        self._web_tx_gain = max(0.0, min(1.0, float(value)))
        self.call("set_web_tx_gain", self._web_tx_gain)

    @property
    def web_rx_gain(self) -> float:
        return self._web_rx_gain

    @property
    def web_tx_gain(self) -> float:
        return self._web_tx_gain

    def _apply_rx_volume(self) -> None:
        vol = self._rx_volume
        if self._sdr_active():
            # El audio SDR va por su propia ruta procesada (``_sdr_volume``); la
            # ruta de radio se silencia. Se aplica un ligero realce (como el
            # original) para que el rango del dial resulte cómodo.
            self.call("set_volumen_rx", 0.0)
            self.call("set_volumen_sdr", min(100.0, vol * 2.2))
        else:
            self.call("set_volumen_sdr", 0.0)
            self.call("set_volumen_rx", vol)

    def start_tx(self) -> None:
        """Pasa el pipeline a TX (captura de micro → radio)."""
        if self._sdr_active():
            self.call("set_sdr_paused", True)  # silencia el SDR mientras se transmite
        self.call("habilitar_audio_en_modo", "tx")

    def stop_tx(self) -> None:
        """Vuelve a RX tras transmitir."""
        self.call("stop_tx_test_tone")
        self.call("habilitar_audio_en_modo", "rx")
        if self._sdr_active():
            self.call("set_sdr_paused", False)

    def reset_anr(self) -> None:
        """Recrea el estado interno del ANR (Speex) sin cortar el audio.

        Con una señal de entrada muy fuerte y sostenida, el supresor de
        ruido puede quedar en un estado degradado (audio distorsionado y muy
        flojo) que no se recupera solo — no es un fallo del equipo de radio.
        ``dsp_pipeline.configure_ctx`` siempre reconstruye el motor Speex
        desde cero; volver a llamarlo con los mismos parámetros que ya tiene
        registrados cada contexto ("gui"/"web"/"sdr_gui"/"sdr_web") es la
        única forma de limpiar ese estado sin reabrir los flujos de audio.
        No se puede añadir esto en ``_vendor`` (ver ``_vendor/README.md``:
        "no añadir features aquí"), así que se hace leyendo el estado ya
        expuesto por el módulo en vez de tocarlo.

        No hace falta un control aparte para esto: ``reconfigure()`` ya lo
        llama solo al reactivar el ANR (desactivar + activar = reset).
        """
        mod = self._module
        if mod is None:
            return
        dsp_filters = getattr(mod, "dsp_filters", None)
        managers = getattr(dsp_filters, "_MANAGERS", None)
        configure_ctx = getattr(dsp_filters, "configure_ctx", None)
        if not isinstance(managers, dict) or not callable(configure_ctx):
            self.log.debug("reset_anr: dsp_pipeline no disponible o cambió su forma interna")
            return
        for ctx, manager in list(managers.items()):
            try:
                rate = int(manager._sample_rate)
                channels = int(manager._channels)
                frame_size = int(manager._frame_size)
            except (TypeError, ValueError, AttributeError):
                continue
            try:
                configure_ctx(ctx, rate, channels, frame_size)
            except Exception:  # noqa: BLE001
                self.log.debug("no se pudo reiniciar el ANR del contexto %s", ctx, exc_info=True)

    def play_file(self, path: str, stop_checker: Callable[[], bool] | None = None) -> bool:
        """Reproduce ``path`` hacia el micro de la radio (bloqueante).

        Usa ``reproducir_audio_en_radio`` del módulo heredado: abre su propio
        stream PyAudio hacia ``Microfono_Radio_Index`` (independiente del
        pipeline RX/TX en vivo), así que no hace falta pasar por
        ``start_tx``/``stop_tx``. Lo inyecta ``runtime.build_context`` como
        ``play_audio`` de :class:`~poorsdr.services.autocall.AutocallService`.

        ``stop_checker`` (si se pasa) se consulta entre bloques de audio: al
        volverse ``True`` corta el streaming en el acto en vez de esperar a
        que termine el archivo — es lo que permite que "pulsar el botón"
        detenga la reproducción y el TX al momento, no al acabar la macro.
        """
        return bool(
            self.call("reproducir_audio_en_radio", path, wait=True, stop_checker=stop_checker)
        )

    def start_tune_tone(self) -> None:
        self.start_tx()
        self.call("start_tx_test_tone")

    def stop_tune_tone(self) -> None:
        self.call("stop_tx_test_tone")
        self.call("habilitar_audio_en_modo", "rx")
        if self._sdr_active():
            self.call("set_sdr_paused", False)

    # ---- API (controles externos: consola, servidor web) ------------ #
    def set_anr(self, enabled: bool, *, source: str = "app") -> None:
        """Activa/desactiva el ANR sin pasar por ``reconfigure``/persistir.

        Igual que ``RadioService.set_frequency``/``set_mode``/``set_ptt``:
        actualiza el estado en memoria del propio servicio y avisa por el bus
        (``audio.anr``) para que la consola refleje el cambio aunque lo haya
        disparado otro origen (p. ej. el servidor web).
        """
        self._cfg = replace(self._cfg, dsp=replace(self._cfg.dsp, anr_enabled=bool(enabled)))
        self._apply_anr(source=source)

    def set_anr_intensity(self, intensity: int, *, source: str = "app") -> None:
        self._cfg = replace(self._cfg, dsp=replace(self._cfg.dsp, anr_intensity=int(intensity)))
        self._apply_anr(source=source)

    # ---- internos --------------------------------------------------- #
    def _apply_anr(self, *, source: str = "app") -> None:
        self.call("establecer_anr", bool(self._cfg.dsp.anr_enabled))
        self.call("establecer_intensidad_anr", int(self._cfg.dsp.anr_intensity))
        self.bus.publish(
            "audio.anr",
            enabled=bool(self._cfg.dsp.anr_enabled),
            intensity=int(self._cfg.dsp.anr_intensity),
            source=source,
        )

    def _apply_rx_source(self) -> None:
        src = self._cfg.audio.rx_source
        self.call("set_rx_source", src)
        if src == "sdr":
            # El visor nativo manda el audio ya decodificado (push_owrx_chunk):
            # hay que arrancar la tubería SDR interna (hilo consumidor + sink
            # oculto) o los chunks se encolan y no suenan.
            self.call("enable_owrx_sdr_anr")
            self.call("route_owrx_to_configured_pc_sink")
            self.call("set_sdr_output_active", True)
            self.call("set_sdr_paused", False)
        else:
            self.call("set_sdr_output_active", False)
            self.call("set_sdr_paused", True)
            self.call("disable_owrx_sdr_anr")
        # Sin esto, la ruta que se acaba de activar se queda muda: su volumen
        # se puso a 0 la última vez que estuvo inactiva.
        self._apply_rx_volume()

    def _sdr_active(self) -> bool:
        return self._cfg.audio.rx_source == "sdr"


def _device_selection(audio_cfg: Any) -> tuple:
    return tuple(
        (getattr(dev, "index", -1), getattr(dev, "label", ""))
        for dev in (
            audio_cfg.speaker_pc,
            audio_cfg.speaker_radio,
            audio_cfg.mic_pc,
            audio_cfg.mic_radio,
        )
    )


__all__ = ["AudioService"]
