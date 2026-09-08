from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from paths import runtime_path
from platform_config import load_platform_config


def get_config_path() -> str:
    return str(runtime_path("config.json"))


def load_runtime_config() -> tuple[Path, dict]:
    config_file = runtime_path("config.json")
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config = load_platform_config(config_file, persist=True)
    if not isinstance(config, dict):
        config = {}
    return config_file, config


def persist_runtime_config(
    config_file: Path,
    config: dict,
    *,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    try:
        with open(config_file, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=4, ensure_ascii=False)
    except Exception as exc:
        if on_error:
            on_error(exc)


def as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)


def clamp(value: float, minimo: float, maximo: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return minimo
    return max(minimo, min(maximo, value))


def normalize_anr_config(
    config: dict,
    *,
    persist_callback: Callable[[], None],
    on_error: Callable[[Exception], None] | None = None,
) -> bool:
    """
    Keep legacy ANR_* keys and DSPFilters in sync.
    Returns True when config was changed.
    """
    try:
        filtros = config.get("DSPFilters")
        if not isinstance(filtros, dict):
            return False
        anr = filtros.get("anr")
        if not isinstance(anr, dict):
            return False

        enabled = anr.get("enabled")
        intensity = anr.get("intensity")
        changed = False

        enabled_bool = as_bool(enabled, default=True)
        if enabled is not None and config.get("ANR_Enabled") != enabled_bool:
            config["ANR_Enabled"] = enabled_bool
            changed = True

        if intensity is not None:
            try:
                intensity_int = max(1, min(10, int(intensity)))
            except (TypeError, ValueError):
                intensity_int = None
            if intensity_int is not None and config.get("ANR_Intensity") != intensity_int:
                config["ANR_Intensity"] = intensity_int
                changed = True

        if changed:
            persist_callback()
        return changed
    except Exception as exc:
        if on_error:
            on_error(exc)
        return False
