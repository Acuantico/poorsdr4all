"""Rutas estándar de la aplicación siguiendo la XDG Base Directory Spec.

Una sola fuente de verdad para dónde viven la configuración, los datos y la
caché de PoorSDR4All. El proyecto original resolvía todo relativo al directorio
del script (``paths.runtime_path``), lo que mezclaba código, config y logs de
runtime en la misma carpeta.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "poorsdr"

# Ruta del proyecto PoorSDR original, del que se importa la config en el primer
# arranque. Se puede sobreescribir con ``POORSDR_LEGACY_HOME``.
LEGACY_HOME = Path(
    os.environ.get("POORSDR_LEGACY_HOME", Path.home() / "Apps" / "PoorSDR4")
).expanduser()


def _xdg(env_var: str, default: Path) -> Path:
    raw = os.environ.get(env_var)
    base = Path(raw).expanduser() if raw else default
    return base / APP_NAME


def _windows_base(env_var: str, fallback: Path) -> Path:
    raw = os.environ.get(env_var)
    return Path(raw).expanduser() if raw else fallback


def config_dir() -> Path:
    """``$XDG_CONFIG_HOME/poorsdr`` (por defecto ``~/.config/poorsdr``)."""
    if os.name == "nt":
        return _windows_base("APPDATA", Path.home() / "AppData" / "Roaming") / APP_NAME
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config")


def data_dir() -> Path:
    """``$XDG_DATA_HOME/poorsdr`` (por defecto ``~/.local/share/poorsdr``)."""
    if os.name == "nt":
        return _windows_base("LOCALAPPDATA", Path.home() / "AppData" / "Local") / APP_NAME
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")


def cache_dir() -> Path:
    """``$XDG_CACHE_HOME/poorsdr`` (por defecto ``~/.cache/poorsdr``)."""
    if os.name == "nt":
        return data_dir() / "cache"
    return _xdg("XDG_CACHE_HOME", Path.home() / ".cache")


def runtime_dir() -> Path:
    """Datos temporales de compatibilidad, siempre fuera del paquete instalado."""
    return data_dir() / "runtime"


def log_dir() -> Path:
    """Directorio de logs rotativos."""
    return data_dir() / "logs"


def config_file() -> Path:
    """Ruta del ``config.json`` nativo del usuario."""
    return config_dir() / "config.json"


def legacy_config_file() -> Path:
    """``config.json`` del proyecto PoorSDR original (solo lectura)."""
    return LEGACY_HOME / "config.json"


def ensure_dir(path: Path) -> Path:
    """Crea ``path`` (y padres) si no existe y lo devuelve."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_runtime_dirs() -> None:
    """Crea config/data/cache/logs de una vez, al arrancar."""
    for factory in (config_dir, data_dir, cache_dir, log_dir, runtime_dir):
        ensure_dir(factory())


__all__ = [
    "APP_NAME",
    "LEGACY_HOME",
    "cache_dir",
    "config_dir",
    "config_file",
    "data_dir",
    "ensure_dir",
    "ensure_runtime_dirs",
    "legacy_config_file",
    "log_dir",
    "runtime_dir",
]
