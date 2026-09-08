"""poorsdr.viewers.launcher: construcción de args/entorno de los visores."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT / "src" / "poorsdr" / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.viewers import launcher  # noqa: E402


class LauncherTests(unittest.TestCase):
    def test_open_waterfall_builds_expected_command(self):
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value = mock.Mock(poll=lambda: None)
            launcher.open_waterfall(AppConfig())
        self.assertTrue(popen.called)
        args, kwargs = popen.call_args
        cmd = args[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertTrue(cmd[1].endswith("waterfall.py"))
        self.assertEqual(cmd[2], "http://127.0.0.1:8073/")
        self.assertIn("start_new_session", kwargs)
        env = kwargs["env"]
        self.assertIn("OWRX_CONFIG_PATH", env)
        self.assertTrue(env["OWRX_FORCE_GEOMETRY"].startswith("1912x262"))

    def test_open_digi_uses_digi_helper(self):
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value = mock.Mock(poll=lambda: None)
            launcher.open_digi(AppConfig())
        self.assertTrue(popen.call_args[0][0][1].endswith("digi.py"))

    def test_geometry_helpers(self):
        self.assertTrue(launcher._looks_like_geometry("1284x760+10+20"))
        self.assertTrue(launcher._looks_like_geometry("800x600"))
        self.assertFalse(launcher._looks_like_geometry("nope"))
        self.assertEqual(launcher._size("1000x500+1+2", (9, 9)), (1000, 500))
        self.assertEqual(launcher._size("bad", (9, 9)), (9, 9))

    def test_viewer_handle_terminate(self):
        # proceso real corto que ignora SIGTERM para forzar el kill
        code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        proc = launcher.subprocess.Popen([sys.executable, "-c", code])
        h = launcher.ViewerHandle(proc=proc, command_port=0)
        self.assertTrue(h.running())
        h.terminate(timeout=0.3)  # SIGTERM ignorado → kill
        self.assertFalse(h.running())

    def test_viewer_handle_terminate_noop_when_dead(self):
        proc = launcher.subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        h = launcher.ViewerHandle(proc=proc, command_port=0)
        h.terminate()  # no revienta
        self.assertFalse(h.running())


if __name__ == "__main__":
    unittest.main()
