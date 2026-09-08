"""Configuración de pytest: rutas de import compartidas por toda la suite."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "src", _ROOT / "src" / "poorsdr" / "_vendor"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
