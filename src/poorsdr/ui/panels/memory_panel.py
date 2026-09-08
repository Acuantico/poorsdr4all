"""Panel de memorias de frecuencia."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from poorsdr.core.bands import band_names
from poorsdr.core.memory import VALID_MODES, MemoryEntry, parse_memory_frequency
from poorsdr.i18n import t
from poorsdr.ui.theme import THEME_COLORS, UI_FONT_SMALL

if TYPE_CHECKING:
    from poorsdr.core.tuning import FrequencyParts  # noqa: F401

_BG = THEME_COLORS["panel_bg"]
_FG = THEME_COLORS["text_primary"]


class MemoryPanel(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_recall: Callable[[MemoryEntry], None],
        on_save: Callable[[MemoryEntry], None],
        on_delete: Callable[[int], None],
        current_hz: Callable[[], int],
        lang: str = "es",
    ) -> None:
        super().__init__(parent, bg=_BG, padx=12, pady=8)
        self._on_recall = on_recall
        self._on_save = on_save
        self._on_delete = on_delete
        self._current_hz = current_hz
        self._lang = lang
        self._entries: list[MemoryEntry] = []

        tk.Label(self, text=t("memories_title", lang), font=UI_FONT_SMALL, bg=_BG, fg=_FG).pack(anchor="w")
        self.listbox = tk.Listbox(self, height=6, width=34, activestyle="dotbox")
        self.listbox.pack(anchor="w", pady=4)
        self.listbox.bind("<Double-Button-1>", lambda _e: self._recall())

        form = tk.Frame(self, bg=_BG)
        form.pack(anchor="w", pady=2)
        self.name = tk.StringVar()
        self.freq = tk.StringVar()
        self.mode = tk.StringVar(value=VALID_MODES[0])
        self.band = tk.StringVar()
        tk.Entry(form, textvariable=self.name, width=12).grid(row=0, column=0, padx=2)
        tk.Entry(form, textvariable=self.freq, width=10).grid(row=0, column=1, padx=2)
        ttk.Combobox(form, textvariable=self.mode, values=list(VALID_MODES), width=4,
                     state="readonly").grid(row=0, column=2, padx=2)
        ttk.Combobox(form, textvariable=self.band, values=["", *band_names()], width=5,
                     state="readonly").grid(row=0, column=3, padx=2)

        btns = tk.Frame(self, bg=_BG)
        btns.pack(anchor="w", pady=4)
        tk.Button(btns, text=t("memories_recall", lang), command=self._recall).pack(side="left", padx=2)
        tk.Button(btns, text=t("save", lang), command=self._save).pack(side="left", padx=2)
        tk.Button(btns, text=t("memories_delete", lang), command=self._delete).pack(side="left", padx=2)

    # ---- API ------------------------------------------------------- #
    def set_entries(self, entries: Sequence[MemoryEntry]) -> None:
        self._entries = list(entries)
        self.listbox.delete(0, tk.END)
        for e in self._entries:
            self.listbox.insert(tk.END, f"{e.name}  {e.hz / 1_000_000:.4f}  {e.mode}  {e.band}")

    # ---- internos ------------------------------------------------ #
    def _selected(self) -> int | None:
        sel = self.listbox.curselection()
        return int(sel[0]) if sel else None

    def _recall(self) -> None:
        idx = self._selected()
        if idx is not None and 0 <= idx < len(self._entries):
            self._on_recall(self._entries[idx])

    def _save(self) -> None:
        title = t("memories_title", self._lang)
        name = self.name.get().strip()
        if not name:
            messagebox.showerror(title, t("memories_name_required", self._lang))
            return
        hz = parse_memory_frequency(self.freq.get(), default_hz=self._current_hz())
        if hz is None:
            messagebox.showerror(title, t("memories_invalid_freq", self._lang))
            return
        self._on_save(MemoryEntry(name=name, hz=hz, mode=self.mode.get(), band=self.band.get()))

    def _delete(self) -> None:
        idx = self._selected()
        if idx is not None:
            self._on_delete(idx)


__all__ = ["MemoryPanel"]
