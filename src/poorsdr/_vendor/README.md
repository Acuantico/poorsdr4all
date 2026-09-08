# `poorsdr/_vendor` — implementaciones de bajo nivel vendorizadas

Módulos de **DSP y protocolo** tomados verbatim del proyecto original y
envueltos por la capa de servicios (`poorsdr/services/`). **No es la API
pública**: los desarrolladores de la comunidad trabajan sobre `poorsdr/`
(config, core, infra, services, ui, viewers, i18n).

## Qué hay aquí y quién lo envuelve

| módulo | envuelto por | qué es |
|--------|--------------|--------|
| `audio.py` (+ `audio_*_domain.py`, `dsp_pipeline.py`, `audio_backend.py`, `audio_remote.py`) | `services/audio.py` | pipeline RX/TX PyAudio, ANR, enrutado SDR |
| `cat.py` | `services/radio.py` | CAT serie (Kenwood/TS-480) |
| `rigctld_proxy.py` | `services/rigctld.py` | servidor proxy hamlib TCP |
| `ts480_emulator.py` | `services/n1m.py` | emulador TS-480 para N1MM |
| `filter_relays_wifi.py` | `services/filter_relays.py` | relés de filtros por HTTP |
| `owrx_client.py` | `services/owrx_client.py` | cliente WebSocket de control OWRX |
| `webserver.py` (+ `webui/`) | `services/web.py` | servidor web remoto FastAPI/WebRTC |
| `paths.py`, `platform_config.py` | deps internas | resolución de rutas y saneado de config |

El puente plano `config.json` se genera en el directorio de datos del usuario,
nunca junto al código instalado. `audio.py` lo lee al arrancar y los visores
vigilan su fecha de modificación para aplicar cambios.

`runtime/spiderd/` deriva del proyecto AGPL `owrx-spider`; contiene su licencia
y procedencia. El resto de `_vendor` procede del código original de
PoorSDR4All y permanece bajo la licencia principal.

## Reglas

- No añadir features aquí. Un cambio de comportamiento se hace en `poorsdr/` o
  reescribiendo el módulo correspondiente y sacándolo de `_vendor`.
- Estos ficheros están excluidos de `ruff` y `mypy` (código portado, estable).
- Los visores se migraron a `poorsdr/viewers/`. El repositorio conserva el
  fuente C del acelerador ADPCM, pero nunca un binario precompilado.
