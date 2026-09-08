"""Lógica pura de OWRX en ``poorsdr.core.owrx`` (portada de ``owrx_*_domain``)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT / "src" / "poorsdr" / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from poorsdr.core.owrx import launch, process, spiderd, state  # noqa: E402


class CanonicalImportTests(unittest.TestCase):
    def test_process_helpers(self):
        self.assertFalse(process.is_process_running(None))
        self.assertEqual(process.normalize_display_mode("usb"), "USB")
        self.assertEqual(process.parse_incoming_tune_frequency("7074000"), 7074000)

    def test_state_paths(self):
        self.assertEqual(state.owrx_state_path(lambda p: f"/x/{p}"), "/x/waterfall_state.json")
        self.assertEqual(state.digi_state_path(lambda p: f"/x/{p}"), "/x/digi_state.json")

    def test_launch_allocates_free_port(self):
        port = launch.allocate_loopback_port()
        self.assertTrue(port is None or 1024 < port < 65536)

    def test_spiderd_renders_mqtt_ini(self):
        text = spiderd.render_spiderd_conf({})
        self.assertIn("[mqtt]", text)
        self.assertEqual(spiderd.normalize_spider_source("MQTT"), "mqtt")


if __name__ == "__main__":
    unittest.main()
