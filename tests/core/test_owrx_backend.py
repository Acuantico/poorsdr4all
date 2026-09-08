"""Lógica pura de gestión del backend OpenWebRX+."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.core.owrx import backend  # noqa: E402


class BackendHelpersTests(unittest.TestCase):
    def test_is_local_host(self):
        for h in ("127.0.0.1", "localhost", "::1", "", "  LOCALHOST "):
            self.assertTrue(backend.is_local_host(h), h)
        for h in ("192.168.1.5", "owrx.lan", "10.0.0.2"):
            self.assertFalse(backend.is_local_host(h), h)

    def test_should_manage_backend(self):
        self.assertTrue(
            backend.should_manage_backend(enabled=True, runtime="native", host="127.0.0.1")
        )
        self.assertFalse(
            backend.should_manage_backend(enabled=False, runtime="native", host="127.0.0.1")
        )
        self.assertFalse(
            backend.should_manage_backend(enabled=True, runtime="docker", host="127.0.0.1")
        )
        self.assertFalse(
            backend.should_manage_backend(enabled=True, runtime="native", host="192.168.1.9")
        )

    def test_should_stop_on_exit(self):
        self.assertTrue(backend.should_stop_on_exit(manage=True, stop_on_exit=True))
        self.assertFalse(backend.should_stop_on_exit(manage=True, stop_on_exit=False))
        self.assertFalse(backend.should_stop_on_exit(manage=False, stop_on_exit=True))

    def test_service_command(self):
        self.assertEqual(
            backend.service_command("start"),
            ["sudo", "-n", "systemctl", "start", "openwebrx.service"],
        )
        self.assertEqual(backend.service_command("stop")[3], "stop")
        with self.assertRaises(ValueError):
            backend.service_command("frobnicate")

    def test_backend_http_url(self):
        self.assertEqual(backend.backend_http_url("", 8073), "http://127.0.0.1:8073/")
        self.assertEqual(backend.backend_http_url("owrx.lan", 8074), "http://owrx.lan:8074/")

    def test_body_looks_like_owrx(self):
        self.assertTrue(backend.body_looks_like_owrx("<title>OpenWebRX</title>"))
        self.assertTrue(backend.body_looks_like_owrx(b"... webrx client ..."))
        self.assertTrue(backend.body_looks_like_owrx("Your RECEIVER is ready"))
        self.assertFalse(backend.body_looks_like_owrx("404 not found"))
        self.assertFalse(backend.body_looks_like_owrx(None))
        self.assertFalse(backend.body_looks_like_owrx(b""))


if __name__ == "__main__":
    unittest.main()
