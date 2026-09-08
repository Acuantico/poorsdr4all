#!/usr/bin/env python3
"""Valida los wheel y sdist construidos antes de publicarlos."""

from __future__ import annotations

import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIRS = (ROOT / "dist", *(ROOT / "plugins").glob("*/dist"))
FORBIDDEN_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".dll", ".dylib", ".pem", ".pyc", ".pyd", ".pyo", ".so", ".sqlite"}
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
)


def archive_members(path: Path) -> dict[str, bytes]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"miembro ZIP corrupto: {bad}")
            return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return {
                member.name: extracted.read()
                for member in archive.getmembers()
                if member.isfile() and (extracted := archive.extractfile(member)) is not None
            }
    raise ValueError("formato no admitido")


def contains_suffix(names: set[str], suffix: str) -> bool:
    return any(name.endswith(suffix) for name in names)


def main() -> int:
    errors: list[str] = []
    archives = sorted(
        path
        for directory in ARCHIVE_DIRS
        for path in directory.glob("*")
        if path.suffix == ".whl" or path.name.endswith(".tar.gz")
    )
    expected_names = {
        "poorsdr4all-1.0.0a1-py3-none-any.whl",
        "poorsdr4all-1.0.0a1.tar.gz",
        "poorsdr_filter_relays-1.0.0a1-py3-none-any.whl",
        "poorsdr_filter_relays-1.0.0a1.tar.gz",
    }
    actual_names = {path.name for path in archives}
    for missing in sorted(expected_names - actual_names):
        errors.append(f"falta el artefacto: {missing}")
    for unexpected in sorted(actual_names - expected_names):
        errors.append(f"artefacto inesperado: {unexpected}")

    checksum_path = ROOT / "dist" / "SHA256SUMS"
    if not checksum_path.is_file():
        errors.append("falta el manifiesto dist/SHA256SUMS")
    else:
        expected_lines = {
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}"
            for path in archives
        }
        actual_lines = set(checksum_path.read_text(encoding="ascii").splitlines())
        if actual_lines != expected_lines:
            errors.append("dist/SHA256SUMS no coincide con los paquetes")

    for path in archives:
        try:
            members = archive_members(path)
        except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError) as error:
            errors.append(f"{path.name}: no se puede leer ({error})")
            continue
        names = set(members)
        for name, content in members.items():
            parts = set(Path(name).parts)
            if parts & FORBIDDEN_PARTS or name.endswith(".egg-info"):
                errors.append(f"{path.name}: estado de desarrollo incluido: {name}")
            if Path(name).suffix.lower() in FORBIDDEN_SUFFIXES:
                errors.append(f"{path.name}: binario o estado local incluido: {name}")
            if any(marker in content for marker in PRIVATE_KEY_MARKERS):
                errors.append(f"{path.name}: clave privada incluida: {name}")

        if path.name.startswith("poorsdr4all-"):
            for required in (
                "poorsdr/ui/assets/images/back.png",
                "LICENSES/AGPL-3.0-or-later.txt",
                "LICENSES/GPL-3.0-or-later.txt",
                "LICENSES/BSD-3-Clause-SpeexDSP.txt",
            ):
                if not contains_suffix(names, required):
                    errors.append(f"{path.name}: falta {required}")
            has_spiderd = any("poorsdr/_vendor/runtime/spiderd/" in name for name in names)
            if path.suffix == ".whl" and has_spiderd:
                errors.append(f"{path.name}: el componente AGPL spiderd debe distribuirse por separado")
            if path.name.endswith(".tar.gz") and not contains_suffix(
                names, "poorsdr/_vendor/runtime/spiderd/LICENSE"
            ):
                errors.append(f"{path.name}: falta la licencia del componente fuente spiderd")
    if errors:
        print("Artefactos NO válidos:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Artefactos válidos: cuatro paquetes íntegros, completos y sin datos privados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
