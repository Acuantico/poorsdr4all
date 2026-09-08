"""Construcción de tramas de comando CAT (Kenwood / TS-480).

Funciones puras: entrada → cadena de comando terminada en ``;``. El envío por
serie lo hace la capa de servicio.
"""

from __future__ import annotations

from poorsdr.core.cat.modes import mode_to_cat

TERMINATOR = ";"


def _term(cmd: str) -> str:
    return cmd if cmd.endswith(TERMINATOR) else cmd + TERMINATOR


def set_frequency(hz: int) -> str:
    """``FA`` — fija la frecuencia VFO A en Hz (11 dígitos)."""
    freq = max(0, int(hz))
    return _term(f"FA{freq:011d}")


def set_mode(mode: str) -> str:
    """``MD`` — fija el modo."""
    return _term(f"MD{mode_to_cat(mode)}")


def set_ptt(active: bool) -> str:
    """``TX`` / ``RX`` — activa o suelta el PTT."""
    return _term("TX" if active else "RX")


def query_frequency() -> str:
    return _term("FA")


def query_mode() -> str:
    return _term("MD")


def query_if() -> str:
    """``IF`` — estado combinado (frecuencia, modo, PTT…)."""
    return _term("IF")


def query_id() -> str:
    return _term("ID")


__all__ = [
    "TERMINATOR",
    "query_frequency",
    "query_id",
    "query_if",
    "query_mode",
    "set_frequency",
    "set_mode",
    "set_ptt",
]
