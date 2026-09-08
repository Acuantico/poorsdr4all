"""RigctldService: arranque incondicional (si habilitado), enrutado y reflejo."""

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
from poorsdr.services.radio import RadioService  # noqa: E402
from poorsdr.services.rigctld import RigctldService  # noqa: E402


class FakeState:
    def __init__(self):
        self.freq = None
        self.mode = None
        self.ptt = None

    def update_freq(self, hz):
        self.freq = hz

    def update_mode(self, mode):
        self.mode = mode

    def update_ptt(self, ptt):
        self.ptt = ptt


class FakeServer:
    instances: list[FakeServer] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.state = FakeState()
        self.cat = kwargs.get("cat")
        self.started = False
        self.stopped = False
        self.log_path = None
        FakeServer.instances.append(self)

    def set_log_path(self, path):
        self.log_path = path

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _cfg(**rig_over):
    base = AppConfig()
    rig = replace(base.rigctld, **rig_over) if rig_over else base.rigctld
    return replace(base, rigctld=rig)


class RigctldServiceTests(unittest.TestCase):
    def setUp(self):
        FakeServer.instances.clear()
        self.bus = EventBus()
        self.radio = RadioService(self.bus, AppConfig(), controller_factory=lambda c: None)
        self.radio.start()

    def _make(self, cfg=None):
        return RigctldService(
            self.bus, cfg or _cfg(enabled=True), self.radio, server_factory=FakeServer
        )

    def test_disabled_does_not_start_server(self):
        svc = self._make(_cfg(enabled=False))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertEqual(FakeServer.instances, [])

    def test_starts_even_without_physical_cat(self):
        self.assertFalse(self.radio.connected)
        svc = self._make()
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertTrue(FakeServer.instances[0].started)
        self.assertIsNone(FakeServer.instances[0].kwargs["cat"])

    def test_initial_state_pushed_from_radio(self):
        self.radio.frequency_hz = 14074000
        self.radio.mode = "USB"
        svc = self._make()
        svc.start()
        st = FakeServer.instances[0].state
        self.assertEqual(st.freq, 14074000)
        self.assertEqual(st.mode, "USB")
        self.assertEqual(st.ptt, 0)

    def test_client_callbacks_route_to_radio(self):
        svc = self._make()
        svc.start()
        kw = FakeServer.instances[0].kwargs
        kw["set_frequency_cb"](18100000)
        kw["set_mode_cb"]("cw")
        kw["set_ptt_cb"](1)
        self.assertEqual(self.radio.frequency_hz, 18100000)
        self.assertEqual(self.radio.mode, "CW")
        self.assertTrue(self.radio.ptt)

    def test_radio_events_reflect_into_proxy_state(self):
        svc = self._make()
        svc.start()
        st = FakeServer.instances[0].state
        self.bus.publish("radio.frequency", hz=21000000, source="app")
        self.bus.publish("radio.mode", mode="lsb", source="app")
        self.bus.publish("radio.ptt", active=True, source="app")
        self.assertEqual(st.freq, 21000000)
        self.assertEqual(st.mode, "LSB")
        self.assertEqual(st.ptt, 1)

    def test_rigctld_sourced_events_do_not_loop_back(self):
        svc = self._make()
        svc.start()
        st = FakeServer.instances[0].state
        st.freq = 999
        self.bus.publish("radio.frequency", hz=1, source="rigctld")
        self.assertEqual(st.freq, 999)  # ignorado

    def test_reconfigure_restarts_on_port_change(self):
        svc = self._make(_cfg(enabled=True, port=4536))
        svc.start()
        svc.reconfigure(_cfg(enabled=True, port=4540))
        self.assertTrue(FakeServer.instances[0].stopped)
        self.assertEqual(FakeServer.instances[1].kwargs["port"], 4540)
        self.assertTrue(FakeServer.instances[1].started)

    def test_stop_unsubscribes(self):
        svc = self._make()
        svc.start()
        svc.stop()
        st = FakeServer.instances[0].state
        st.freq = 7
        self.bus.publish("radio.frequency", hz=123, source="app")
        self.assertEqual(st.freq, 7)  # ya no está suscrito
        self.assertTrue(FakeServer.instances[0].stopped)


if __name__ == "__main__":
    unittest.main()
