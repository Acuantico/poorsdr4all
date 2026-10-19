"""Selección de fuentes instaladas para la interfaz.

La fuente LED del frecuencímetro es «7LED» y va incluida en el paquete
(``assets/fonts/7LED.ttf``) sin modificar y acompañada de su ``readme.txt``
original. Según ese readme del autor la fuente es *freeware*: puede distribuirse
a quien se quiera siempre que el readme la acompañe, y se pide no modificarla ni
cambiarle el nombre (ver ``THIRD_PARTY_NOTICES.md``). Por eso hay que conservar
ambos ficheros juntos.

``install_led_font()`` la deja visible para la consola al arrancar: en Linux la
copia al directorio de fuentes del usuario; en Windows la registra solo para este
proceso (``AddFontResourceExW`` con ``FR_PRIVATE``: no toca el sistema ni pide
permisos de administrador). Si no estuviera, ``led_font_family()`` usa otra
fuente de estilo LED/LCD ya instalada o la fuente normal de la interfaz.
"""

from __future__ import annotations

import contextlib
import platform
import shutil
import subprocess
import tkinter.font as tkfont
from pathlib import Path

_FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_LED_FAMILY = "7LED"
#: La fuente y su readme (la licencia del autor exige que viajen juntos).
_LED_FILES = ("7LED.ttf", "7LED-readme.txt")
_FR_PRIVATE = 0x10

_LED_CANDIDATES = (
    _LED_FAMILY, "DS-Digital", "Digital-7", "Seven Segment", "LCD", "Segment7",
    "Segoe UI",
)
_UI_CANDIDATES = ("Orbitron", "Rajdhani", "Exo 2", "Bahnschrift", "Segoe UI", "DejaVu Sans")


def _register_windows(ttf: Path) -> bool:
    """Registra la fuente solo para este proceso (visible para Tk y GDI)."""
    try:
        import ctypes

        return bool(ctypes.windll.gdi32.AddFontResourceExW(str(ttf), _FR_PRIVATE, 0))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def _install_linux(src_dir: Path) -> bool:
    target_dir = Path.home() / ".local" / "share" / "fonts" / "poorsdr4all"
    try:
        for name in _LED_FILES:
            src = src_dir / name
            if not src.is_file():
                return False
            dst = target_dir / name
            if dst.is_file() and dst.stat().st_size == src.stat().st_size:
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    except OSError:
        return False
    if shutil.which("fc-cache"):
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(["fc-cache", "-f", str(target_dir)], capture_output=True, check=False, timeout=10)
    return True


def install_led_font() -> str:
    """Deja visible la fuente 7LED del paquete. Devuelve su familia, o ``""`` si no se pudo
    (en ese caso ``led_font_family()`` cae a otro candidato ya instalado)."""
    ttf = _FONTS_DIR / _LED_FILES[0]
    if not ttf.is_file():
        return ""
    system = platform.system()
    if system == "Windows":
        return _LED_FAMILY if _register_windows(ttf) else ""
    if system == "Linux":
        return _LED_FAMILY if _install_linux(_FONTS_DIR) else ""
    return ""


def _pick(root, candidates: tuple[str, ...], fallback: str = "Segoe UI") -> str:  # type: ignore[no-untyped-def]
    try:
        available = {name.lower() for name in tkfont.families(root)}
    except Exception:  # noqa: BLE001
        return fallback
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


def led_font_family(root, detected: str = "") -> str:  # type: ignore[no-untyped-def]
    # «7LED» va siempre primera (es la fuente del frecuencímetro); ``detected`` no se antepone
    # a nada: si el usuario ya la tenía instalada por su cuenta, es la misma.
    del detected
    return _pick(root, _LED_CANDIDATES)


def ui_font_family(root) -> str:  # type: ignore[no-untyped-def]
    return _pick(root, _UI_CANDIDATES)


__all__ = ["install_led_font", "led_font_family", "ui_font_family"]
