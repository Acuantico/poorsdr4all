"""Tests de los módulos vendorizados en ``poorsdr._vendor``.

Prueban la lógica de bajo nivel (dominios de audio, relés, visores) tal cual se
distribuye. Al importar este paquete se añaden ``src`` y ``src/poorsdr/_vendor``
a ``sys.path`` para que resuelvan tanto ``import audio_config_domain`` como
``import poorsdr...``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT / "src" / "poorsdr" / "_vendor"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
