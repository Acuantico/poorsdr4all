"""Ventana de Ajustes.

Sustituye a ``ajustes.py`` (2076 líneas). Genera las pestañas a partir de
:data:`poorsdr.ui.settings.form.TABS`; guardar = ``on_save(nueva_cfg)`` (que
llama a ``AppContext.reconfigure`` → persiste y aplica en caliente).

Los puertos serie y los dispositivos de audio se enumeran al abrir la ventana
(:mod:`poorsdr.infra.devices`); los combos quedan editables por si la
enumeración falla o el equipo está desconectado. Las pestañas "Autollamada" y
"Atajos" usan editores propios. El aspecto (tema oscuro, plano) lo aplica
:mod:`poorsdr.ui.settings.style`.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from poorsdr.core.theme import accent_for_background
from poorsdr.i18n.settings_help import field_help
from poorsdr.i18n.settings_labels import field_label
from poorsdr.infra import devices as devmod
from poorsdr.ui.settings import style as sstyle
from poorsdr.ui.settings.about_panel import AboutPanel
from poorsdr.ui.settings.autocall_panel import AutocallEditor
from poorsdr.ui.settings.form import (
    AUDIO_ROLE,
    TAB_LABEL_KEY,
    TABS,
    audio_label,
    audio_label_for,
    build_config,
    get_value,
    label_core,
)
from poorsdr.ui.settings.hotkeys_panel import HotkeysEditor
from poorsdr.ui.settings.plugins_panel import PluginsEditor
from poorsdr.ui.settings.tooltip import Tooltip

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.devices import AudioEndpoint
    from poorsdr.plugins import DiscoveredPlugin, SettingsTab

class SettingsWindow:
    def __init__(
        self,
        master: tk.Misc,
        cfg: AppConfig,
        on_save: Callable[[AppConfig], None],
        *,
        plugins: Sequence[DiscoveredPlugin] = (),
        plugin_tabs: Sequence[SettingsTab] = (),
    ) -> None:
        self.cfg = cfg
        self._on_save = on_save
        self._plugins = plugins
        self._plugin_tabs = plugin_tabs
        # Idioma para los tooltips (poorsdr.i18n.settings_help); ver docstring
        # del módulo — cae a español si falta la clave o el idioma.
        self._lang = cfg.ui.language
        self._vars: dict[tuple[str, str], tk.Variable] = {}
        self._autocall: AutocallEditor | None = None
        self._hotkeys: HotkeysEditor | None = None
        self._plugins_editor: PluginsEditor | None = None

        # Enumeración del sistema (best-effort, no bloquea si falla).
        self._serial = devmod.serial_ports()
        self._sinks = devmod.audio_outputs()
        self._sources = devmod.audio_inputs()
        self._audio_catalog = (*self._sinks, *self._sources)

        accent = accent_for_background(cfg.ui.background_image)
        self.top = tk.Toplevel(master)
        self.top.title(field_label("label_window_title", self._lang))
        self.top.configure(bg=sstyle.BG)
        sstyle.apply(self.top, accent)

        # Pestañas fijas + las que aporten los plugins activos (p. ej. "Relés").
        all_tabs: dict[str, tuple] = dict(TABS)
        for plugin_tab in self._plugin_tabs:
            all_tabs[plugin_tab.name] = plugin_tab.fields

        nb = ttk.Notebook(self.top)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        for name, spec in all_tabs.items():
            tab = ttk.Frame(nb, padding=10)
            tab_key = TAB_LABEL_KEY.get(name, "")
            nb.add(tab, text=field_label(tab_key, self._lang) if tab_key else name)
            if name == "Autollamada":
                self._autocall = AutocallEditor(tab, self.cfg)
                self._autocall.pack(fill="both", expand=True)
            elif name == "Atajos":
                self._hotkeys = HotkeysEditor(tab, self.cfg)
                self._hotkeys.pack(fill="both", expand=True)
            elif name == "Plugins":
                self._plugins_editor = PluginsEditor(tab, self._plugins, self.cfg)
                self._plugins_editor.pack(fill="both", expand=True)
            elif name == "Acerca de":
                AboutPanel(tab, accent=accent, lang=self._lang).pack(fill="both", expand=True)
            else:
                self._build_tab(tab, spec)

        bar = ttk.Frame(self.top, style="Ground.TFrame", padding=(10, 6))
        bar.pack(fill="x")
        ttk.Button(
            bar, text=field_label("label_save", self._lang), style="Accent.TButton",
            command=self._save,
        ).pack(side="right", padx=(6, 0))
        ttk.Button(
            bar, text=field_label("label_cancel", self._lang), command=self.top.destroy,
        ).pack(side="right")

    # -- helpers de combos ------------------------------------------------ #
    @staticmethod
    def _with_current(current: str, listed: Sequence[str]) -> list[str]:
        options = [""]
        if current and current not in listed:
            options.append(current)
        options.extend(listed)
        return options

    @staticmethod
    def _audio_display(dev: object, endpoints: Sequence[AudioEndpoint], role: str) -> str:
        """Etiqueta a mostrar para el ``AudioDevice`` guardado: se prefiere casar
        por el nombre PulseAudio estable (así se recoge el número aunque la
        descripción del dispositivo haya cambiado)."""
        pulse = getattr(dev, "pulse", "") or ""
        label = getattr(dev, "label", "") or ""
        if pulse:
            for endpoint in endpoints:
                if endpoint.name == pulse:
                    return audio_label_for(dev, endpoint, role)
        stored = label or pulse
        core = label_core(stored, role)
        for endpoint in endpoints:
            if stored in (endpoint.name, endpoint.description) or core in (
                endpoint.name,
                endpoint.description,
            ):
                return audio_label(endpoint, role)
        return stored

    def _build_tab(self, tab: ttk.Frame, spec: tuple) -> None:
        row = 0
        for field in spec:
            var: tk.Variable

            if field.kind == "bool":
                var = tk.BooleanVar(value=bool(get_value(self.cfg, field)))
                control = ttk.Checkbutton(
                    tab, text=field_label(field.label_key, self._lang), variable=var,
                )
                control.grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=3)
                self._vars[(field.section, field.attr)] = var
                Tooltip(control, field_help(field.help_key, self._lang))
                row += 1
                continue

            label = ttk.Label(tab, text=field_label(field.label_key, self._lang))
            label.grid(row=row, column=0, sticky="w", padx=(4, 12), pady=4)
            value = get_value(self.cfg, field)

            if field.kind in ("choice", "theme"):
                var = tk.StringVar(value=str(value))
                control = ttk.Combobox(tab, textvariable=var, values=list(field.choices),
                                        state="readonly", width=18)
            elif field.kind == "serial":
                current = str(value or "")
                var = tk.StringVar(value=current)
                control = ttk.Combobox(tab, textvariable=var,
                                        values=self._with_current(current, self._serial), width=32)
            elif field.kind in ("sink", "source"):
                endpoints = self._sinks if field.kind == "sink" else self._sources
                role = AUDIO_ROLE.get(field.kind, "")
                dev = getattr(self.cfg.audio, field.attr)
                shown = self._audio_display(dev, endpoints, role)
                labels = [audio_label(e, role) for e in endpoints]
                var = tk.StringVar(value=shown)
                control = ttk.Combobox(tab, textvariable=var,
                                        values=self._with_current(shown, labels), width=48)
            elif field.kind == "json":
                var = tk.StringVar(value=json.dumps(value, ensure_ascii=False))
                control = ttk.Entry(tab, textvariable=var, width=46)
            else:
                show = "*" if field.kind in ("password", "web_password") else ""
                var = tk.StringVar(value="" if value is None else str(value))
                control = ttk.Entry(tab, textvariable=var, width=32, show=show)
            control.grid(row=row, column=1, sticky="w")
            self._vars[(field.section, field.attr)] = var
            help_text = field_help(field.help_key, self._lang)
            Tooltip(label, help_text)
            Tooltip(control, help_text)
            row += 1

    def _save(self) -> None:
        raw = {key: var.get() for key, var in self._vars.items()}
        if self._autocall is not None:
            raw.update(self._autocall.values())
        if self._hotkeys is not None:
            raw.update(self._hotkeys.values())
        if self._plugins_editor is not None:
            raw.update(self._plugins_editor.values())
        extra_fields = [f for tab in self._plugin_tabs for f in tab.fields]
        try:
            new = build_config(
                self.cfg, raw, audio_catalog=self._audio_catalog, extra_fields=extra_fields
            )
        except (ValueError, json.JSONDecodeError) as exc:
            title = field_label("label_window_title", self._lang)
            prefix = field_label("label_invalid_value", self._lang)
            messagebox.showerror(title, f"{prefix} {exc}", parent=self.top)
            return
        self._on_save(new)
        self.top.destroy()


__all__ = ["SettingsWindow"]
