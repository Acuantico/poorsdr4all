"""Textos de la interfaz en los idiomas soportados.

``strings.idiomas`` es el diccionario portado de ``_legacy/idiomas.py`` (shim
allí). :func:`t` es el acceso recomendado.
"""

from __future__ import annotations

from poorsdr.i18n.strings import idiomas

DEFAULT_LANG = "es"
LANGUAGES: tuple[str, ...] = tuple(idiomas)


def translations(lang: str) -> dict[str, str]:
    """Diccionario de textos para ``lang`` (cae a ``es`` si no existe)."""
    return dict(idiomas.get(lang, idiomas[DEFAULT_LANG]))


def t(key: str, lang: str = DEFAULT_LANG, *, default: str | None = None) -> str:
    """Texto de ``key`` en ``lang``; si falta, prueba ``es`` y luego ``default``/``key``."""
    table = idiomas.get(lang, {})
    if key in table:
        return table[key]
    fallback = idiomas[DEFAULT_LANG]
    if key in fallback:
        return fallback[key]
    return default if default is not None else key


__all__ = ["DEFAULT_LANG", "LANGUAGES", "idiomas", "t", "translations"]
