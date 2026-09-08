"""Sistema de plugins de PoorSDR4All.

Un plugin es un paquete Python instalable con pip que declara un *entry point*
del grupo ``poorsdr.plugins`` apuntando a un objeto con esta forma::

    class MiPlugin:
        id = "mi_plugin"
        name = "Mi plugin"
        def register(self, ctx: PluginContext) -> None: ...
        def shutdown(self) -> None: ...        # opcional

``register`` recibe un :class:`PluginContext` con el que puede:

- suscribirse / publicar en el ``EventBus`` (``ctx.bus``),
- registrar un servicio en el ``ServiceManager`` (``ctx.add_service``),
- añadir un botón a la consola (``ctx.add_console_button``),
- añadir una pestaña a Ajustes (``ctx.add_settings_tab``) — solo aparece si el
  plugin está instalado y activo.

PoorSDR arranca perfectamente sin ningún plugin instalado. La activación por
usuario se guarda en ``config.json`` bajo la clave ``PLUGINS`` (``{id: bool}``);
lo no listado se considera activo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from poorsdr.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus
    from poorsdr.services.base import BaseService, ServiceManager

_log = get_logger("plugins")

ENTRY_POINT_GROUP = "poorsdr.plugins"


@runtime_checkable
class Plugin(Protocol):
    id: str
    name: str

    def register(self, ctx: PluginContext) -> None: ...


@dataclass(frozen=True)
class ConsoleButton:
    """Botón que un plugin añade a la consola."""

    plugin_id: str
    id: str
    label: str
    on_click: Callable[[], None]


@dataclass(frozen=True)
class SettingsTab:
    """Pestaña de Ajustes que aporta un plugin (solo visible si está activo)."""

    plugin_id: str
    name: str
    fields: tuple[Any, ...]  # poorsdr.ui.settings.form.Field, sin acoplar el tipo aquí


@dataclass
class PluginContext:
    """Lo que un plugin recibe en ``register``."""

    bus: EventBus
    config: AppConfig
    services: ServiceManager
    _buttons: list[ConsoleButton] = field(default_factory=list)
    _tabs: list[SettingsTab] = field(default_factory=list)
    _current: str = ""  # id del plugin que se está registrando

    def add_service(self, service: BaseService) -> None:
        self.services.register(service)

    def add_console_button(self, button_id: str, label: str, on_click: Callable[[], None]) -> None:
        self._buttons.append(ConsoleButton(self._current, button_id, label, on_click))

    def add_settings_tab(self, name: str, fields: Sequence[Any]) -> None:
        self._tabs.append(SettingsTab(self._current, name, tuple(fields)))


@dataclass(frozen=True)
class DiscoveredPlugin:
    id: str
    name: str
    enabled: bool
    loaded: bool
    error: str = ""


class PluginManager:
    """Descubre (entry points), carga y registra los plugins activos."""

    def __init__(self, enabled_map: Mapping[str, bool] | None = None) -> None:
        self._enabled = {str(k): bool(v) for k, v in (enabled_map or {}).items()}
        self._plugins: list[Plugin] = []
        self._discovered: list[DiscoveredPlugin] = []
        self._ctx: PluginContext | None = None

    # ---- descubrimiento ------------------------------------------------- #
    def _is_enabled(self, plugin_id: str) -> bool:
        return self._enabled.get(plugin_id, True)

    def discover(self, entry_points: Any | None = None) -> None:
        self._plugins = []
        self._discovered = []
        try:
            eps = entry_points if entry_points is not None else metadata.entry_points(
                group=ENTRY_POINT_GROUP
            )
        except Exception:  # noqa: BLE001 - importlib.metadata quisquilloso
            _log.debug("no se pudieron enumerar los entry points de plugins", exc_info=True)
            return
        for ep in eps:
            try:
                obj = ep.load()
                plugin = obj() if isinstance(obj, type) else obj
                pid = str(getattr(plugin, "id", ep.name) or ep.name)
                pname = str(getattr(plugin, "name", pid) or pid)
            except Exception as exc:  # noqa: BLE001
                _log.warning("plugin '%s' no se pudo cargar: %s", ep.name, exc)
                self._discovered.append(
                    DiscoveredPlugin(ep.name, ep.name, self._is_enabled(ep.name), False, str(exc))
                )
                continue
            enabled = self._is_enabled(pid)
            self._discovered.append(DiscoveredPlugin(pid, pname, enabled, enabled))
            if enabled:
                self._plugins.append(plugin)

    # ---- ciclo de vida ----------------------------------------------- #
    def register_all(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        for plugin in self._plugins:
            ctx._current = str(getattr(plugin, "id", ""))
            try:
                plugin.register(ctx)
            except Exception:  # noqa: BLE001
                _log.exception("plugin '%s' falló en register()", ctx._current)
        ctx._current = ""

    def shutdown_all(self) -> None:
        for plugin in self._plugins:
            fn = getattr(plugin, "shutdown", None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    _log.debug("plugin shutdown() con excepción", exc_info=True)

    # ---- consultas ------------------------------------------------- #
    @property
    def console_buttons(self) -> list[ConsoleButton]:
        return list(self._ctx._buttons) if self._ctx is not None else []

    @property
    def settings_tabs(self) -> list[SettingsTab]:
        return list(self._ctx._tabs) if self._ctx is not None else []

    @property
    def discovered(self) -> list[DiscoveredPlugin]:
        return list(self._discovered)


__all__ = [
    "ENTRY_POINT_GROUP",
    "ConsoleButton",
    "DiscoveredPlugin",
    "Plugin",
    "PluginContext",
    "PluginManager",
    "SettingsTab",
]
