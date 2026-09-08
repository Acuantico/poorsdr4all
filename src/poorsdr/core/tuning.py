"""Frecuencia de sintonía: representación, parseo, normalización y paso.

Portado de los helpers de ``RadioCBApp`` (``_split_frequency_parts``,
``_parse_frequency_parts``, ``_coerce_frequency``, ``_update_frequency_display``,
``_sync_step_from_config`` / ``_apply_step_change``). Todo puro.
"""

from __future__ import annotations

from dataclasses import dataclass

# Límites heredados: frecuencias de HF/CB "razonables".
MIN_HZ = 100_000
MAX_HZ = 100_000_000
FALLBACK_HZ = 27_065_000  # 27.065 MHz (CB canal 19-ish), igual que el legacy


@dataclass(frozen=True, slots=True)
class FrequencyParts:
    """La frecuencia partida como la muestra la UI: ``MHz.kHz,cHz``."""

    mhz: int
    khz: int  # 0..999
    chz: int  # centenas de Hz en pasos de 10: 0..99  (hz10 en el legacy)

    @property
    def hz(self) -> int:
        return self.mhz * 1_000_000 + self.khz * 1_000 + self.chz * 10


def split_frequency(hz: int) -> FrequencyParts:
    total = max(0, int(hz or 0))
    mhz, rem = divmod(total, 1_000_000)
    khz, rem = divmod(rem, 1_000)
    return FrequencyParts(mhz=mhz, khz=khz, chz=rem // 10)


def combine_frequency(mhz: int | str, khz: int | str, chz: int | str) -> int | None:
    """Combina las tres cajas de la UI en Hz, o ``None`` si no son válidas.

    Réplica de ``_parse_frequency_parts``: los tres campos deben ser dígitos,
    ``khz <= 999`` y ``chz <= 99``.
    """
    parts = [str(x).strip() for x in (mhz, khz, chz)]
    if not all(parts) or not all(p.isdigit() for p in parts):
        return None
    m, k, c = (int(p) for p in parts)
    if k > 999 or c > 99:
        return None
    return m * 1_000_000 + k * 1_000 + c * 10


def format_frequency(hz: int) -> str:
    """``"27.555,00 MHz"`` — igual que ``frequency_label_var`` del legacy."""
    p = split_frequency(hz)
    return f"{p.mhz}.{p.khz:03d},{p.chz:02d} MHz"


def coerce_frequency(value: object, *, fallback: int = FALLBACK_HZ) -> int:
    """Normaliza cualquier entrada de frecuencia a un entero de Hz saneado.

    Acepta enteros, ``"28074000"``, ``"28.074"`` / ``"28,074"`` (MHz). Recorta
    ceros de más (``280740000000`` → ``28074000``) y cae al ``fallback`` fuera de
    ``[MIN_HZ, MAX_HZ]``. Réplica de ``_coerce_frequency``.
    """
    if value is None:
        return fallback
    try:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return fallback
            if "." in text or "," in text:
                freq = int(float(text.replace(",", ".")) * 1_000_000)
            else:
                freq = int(text)
        else:
            freq = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return fallback

    while freq > MAX_HZ:
        freq //= 10
    if freq < MIN_HZ or freq > MAX_HZ:
        return fallback
    return freq


# ---- paso de sintonía ------------------------------------------------------- #
def step_khz_to_hz(khz: float | str) -> int | None:
    """``"0.5"`` kHz → ``500`` Hz. ``None`` si no es un número positivo."""
    try:
        value = float(str(khz).strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return int(round(value * 1_000))


def step_hz_to_khz_text(hz: int) -> str:
    """``500`` Hz → ``"0.5"`` (sin ceros de más), como ``_sync_step_from_config``."""
    return f"{max(1, int(hz or 1)) / 1_000:g}"


def apply_step(hz: int, step_hz: int, direction: int) -> int:
    """Sube/baja ``hz`` un ``step_hz`` (``direction`` = +1 / -1), sin bajar de 0."""
    step = max(1, int(step_hz or 1))
    return max(0, int(hz or 0) + (1 if direction >= 0 else -1) * step)


__all__ = [
    "FALLBACK_HZ",
    "MAX_HZ",
    "MIN_HZ",
    "FrequencyParts",
    "apply_step",
    "coerce_frequency",
    "combine_frequency",
    "format_frequency",
    "split_frequency",
    "step_hz_to_khz_text",
    "step_khz_to_hz",
]
