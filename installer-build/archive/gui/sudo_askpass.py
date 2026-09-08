#!/usr/bin/env python3
"""Ventana gráfica de contraseña usada como SUDO_ASKPASS por el instalador
de PoorSDR4All (ver wizard.py:build_sudo_shim).

sudo -A lanza este script como proceso aparte cada vez que una llamada a
`sudo` dentro de install.sh necesita autenticarse, y espera EXCLUSIVAMENTE
la contraseña por stdout. Por eso aquí no debe imprimirse nada más en
stdout — cualquier mensaje para el usuario va a la propia ventana o, como
mucho, a stderr.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk


def main() -> int:
    root = tk.Tk()
    root.title("Autenticación necesaria")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    result: dict[str, str | None] = {"pw": None}

    frame = tk.Frame(root, padx=24, pady=18)
    frame.pack()

    tk.Label(
        frame,
        justify="left",
        text=(
            "El instalador de PoorSDR4All necesita\n"
            "permisos de administrador para continuar."
        ),
    ).pack(anchor="w", pady=(0, 12))

    tk.Label(frame, text="Contraseña:").pack(anchor="w")
    pw_var = tk.StringVar()
    entry = tk.Entry(frame, textvariable=pw_var, show="*", width=34)
    entry.pack(pady=(2, 14))
    entry.focus_set()

    def accept(_event=None) -> None:
        result["pw"] = pw_var.get()
        root.destroy()

    def cancel(_event=None) -> None:
        result["pw"] = None
        root.destroy()

    entry.bind("<Return>", accept)
    root.bind("<Escape>", cancel)

    buttons = tk.Frame(frame)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Cancelar", command=cancel).pack(side="right", padx=(6, 0))
    ttk.Button(buttons, text="Aceptar", command=accept).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", cancel)
    root.update_idletasks()
    try:
        root.eval("tk::PlaceWindow . center")
    except tk.TclError:
        pass
    root.mainloop()

    if result["pw"] is None:
        return 1
    # Única línea que debe llegar a stdout: la propia contraseña.
    sys.stdout.write(result["pw"] + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
