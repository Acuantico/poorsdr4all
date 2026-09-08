"""
Utility helpers to locate application resources in both frozen (PyInstaller)
and normal Python execution modes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _frozen_base() -> Path:
    """Return the base directory when running from a frozen bundle."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(sys.executable).resolve().parent


def _script_base() -> Path:
    """Return the project directory when running from source."""
    return Path(__file__).resolve().parent


def resource_path(*relative: str) -> Path:
    """
    Resolve a resource path. When frozen, resources live alongside the bundled
    executable; otherwise they are relative to this file.
    """
    base = _frozen_base() if getattr(sys, "frozen", False) else _script_base()
    if not relative:
        return base
    return base.joinpath(*relative).resolve()


def runtime_path(*relative: str) -> Path:
    """
    Resolve a writable path for runtime data (config, logs, etc.).
    When frozen we use the executable directory, otherwise the project root.
    """
    configured = os.environ.get("POORSDR_RUNTIME_DIR", "").strip()
    if configured:
        base = Path(configured).expanduser()
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        base = root / "poorsdr" / "runtime"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        base = root / "poorsdr" / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    if not relative:
        return base
    return base.joinpath(*relative).resolve()


def ensure_directory(path_like: str | Path) -> Path:
    """
    Ensure the directory for the given path exists.
    Accepts both directory paths and file paths.
    """
    path = Path(path_like)
    directory = path if path.suffix == "" else path.parent
    directory.mkdir(parents=True, exist_ok=True)
    return directory
