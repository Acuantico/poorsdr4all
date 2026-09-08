"""Perfiles de llamada automática (macro de CQ): modelo y validación puros.

Portado de ``_legacy/autocall.py:AutoCall.autollamada_personalizada`` y de
``RadioCBApp.cargar_perfiles_autollamada``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def parse_repeats(value: object) -> int | None:
    try:
        n = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_interval(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0.0, f)


#: Máximo de macros configurables y número de botones en la consola.
MACRO_LIMIT = 10
BUTTON_COUNT = 4


@dataclass(frozen=True, slots=True)
class AutocallProfile:
    audio: str
    repeats: int = 1
    interval: float = 0.0
    name: str = ""

    @property
    def valid(self) -> bool:
        return bool(self.audio) and self.repeats > 0

    @property
    def title(self) -> str:
        return self.name or self.audio


def profile_from_dict(raw: Mapping[str, object]) -> AutocallProfile | None:
    """Un elemento de ``AutoCallProfiles`` → ``AutocallProfile`` o ``None``."""
    audio = str(raw.get("Audio", "") or "").strip()
    if not audio:
        return None
    repeats = parse_repeats(raw.get("Repeticiones", 1)) or 1
    interval = parse_interval(raw.get("Intervalo", 0)) or 0.0
    name = str(raw.get("Nombre", "") or "").strip()
    return AutocallProfile(audio=audio, repeats=repeats, interval=interval, name=name)


def profiles_from_config(cfg_legacy: Mapping[str, object]) -> list[AutocallProfile]:
    raw = cfg_legacy.get("AutoCallProfiles")
    out: list[AutocallProfile] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                prof = profile_from_dict(item)
                if prof is not None:
                    out.append(prof)
    if not out:
        # compat: los campos sueltos del legacy
        audio = str(cfg_legacy.get("Audio_Llamada_Automatica", "") or "").strip()
        if audio:
            out.append(
                AutocallProfile(
                    audio=audio,
                    repeats=parse_repeats(cfg_legacy.get("Repeticiones", 1)) or 1,
                    interval=parse_interval(cfg_legacy.get("Intervalo", 0)) or 0.0,
                )
            )
    return out


def slots_from_config(cfg_legacy: Mapping[str, object]) -> list[AutocallProfile]:
    """Macros por **posición** (índice estable). Las inválidas ocupan su hueco.

    A diferencia de :func:`profiles_from_config`, no descarta las inválidas: el
    índice de cada macro es el que usan ``AutoCallButtons`` y los 4 botones.
    """
    raw = cfg_legacy.get("AutoCallProfiles")
    slots: list[AutocallProfile] = []
    if isinstance(raw, list):
        for item in raw[:MACRO_LIMIT]:
            parsed = profile_from_dict(item) if isinstance(item, Mapping) else None
            slots.append(parsed or AutocallProfile(audio=""))
    if not slots:
        for prof in profiles_from_config(cfg_legacy):
            slots.append(prof)
    return slots


def button_targets(cfg_legacy: Mapping[str, object]) -> list[int]:
    """Índice de macro que dispara cada uno de los 4 botones (``-1`` = sin asignar)."""
    raw = cfg_legacy.get("AutoCallButtons")
    out: list[int] = []
    if isinstance(raw, (list, tuple)):
        for value in list(raw)[:BUTTON_COUNT]:
            try:
                out.append(int(value))
            except (TypeError, ValueError):
                out.append(-1)
    while len(out) < BUTTON_COUNT:
        out.append(len(out))  # por defecto botón i → macro i
    return out


__all__ = [
    "BUTTON_COUNT",
    "MACRO_LIMIT",
    "AutocallProfile",
    "button_targets",
    "parse_interval",
    "parse_repeats",
    "profile_from_dict",
    "profiles_from_config",
    "slots_from_config",
]
