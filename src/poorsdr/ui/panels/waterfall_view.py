"""Cascada embebida (matplotlib) para el marco central de la ventana principal.

Portado de ``RadioCBApp.configurar_cascada`` (la parte de vista). La señal la
procesa :class:`poorsdr.core.waterfall.WaterfallProcessor`.
"""

from __future__ import annotations

import tkinter as tk

import numpy as np

from poorsdr.core.theme import cascada_colors_for_background
from poorsdr.core.waterfall import WaterfallConfig, blank_image, scroll_in
from poorsdr.i18n import t
from poorsdr.infra.logging import get_logger
from poorsdr.ui.theme import THEME_COLORS

_log = get_logger("ui.waterfall")
_BG = THEME_COLORS["bg_main"]
_DEFAULT_ACCENT = "#1e90ff"


def _load_mpl():  # type: ignore[no-untyped-def]
    import matplotlib

    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.figure import Figure

    return Figure, FigureCanvasTkAgg, LinearSegmentedColormap


class WaterfallView(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        cfg: WaterfallConfig | None = None,
        *,
        accent: str = _DEFAULT_ACCENT,
        background: str = "back.png",
        lang: str = "es",
    ) -> None:
        super().__init__(parent, bg=_BG)
        self.cfg = cfg or WaterfallConfig()
        self._accent = accent
        self._background = background
        self._image = blank_image(self.cfg)
        self._img_artist = None
        self._canvas = None
        self._make_cmap = None
        try:
            Figure, FigureCanvasTkAgg, LinearSegmentedColormap = _load_mpl()
        except Exception:  # noqa: BLE001
            _log.warning("matplotlib no disponible; cascada desactivada")
            tk.Label(self, text=t("waterfall_fallback", lang), bg=_BG, fg=THEME_COLORS["text_muted"]).place(
                relx=0.5, rely=0.5, anchor="center"
            )
            return

        self._make_cmap = lambda acc: LinearSegmentedColormap.from_list(
            "poorsdr_wf", cascada_colors_for_background(self._background, acc)
        )
        cmap = self._make_cmap(accent)
        fig = Figure(figsize=(2.4, 2.4), dpi=100, facecolor=_BG)
        ax = fig.add_subplot(111)
        ax.set_facecolor(_BG)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.subplots_adjust(0, 0, 1, 1)
        self._img_artist = ax.imshow(
            self._image, aspect="auto", origin="lower", cmap=cmap,
            vmin=self.cfg.vmin, vmax=self.cfg.vmax, interpolation="nearest",
        )
        self._canvas = FigureCanvasTkAgg(fig, master=self)
        widget = self._canvas.get_tk_widget()
        widget.place(x=0, y=0, relwidth=1, relheight=1)

    def push_row(self, row: np.ndarray | None) -> None:
        if row is None or self._img_artist is None:
            return
        scroll_in(self._image, np.asarray(row, dtype=np.float32))
        self._img_artist.set_data(self._image)
        if self._canvas is not None:
            self._canvas.draw_idle()

    def clear(self) -> None:
        self._image = blank_image(self.cfg)
        if self._img_artist is not None:
            self._img_artist.set_data(self._image)
            if self._canvas is not None:
                self._canvas.draw_idle()

    def set_accent(self, accent: str, *, background: str | None = None) -> None:
        self._accent = accent
        if background is not None:
            self._background = background
        if self._img_artist is not None and self._make_cmap is not None:
            self._img_artist.set_cmap(self._make_cmap(accent))
            if self._canvas is not None:
                self._canvas.draw_idle()


__all__ = ["WaterfallView"]
