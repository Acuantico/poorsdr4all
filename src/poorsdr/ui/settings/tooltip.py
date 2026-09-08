"""Tooltip por hover para los controles de Ajustes.

Sustituye al texto de ayuda fijo bajo cada campo (``Field.help``): la ventana
queda limpia y la explicación solo aparece si el usuario deja el ratón quieto
sobre el campo un momento, en vez de ensuciar cada pestaña con una línea de
texto por control.
"""

from __future__ import annotations

import contextlib
import tkinter as tk

from poorsdr.ui.settings.style import BORDER, FG, FIELD

#: Milisegundos de hover antes de mostrar el tooltip.
DELAY_MS = 600
WRAPLENGTH = 360


class Tooltip:
    """Asocia ``text`` a ``widget``: aparece tras ``delay_ms`` de hover quieto."""

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = DELAY_MS) -> None:
        self._widget = widget
        self._text = text
        self._delay_ms = delay_ms
        self._after_id: str | None = None
        self._popup: tk.Toplevel | None = None
        if not text:
            return
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, event: tk.Event) -> None:
        self._cancel_pending()
        x_root, y_root = event.x_root, event.y_root
        self._after_id = self._widget.after(self._delay_ms, lambda: self._show(x_root, y_root))

    def _on_leave(self, _event: object = None) -> None:
        self._cancel_pending()
        self._hide()

    def _cancel_pending(self) -> None:
        if self._after_id is not None:
            with contextlib.suppress(Exception):
                self._widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self, x_root: int, y_root: int) -> None:
        if self._popup is not None:
            return
        popup = tk.Toplevel(self._widget)
        popup.wm_overrideredirect(True)
        with contextlib.suppress(tk.TclError):
            popup.wm_attributes("-topmost", True)
        popup.configure(bg=BORDER)
        label = tk.Label(
            popup, text=self._text, justify="left", wraplength=WRAPLENGTH,
            bg=FIELD, fg=FG, padx=8, pady=5, font=("TkDefaultFont", 9),
        )
        label.pack(padx=1, pady=1)  # borde de 1px (bg de popup) alrededor del label
        popup.wm_geometry(f"+{x_root + 12}+{y_root + 16}")
        self._popup = popup

    def _hide(self) -> None:
        if self._popup is not None:
            with contextlib.suppress(Exception):
                self._popup.destroy()
            self._popup = None


__all__ = ["Tooltip"]
