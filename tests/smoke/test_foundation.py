"""Smoke tests de la fundación (Fase 0): imports, logging, bus y servicios."""

from __future__ import annotations

import importlib
import logging
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))


class ImportsTests(unittest.TestCase):
    def test_public_modules_import(self):
        for name in (
            "poorsdr",
            "poorsdr.app",
            "poorsdr.runtime",
            "poorsdr.config",
            "poorsdr.config.model",
            "poorsdr.config.loader",
            "poorsdr.config.migrate",
            "poorsdr.infra",
            "poorsdr.infra.paths",
            "poorsdr.infra.logging",
            "poorsdr.infra.events",
            "poorsdr.services",
            "poorsdr.services.base",
        ):
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_version_present(self):
        import poorsdr

        self.assertRegex(poorsdr.__version__, r"^\d+\.\d+")


class LoggingTests(unittest.TestCase):
    def test_configure_is_idempotent(self):
        from poorsdr.infra import logging as plog

        with __import__("tempfile").TemporaryDirectory() as tmp:
            path1 = plog.configure(level=logging.DEBUG, log_dir=Path(tmp))
            path2 = plog.configure(level=logging.DEBUG, log_dir=Path(tmp))
            self.assertEqual(path1, path2)
            log = plog.get_logger("smoke")
            log.info("linea de prueba")
            root = logging.getLogger(plog.ROOT_LOGGER)
            for handler in root.handlers:
                handler.flush()
            self.assertTrue(path1.exists())
            self.assertIn("linea de prueba", path1.read_text(encoding="utf-8"))
            # Cierra los handlers antes de que el "with" borre el directorio
            # temporal: en Windows no se puede eliminar un fichero mientras
            # el propio proceso lo tenga abierto (a diferencia de Linux).
            for handler in list(root.handlers):
                handler.close()
                root.removeHandler(handler)


class EventBusTests(unittest.TestCase):
    def test_pub_sub_and_unsubscribe(self):
        from poorsdr.infra.events import EventBus

        bus = EventBus()
        seen: list = []
        cancel = bus.subscribe("radio.frequency", lambda ev: seen.append(ev["hz"]))
        bus.publish("radio.frequency", hz=7074000)
        bus.publish("radio.frequency", hz=14074000)
        cancel()
        bus.publish("radio.frequency", hz=1)
        self.assertEqual(seen, [7074000, 14074000])

    def test_failing_subscriber_does_not_break_bus(self):
        from poorsdr.infra.events import EventBus

        bus = EventBus()
        hits: list = []

        def boom(_ev):
            raise RuntimeError("explota")

        bus.subscribe("t", boom)
        bus.subscribe("t", lambda _ev: hits.append(1))
        bus.publish("t")
        self.assertEqual(hits, [1])


class ServiceManagerTests(unittest.TestCase):
    def test_lifecycle_and_reconfigure(self):
        from poorsdr.config.model import AppConfig
        from poorsdr.infra.events import EventBus
        from poorsdr.services.base import BaseService, ServiceManager, ServiceState

        events: list[str] = []

        class Fake(BaseService):
            name = "fake"

            def start(self) -> None:
                events.append("start")
                self._set_status(ServiceState.RUNNING)

            def stop(self) -> None:
                events.append("stop")
                self._set_status(ServiceState.STOPPED)

            def reconfigure(self, cfg: AppConfig) -> None:
                events.append("reconfigure")

        bus = EventBus()
        mgr = ServiceManager(bus)
        svc = mgr.register(Fake(bus))
        mgr.start_all()
        self.assertTrue(svc.status.ok)
        mgr.reconfigure_all(AppConfig())
        mgr.stop_all()
        self.assertEqual(events, ["start", "reconfigure", "stop"])
        self.assertIs(mgr.get("fake"), svc)

    def test_one_failing_service_does_not_abort_the_rest(self):
        from poorsdr.infra.events import EventBus
        from poorsdr.services.base import BaseService, ServiceManager

        started: list[str] = []

        class Ok(BaseService):
            def __init__(self, bus, name):
                super().__init__(bus)
                self.name = name

            def start(self) -> None:
                started.append(self.name)

        class Bad(BaseService):
            name = "bad"

            def start(self) -> None:
                raise RuntimeError("nope")

        bus = EventBus()
        mgr = ServiceManager(bus)
        mgr.register(Ok(bus, "a"))
        mgr.register(Bad(bus))
        mgr.register(Ok(bus, "b"))
        mgr.start_all()
        self.assertEqual(started, ["a", "b"])


class ConfigLoaderTests(unittest.TestCase):
    def test_save_then_load_native_round_trip(self):
        import tempfile

        from poorsdr.config import loader
        from poorsdr.config.model import AppConfig

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            cfg = AppConfig()
            loader.save(cfg, target)
            self.assertTrue(target.exists())
            reloaded = loader.load(target)
            self.assertEqual(reloaded.to_legacy(), cfg.to_legacy())

    def test_bootstrap_imports_legacy_flat_config(self):
        import json
        import tempfile

        from poorsdr.config import loader

        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.json"
            legacy.write_text(json.dumps({"CAT_COM": "/dev/ttyUSB9", "OWRX_PORT": 9999}))
            target = Path(tmp) / "out" / "config.json"
            raw = json.loads(legacy.read_text())
            from poorsdr.config import migrate

            cfg = migrate.from_legacy(raw)
            loader.save(cfg, target)
            self.assertEqual(cfg.cat.port, "/dev/ttyUSB9")
            self.assertEqual(cfg.owrx.port, 9999)
            self.assertTrue(migrate.is_native(json.loads(target.read_text())))


if __name__ == "__main__":
    unittest.main()
