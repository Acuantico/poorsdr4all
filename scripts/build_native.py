#!/usr/bin/env python3
"""Compila el acelerador ADPCM opcional para la plataforma actual.

La aplicación conserva una implementación Python funcional, por lo que un
compilador ausente no impide ejecutar PoorSDR4All. Este script no descarga ni
incorpora código de terceros.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "poorsdr" / "_vendor" / "native" / "fft_adpcm.c"


def default_output_dir() -> Path:
    configured = os.environ.get("POORSDR_RUNTIME_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "poorsdr" / "runtime"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "poorsdr" / "runtime"


def output_name() -> str:
    if sys.platform.startswith("win"):
        return "poorsdr_fft_adpcm.dll"
    if sys.platform == "darwin":
        return "libpoorsdr_fft_adpcm.dylib"
    return "libpoorsdr_fft_adpcm.so"


def compiler() -> list[str]:
    configured = os.environ.get("CC", "").strip()
    if configured:
        return shlex.split(configured)
    candidates = ("cl", "clang", "gcc", "cc") if os.name == "nt" else ("cc", "clang", "gcc")
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return [found]
    raise SystemExit("No se encontró un compilador C. Instala MSVC/Build Tools, clang o gcc.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir(),
        help="directorio de destino (por defecto, el directorio de datos del usuario)",
    )
    args = parser.parse_args()
    cc = compiler()
    output_dir = args.output_dir.expanduser().resolve()
    output = output_dir / output_name()
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = Path(cc[0]).name.lower()
    with tempfile.TemporaryDirectory(prefix="poorsdr-native-") as build_dir:
        if executable in {"cl", "cl.exe"}:
            command = [*cc, "/nologo", "/O2", "/LD", str(SOURCE), f"/Fe:{output}"]
        elif sys.platform == "darwin":
            command = [*cc, "-O3", "-dynamiclib", str(SOURCE), "-o", str(output)]
        elif sys.platform.startswith("win"):
            # clang o gcc en Windows (p. ej. MSVC Build Tools no encontrado,
            # o un clang de LLVM con destino MSVC): "-fPIC" no significa nada
            # en PE/COFF (el código ya es reubicable sin esa opción) y clang
            # con destino MSVC directamente la rechaza como no soportada.
            command = [*cc, "-O3", "-shared", str(SOURCE), "-o", str(output)]
        else:
            command = [*cc, "-O3", "-fPIC", "-shared", str(SOURCE), "-o", str(output)]
        subprocess.run(command, cwd=build_dir, check=True)
    print(f"Generado: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
