"""Lógica pura de OWRX.

- ``backend`` — gestión del servicio systemd ``openwebrx.service`` (funciones puras).
- ``process`` — sincronización OWRX↔digi, ventanas de bloqueo, parsing de tune…
  (portado de ``_legacy/gui_app/owrx_process_domain``).
- ``state``   — rutas y geometría de ventanas de los visores
  (portado de ``owrx_state_domain``).
- ``launch``  — construcción de args/entorno y lanzamiento de los visores
  (portado de ``owrx_launch_domain``).
- ``spiderd`` — render del INI de ``spiderd.conf`` (portado de ``spiderd_domain``).

El código heredado sigue importándolos vía ``gui_app.owrx_*_domain`` (shims).
"""

from __future__ import annotations

from poorsdr.core.owrx import backend, launch, process, spiderd, state

__all__ = ["backend", "launch", "process", "spiderd", "state"]
