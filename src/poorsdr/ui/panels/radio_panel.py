"""Panel de operación: VFO, paso, banda, modo y PTT.

Vista fina: pinta un :class:`~poorsdr.ui.state.RadioView` y avisa por callbacks.
No conoce los servicios ni el bus (los cablea ``poorsdr.ui.app``).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk

from poorsdr.core.bands import BAND_MAP_HZ
from poorsdr.core.tuning import combine_frequency
from poorsdr.ui.state import UI_MODES, RadioView
from poorsdr.ui.theme import THEME_COLORS, UI_FONT, UI_FONT_LARGE, UI_FONT_SMALL, UI_FONT_XL

_BG = THEME_COLORS["panel_bg"]
_FG = THEME_COLORS["text_primary"]
_MUTED = THEME_COLORS["text_muted"]
_ACCENT = THEME_COLORS["accent"]
_TX = THEME_COLORS["accent_tx"]


class RadioPanel(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_tune: Callable[[int], None],
        on_step: Callable[[int], None],
        on_nudge: Callable[[int], None],
        on_mode: Callable[[str], None],
        on_band: Callable[[str], None],
        on_ptt: Callable[[bool], None],
    ) -> None:
        super().__init__(parent, bg=_BG, padx=16, pady=12)
        self._on_tune = on_tune
        self._on_step = on_step
        self._on_nudge = on_nudge
        self._on_mode = on_mode
        self._on_band = on_band
        self._on_ptt = on_ptt
        self._editing = False
        self._ptt = False

        self.mhz = tk.StringVar()
        self.khz = tk.StringVar()
        self.chz = tk.StringVar()
        self.step = tk.StringVar(value="1")
        self.band = tk.StringVar()
        self.freq_label = tk.StringVar(value="—")
        self.cat_label = tk.StringVar(value="sin CAT")
        self._mode_btns: dict[str, tk.Button] = {}

        self._build()

    # ---- construcción --------------------------------------------------- #
    def _build(self) -> None:
        tk.Label(self, textvariable=self.freq_label, font=UI_FONT_XL, bg=_BG, fg=_FG).pack(anchor="w")
        tk.Label(self, textvariable=self.cat_label, font=UI_FONT_SMALL, bg=_BG, fg=_MUTED).pack(
            anchor="w", pady=(0, 8)
        )

        row = tk.Frame(self, bg=_BG)
        row.pack(anchor="w", pady=4)
        for var, width, sep in ((self.mhz, 3, "."), (self.khz, 3, ","), (self.chz, 2, "")):
            e = tk.Entry(row, textvariable=var, width=width, font=UI_FONT_LARGE, justify="right")
            e.pack(side="left")
            e.bind("<FocusIn>", self._on_focus_in)
            e.bind("<FocusOut>", self._on_focus_out)
            e.bind("<Return>", self._apply_entries)
            if sep:
                tk.Label(row, text=sep, font=UI_FONT_LARGE, bg=_BG, fg=_FG).pack(side="left")
        tk.Label(row, text="MHz", font=UI_FONT_SMALL, bg=_BG, fg=_MUTED).pack(side="left", padx=(6, 0))

        nudge = tk.Frame(self, bg=_BG)
        nudge.pack(anchor="w", pady=4)
        tk.Button(nudge, text="▼", width=3, command=lambda: self._on_nudge(-1)).pack(side="left")
        tk.Button(nudge, text="▲", width=3, command=lambda: self._on_nudge(+1)).pack(side="left", padx=(4, 12))
        tk.Label(nudge, text="paso (kHz)", font=UI_FONT_SMALL, bg=_BG, fg=_MUTED).pack(side="left")
        se = tk.Entry(nudge, textvariable=self.step, width=6, font=UI_FONT)
        se.pack(side="left", padx=6)
        se.bind("<Return>", self._apply_step)

        brow = tk.Frame(self, bg=_BG)
        brow.pack(anchor="w", pady=(10, 4))
        tk.Label(brow, text="Banda", font=UI_FONT_SMALL, bg=_BG, fg=_MUTED).pack(side="left", padx=(0, 6))
        combo = ttk.Combobox(
            brow, textvariable=self.band, values=list(BAND_MAP_HZ), width=6, state="readonly"
        )
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_band(self.band.get()))

        mrow = tk.Frame(self, bg=_BG)
        mrow.pack(anchor="w", pady=4)
        for m in UI_MODES:
            b = tk.Button(mrow, text=m, width=4, command=partial(self._on_mode, m))
            b.pack(side="left", padx=2)
            self._mode_btns[m] = b

        self.ptt_btn = tk.Button(
            self, text="PTT", font=UI_FONT_LARGE, height=2, width=16,
            command=self._toggle_ptt, bg=_BG, fg=_FG, activebackground=_TX,
        )
        self.ptt_btn.pack(anchor="w", pady=(12, 0))

    # ---- eventos de la vista ---------------------------------------- #
    def _on_focus_in(self, _e: object) -> None:
        self._editing = True

    def _on_focus_out(self, _e: object) -> None:
        self._editing = False

    def _apply_entries(self, _e: object = None) -> None:
        hz = combine_frequency(self.mhz.get(), self.khz.get(), self.chz.get())
        self._editing = False
        if hz is not None:
            self._on_tune(hz)

    def _apply_step(self, _e: object = None) -> None:
        self._on_step(self._step_hz())

    def _step_hz(self) -> int:
        from poorsdr.core.tuning import step_khz_to_hz

        return step_khz_to_hz(self.step.get()) or 1_000

    def _toggle_ptt(self) -> None:
        self._on_ptt(not self._ptt)

    # ---- refresco desde el estado ---------------------------------- #
    def apply_view(self, view: RadioView) -> None:
        self.freq_label.set(view.freq_label)
        self.cat_label.set(view.cat_status_text)
        if not self._editing:
            p = view.parts
            self.mhz.set(str(p.mhz))
            self.khz.set(f"{p.khz:03d}")
            self.chz.set(f"{p.chz:02d}")
        self.step.set(f"{view.step_hz / 1000:g}")
        if view.band and self.band.get() != view.band:
            self.band.set(view.band)
        for m, btn in self._mode_btns.items():
            btn.configure(bg=_ACCENT if m == view.mode else _BG, fg=_FG)
        self._ptt = view.ptt
        self.ptt_btn.configure(
            text="TX" if view.ptt else "PTT",
            bg=_TX if view.ptt else _BG,
        )


__all__ = ["RadioPanel"]
