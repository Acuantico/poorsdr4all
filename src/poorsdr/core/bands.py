"""Bandas de operación y su frecuencia representativa.

Portado de ``RadioCBApp.band_map_hz`` + ``_infer_band_from_frequency``
(``_legacy/gui_app/mixins_memory.py``). Lógica pura.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Banda → frecuencia central representativa (Hz). Orden = orden de UI.
BAND_MAP_HZ: dict[str, int] = {
    "160m": 1_900_000,
    "80m": 3_650_000,
    "60m": 5_357_000,
    "40m": 7_074_000,
    "30m": 10_136_000,
    "20m": 14_074_000,
    "17m": 18_100_000,
    "15m": 21_074_000,
    "11m": 27_555_000,
    "10m": 28_074_000,
}


def band_names() -> list[str]:
    return list(BAND_MAP_HZ)


def infer_band(hz: int, band_map: Mapping[str, int] | None = None) -> str:
    """Banda cuya frecuencia representativa está más cerca de ``hz``.

    Devuelve ``""`` si el mapa está vacío. Réplica exacta del criterio heredado
    (``min`` por distancia absoluta; ante empate gana el primero del mapa).
    """
    table = band_map if band_map is not None else BAND_MAP_HZ
    if not table:
        return ""
    target = int(hz or 0)
    return min(table.items(), key=lambda item: abs(item[1] - target))[0]


def band_center_hz(band: str, band_map: Mapping[str, int] | None = None) -> int | None:
    table = band_map if band_map is not None else BAND_MAP_HZ
    return table.get(band)


__all__ = ["BAND_MAP_HZ", "band_center_hz", "band_names", "infer_band"]
