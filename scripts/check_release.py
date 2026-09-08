#!/usr/bin/env python3
"""Comprueba que un árbol de release no contenga estado local ni binarios."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv",
    "__pycache__", "build", "dist",
}
FORBIDDEN_SUFFIXES = {".dll", ".dylib", ".pyd", ".pyc", ".pyo", ".so", ".pem", ".sqlite"}
REQUIRED = {
    "LICENSE", "CLA.md", "COMMERCIAL-LICENSE.md", "CONTRIBUTING.md",
    "SECURITY.md", "THIRD_PARTY_NOTICES.md", "scripts/check_owrx_config.py",
    "LICENSES/GPL-3.0-or-later.txt", "LICENSES/AGPL-3.0-or-later.txt",
    "LICENSES/BSD-3-Clause-SpeexDSP.txt", "LICENSES/OFL-1.1-DSEG.txt",
    "LICENSES/GPL-2.0-or-later-makeself.txt",
}


def files() -> list[Path]:
    result: list[Path] = []
    for directory, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS and not name.endswith(".egg-info")]
        result.extend(Path(directory) / name for name in filenames)
    return result


def main() -> int:
    errors: list[str] = []
    private_key_markers = (
        b"-----BEGIN " + b"PRIVATE KEY-----",
        b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    )
    maintainer_home = b"/home/" + b"boss/"
    for required in sorted(REQUIRED):
        if not (ROOT / required).is_file():
            errors.append(f"falta el archivo obligatorio: {required}")

    for path in files():
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"artefacto no distribuible: {relative}")
        if path.stat().st_size > 50 * 1024 * 1024:
            errors.append(f"archivo mayor de 50 MiB: {relative}")
        if path.stat().st_size <= 5 * 1024 * 1024:
            content = path.read_bytes()
            if any(marker in content for marker in private_key_markers):
                errors.append(f"clave privada detectada: {relative}")
            if maintainer_home in content:
                errors.append(f"ruta personal detectada: {relative}")

    if errors:
        print("Release NO válida:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Release válida: sin binarios, claves, estado local ni recursos alterados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
