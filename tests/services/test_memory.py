"""MemoryService: persistencia JSON + importación del memo.json heredado."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.core.memory import MemoryEntry  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402
from poorsdr.services.memory import MemoryService  # noqa: E402


class MemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.events: list = []
        self.bus.subscribe("memory.changed", lambda ev: self.events.append(ev.data))
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "memories.json"
        # aislar del memo.json real: fuente de importación inexistente por defecto
        self.no_import = Path(self._tmp.name) / "no-memo.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _svc(self, import_from=None):
        return MemoryService(
            self.bus, AppConfig(), path=self.path, import_from=import_from or self.no_import
        )

    def test_starts_empty_when_no_file(self):
        svc = self._svc()
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertEqual(svc.entries, [])
        self.assertEqual(self.events[-1]["count"], 0)

    def test_add_persists_and_publishes(self):
        svc = self._svc()
        svc.start()
        svc.add(MemoryEntry("CQ", 7074000, "USB", "40m"))
        self.assertEqual(len(svc.entries), 1)
        self.assertTrue(self.path.exists())
        on_disk = json.loads(self.path.read_text())
        self.assertEqual(on_disk[0]["name"], "CQ")
        self.assertEqual(self.events[-1]["count"], 1)

    def test_reload_from_disk(self):
        s1 = self._svc()
        s1.start()
        s1.add(MemoryEntry("A", 1))
        s1.add(MemoryEntry("B", 2))
        s2 = self._svc()
        s2.start()
        self.assertEqual([e.name for e in s2.entries], ["A", "B"])

    def test_remove_and_get(self):
        svc = self._svc()
        svc.start()
        svc.add(MemoryEntry("A", 1))
        svc.add(MemoryEntry("B", 2))
        self.assertEqual(svc.get(1).name, "B")
        svc.remove(0)
        self.assertEqual([e.name for e in svc.entries], ["B"])
        self.assertIsNone(svc.get(5))

    def test_imports_legacy_memo_json(self):
        legacy_memo = Path(self._tmp.name) / "memo.json"
        legacy_memo.write_text(
            json.dumps([{"name": "vieja", "hz": 27555000, "mode": "lsb", "band": "11m"}])
        )
        svc = self._svc(import_from=legacy_memo)
        svc.start()
        self.assertEqual([e.name for e in svc.entries], ["vieja"])
        # y se re-persistió en la ruta XDG nueva
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
