from __future__ import annotations

import importlib.util
from pathlib import Path


def test_openwebrx_template_is_synchronized() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_owrx_config.py"
    spec = importlib.util.spec_from_file_location("check_owrx_config", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.validate() == []
