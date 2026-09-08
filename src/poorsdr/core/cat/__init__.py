"""Lógica pura de CAT/hamlib (Kenwood / TS-480): modos, tramas y parsers.

Extraída de ``_legacy/cat.py``. La E/S por serie y el estado viven en
``poorsdr.services.radio``.
"""

from __future__ import annotations

from poorsdr.core.cat import frames, parse, profiles
from poorsdr.core.cat.modes import (
    CAT_TO_MODE,
    DEFAULT_MODE,
    MODE_TO_CAT,
    cat_to_mode,
    mode_to_cat,
)
from poorsdr.core.cat.parse import parse_frequency, parse_if, parse_if_ptt, parse_mode
from poorsdr.core.cat.profiles import apply_profile, resolve_profile

__all__ = [
    "CAT_TO_MODE",
    "DEFAULT_MODE",
    "MODE_TO_CAT",
    "apply_profile",
    "cat_to_mode",
    "frames",
    "mode_to_cat",
    "parse",
    "parse_frequency",
    "parse_if",
    "parse_if_ptt",
    "parse_mode",
    "profiles",
    "resolve_profile",
]
