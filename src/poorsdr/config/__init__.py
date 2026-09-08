"""Modelo de configuración tipado, migración y carga/guardado."""

from __future__ import annotations

from poorsdr.config.loader import bootstrap, export_legacy, load, save
from poorsdr.config.migrate import from_legacy, is_native, load_any, to_native
from poorsdr.config.model import AppConfig

__all__ = [
    "AppConfig",
    "bootstrap",
    "export_legacy",
    "from_legacy",
    "is_native",
    "load",
    "load_any",
    "save",
    "to_native",
]
