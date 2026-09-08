"""Tema oscuro y plano para la ventana de Ajustes (nada de gris "Windows XP").

Una sola llamada, :func:`apply`, configura un ``ttk.Style`` basado en *clam*
para todos los widgets ``ttk`` de la ventana. Los paneles usan ``ttk`` en vez
de ``tk`` para heredarlo.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from tkinter import ttk

from poorsdr.ui.theme import THEME_COLORS

BG = THEME_COLORS["bg_main"]
PANEL = THEME_COLORS["panel_bg"]
FG = THEME_COLORS["text_primary"]
MUTED = THEME_COLORS["text_muted"]
BORDER = THEME_COLORS["border"]
FIELD = "#0d1015"       # fondo de los campos, algo más claro que BG
FIELD_HOVER = "#141821"


def apply(root: tk.Misc, accent: str) -> None:
    style = ttk.Style(root)
    with contextlib.suppress(tk.TclError):  # clam siempre está en Tk moderno
        style.theme_use("clam")

    style.configure(
        ".", background=PANEL, foreground=FG, fieldbackground=FIELD,
        bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL,
        troughcolor=BG, focuscolor=accent, insertcolor=FG, arrowcolor=FG,
    )
    style.configure("TFrame", background=PANEL)
    style.configure("Ground.TFrame", background=BG)
    style.configure("TLabel", background=PANEL, foreground=FG)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Header.TLabel", background=PANEL, foreground=MUTED,
                    font=("TkDefaultFont", 9, "bold"))

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                    padding=(14, 6), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", BG)],
              foreground=[("selected", accent), ("active", FG)])

    style.configure("TButton", background=PANEL, foreground=FG, borderwidth=1,
                    padding=(12, 5), relief="flat")
    style.map("TButton",
              background=[("pressed", BG), ("active", FIELD_HOVER)],
              bordercolor=[("active", accent), ("focus", accent)],
              foreground=[("disabled", MUTED)])

    style.configure("Accent.TButton", background=accent, foreground=BG, borderwidth=0)
    style.map("Accent.TButton", background=[("active", accent), ("pressed", accent)])

    style.configure("TEntry", fieldbackground=FIELD, foreground=FG, borderwidth=1,
                    padding=4)
    style.map("TEntry", bordercolor=[("focus", accent)])

    style.configure("TCombobox", fieldbackground=FIELD, foreground=FG,
                    background=PANEL, borderwidth=1, padding=3,
                    selectbackground=accent, selectforeground=BG)
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD), ("disabled", PANEL)],
              foreground=[("disabled", MUTED)],
              bordercolor=[("focus", accent)])

    style.configure("TCheckbutton", background=PANEL, foreground=FG, padding=3)
    style.map("TCheckbutton",
              background=[("active", PANEL)],
              indicatorcolor=[("selected", accent), ("!selected", FIELD)])

    style.configure("TLabelframe", background=PANEL, bordercolor=BORDER, borderwidth=1)
    style.configure("TLabelframe.Label", background=PANEL, foreground=MUTED)

    # Lista desplegable de los Combobox (es un Listbox tk clásico).
    prefix = str(root)
    for opt, val in (
        ("*TCombobox*Listbox.background", FIELD),
        ("*TCombobox*Listbox.foreground", FG),
        ("*TCombobox*Listbox.selectBackground", accent),
        ("*TCombobox*Listbox.selectForeground", BG),
        ("*TCombobox*Listbox.borderWidth", "0"),
    ):
        root.option_add(f"{prefix}{opt}", val)


__all__ = ["BG", "BORDER", "FG", "FIELD", "MUTED", "PANEL", "apply"]
