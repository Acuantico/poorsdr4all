"""Mapa de modos entre nombres y códigos CAT (Kenwood / TS-480).

Portado tal cual de ``_legacy/cat.py`` (``MODE_TO_CAT`` / ``CAT_TO_MODE``), como
lógica pura y testeable.
"""

from __future__ import annotations

MODE_TO_CAT: dict[str, int] = {
    "LSB": 1,
    "USB": 2,
    "CW": 3,
    "FM": 4,
    "AM": 5,
    "DIGU": 6,
}

CAT_TO_MODE: dict[int, str] = {code: name for name, code in MODE_TO_CAT.items()}

DEFAULT_MODE = "USB"


def mode_to_cat(mode: str | None) -> int:
    """Nombre de modo → código CAT. Desconocido → código de :data:`DEFAULT_MODE`."""
    return MODE_TO_CAT.get((mode or "").strip().upper(), MODE_TO_CAT[DEFAULT_MODE])


def cat_to_mode(code: int | str | None) -> str | None:
    """Código CAT → nombre de modo, o ``None`` si no se reconoce."""
    try:
        return CAT_TO_MODE.get(int(code))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


__all__ = ["CAT_TO_MODE", "DEFAULT_MODE", "MODE_TO_CAT", "cat_to_mode", "mode_to_cat"]
