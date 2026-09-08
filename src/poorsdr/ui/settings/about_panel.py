"""Pestaña "Acerca de" en Ajustes: autor, versión, web y agradecimientos.

Puramente informativa — no aporta ``Field`` ni se guarda nada al pulsar
Guardar (igual que "Plugins": ``TABS["Acerca de"] = ()``).
"""

from __future__ import annotations

import contextlib
import tkinter as tk
import webbrowser
from tkinter import ttk

from poorsdr.i18n.settings_labels import field_label
from poorsdr.ui.settings.style import BORDER, FG, MUTED, PANEL

_APP_NAME = "PoorSDR4All"
_VERSION = "1.0.0a1 · Alpha"
_AUTHOR = "Acuantico Power"
_WEBSITE_LABEL = "acuanticopower.com/poorsdr4all"
_WEBSITE_URL = f"https://{_WEBSITE_LABEL}"
_LICENSE_URL = "https://acuanticopower.com/poorsdr4all/license"
_KOFI_URL = "https://ko-fi.com/acuanticopower"

_ACK_LEAD = (
    "PoorSDR4All no existiría sin el impulso y el apoyo de EA5PR desde el "
    "principio. Mi agradecimiento hacia él será siempre enorme."
)
_ACK_BODY = (
    "Lo que comenzó como una herramienta personal ha ido creciendo alimentado "
    "por la ilusión, la comunidad y, sobre todo, la amistad.\n\n"
    "Espero que ahora, al compartirlo con todos, pueda ser útil y hacer "
    "disfrutar a mucha más gente.\n\n"
    "Gracias a todos los que, de una forma u otra, habéis formado parte del camino."
)


def _open_url(url: str) -> None:
    with contextlib.suppress(Exception):
        webbrowser.open(url)


class AboutPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, *, accent: str, lang: str = "es") -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)

        def _t(key: str, **kwargs: object) -> str:
            return field_label(key, lang, **kwargs)

        ttk.Label(self, text=_APP_NAME, font=("TkDefaultFont", 15, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self, text=_t("label_about_version", version=_VERSION), style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(self, text=_t("label_about_author", author=_AUTHOR)).grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        links = ttk.Frame(self)
        links.grid(row=3, column=0, sticky="w", pady=(2, 0))
        self._link(links, _WEBSITE_LABEL, _WEBSITE_URL, accent).pack(side="left")
        ttk.Label(links, text="  ·  ", style="Muted.TLabel").pack(side="left")
        self._link(links, _t("label_license_link"), _LICENSE_URL, accent).pack(side="left")

        ttk.Separator(self).grid(row=4, column=0, sticky="ew", pady=14)

        # El texto de agradecimiento es personal (dedicado a EA5PR) y de
        # momento solo se muestra en español, independientemente del idioma
        # de la interfaz.
        ack = tk.Text(
            self, wrap="word", height=11, bd=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=BORDER, bg=PANEL, fg=FG,
            font=("TkDefaultFont", 9), padx=10, pady=10, cursor="arrow",
        )
        ack.tag_configure("h1", font=("TkDefaultFont", 11, "bold"), foreground=FG)
        ack.tag_configure("lead", font=("TkDefaultFont", 9, "bold"), foreground=FG)
        ack.tag_configure("body", foreground=MUTED)
        ack.insert("end", _t("label_thanks_heading") + "\n\n", "h1")
        ack.insert("end", _ACK_LEAD + "\n\n", "lead")
        ack.insert("end", _ACK_BODY, "body")
        ack.configure(state="disabled")
        ack.grid(row=5, column=0, sticky="nsew")
        self.rowconfigure(5, weight=1)

        support = ttk.Frame(self)
        support.grid(row=6, column=0, sticky="w", pady=(14, 0))
        ttk.Label(
            support, text=_t("label_support_prompt"), style="Muted.TLabel"
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            support, text="☕ Ko-fi", style="Accent.TButton",
            command=lambda: _open_url(_KOFI_URL),
        ).pack(side="left")

    @staticmethod
    def _link(master: tk.Misc, text: str, url: str, accent: str) -> tk.Label:
        label = tk.Label(
            master, text=text, bg=PANEL, fg=accent, cursor="hand2",
            font=("TkDefaultFont", 9, "underline"),
        )
        label.bind("<Button-1>", lambda _e: _open_url(url))
        return label


__all__ = ["AboutPanel"]
