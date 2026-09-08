"""poorsdr.ui.hotkeys: catálogo de acciones y resolución con la config."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.ui import hotkeys  # noqa: E402


class HotkeysTests(unittest.TestCase):
    def test_actions_have_unique_ids_and_no_forbidden(self):
        ids = [a.id for a in hotkeys.HOTKEY_ACTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for forbidden in ("edit", "open_settings", "toggle_web", "web"):
            self.assertNotIn(forbidden, ids)

    def test_resolved_merges_defaults_and_user(self):
        got = hotkeys.resolved({"ptt_toggle": "p", "desconocida": "x"})
        self.assertEqual(got["ptt_toggle"], "p")          # override del usuario
        self.assertEqual(got["ch_plus"], "KP_Add")        # default intacto
        self.assertNotIn("desconocida", got)              # id no conocido, descartado
        self.assertEqual(set(got), hotkeys.ACTION_IDS)

    def test_active_bindings_drops_empty(self):
        got = hotkeys.active_bindings({"ptt_toggle": "", "open_mem": "F5"})
        self.assertNotIn("ptt_toggle", got)
        self.assertEqual(got["open_mem"], "F5")

    def test_none_user_gives_defaults(self):
        self.assertEqual(hotkeys.resolved(None)["auto_call_1"], "1")


if __name__ == "__main__":
    unittest.main()
