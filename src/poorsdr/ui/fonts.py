"""Selección de fuentes instaladas para la interfaz.

No se redistribuyen tipografías de procedencia incierta. La única fuente LED
que este proyecto sí redistribuye es DSEG7 Classic (SIL OFL 1.1, ver
``assets/fonts/`` y ``THIRD_PARTY_NOTICES.md``): su licencia permite
explícitamente embeberla en otro software. Otras fuentes "LED" populares
(p. ej. "7LED" de dafont.com) son "gratis solo para uso personal" y por eso
no se instalan — si el usuario ya las tiene puestas por su cuenta, se siguen
detectando y usando igual, pero nunca se copian desde aquí.
"""

from __future__ import annotations

import contextlib
import platform
import shutil
import subprocess
import tkinter.font as tkfont
from pathlib import Path

_FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_DSEG_FAMILY = "DSEG7 Classic"
_DSEG_FILES = (
    "DSEG7Classic-Regular.ttf",
    "DSEG7Classic-Bold.ttf",
    "DSEG7Classic-Italic.ttf",
    "DSEG7Classic-BoldItalic.ttf",
)

_LED_CANDIDATES = (
    "7LED", "DS-Digital", "Digital-7", "Seven Segment", "LCD", "Segment7",
    "DSEG7 Modern", _DSEG_FAMILY, "Segoe UI",
)
_UI_CANDIDATES = ("Orbitron", "Rajdhani", "Exo 2", "Bahnschrift", "Segoe UI", "DejaVu Sans")


def install_led_font() -> str:
    """Copia DSEG7 Classic al directorio de fuentes del usuario si hace
    falta y refresca la caché de fontconfig (Linux). Devuelve el nombre de
    familia si quedó instalada (o ya lo estaba), o ``""`` si no se pudo —
    en ese caso ``led_font_family()`` cae a otro candidato ya instalado o a
    la fuente por defecto de Tk, como si esta función no existiera.

    Solo Linux por ahora: es la plataforma donde se confirmó el problema
    (consola sin fuente LED en una instalación nueva) y donde copiar el
    archivo + `fc-cache` basta. En Windows/macOS no se intenta nada — un
    intento a medias (sin registrar la fuente en el sistema) sería peor que
    no intentarlo, así que se deja para cuando haya forma de probarlo de
    verdad en esas plataformas.
    """
    if platform.system() != "Linux":
        return ""
    target_dir = Path.home() / ".local" / "share" / "fonts" / "poorsdr4all"
    try:
        installed_any = False
        for name in _DSEG_FILES:
            src = _FONTS_DIR / name
            if not src.is_file():
                continue
            dst = target_dir / name
            if dst.is_file() and dst.stat().st_size == src.stat().st_size:
                installed_any = True
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            installed_any = True
        if not installed_any:
            return ""
    except OSError:
        return ""
    if shutil.which("fc-cache"):
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["fc-cache", "-f", str(target_dir)],
                capture_output=True,
                check=False,
                timeout=10,
            )
    return _DSEG_FAMILY


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
    # "detected" (lo que devolvió install_led_font(), casi siempre
    # _DSEG_FAMILY) NO se antepone: si el usuario ya tiene puesta su propia
    # fuente LED (p. ej. "7LED", uso personal legítimo desde antes de que
    # existiera este mecanismo), esa debe seguir ganando. DSEG7 Classic
    # solo entra en juego si nada de _LED_CANDIDATES está ya instalado —
    # exactamente el orden en el que ya aparece en la propia tupla.
    del detected
    return _pick(root, _LED_CANDIDATES)


def ui_font_family(root) -> str:  # type: ignore[no-untyped-def]
    return _pick(root, _UI_CANDIDATES)


__all__ = ["install_led_font", "led_font_family", "ui_font_family"]
