"""Editor de atajos de teclado para la ventana de Ajustes.

Una fila por acción de :data:`poorsdr.ui.hotkeys.HOTKEY_ACTIONS`: pulsa el
recuadro y luego una tecla para asignarla; "×" la borra. :meth:`HotkeysEditor.values`
devuelve ``{("ui", "hotkeys"): json}`` para ``build_config``.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from poorsdr.i18n.settings_help import field_help
from poorsdr.i18n.settings_labels import field_label
from poorsdr.ui.hotkeys import HOTKEY_ACTIONS, resolved
from poorsdr.ui.settings.tooltip import Tooltip

if TYPE_CHECKING:
    from poorsdr.config.model import AppConfig

_COLS = 2  # dos columnas de acciones para que quepan todas

_MODIFIER_KEYS = frozenset({
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Super_L", "Super_R", "Caps_Lock", "Num_Lock", "Tab", "??",
})


class HotkeysEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, cfg: AppConfig) -> None:
        super().__init__(master)
        current = resolved(cfg.ui.hotkeys)
        self._keys: dict[str, tk.StringVar] = {}
        self._capturing: str | None = None
        capture_help = field_help("help_hotkeys_capture", cfg.ui.language)
        clear_help = field_help("help_hotkeys_clear", cfg.ui.language)

        for i, action in enumerate(HOTKEY_ACTIONS):
            col = (i % _COLS) * 3
            row = i // _COLS
            var = tk.StringVar(value=current.get(action.id, ""))
            self._keys[action.id] = var
            label = ttk.Label(
                self, text=field_label(action.label_key, cfg.ui.language), width=20, anchor="w",
            )
            label.grid(row=row, column=col, sticky="w", padx=(0, 4), pady=2)
            Tooltip(label, capture_help)
            entry = ttk.Entry(
                self, textvariable=var, width=12, justify="center", state="readonly",
            )
            entry.grid(row=row, column=col + 1, sticky="w", pady=2)
            entry.bind("<Button-1>", lambda _e, a=action.id, w=entry: self._start_capture(a, w))
            entry.bind("<KeyPress>", lambda e, a=action.id: self._captured(a, e))
            entry.bind("<FocusOut>", lambda _e: self._stop_capture())
            Tooltip(entry, capture_help)
            clear_button = ttk.Button(
                self, text="×", width=2, command=lambda a=action.id: self._keys[a].set(""),
            )
            clear_button.grid(row=row, column=col + 2, sticky="w", padx=(4, 16))
            Tooltip(clear_button, clear_help)

    # -- captura de tecla --------------------------------------------- #
    def _start_capture(self, action_id: str, widget: ttk.Entry) -> None:
        self._capturing = action_id
        widget.focus_set()

    def _stop_capture(self) -> None:
        self._capturing = None

    def _captured(self, action_id: str, event: tk.Event) -> str:
        if self._capturing != action_id:
            return "break"
        keysym = str(event.keysym or "").strip()
        if keysym == "Escape":
            self._keys[action_id].set("")
        elif keysym and keysym not in _MODIFIER_KEYS:
            self._keys[action_id].set(keysym)
        self._stop_capture()
        return "break"

    # -- salida ----------------------------------------------------- #
    def values(self) -> dict[tuple[str, str], str]:
        mapping = {aid: var.get().strip() for aid, var in self._keys.items() if var.get().strip()}
        return {("ui", "hotkeys"): json.dumps(mapping, ensure_ascii=False)}


__all__ = ["HotkeysEditor"]
