"""Enganche del plugin: añade el botón de consola que abre el panel RTTY.

A diferencia de NMN1M ("Log"), este plugin corre EN EL MISMO PROCESO que la
consola en vez de lanzar uno aparte: necesita llamar directamente a las
funciones de ``poorsdr._vendor.audio`` que leen/inyectan PCM del uSDX, algo
que no es alcanzable desde un proceso separado. Los plugins ya se cargan
dentro del proceso de la consola (``PluginManager.discover``/``register``),
así que ``ctx.services`` da acceso a los mismos servicios "audio"/"radio" que
usa el resto de la app, y ``tkinter._default_root`` a la ventana ya creada
para poder abrir el panel como ``Toplevel`` suyo.
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING, Any

from poorsdr_rtty_power.engine import RttyEngine

if TYPE_CHECKING:
    from poorsdr.plugins import PluginContext
    from poorsdr_rtty_power.panel import RttyPanel


class RttyPowerPlugin:
    id = "rtty_power"
    name = "RTTY Power"

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None
        self._panel: RttyPanel | None = None

    def register(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        ctx.add_console_button("rtty_power", "RTTY", self._toggle)

    def _toggle(self) -> None:
        if self._panel is not None:
            self._panel._close()  # noqa: SLF001 - API de cierre del propio panel
            return

        ctx = self._ctx
        if ctx is None:
            return
        audio: Any = ctx.services.get("audio")
        radio: Any = ctx.services.get("radio")
        module = getattr(audio, "module", None) if audio is not None else None
        if module is None:
            return

        root = tk._default_root  # type: ignore[attr-defined]
        if root is None:
            return

        from poorsdr_rtty_power.panel import RttyPanel

        # La frecuencia real de la rama RX digi (la de la tarjeta del uSDX),
        # no 48000 a ciegas: con otra, el reloj de bits RTTY se desfasa.
        get_rate = getattr(module, "get_rx_sample_rate", None)
        sample_rate = int(get_rate()) if get_rate is not None else 48000
        engine = RttyEngine(
            audio_module=module, radio=radio, audio_service=audio, sample_rate=sample_rate
        )

        def _on_close() -> None:
            self._panel = None

        # ctx.config es una foto fija de cuando se registró el plugin (al
        # arrancar la app) -- Ajustes no la refresca al guardar (ver
        # AppContext.reconfigure, que solo llama a services.reconfigure_all,
        # nunca vuelve a registrar plugins). Se relee del disco aquí, al
        # abrir el panel, para que un indicativo cambiado en Ajustes se note
        # sin tener que reiniciar toda la aplicación -- basta con cerrar y
        # volver a abrir el panel RTTY.
        from poorsdr.config import loader as _config_loader

        my_call = _config_loader.load().ui.operator_callsign.strip().upper()

        # El filtro del uSDX elegido en el panel ajusta también el ancho del
        # selector de la cascada de OWRX.
        owrx: Any = ctx.services.get("owrx-control")
        set_passband = getattr(owrx, "set_audio_passband", None)

        self._panel = RttyPanel(
            root, engine, my_call=my_call, on_close=_on_close, on_filter_change=set_passband
        )


PLUGIN = RttyPowerPlugin()

__all__ = ["RttyPowerPlugin", "PLUGIN"]
