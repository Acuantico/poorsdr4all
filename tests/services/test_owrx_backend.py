"""OwrxBackendService: arranque/parada de openwebrx.service vía systemctl."""

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
from poorsdr.services.owrx_backend import OwrxBackendService  # noqa: E402


def _cfg(**owrx_over):
    base = AppConfig()
    owrx = replace(base.owrx, **owrx_over) if owrx_over else base.owrx
    return replace(base, owrx=owrx)


class Recorder:
    """Runner y probe deterministas para el test."""

    def __init__(self, *, ready_after: int | None = 0, start_rc: int = 0):
        self.ready_after = ready_after  # nº de probes tras los que el backend responde
        self.start_rc = start_rc
        self.commands: list[list[str]] = []
        self.probes = 0

    def run(self, cmd, timeout):
        self.commands.append(cmd)
        return (self.start_rc, "")

    def probe(self, url, timeout):
        n = self.probes
        self.probes += 1
        if self.ready_after is not None and n >= self.ready_after:
            return "<html>OpenWebRX</html>"
        return None


class OwrxBackendServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.status_events: list[dict] = []
        self.bus.subscribe("owrx.status", lambda ev: self.status_events.append(ev.data))

    def _svc(self, rec, cfg=None):
        return OwrxBackendService(
            self.bus,
            cfg or _cfg(enabled=True),
            runner=rec.run,
            http_probe=rec.probe,
            sleep=lambda _s: None,
            ready_timeout_s=5,
            poll_interval_s=0.01,
        )

    def test_disabled_is_stopped_and_touches_nothing(self):
        rec = Recorder()
        svc = self._svc(rec, _cfg(enabled=False))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertEqual(rec.commands, [])

    def test_already_running_does_not_call_systemctl(self):
        rec = Recorder(ready_after=0)
        svc = self._svc(rec)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertEqual(rec.commands, [])
        self.assertEqual(self.status_events[-1]["ready"], True)

    def test_starts_service_and_waits_ready(self):
        rec = Recorder(ready_after=2)  # 1er probe falla, arranca, luego responde
        svc = self._svc(rec)
        svc.start()
        self.assertEqual(rec.commands, [["sudo", "-n", "systemctl", "start", "openwebrx.service"]])
        self.assertEqual(svc.status.state, ServiceState.RUNNING)

    def test_error_when_service_never_responds(self):
        rec = Recorder(ready_after=None)
        svc = self._svc(rec)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.ERROR)
        self.assertEqual(self.status_events[-1]["ready"], False)

    def test_remote_backend_is_observed_not_managed(self):
        rec = Recorder(ready_after=None)
        svc = self._svc(rec, _cfg(enabled=True, host="192.168.1.50"))
        svc.start()
        self.assertEqual(rec.commands, [])  # nunca systemctl en remoto
        self.assertEqual(svc.status.state, ServiceState.ERROR)

    def test_stop_calls_systemctl_when_managed(self):
        rec = Recorder(ready_after=0)
        svc = self._svc(rec)
        svc.start()
        rec.commands.clear()
        svc.stop()
        self.assertEqual(rec.commands, [["sudo", "-n", "systemctl", "stop", "openwebrx.service"]])
        self.assertEqual(svc.status.state, ServiceState.STOPPED)

    def test_stop_respects_stop_on_exit_false(self):
        rec = Recorder(ready_after=0)
        svc = self._svc(rec, _cfg(enabled=True, stop_on_exit=False))
        svc.start()
        rec.commands.clear()
        svc.stop()
        self.assertEqual(rec.commands, [])

    def test_reconfigure_restarts_on_port_change(self):
        rec = Recorder(ready_after=0)
        svc = self._svc(rec, _cfg(enabled=True, port=8073))
        svc.start()
        rec.commands.clear()
        svc.reconfigure(_cfg(enabled=True, port=8074))
        self.assertIn(["sudo", "-n", "systemctl", "stop", "openwebrx.service"], rec.commands)
        self.assertEqual(svc.status.state, ServiceState.RUNNING)

    def test_reconfigure_noop_when_unchanged(self):
        rec = Recorder(ready_after=0)
        svc = self._svc(rec, _cfg(enabled=True, port=8073))
        svc.start()
        rec.commands.clear()
        svc.reconfigure(_cfg(enabled=True, port=8073))
        self.assertEqual(rec.commands, [])


if __name__ == "__main__":
    unittest.main()
