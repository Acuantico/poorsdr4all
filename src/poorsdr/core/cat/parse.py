"""Parsers de respuestas CAT (Kenwood / TS-480 y emulaciones tipo uSDX).

Portado de los métodos ``_parse_*`` de ``_legacy/cat.py`` a funciones puras.
Ninguna lanza: entrada inválida → ``None``.
"""

from __future__ import annotations

import re

from poorsdr.core.cat.modes import cat_to_mode

_IF_PTT_RE = re.compile(
    r"^IF\d{11}.{5}[+-]\d{4}[01][01][01]\d{2}([01])\d[01][01][01][01]\d{2};$"
)


def parse_frequency(response: str | None, prefix: str = "FA") -> int | None:
    """Extrae la frecuencia en Hz de una respuesta ``FA...`` / ``FB...``."""
    if not response:
        return None
    text = response.strip()
    if not text.startswith(prefix):
        return None
    digits = "".join(ch for ch in text[len(prefix):] if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits[:11])
    except ValueError:
        return None


def parse_if(response: str | None) -> tuple[int | None, str | None]:
    """De una respuesta ``IF...`` devuelve ``(frecuencia_hz, modo)``."""
    if not response:
        return None, None
    text = response.strip()
    if not text.startswith("IF"):
        return None, None

    freq: int | None = None
    freq_digits = text[2:13]
    if freq_digits.isdigit():
        freq = int(freq_digits)

    mode: str | None = None
    # IF estilo Kenwood: dígito de modo en la posición 28 (1-based) para TS-480;
    # la emulación parcial de uSDX sigue este layout.
    if len(text) >= 30 and text[27].isdigit():
        mode = cat_to_mode(int(text[27]))

    return freq, mode


def parse_if_ptt(response: str | None) -> bool | None:
    """De una respuesta ``IF...`` devuelve el estado de PTT (TX=True)."""
    if not response:
        return None
    text = str(response).strip()
    if not text.startswith("IF"):
        return None

    match = _IF_PTT_RE.match(text)
    if match:
        return bool(int(match.group(1)))

    # Fallback tolerante por índice (radios que no cuadran el formato estricto).
    for idx in (28, 26):
        if len(text) > idx and text[idx] in ("0", "1"):
            return bool(int(text[idx]))
    return None


def parse_mode(response: str | None) -> str | None:
    """De una respuesta ``MD<n>`` devuelve el nombre de modo."""
    if response and response.startswith("MD") and len(response) > 2 and response[2].isdigit():
        return cat_to_mode(int(response[2]))
    return None


__all__ = ["parse_frequency", "parse_if", "parse_if_ptt", "parse_mode"]
