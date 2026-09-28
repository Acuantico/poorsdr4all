# RTTY Power

Plugin opcional de PoorSDR4All para operar RTTY con el uSDX: decodifica el
audio real de la radio, transmite por macros y ayuda en concursos
(CQ WW RTTY). Añade un botón **RTTY** a la consola; sin el plugin, PoorSDR4All
funciona igual, solo sin ese botón.

**Experimental (alfa).**

## Qué hace

- **Decodificador propio** (45,45 baudios, 170 Hz): FSK no coherente con
  filtros de tono, ATC y validación de bits de arranque/parada. USB y LSB (en
  LSB invierte marca/espacio automáticamente en RX y TX). Casilla **Rev** para
  estaciones con polaridad invertida.
- **Selección por clic** sobre la señal, sin mover la radio (como WSJT-X).
  **AFC** opcional que solo afina la estación elegida (±25 Hz) y no se va a
  otra cuando esa deja de transmitir.
- **Indicativos en color**: trabajados, por trabajar, el actual y los que te
  llaman a ti.
- **Doble clic** sobre el indicativo de quien llama CQ: le contesta. Botón
  **Llamar** para contestar a quien solo manda su indicativo, sin CQ.
- **Continuación automática** del QSO y botón **Responder**, que envía lo que
  toca según la fase del QSO (llamada, reporte, despedida).
- **Concurso CQ WW RTTY**: intercambio con zona CQ (y estado/provincia para
  EE.UU./Canadá), aviso de duplicados por banda y de bandas que no cuentan.
- **Guardar QSO**: lo envía como un "Logged ADIF" de WSJT-X (UDP 2237), que
  NMN1M o cualquier otro libro que escuche ese protocolo importa solo.
- **Filtro (Hz)**: selector del filtro puesto en el uSDX; adapta el panel y el
  ancho del selector de la cascada de OWRX.

## Requisitos

- PoorSDR4All 1.0.0a2 o posterior.
- Radio con CAT y audio configurados en PoorSDR4All (probado con uSDX).

## Instalar

En el mismo entorno de Python que PoorSDR4All, desde esta carpeta:

```sh
python -m pip install .
```

Reinicia PoorSDR4All: aparece el botón **RTTY** en la consola. Se puede
activar o desactivar en Ajustes → **Plugins**.

Pon tu indicativo en Ajustes → Interfaz → **Mi indicativo**; los macros lo
usan (p. ej. `CQ DE EA1ABC EA1ABC`).

## Tests

```sh
python -m pytest tests
```

`scripts/rtty_bench.py` mide la tasa de error del decodificador con señales
sintéticas (ruido, desvanecimiento, desintonía, estación vecina...).

## Licencia

El código propio se distribuye bajo PolyForm Noncommercial 1.0.0. Consulta
`LICENSE` antes de redistribuirlo o utilizarlo con fines comerciales.
