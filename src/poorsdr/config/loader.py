"""Carga y guardado de la configuración del usuario.

- ``load()``  → :class:`AppConfig` desde ``~/.config/poorsdr/config.json``,
  creándolo por migración del ``config.json`` legacy en el primer arranque.
- ``save(cfg)`` → escribe el formato nuevo anidado (``schema_version``).
- ``export_legacy(cfg, path)`` → vuelca el dict plano legacy (red de seguridad).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from poorsdr.config import migrate
from poorsdr.config.model import AppConfig
from poorsdr.infra import paths
from poorsdr.infra.logging import get_logger

_log = get_logger("config")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        _log.error("no se pudo leer %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        _log.error("%s no contiene un objeto JSON", path)
        return None
    return data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    paths.ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def bootstrap(path: Path | None = None) -> AppConfig:
    """Devuelve la config del usuario, creándola si aún no existe.

    Orden de resolución:
    1. ``~/.config/poorsdr/config.json`` si existe.
    2. Si no, migra ``~/Apps/PoorSDR4/config.json`` (legacy) y lo guarda en (1).
    3. Si tampoco, defaults.
    """
    target = path or paths.config_file()

    data = _read_json(target)
    if data is not None:
        cfg = migrate.load_any(data)
        if not migrate.is_native(data):
            _log.info("config en formato legacy; reescribiendo %s en formato nuevo", target)
            save(cfg, target)
        return cfg

    legacy = _read_json(paths.legacy_config_file())
    if legacy is not None:
        _log.info("primer arranque: importando config desde %s", paths.legacy_config_file())
        cfg = migrate.from_legacy(legacy)
        save(cfg, target)
        return cfg

    _log.info("sin config previa; usando valores por defecto (%s)", target)
    cfg = AppConfig()
    save(cfg, target)
    return cfg


def load(path: Path | None = None) -> AppConfig:
    """Carga la config existente; si no hay ninguna, arranca la de por defecto."""
    return bootstrap(path)


def save(cfg: AppConfig, path: Path | None = None) -> Path:
    """Escribe ``cfg`` en formato nuevo anidado de forma atómica."""
    target = path or paths.config_file()
    _atomic_write_json(target, migrate.to_native(cfg))
    return target


def export_legacy(cfg: AppConfig, path: Path) -> Path:
    """Vuelca el dict plano legacy (compatibilidad / depuración)."""
    _atomic_write_json(path, cfg.to_legacy())
    return path


__all__ = ["bootstrap", "export_legacy", "load", "save"]
