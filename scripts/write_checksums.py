#!/usr/bin/env python3
"""Genera el manifiesto SHA-256 de los cuatro paquetes de distribución."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    packages = sorted(
        path
        for directory in (ROOT / "dist", *(ROOT / "plugins").glob("*/dist"))
        for path in directory.glob("*")
        if path.suffix == ".whl" or path.name.endswith(".tar.gz")
    )
    if len(packages) != 4:
        raise SystemExit(f"Se esperaban 4 paquetes y se encontraron {len(packages)}")
    lines = [f"{digest(path)}  {path.relative_to(ROOT).as_posix()}" for path in packages]
    output = ROOT / "dist" / "SHA256SUMS"
    output.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"Generado: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
