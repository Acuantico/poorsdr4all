"""FilterRelayService: manda la banda al controlador al cambiar la frecuencia."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402
from poorsdr.services.filter_relays import FilterRelayService  # noqa: E402


class FakeController:
    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self.calls: list[str] = []

    def apply_band(self, band, *, force=False, source=""):
        self.calls.append(band)
        return True


def _cfg(**relays):
    base = AppConfig()
    return replace(base, relays=replace(base.relays, **relays)) if relays else base


class FilterRelayServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.ctrl = FakeController()

    def _svc(self, cfg=None, ctrl=None):
        c = ctrl or self.ctrl
        return FilterRelayService(
            self.bus, cfg or _cfg(enabled=True, url="http://1.2.3.4"),
            controller_factory=lambda _cfg, _log: c,
        )

    def test_disabled(self):
        svc = FilterRelayService(
            self.bus, _cfg(enabled=False), controller_factory=lambda *_: self.ctrl
        )
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)

    def test_applies_band_on_frequency_change(self):
        svc = self._svc()
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.bus.publish("radio.frequency", hz=7_074_000, source="app")
        self.bus.publish("radio.frequency", hz=7_100_000, source="app")  # misma banda 40m
        self.bus.publish("radio.frequency", hz=27_555_000, source="app")  # 11m
        self.assertEqual(self.ctrl.calls, ["40m", "11m"])  # sin repetir 40m

    def test_no_apply_when_controller_disabled(self):
        svc = self._svc(ctrl=FakeController(enabled=False))
        svc.start()
        self.bus.publish("radio.frequency", hz=7_074_000, source="app")
        # el controlador está deshabilitado → no se llama
        self.assertEqual(svc.status.state, ServiceState.RUNNING)

    def test_stop_unsubscribes(self):
        svc = self._svc()
        svc.start()
        svc.stop()
        self.bus.publish("radio.frequency", hz=7_074_000, source="app")
        self.assertEqual(self.ctrl.calls, [])

    def test_reconfigure_recreates_on_url_change(self):
        made: list[str] = []

        def factory(cfg, _log):
            made.append(cfg.relays.url)
            return FakeController()

        svc = FilterRelayService(
            self.bus, _cfg(enabled=True, url="http://a"), controller_factory=factory
        )
        svc.start()
        svc.reconfigure(_cfg(enabled=True, url="http://b"))
        self.assertEqual(made, ["http://a", "http://b"])


if __name__ == "__main__":
    unittest.main()
