"""Núcleo funcional puro: lógica sin efectos de IO ni estado global.

- ``core.cat``      — modos, tramas y parsers CAT (Kenwood / TS-480).
- ``core.bands``    — mapa de bandas + inferencia por frecuencia.
- ``core.tuning``   — frecuencia ↔ (MHz, kHz, cHz), parseo, clamp, paso.
- ``core.waterfall``— FFT del audio RX → fila de la cascada.
- ``core.theme``    — paletas de tema y colormap de la cascada.
- ``core.memory``   — modelo y validación de memorias de frecuencia.
- ``core.autocall`` — perfiles de llamada automática.
- ``core.owrx``     — gestión del backend systemd, sync OWRX↔digi, spiderd.
- ``core.smeter``   — dBFS (nivel de OWRX) ↔ unidades de aguja / ángulo del S-metro.

Nada de aquí importa ``poorsdr.services``, ``poorsdr.ui`` ni ``poorsdr._vendor``.
"""
