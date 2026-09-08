"""Lanzamiento de los visores externos (cascada OWRX y panel Digi).

Los visores (``owrx_native.py`` / ``owrx_digi.py``) siguen en ``_vendor`` de
momento; aquí se construyen sus argumentos y entorno con la lógica pura de
:mod:`poorsdr.core.owrx.launch`.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from poorsdr.core.owrx import launch as owrx_launch
from poorsdr.infra import paths
from poorsdr.infra.logging import get_logger
from poorsdr.runtime import VENDOR_CONFIG_PATH, VENDOR_DIR

_SRC_DIR = Path(__file__).resolve().parents[2]
_VIEWERS_DIR = Path(__file__).resolve().parent

if TYPE_CHECKING:
    from poorsdr.config.model import AppConfig

_log = get_logger("viewers")

_DEFAULT_WATERFALL_GEOMETRY = "1912x262+0+789"
_DEFAULT_DIGI_GEOMETRY = "1284x760+0+0"
_GEOMETRY_RE = re.compile(r"(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?")


@dataclass(frozen=True)
class ViewerHandle:
    """Proceso del visor y el puerto local por el que escucha comandos."""

    proc: subprocess.Popen
    command_port: int

    def running(self) -> bool:
        return self.proc.poll() is None

    def terminate(self, *, timeout: float = 2.0) -> None:
        if self.proc.poll() is not None:
            return
        with contextlib.suppress(Exception):
            self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001 - timeout u otro: forzar
            with contextlib.suppress(Exception):
                self.proc.kill()


def _looks_like_geometry(value: str) -> bool:
    return bool(_GEOMETRY_RE.fullmatch((value or "").strip()))


def _size(geometry: str, fallback: tuple[int, int]) -> tuple[int, int]:
    m = _GEOMETRY_RE.match((geometry or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else fallback


def _spawn(
    name: str,
    helper: str,
    url: str,
    geometry: str,
    state_key: str,
    fallback_size: tuple[int, int],
    *,
    control_port: int = 0,
    lang: str = "es",
    display_scale: float | None = None,
) -> ViewerHandle | None:
    helper_path = _VIEWERS_DIR / helper
    if not helper_path.is_file():
        _log.warning("visor %s no encontrado en %s", name, helper_path)
        return None

    width, height = _size(geometry, fallback_size)
    viewer_port = owrx_launch.allocate_loopback_port() or 0
    env = owrx_launch.build_viewer_launcher_env(
        base_env=os.environ.copy(),
        config_path=str(VENDOR_CONFIG_PATH),
        geometry=geometry,
        is_valid_geometry_fn=_looks_like_geometry,
        state_path=str(paths.cache_dir() / f"{state_key}.json"),
    )
    # los visores viven en poorsdr.viewers → hace falta src en el path
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_SRC_DIR}{os.pathsep}{existing}" if existing else str(_SRC_DIR)
    env["POORSDR_UI_LANG"] = str(lang or "es")
    # waterfall.py ya sabe reescalar todo su contenido (fuentes, tamanos
    # minimos...) segun POORSDR_DISPLAY_SCALE — pensado en su dia para
    # Raspberry Pi, pero sirve igual para cualquier pantalla pequena: se le
    # pasa el mismo factor que ya calculo MainWindow para la consola, en
    # vez de dejar que se quede siempre en 1.0 (su valor por defecto si
    # nadie fija la variable).
    if display_scale is not None:
        env["POORSDR_DISPLAY_SCALE"] = str(display_scale)
    args = owrx_launch.build_viewer_launch_args(
        helper_python=sys.executable,
        helper_path=str(helper_path),
        url=url,
        width=width,
        height=height,
        viewer_port=viewer_port,
        control_host="127.0.0.1",
        control_port=control_port or None,
    )
    _log.info("lanzando visor %s (command_port=%s, control_port=%s)", name, viewer_port, control_port)
    try:
        proc = subprocess.Popen(  # noqa: S603
            args, cwd=str(VENDOR_DIR), env=env, start_new_session=True
        )
    except Exception:  # noqa: BLE001
        _log.exception("no se pudo lanzar el visor %s", name)
        return None
    return ViewerHandle(proc=proc, command_port=viewer_port)


def _owrx_url(cfg: AppConfig) -> str:
    host = (cfg.owrx.host or "127.0.0.1").strip()
    return f"http://{host}:{int(cfg.owrx.port)}/"


def open_waterfall(
    cfg: AppConfig,
    *,
    control_port: int = 0,
    default_geometry: str | None = None,
    display_scale: float | None = None,
) -> ViewerHandle | None:
    # cfg.ui.owrx_window_geometry es donde queda la posicion/tamano una vez
    # que el usuario ha movido o redimensionado la ventana de la cascada a
    # mano — a partir de ahi, se respeta siempre. Solo la PRIMERA vez (sin
    # nada guardado todavia) hace falta un valor por defecto, y ahi
    # "1912x262+0+789" (pensado para una pantalla de referencia bastante
    # ancha) se sale literalmente de cualquier pantalla mas pequena —
    # confirmado en real en un portatil de 1366x768, donde ni siquiera
    # llegaba a verse. `default_geometry`, si se pasa, sustituye a ese
    # valor fijo por uno calculado en el momento a partir de la pantalla y
    # la ventana de la consola real (ver MainWindow._waterfall_geometry_hint).
    geom = cfg.ui.owrx_window_geometry.strip() or default_geometry or _DEFAULT_WATERFALL_GEOMETRY
    return _spawn(
        "cascada", "waterfall.py", _owrx_url(cfg), geom, "waterfall_state",
        (1912, 262), control_port=control_port, lang=cfg.ui.language,
        display_scale=display_scale,
    )


def open_digi(cfg: AppConfig, *, control_port: int = 0) -> ViewerHandle | None:
    geom = cfg.ui.digi_window_geometry.strip() or _DEFAULT_DIGI_GEOMETRY
    return _spawn(
        "digi", "digi.py", _owrx_url(cfg), geom, "digi_state",
        (1284, 760), control_port=control_port, lang=cfg.ui.language,
    )


__all__ = ["ViewerHandle", "open_digi", "open_waterfall"]
