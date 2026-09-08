"""Diálogo de "abrir archivo" del **gestor de archivos del sistema**.

En Linux, ``tkinter.filedialog`` dibuja su propio selector (anticuado y ajeno al
escritorio). Aquí se usa el diálogo nativo vía ``kdialog`` (KDE), ``zenity`` /
``qarma`` / ``yad`` (GTK). Si no hay ninguno, :func:`available` devuelve ``False``
y el llamante puede caer en ``tkinter.filedialog``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_KDE = "kde" in (os.environ.get("XDG_CURRENT_DESKTOP", "").lower())


def _tool() -> str | None:
    order = ("kdialog", "zenity", "qarma", "yad") if _KDE else ("zenity", "qarma", "yad", "kdialog")
    for name in order:
        if shutil.which(name):
            return name
    return None


def available() -> bool:
    """¿Hay un diálogo de archivos nativo utilizable?"""
    return _tool() is not None


def _run(cmd: list[str]) -> str | None:
    try:
        proc = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None  # cancelado o error
    out = (proc.stdout or "").strip().splitlines()
    return out[0].strip() if out and out[0].strip() else None


def _kdialog_filter(patterns: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"{globs}|{label}" for label, globs in patterns)


def open_file(
    *,
    title: str = "Elegir archivo",
    patterns: Sequence[tuple[str, str]] = (),
    initial: str | None = None,
) -> str | None:
    """Ruta elegida por el usuario, o ``None`` si cancela / no hay diálogo nativo."""
    tool = _tool()
    if tool is None:
        return None
    start = initial or os.path.expanduser("~")

    if tool == "kdialog":
        cmd = ["kdialog", "--title", title, "--getopenfilename", start]
        if patterns:
            cmd.append(_kdialog_filter(patterns))
        return _run(cmd)

    # zenity / qarma / yad comparten la interfaz de zenity
    cmd = [tool, "--file-selection", f"--title={title}"]
    if initial:
        cmd.append(f"--filename={initial}")
    for label, globs in patterns:
        cmd.append(f"--file-filter={label} | {globs}")
    return _run(cmd)


__all__ = ["available", "open_file"]
