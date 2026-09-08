"""OwrxClientService: envuelve OwrxClient y lo alimenta desde el bus."""

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
from poorsdr.services.owrx_client import OwrxClientService  # noqa: E402


class FakeClient:
    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self.started = False
        self.stopped = False
        self.calls: list[tuple] = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send_frequency(self, hz):
        self.calls.append(("freq", hz))

    def send_mode(self, mode):
        self.calls.append(("mode", mode))

    def send_profile(self, profile):
        self.calls.append(("profile", profile))


def _cfg(**owrx_over):
    base = AppConfig()
    owrx = replace(base.owrx, **owrx_over) if owrx_over else base.owrx
    return replace(base, owrx=owrx)


class OwrxClientServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def test_disabled_does_not_build_client(self):
        made = []
        svc = OwrxClientService(
            self.bus, _cfg(enabled=False), client_factory=lambda c: made.append(1) or FakeClient()
        )
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertEqual(made, [])

    def test_no_host_does_not_build_client(self):
        svc = OwrxClientService(self.bus, _cfg(enabled=True, host=""), client_factory=lambda c: FakeClient())
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)

    def test_start_connects_and_subscribes(self):
        fake = FakeClient()
        svc = OwrxClientService(self.bus, _cfg(enabled=True), client_factory=lambda c: fake)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertTrue(fake.started)

        self.bus.publish("radio.frequency", hz=7074000, source="app")
        self.bus.publish("radio.mode", mode="USB", source="app")
        self.bus.publish("owrx.band", band="40m", profile="RTL 40m")
        self.assertEqual(
            fake.calls, [("freq", 7074000), ("mode", "USB"), ("profile", "RTL 40m")]
        )

    def test_forward_skipped_when_client_disabled(self):
        fake = FakeClient(enabled=False)
        svc = OwrxClientService(self.bus, _cfg(enabled=True), client_factory=lambda c: fake)
        svc.start()
        self.bus.publish("radio.frequency", hz=1, source="app")
        self.assertEqual(fake.calls, [])

    def test_stop_unsubscribes_and_stops_client(self):
        fake = FakeClient()
        svc = OwrxClientService(self.bus, _cfg(enabled=True), client_factory=lambda c: fake)
        svc.start()
        svc.stop()
        self.assertTrue(fake.stopped)
        self.bus.publish("radio.frequency", hz=1, source="app")
        self.assertEqual(fake.calls, [])  # ya no suscrito

    def test_reconfigure_reconnects_on_key_change(self):
        made: list[str] = []

        def factory(c):
            made.append(c.owrx.key)
            return FakeClient()

        svc = OwrxClientService(self.bus, _cfg(enabled=True, key="A"), client_factory=factory)
        svc.start()
        svc.reconfigure(_cfg(enabled=True, key="B"))
        self.assertEqual(made, ["A", "B"])

    def test_reconfigure_noop_when_unchanged(self):
        made = []
        svc = OwrxClientService(
            self.bus, _cfg(enabled=True), client_factory=lambda c: made.append(1) or FakeClient()
        )
        svc.start()
        svc.reconfigure(_cfg(enabled=True))
        self.assertEqual(len(made), 1)

    def test_missing_legacy_client_is_running_but_not_ready(self):
        svc = OwrxClientService(self.bus, _cfg(enabled=True), client_factory=lambda c: None)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        # no revienta al publicar
        self.bus.publish("radio.frequency", hz=1, source="app")


if __name__ == "__main__":
    unittest.main()
