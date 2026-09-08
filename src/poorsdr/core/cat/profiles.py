"""Perfiles de radio conocidos para la familia uSDX / (tr)uSDX.

Un perfil es solo una **plantilla** de baudrate que Ajustes puede aplicar
sobre ``CatConfig``. En tiempo de ejecución, :mod:`poorsdr.services.radio` lo
resuelve y sustituye ``baud`` — salvo que el perfil sea ``CUSTOM`` (el valor
por defecto): entonces respeta ``baud`` tal cual esté, sin cambiar nada en
instalaciones existentes.

El dialecto CAT en sí (``FA``/``MD``/``IF``/``TX``/``RX``/``ID``, ver
:mod:`poorsdr.core.cat.frames` y :mod:`poorsdr.core.cat.parse``) no cambia
entre perfiles: la familia uSDX comparte el mismo subconjunto Kenwood TS-480
heredado de un linaje de firmware común (threeme3/usdx → GW8RDI/uSDXOpen →
forks como (tr)uSDX). Lo que sí varía, y es lo que un perfil ajusta, es el
enlace serie: el baudrate. El PTT es siempre por CAT (``TX;``/``RX;``); no
hay una alternativa por línea serie (RTS) que un perfil pueda seleccionar.

Modelos con solo diferencias de carcasa/botonera (Black Brick, White/Red
Buttons, uSDX original) no tienen perfil propio: no hay ninguna diferencia de
protocolo CAT documentada frente a ``GENERIC_TS480`` que la justifique. Añade
uno nuevo solo cuando se confirme una diferencia real (firmware, hardware o
prueba de un colaborador) — ver ``CONTRIBUTING.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RigProfile:
    """Plantilla de conexión CAT. ``None`` en ``baud`` significa "no tocar ese
    valor" (caso de :data:`CUSTOM`)."""

    id: str
    label: str
    baud: int | None
    verified: bool
    notes: str = ""


CUSTOM = RigProfile(
    id="custom",
    label="Personalizado (usa Baudios de Ajustes)",
    baud=None,
    verified=True,
    notes="Valor por defecto; no cambia nada en instalaciones existentes.",
)

GENERIC_TS480 = RigProfile(
    id="generic-ts480",
    label="Kenwood TS-480 genérico (uSDX / (tr)uSDX, firmware < 2.00t)",
    baud=38400,
    verified=True,
    notes=(
        "Dialecto usado por el uSDX del mantenedor. También documentado para "
        "Black Brick, White/Red Buttons y el uSDX original: mismo linaje de "
        "firmware, sin diferencias de CAT conocidas."
    ),
)

TRUSDX_115200 = RigProfile(
    id="trusdx-115200",
    label="(tr)uSDX firmware ≥ 2.00t (115200 baudios)",
    baud=115200,
    verified=False,
    notes="Documentado en dl2man.de/5-trusdx-details; no probado por el "
          "mantenedor en hardware real.",
)

_PROFILES: tuple[RigProfile, ...] = (CUSTOM, GENERIC_TS480, TRUSDX_115200)

PROFILES_BY_ID: dict[str, RigProfile] = {p.id: p for p in _PROFILES}
DEFAULT_PROFILE_ID = CUSTOM.id


def resolve_profile(profile_id: str | None) -> RigProfile:
    """Perfil para ``profile_id``; :data:`CUSTOM` si es desconocido o vacío."""
    return PROFILES_BY_ID.get((profile_id or "").strip(), CUSTOM)


def profile_choices() -> tuple[str, ...]:
    """IDs en el orden declarado, para el desplegable de Ajustes."""
    return tuple(p.id for p in _PROFILES)


def profile_labels() -> dict[str, str]:
    """``id -> etiqueta`` para pintar el desplegable de Ajustes."""
    return {p.id: p.label for p in _PROFILES}


def apply_profile(baud: int, profile_id: str | None) -> int:
    """``baud`` resultante de aplicar el perfil sobre el valor actual. Con
    :data:`CUSTOM` (o un id desconocido) lo devuelve sin tocar."""
    profile = resolve_profile(profile_id)
    return profile.baud if profile.baud is not None else int(baud)


__all__ = [
    "CUSTOM",
    "DEFAULT_PROFILE_ID",
    "GENERIC_TS480",
    "PROFILES_BY_ID",
    "TRUSDX_115200",
    "RigProfile",
    "apply_profile",
    "profile_choices",
    "profile_labels",
    "resolve_profile",
]
