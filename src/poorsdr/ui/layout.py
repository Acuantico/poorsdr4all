"""Posiciones (``place``) de los controles de la consola.

``LAYOUT_DEFAULTS`` son las de fábrica. Con el botón **EDIT** activo se pueden
arrastrar los controles; al desactivarlo, las posiciones nuevas se guardan en
``~/.config/poorsdr/layout.json`` y :func:`load_overrides` las aplica encima de
las de fábrica en el siguiente arranque.

El botón EDIT es una herramienta de desarrollo (recolocar controles a mano
mientras se ajusta ``LAYOUT_DEFAULTS``): no debe verse en un uso normal, así
que ``DEV_LAYOUT_MODE`` es ``False`` por defecto. Para activarlo y que el
botón EDIT aparezca en la consola, arranca con la variable de entorno
``POORSDR_DEV_LAYOUT=1`` (o ``true``/``yes``/``on``), p. ej.::

    POORSDR_DEV_LAYOUT=1 python -m poorsdr

Ver también ``docs/ARCHITECTURE.md``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEV_LAYOUT_MODE = str(os.environ.get("POORSDR_DEV_LAYOUT", "0") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# BEGIN_LAYOUT_DEFAULTS
LAYOUT_DEFAULTS = {'anr_frame': {'anchor': 'nw', 'x': 17, 'y': 156},
 'auto_call': {'anchor': 'nw', 'x': 196, 'y': 679},
 'band_selector': {'anchor': 'n', 'x': 102, 'y': 591},
 'center_panel': {'anchor': 'nw', 'height': 260, 'width': 190, 'x': 211, 'y': 8},
 'ch_controls': {'anchor': 'nw', 'width': 240, 'x': 188, 'y': 510},
 'digi_button': {'anchor': 'nw', 'x': 193, 'y': 473},
 'edit_check': {'anchor': 'nw', 'x': 110, 'y': 4},
 'external_button': {'anchor': 'nw', 'height': 80, 'width': 110, 'x': 440, 'y': 565},
 'frequency_controls': {'anchor': 'nw', 'x': 147, 'y': 277},
 'ganancia': {'anchor': 'nw', 'x': 29, 'y': 363},
 'log_button': {'anchor': 'nw', 'x': 469, 'y': 666},
 'mem_button': {'anchor': 'nw', 'x': 470, 'y': 705},
 'mode_selector': {'anchor': 'nw', 'x': 453, 'y': 592},
 'owrx_button': {'anchor': 'nw', 'x': 193, 'y': 408},
 'owrx_spots_button': {'anchor': 'nw', 'x': 193, 'y': 440},
 'ptt_button': {'anchor': 'nw', 'height': 80, 'width': 240, 'x': 189, 'y': 566},
 'rx_audio': {'anchor': 'nw', 'x': 310, 'y': 409},
 'settings_button': {'anchor': 'nw', 'x': 510, 'y': 1},
 'smeter': {'anchor': 'nw', 'x': 16, 'y': 86},
 'step_controls': {'anchor': 'nw', 'x': 257, 'y': 355},
 'tone_ptt_button': {'anchor': 'nw', 'x': 145, 'y': 158},
 'volumen': {'anchor': 'nw', 'x': 447, 'y': 364},
 'web_server_button': {'anchor': 'nw', 'x': 2, 'y': 0}}
# END_LAYOUT_DEFAULTS


def _overrides_path() -> Path:
    from poorsdr.infra import paths

    return paths.config_dir() / "layout.json"


def load_overrides() -> dict[str, dict[str, Any]]:
    """Posiciones guardadas por el usuario en modo EDIT (``{}`` si no hay)."""
    try:
        data = json.loads(_overrides_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}


def save_overrides(positions: dict[str, dict[str, Any]]) -> None:
    path = _overrides_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(positions, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        pass


__all__ = ["DEV_LAYOUT_MODE", "LAYOUT_DEFAULTS", "load_overrides", "save_overrides"]
