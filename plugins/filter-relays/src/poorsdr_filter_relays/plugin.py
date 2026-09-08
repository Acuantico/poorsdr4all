"""Enganche del plugin: registra el servicio de relés y su pestaña de Ajustes.

El servicio en sí (``FilterRelayService``) vive todavía en ``poorsdr.services``;
este plugin solo decide si se instancia y si aparece la pestaña "Relés". Sin el
plugin instalado/activo, PoorSDR no controla ningún relé y esa pestaña no sale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from poorsdr.services.filter_relays import FilterRelayService
from poorsdr.ui.settings.form import Field

if TYPE_CHECKING:
    from poorsdr.plugins import PluginContext

_SETTINGS_FIELDS = (
    Field("relays", "enabled", "label_relays_enabled", "bool", help_key="help_relays_enabled"),
    Field("relays", "url", "label_relays_url", help_key="help_relays_url"),
    Field("relays", "api_key", "label_relays_api_key", "password",
          help_key="help_relays_api_key"),
    Field("relays", "timeout_ms", "label_relays_timeout_ms", "int",
          help_key="help_relays_timeout_ms"),
    Field("relays", "band_groups", "label_relays_band_groups", "json",
          help_key="help_relays_band_groups"),
)


class FilterRelaysPlugin:
    id = "filter_relays"
    name = "Relés WiFi por banda"

    def register(self, ctx: PluginContext) -> None:
        ctx.add_service(FilterRelayService(ctx.bus, ctx.config))
        ctx.add_settings_tab("Relés", _SETTINGS_FIELDS)


PLUGIN = FilterRelaysPlugin()
