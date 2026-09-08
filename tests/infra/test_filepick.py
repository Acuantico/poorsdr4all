"""poorsdr.infra.filepick: diálogo de archivos nativo (subprocess simulado)."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.infra import filepick  # noqa: E402

_PATTERNS = [("Audio", "*.wav *.mp3"), ("Todos", "*")]


def _fake_run(stdout: str, returncode: int = 0):
    def run(cmd, **_kw):
        run.cmd = cmd
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return run


class FilePickTests(unittest.TestCase):
    def test_unavailable_returns_none(self):
        with mock.patch.object(filepick.shutil, "which", return_value=None):
            self.assertFalse(filepick.available())
            self.assertIsNone(filepick.open_file(patterns=_PATTERNS))

    def test_zenity_builds_filters_and_returns_path(self):
        fake = _fake_run("/home/op/cq.wav\n")
        with mock.patch.object(
            filepick.shutil, "which", side_effect=lambda n: "/usr/bin/zenity" if n == "zenity" else None
        ), mock.patch.object(filepick.subprocess, "run", fake):
            got = filepick.open_file(title="X", patterns=_PATTERNS, initial="/home/op/old.wav")
        self.assertEqual(got, "/home/op/cq.wav")
        self.assertIn("--file-selection", fake.cmd)
        self.assertIn("--file-filter=Audio | *.wav *.mp3", fake.cmd)
        self.assertIn("--filename=/home/op/old.wav", fake.cmd)

    def test_kdialog_used_when_present(self):
        fake = _fake_run("/snd/beep.mp3")
        with mock.patch.object(
            filepick.shutil, "which",
            side_effect=lambda n: f"/usr/bin/{n}" if n == "kdialog" else None,
        ), mock.patch.object(filepick.subprocess, "run", fake):
            got = filepick.open_file(patterns=_PATTERNS)
        self.assertEqual(got, "/snd/beep.mp3")
        self.assertEqual(fake.cmd[0], "kdialog")
        self.assertIn("--getopenfilename", fake.cmd)
        self.assertIn("*.wav *.mp3|Audio\n*|Todos", fake.cmd)

    def test_cancel_returns_none(self):
        fake = _fake_run("", returncode=1)
        with mock.patch.object(
            filepick.shutil, "which", side_effect=lambda n: "/usr/bin/zenity" if n == "zenity" else None
        ), mock.patch.object(filepick.subprocess, "run", fake):
            self.assertIsNone(filepick.open_file(patterns=_PATTERNS))


if __name__ == "__main__":
    unittest.main()
