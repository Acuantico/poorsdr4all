"""Ventana de Ajustes (sustituye a ``ajustes.py``)."""

from __future__ import annotations

from poorsdr.ui.settings.form import TABS, Field, build_config, coerce_value, get_value

__all__ = ["TABS", "Field", "build_config", "coerce_value", "get_value"]


def __getattr__(name: str) -> object:
    # SettingsWindow requiere tkinter; import perezoso.
    if name == "SettingsWindow":
        from poorsdr.ui.settings.window import SettingsWindow

        return SettingsWindow
    raise AttributeError(name)
