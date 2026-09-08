"""Memorias de frecuencia: modelo y validación puros.

Portado de ``_legacy/gui_app/mixins_memory.py`` (``_load_memory_frequencies``,
``_parse_memory_frequency``, ``_guardar_memoria``). Sin IO.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from poorsdr.core.bands import BAND_MAP_HZ

VALID_MODES: tuple[str, ...] = ("AM", "FM", "USB", "LSB", "CW")
DEFAULT_MODE = "AM"


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    name: str
    hz: int
    mode: str = DEFAULT_MODE
    band: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "hz": self.hz, "mode": self.mode, "band": self.band}


def _valid_band(band: str, bands: Iterable[str]) -> str:
    return band if band in set(bands) else ""


def coerce_entry(raw: Mapping[str, object], *, bands: Iterable[str] = tuple(BAND_MAP_HZ)) -> MemoryEntry | None:
    """Un dict del JSON → ``MemoryEntry`` saneado, o ``None`` si no es válido."""
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    try:
        hz = int(raw.get("hz"))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    mode = str(raw.get("mode", "")).upper()
    if mode not in VALID_MODES:
        mode = DEFAULT_MODE
    band = _valid_band(str(raw.get("band", "")).strip(), bands)
    return MemoryEntry(name=name, hz=hz, mode=mode, band=band)


def normalize_entries(
    raw: object, *, bands: Iterable[str] = tuple(BAND_MAP_HZ)
) -> list[MemoryEntry]:
    if not isinstance(raw, list):
        return []
    band_list = tuple(bands)
    out: list[MemoryEntry] = []
    for item in raw:
        if isinstance(item, Mapping):
            entry = coerce_entry(item, bands=band_list)
            if entry is not None:
                out.append(entry)
    return out


def parse_memory_frequency(text: str, *, default_hz: int) -> int | None:
    """Réplica de ``_parse_memory_frequency``: 7 dígitos → ``int * 10``.

    Texto vacío → ``default_hz``. Cualquier otra longitud → ``None``.
    """
    stripped = (text or "").strip()
    if not stripped:
        return int(default_hz)
    digits = "".join(ch for ch in stripped if ch.isdigit())
    if len(digits) != 7:
        return None
    return int(digits) * 10


def upsert(entries: list[MemoryEntry], entry: MemoryEntry) -> list[MemoryEntry]:
    """Sustituye por nombre (case-insensitive) o añade al final. Lista nueva."""
    key = entry.name.lower()
    out = [e for e in entries if e.name.lower() != key]
    out.append(entry)
    return out


def remove_at(entries: list[MemoryEntry], index: int) -> list[MemoryEntry]:
    if 0 <= index < len(entries):
        return [e for i, e in enumerate(entries) if i != index]
    return list(entries)


def to_json_list(entries: Iterable[MemoryEntry]) -> list[dict[str, object]]:
    return [e.as_dict() for e in entries]


__all__ = [
    "DEFAULT_MODE",
    "VALID_MODES",
    "MemoryEntry",
    "coerce_entry",
    "normalize_entries",
    "parse_memory_frequency",
    "remove_at",
    "to_json_list",
    "upsert",
]
