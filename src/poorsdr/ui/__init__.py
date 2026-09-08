"""Interfaz de usuario (Tkinter).

Contiene la aplicación Tk completa, la ventana principal, los paneles de
memorias/cascada, la ventana de ajustes, temas, disposición y atajos. Los
módulos que crean widgets requieren ``tkinter``; este inicializador mantiene
sus importaciones ligeras para que la lógica sin interfaz siga siendo usable.

No se importa ``widgets`` aquí para no exigir ``tkinter`` a quien solo necesita
el tema o el layout.
"""

from __future__ import annotations

from poorsdr.ui import layout, theme

__all__ = ["layout", "theme"]
