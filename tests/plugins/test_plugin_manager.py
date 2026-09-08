"""poorsdr.plugins: descubrimiento, activación y registro."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.plugins import PluginContext, PluginManager  # noqa: E402
from poorsdr.services.base import BaseService, ServiceManager, ServiceState  # noqa: E402


class _FakeService(BaseService):
    name = "fake-plugin-svc"

    def start(self) -> None:
        self._set_status(ServiceState.RUNNING)

    def stop(self) -> None:
        self._set_status(ServiceState.STOPPED)


class _ButtonPlugin:
    id = "botones"
    name = "Plugin con botón"

    def __init__(self) -> None:
        self.clicks = 0

    def register(self, ctx: PluginContext) -> None:
        ctx.add_console_button("b1", "Etiqueta", self._go)
        ctx.add_service(_FakeService(ctx.bus))
        ctx.add_settings_tab("Mi pestaña", ("campo-falso",))

    def _go(self) -> None:
        self.clicks += 1


class _BrokenPlugin:
    id = "roto"
    name = "Plugin roto"

    def register(self, ctx: PluginContext) -> None:
        raise RuntimeError("boom")


class _EP:
    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        return self._obj


def _ctx(mgr: PluginManager) -> PluginContext:
    bus = EventBus()
    return PluginContext(bus=bus, config=AppConfig(), services=ServiceManager(bus))


class PluginManagerTests(unittest.TestCase):
    def test_discovers_and_registers_button_and_service(self):
        plugin = _ButtonPlugin()
        mgr = PluginManager()
        mgr.discover([_EP("botones", plugin)])
        ctx = _ctx(mgr)
        mgr.register_all(ctx)

        self.assertEqual([d.id for d in mgr.discovered], ["botones"])
        self.assertEqual(len(mgr.console_buttons), 1)
        btn = mgr.console_buttons[0]
        self.assertEqual((btn.plugin_id, btn.id, btn.label), ("botones", "b1", "Etiqueta"))
        btn.on_click()
        self.assertEqual(plugin.clicks, 1)
        self.assertIn("fake-plugin-svc", [s.name for s in ctx.services])
        self.assertEqual(len(mgr.settings_tabs), 1)
        tab = mgr.settings_tabs[0]
        self.assertEqual((tab.plugin_id, tab.name, tab.fields), ("botones", "Mi pestaña", ("campo-falso",)))

    def test_disabled_plugin_contributes_no_settings_tab(self):
        mgr = PluginManager({"botones": False})
        mgr.discover([_EP("botones", _ButtonPlugin())])
        mgr.register_all(_ctx(mgr))
        self.assertEqual(mgr.settings_tabs, [])

    def test_disabled_plugin_is_not_loaded(self):
        mgr = PluginManager({"botones": False})
        mgr.discover([_EP("botones", _ButtonPlugin())])
        mgr.register_all(_ctx(mgr))
        self.assertEqual(mgr.console_buttons, [])
        disc = mgr.discovered[0]
        self.assertFalse(disc.enabled)
        self.assertFalse(disc.loaded)

    def test_broken_plugin_does_not_break_the_rest(self):
        good = _ButtonPlugin()
        mgr = PluginManager()
        mgr.discover([_EP("roto", _BrokenPlugin()), _EP("botones", good)])
        mgr.register_all(_ctx(mgr))
        # el bueno sigue registrando su botón pese al fallo del otro
        self.assertEqual([b.plugin_id for b in mgr.console_buttons], ["botones"])

    def test_class_entry_point_is_instantiated(self):
        mgr = PluginManager()
        mgr.discover([_EP("botones", _ButtonPlugin)])  # la clase, no una instancia
        mgr.register_all(_ctx(mgr))
        self.assertEqual(len(mgr.console_buttons), 1)


if __name__ == "__main__":
    unittest.main()
