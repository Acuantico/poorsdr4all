"""poorsdr.ui.layout: overrides de posiciones del modo EDIT."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.ui import layout  # noqa: E402


class LayoutOverridesTests(unittest.TestCase):
    def test_round_trip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "layout.json"
            with mock.patch.object(layout, "_overrides_path", return_value=path):
                self.assertEqual(layout.load_overrides(), {})
                layout.save_overrides(
                    {"ptt_button": {"x": 10, "y": 20, "anchor": "nw", "width": 240}}
                )
                got = layout.load_overrides()
        self.assertEqual(got["ptt_button"]["x"], 10)
        self.assertEqual(got["ptt_button"]["width"], 240)

    def test_bad_file_returns_empty(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "layout.json"
            path.write_text("{ not json", encoding="utf-8")
            with mock.patch.object(layout, "_overrides_path", return_value=path):
                self.assertEqual(layout.load_overrides(), {})

    def test_non_dict_entries_dropped(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "layout.json"
            path.write_text('{"a": {"x": 1, "y": 2}, "b": 5}', encoding="utf-8")
            with mock.patch.object(layout, "_overrides_path", return_value=path):
                got = layout.load_overrides()
        self.assertEqual(set(got), {"a"})


if __name__ == "__main__":
    unittest.main()
