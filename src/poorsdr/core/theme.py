"""Paletas de tema y colormap de la cascada.

El "tema" lo elige ``Imagen_Fondo`` (6 opciones). Cada uno lleva un ``accent``.
La cascada construye su degradado a partir de ese acento. Portado de
``ajustes.THEME_PALETTES`` / ``RadioCBApp._get_cascada_colors``. Puro.
"""

from __future__ import annotations

_BASE = {
    "bg_main": "#121417",
    "panel_bg": "#1e2228",
    "text_primary": "#e0e0e0",
    "text_muted": "#b5b8bf",
    "border": "#2a2f36",
}

THEME_PALETTES: dict[str, dict[str, str]] = {
    "back.png": {**_BASE, "accent": "#7b8794"},   # Executive (acero suave)
    "back.jpg": {**_BASE, "accent": "#f10a0a"},   # Devil Power
    "back0.jpg": {**_BASE, "accent": "#ffd200"},  # Bannana Cream
    "back1.jpg": {**_BASE, "accent": "#36f715"},  # Acid Jungle
    "back2.jpg": {**_BASE, "accent": "#0314ec"},  # Mizuno Night
    "back3.jpg": {**_BASE, "accent": "#dc12b0"},  # Fresh Squishee
}

#: etiqueta visible → fichero de fondo
THEME_OPTIONS: dict[str, str] = {
    "Executive": "back.png",
    "Devil Power": "back.jpg",
    "Bannana Cream": "back0.jpg",
    "Acid Jungle": "back1.jpg",
    "Mizuno Night": "back2.jpg",
    "Fresh Squishee": "back3.jpg",
}
LABEL_BY_FILE: dict[str, str] = {v: k for k, v in THEME_OPTIONS.items()}

_DEFAULT_FILE = "back.jpg"


def palette_for_background(background_name: str) -> dict[str, str]:
    return dict(THEME_PALETTES.get(background_name, THEME_PALETTES[_DEFAULT_FILE]))


def accent_for_background(background_name: str) -> str:
    return palette_for_background(background_name)["accent"]


def theme_label(background_name: str) -> str:
    return LABEL_BY_FILE.get(background_name, LABEL_BY_FILE[_DEFAULT_FILE])


def background_for_label(label: str) -> str:
    return THEME_OPTIONS.get(label, _DEFAULT_FILE)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))  # type: ignore[return-value]


def cascada_colors(accent: str) -> list[tuple[float, str]]:
    """Paradas del degradado de la cascada para un color de acento (0.0–1.0)."""
    bg_dark = _hex_to_rgb("#0b0f14")
    acc = _hex_to_rgb(accent)
    return [
        (0.0, "#0b0f14"),
        (0.25, "#12171d"),
        (0.45, "#182028"),
        (0.60, "#22313a"),
        (0.72, "#2c4450"),
        (0.82, _rgb_to_hex(_mix(bg_dark, acc, 0.45))),
        (0.90, _rgb_to_hex(_mix(bg_dark, acc, 0.70))),
        (0.96, _rgb_to_hex(_mix(bg_dark, acc, 0.85))),
        (1.0, _rgb_to_hex(_mix(acc, (255, 255, 255), 0.55))),
    ]


#: Degradado fijo estilo "clásico" (el de toda la vida en SDR#/GQRX): negro →
#: azul → cian → verde → amarillo → rojo → blanco. Excepción única del tema
#: Classic: la cascada NO seguiría el plateado del tema (quedaría deslucida),
#: así que aquí ignora el acento y usa siempre este arcoíris fijo.
#: El tramo negro se alarga a propósito hasta el 60%: con ruido de fondo o
#: sin señal (silencio) el nivel normalizado no llega muy arriba, y un
#: arcoíris que arrancara ya en azul/cian a esa altura (como en la primera
#: versión) se veía encendido en color aun sin haber señal real.
CLASSIC_CASCADA_COLORS: list[tuple[float, str]] = [
    (0.00, "#000000"),
    (0.60, "#000000"),
    (0.68, "#00008b"),
    (0.76, "#0000ff"),
    (0.82, "#00ffff"),
    (0.87, "#00ff00"),
    (0.91, "#ffff00"),
    (0.95, "#ff8000"),
    (0.98, "#ff0000"),
    (1.00, "#ffffff"),
]


def cascada_colors_for_background(background_name: str, accent: str) -> list[tuple[float, str]]:
    """Como :func:`cascada_colors`, salvo en Classic (fondo fijo estilo SDR#)."""
    if background_name == "back.png":
        return list(CLASSIC_CASCADA_COLORS)
    return cascada_colors(accent)


__all__ = [
    "CLASSIC_CASCADA_COLORS",
    "LABEL_BY_FILE",
    "THEME_OPTIONS",
    "THEME_PALETTES",
    "accent_for_background",
    "background_for_label",
    "cascada_colors",
    "cascada_colors_for_background",
    "palette_for_background",
    "theme_label",
]
