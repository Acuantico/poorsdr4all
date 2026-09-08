from __future__ import annotations

from typing import Callable

import json
import os


def owrx_state_path(runtime_path_fn: Callable[[str], str]) -> str:
    return str(runtime_path_fn("waterfall_state.json"))


def digi_state_path(runtime_path_fn: Callable[[str], str]) -> str:
    return str(runtime_path_fn("digi_state.json"))


def load_state_geometry(
    *,
    path: str,
    is_valid_geometry_fn: Callable[[str], bool],
    isfile_fn: Callable[[str], bool] = os.path.isfile,
    open_fn=open,
    json_load_fn: Callable[..., object] = json.load,
) -> str:
    try:
        if not isfile_fn(path):
            return ""
        with open_fn(path, "r", encoding="utf-8-sig") as handle:
            data = json_load_fn(handle)
        if not isinstance(data, dict):
            return ""
        w = int(data.get("width", 0) or 0)
        h = int(data.get("height", 0) or 0)
        x = data.get("x", None)
        y = data.get("y", None)
        if w <= 0 or h <= 0 or x in (None, "") or y in (None, ""):
            return ""
        geom = f"{w}x{h}+{int(x)}+{int(y)}"
        return geom if is_valid_geometry_fn(geom) else ""
    except Exception:
        return ""


def sync_geometry_to_config(
    *,
    config: dict,
    config_key: str,
    load_geometry_fn: Callable[[], str],
    save_config_fn: Callable[[], None],
) -> None:
    geom = load_geometry_fn()
    if not geom:
        return
    if str(config.get(config_key, "") or "").strip() == geom:
        return
    config[config_key] = geom
    save_config_fn()


def resolve_window_geometry(
    *,
    config_geometry: str,
    state_geometry: str,
    is_valid_geometry_fn: Callable[[str], bool],
    sanitize_geometry_fn: Callable[[str], str],
    anchor_geometry_fn: Callable[[], str],
) -> tuple[str, bool]:
    base = str(config_geometry or "").strip()
    from_state = False
    if is_valid_geometry_fn(str(state_geometry or "").strip()):
        base = str(state_geometry or "").strip()
        from_state = True
    resolved = sanitize_geometry_fn(base) or anchor_geometry_fn()
    return str(resolved or ""), from_state
