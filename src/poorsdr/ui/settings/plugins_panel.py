"""Editor de plugins para la ventana de Ajustes.

Lista los plugins detectados (entry points ``poorsdr.plugins``) con un check
para activarlos/desactivarlos. El estado se guarda en ``config.json`` bajo la
clave ``PLUGINS`` (``{id: bool}``); lo no listado se considera activo.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from poorsdr.i18n.settings_help import field_help
from poorsdr.i18n.settings_labels import field_label
from poorsdr.ui.settings.form import PLUGINS_KEY
from poorsdr.ui.settings.tooltip import Tooltip

if TYPE_CHECKING:
    from collections.abc import Sequence

    from poorsdr.config.model import AppConfig
    from poorsdr.plugins import DiscoveredPlugin


class PluginsEditor(ttk.Frame):
    def __init__(
        self, master: tk.Misc, discovered: Sequence[DiscoveredPlugin], cfg: AppConfig
    ) -> None:
        super().__init__(master)
        self._vars: dict[str, tk.BooleanVar] = {}
        restart_help = field_help("help_plugins_restart", cfg.ui.language)

        if not discovered:
            ttk.Label(
                self, style="Muted.TLabel", wraplength=560, justify="left",
                text=field_label("label_no_plugins", cfg.ui.language),
            ).grid(row=0, column=0, sticky="w")
            return

        for i, plugin in enumerate(discovered):
            var = tk.BooleanVar(value=plugin.enabled)
            self._vars[plugin.id] = var
            check = ttk.Checkbutton(self, text=plugin.name, variable=var)
            check.grid(row=i, column=0, sticky="w", pady=2)
            Tooltip(check, restart_help)
            note = plugin.id if not plugin.error else f"{plugin.id} — error: {plugin.error}"
            note_label = ttk.Label(self, text=note, style="Muted.TLabel")
            note_label.grid(row=i, column=1, sticky="w", padx=(12, 0))
            Tooltip(note_label, restart_help if not plugin.error else note)

    def values(self) -> dict[tuple[str, str], str]:
        mapping = {pid: var.get() for pid, var in self._vars.items()}
        return {PLUGINS_KEY: json.dumps(mapping)}


__all__ = ["PluginsEditor"]
