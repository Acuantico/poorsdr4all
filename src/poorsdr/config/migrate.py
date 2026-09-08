"""Migración del ``config.json`` plano del proyecto original al modelo tipado.

El formato *legacy* es un diccionario plano de ~88–120 claves en
``MAYUSCULAS_CON_GUION`` / nombres en español (``Idioma``, ``Altavoz_PC``…). El
formato nuevo es anidado y lleva ``schema_version``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from poorsdr.config.model import SCHEMA_VERSION, AppConfig, known_legacy_keys
from poorsdr.infra.logging import get_logger

_log = get_logger("config")


def is_native(data: Mapping[str, Any]) -> bool:
    """``True`` si ``data`` ya está en el formato nuevo anidado."""
    version = data.get("schema_version")
    return isinstance(version, int) and version >= 2


def unknown_keys(flat: Mapping[str, Any]) -> list[str]:
    """Claves legacy que ningún campo del modelo reconoce."""
    known = known_legacy_keys()
    return sorted(k for k in flat if k not in known and k != "schema_version")


def from_legacy(flat: Mapping[str, Any], *, warn: bool = True) -> AppConfig:
    """Construye :class:`AppConfig` desde el dict plano legacy.

    Las claves no reconocidas no se pierden: se guardan en ``AppConfig.extra`` y
    (si ``warn``) se registran.
    """
    leftovers = unknown_keys(flat)
    if leftovers and warn:
        _log.warning(
            "config legacy con %d clave(s) no modeladas (se conservan en 'extra'): %s",
            len(leftovers),
            ", ".join(leftovers),
        )
    return AppConfig.from_legacy(flat)


def load_any(data: Mapping[str, Any], *, warn: bool = True) -> AppConfig:
    """Carga ``data`` venga en el formato que venga."""
    if is_native(data):
        return AppConfig.from_native(data)
    return from_legacy(data, warn=warn)


def to_native(cfg: AppConfig) -> dict[str, Any]:
    """Dict anidado listo para serializar, con ``schema_version``."""
    data = cfg.to_native()
    data["schema_version"] = SCHEMA_VERSION
    return data


__all__ = ["from_legacy", "is_native", "load_any", "to_native", "unknown_keys"]
