"""N1mService: emulador TS-480 sincronizado por el bus."""

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
from poorsdr.services.n1m import N1mService  # noqa: E402


class FakeServer:
    instances: list[FakeServer] = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.states: list[dict] = []
        self.started = self.stopped = False
        FakeServer.instances.append(self)

    def set_log_path(self, path):  # noqa: D401
        self.log_path = path

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def set_state(self, *, freq=None, mode=None, ptt=None):
        self.states.append({"freq": freq, "mode": mode, "ptt": ptt})


def _cfg(**n1m):
    base = AppConfig()
    return replace(base, n1m=replace(base.n1m, **n1m)) if n1m else base


class N1mServiceTests(unittest.TestCase):
    def setUp(self):
        FakeServer.instances.clear()
        self.bus = EventBus()

    def _svc(self, cfg=None):
        return N1mService(self.bus, cfg or _cfg(enabled=True), server_factory=FakeServer)

    def test_disabled(self):
        svc = N1mService(self.bus, _cfg(enabled=False), server_factory=FakeServer)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertEqual(FakeServer.instances, [])

    def test_start_pushes_initial_state_and_follows_bus(self):
        svc = self._svc(_cfg(enabled=True, port=4599))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        srv = FakeServer.instances[0]
        self.assertTrue(srv.started)
        self.assertEqual(srv.port, 4599)
        self.assertEqual(len(srv.states), 1)  # estado inicial

        self.bus.publish("radio.frequency", hz=14074000, source="app")
        self.bus.publish("radio.mode", mode="usb", source="app")
        self.bus.publish("radio.ptt", active=True, source="app")
        self.assertEqual(srv.states[-1], {"freq": 14074000, "mode": "USB", "ptt": True})

    def test_error_when_bind_fails(self):
        class BadServer(FakeServer):
            def start(self):
                return False

        svc = N1mService(self.bus, _cfg(enabled=True), server_factory=BadServer)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.ERROR)

    def test_stop_unsubscribes(self):
        svc = self._svc()
        svc.start()
        srv = FakeServer.instances[0]
        svc.stop()
        self.assertTrue(srv.stopped)
        n = len(srv.states)
        self.bus.publish("radio.frequency", hz=1, source="app")
        self.assertEqual(len(srv.states), n)

    def test_reconfigure_restarts_on_port_change(self):
        svc = self._svc(_cfg(enabled=True, port=4599))
        svc.start()
        svc.reconfigure(_cfg(enabled=True, port=4600))
        self.assertTrue(FakeServer.instances[0].stopped)
        self.assertEqual(FakeServer.instances[1].port, 4600)


if __name__ == "__main__":
    unittest.main()
