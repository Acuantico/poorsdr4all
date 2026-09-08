"""SpiderdService: render de spiderd.conf + systemctl --user."""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402
from poorsdr.services.spiderd import SpiderdService  # noqa: E402


class Runner:
    def __init__(self, active="active"):
        self.active = active
        self.cmds: list[list[str]] = []

    def __call__(self, cmd, timeout):
        self.cmds.append(cmd)
        if cmd[-2] == "is-active":
            return (0, self.active)
        return (0, "")


def _cfg(*, spots=True, **spider):
    base = AppConfig()
    owrx = replace(base.owrx, spots=replace(base.owrx.spots, enabled=spots))
    sp = replace(base.spider, **spider) if spider else base.spider
    return replace(base, owrx=owrx, spider=sp)


class SpiderdServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self._tmp = tempfile.TemporaryDirectory()
        self.conf = Path(self._tmp.name) / "spiderd.conf"

    def tearDown(self):
        self._tmp.cleanup()

    def _svc(self, cfg, runner):
        return SpiderdService(self.bus, cfg, conf_path=self.conf, runner=runner)

    def test_spots_disabled_writes_nothing(self):
        r = Runner()
        svc = self._svc(_cfg(spots=False), r)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertFalse(self.conf.exists())
        self.assertEqual(r.cmds, [])

    def test_start_renders_conf_and_restarts_unit(self):
        r = Runner(active="active")
        svc = self._svc(_cfg(mqtt_url="wss://example/mqtt"), r)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        text = self.conf.read_text()
        self.assertIn("[mqtt]", text)
        self.assertIn("wss://example/mqtt", text)
        self.assertIn(["systemctl", "--user", "restart", "spiderd.service"], r.cmds)

    def test_error_when_unit_not_active(self):
        svc = self._svc(_cfg(), Runner(active="failed"))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.ERROR)

    def test_stop_leaves_unit_running(self):
        r = Runner()
        svc = self._svc(_cfg(), r)
        svc.start()
        r.cmds.clear()
        svc.stop()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertEqual(r.cmds, [])  # no toca systemctl

    def test_reconfigure_rerenders_only_on_spider_change(self):
        r = Runner()
        svc = self._svc(_cfg(mqtt_url="wss://a"), r)
        svc.start()
        r.cmds.clear()
        svc.reconfigure(_cfg(mqtt_url="wss://a"))  # sin cambios
        self.assertEqual(r.cmds, [])
        svc.reconfigure(_cfg(mqtt_url="wss://b"))  # cambia
        self.assertIn("wss://b", self.conf.read_text())
        self.assertTrue(r.cmds)


if __name__ == "__main__":
    unittest.main()
