"""Editor de macros de autollamada para la ventana de Ajustes.

Hasta :data:`MACRO_LIMIT` macros (nombre + audio + repeticiones + intervalo) y la
asignación de cada una a los 4 botones de la consola. El audio se elige con un
diálogo de archivos, no se teclea la ruta. Expone :meth:`AutocallEditor.values`,
que devuelve ``raw_values`` compatibles con
``poorsdr.ui.settings.form.build_config``.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

from poorsdr.core.autocall import (
    BUTTON_COUNT,
    MACRO_LIMIT,
    button_targets,
    slots_from_config,
)
from poorsdr.i18n.settings_help import field_help
from poorsdr.i18n.settings_labels import field_label
from poorsdr.ui.settings.tooltip import Tooltip

if TYPE_CHECKING:
    from poorsdr.config.model import AppConfig

_AUDIO_TYPES_KEYS = (
    ("label_audio", "*.wav *.WAV *.mp3 *.MP3 *.ogg *.OGG *.flac"),
    ("label_filetype_wav", "*.wav *.WAV"),
    ("label_filetype_all", "*"),
)

#: (clave de etiqueta, clave de ayuda) por columna de la tabla de macros.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("", ""),  # "#"
    ("label_name", "help_autocall_name"),
    ("label_audio", "help_autocall_audio"),
    ("", "help_autocall_pick"),  # botón "…"
    ("label_reps", "help_autocall_reps"),
    ("label_interval_s", "help_autocall_interval"),
)


class AutocallEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, cfg: AppConfig) -> None:
        super().__init__(master)
        self._lang = cfg.ui.language
        legacy = cfg.to_legacy()
        slots = slots_from_config(legacy)
        targets = button_targets(legacy)

        self._rows: list[dict[str, tk.StringVar]] = []
        self._btn_vars: list[tk.StringVar] = []

        self._build_macros(slots)
        self._build_assignment(targets)

    def _help(self, key: str, **kwargs: object) -> str:
        return field_help(key, self._lang, **kwargs)

    def _label(self, key: str, **kwargs: object) -> str:
        return field_label(key, self._lang, **kwargs)

    # -- secciones ------------------------------------------------------- #
    def _build_macros(self, slots: list) -> None:  # type: ignore[type-arg]
        title = self._label("label_autocall_macros_title", n=MACRO_LIMIT)
        box = ttk.Labelframe(self, text=title, padding=8)
        box.pack(fill="both", expand=True, pady=(0, 8))
        for col, (label_key, help_key) in enumerate(_COLUMNS):
            text = "#" if col == 0 else self._label(label_key) if label_key else ""
            header = ttk.Label(box, text=text, style="Header.TLabel")
            header.grid(row=0, column=col, sticky="w", padx=4, pady=(0, 4))
            Tooltip(header, self._help(help_key))
        for i in range(MACRO_LIMIT):
            prof = slots[i] if i < len(slots) else None
            filled = bool(prof and (prof.audio or prof.name))
            name = tk.StringVar(value=prof.name if prof else "")
            audio = tk.StringVar(value=prof.audio if prof else "")
            reps = tk.StringVar(value=str(prof.repeats) if filled and prof.valid else "")
            interval = tk.StringVar(value=f"{prof.interval:g}" if filled and prof.valid else "")
            index_label = ttk.Label(box, text=str(i + 1), style="Muted.TLabel")
            index_label.grid(row=i + 1, column=0, padx=4)
            Tooltip(index_label, self._help("help_autocall_index", n=i + 1, total=MACRO_LIMIT))
            name_entry = ttk.Entry(box, textvariable=name, width=16)
            name_entry.grid(row=i + 1, column=1, padx=2, pady=2)
            Tooltip(name_entry, self._help("help_autocall_name"))
            audio_entry = ttk.Entry(box, textvariable=audio, width=34, state="readonly")
            audio_entry.grid(row=i + 1, column=2, padx=2, pady=2)
            Tooltip(audio_entry, self._help("help_autocall_audio"))
            pick_button = ttk.Button(
                box, text="…", width=2, command=lambda v=audio: self._pick_audio(v)
            )
            pick_button.grid(row=i + 1, column=3, padx=(2, 8))
            Tooltip(pick_button, self._help("help_autocall_pick"))
            reps_entry = ttk.Entry(box, textvariable=reps, width=5)
            reps_entry.grid(row=i + 1, column=4, padx=2, pady=2)
            Tooltip(reps_entry, self._help("help_autocall_reps"))
            interval_entry = ttk.Entry(box, textvariable=interval, width=7)
            interval_entry.grid(row=i + 1, column=5, padx=2, pady=2)
            Tooltip(interval_entry, self._help("help_autocall_interval"))
            self._rows.append(
                {"name": name, "audio": audio, "reps": reps, "interval": interval}
            )

    def _pick_audio(self, var: tk.StringVar) -> None:
        from poorsdr.infra import filepick

        initial = var.get().strip() or None
        title = self._label("label_pick_audio_title")
        patterns = [(self._label(key), pattern) for key, pattern in _AUDIO_TYPES_KEYS]
        if filepick.available():
            path = filepick.open_file(title=title, patterns=patterns, initial=initial)
        else:
            path = filedialog.askopenfilename(
                parent=self, title=title, filetypes=patterns, initialfile=initial,
            )
        if path:
            var.set(path)

    def _build_assignment(self, targets: list[int]) -> None:
        box = ttk.Labelframe(self, text=self._label("label_console_buttons"), padding=8)
        box.pack(fill="x")
        unassigned = self._label("label_unassigned")
        options = [unassigned, *(str(n + 1) for n in range(MACRO_LIMIT))]
        for b in range(BUTTON_COUNT):
            label = ttk.Label(box, text=self._label("label_button_n", n=b + 1))
            label.grid(row=0, column=b * 2, sticky="e", padx=(8, 4))
            help_text = self._help("help_autocall_button", n=b + 1)
            Tooltip(label, help_text)
            idx = targets[b] if b < len(targets) else -1
            var = tk.StringVar(value=str(idx + 1) if 0 <= idx < MACRO_LIMIT else unassigned)
            combo = ttk.Combobox(box, textvariable=var, values=options, state="readonly", width=12)
            combo.grid(row=0, column=b * 2 + 1, sticky="w", padx=(0, 8))
            Tooltip(combo, help_text)
            self._btn_vars.append(var)

    # -- salida -------------------------------------------------------- #
    def values(self) -> dict[tuple[str, str], str]:
        macros: list[dict[str, str]] = []
        for row in self._rows:
            audio = row["audio"].get().strip()
            nombre = row["name"].get().strip()
            if not audio and not nombre:
                macros.append({"Audio": ""})  # hueco: mantiene el índice
                continue
            entry: dict[str, str] = {"Nombre": nombre, "Audio": audio}
            if row["reps"].get().strip():
                entry["Repeticiones"] = row["reps"].get().strip()
            if row["interval"].get().strip():
                entry["Intervalo"] = row["interval"].get().strip()
            macros.append(entry)
        while macros and not macros[-1].get("Audio") and not macros[-1].get("Nombre"):
            macros.pop()

        buttons: list[int] = []
        for var in self._btn_vars:
            raw = var.get().strip()
            buttons.append(int(raw) - 1 if raw.isdigit() else -1)

        return {
            ("autocall", "profiles"): json.dumps(macros, ensure_ascii=False),
            ("autocall", "buttons"): json.dumps(buttons),
        }


__all__ = ["AutocallEditor"]
