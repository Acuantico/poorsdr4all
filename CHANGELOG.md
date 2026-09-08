# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).

## [1.0.0a1] — Alpha inicial

Punto de partida del proyecto: una consola completa para transceptores de la
familia uSDX (CAT, audio, cascada, spots/clúster, servidor web, OpenWebRX+),
organizada en un paquete limpio y distribuible.

### Arquitectura

- **`poorsdr/infra`** — rutas XDG, logging rotativo único, `EventBus` pub/sub.
- **`poorsdr/config`** — modelo tipado (dataclasses frozen anidadas) con
  migración transparente de configuraciones antiguas.
- **`poorsdr/core`** — lógica pura y testeada: `cat` (modos/tramas/parsers y
  perfiles de radio para adaptar baudrate/PTT a variantes de la familia uSDX),
  `bands`, `tuning`, `waterfall`, `theme`, `memory`, `autocall`,
  `owrx` (backend systemd, sync, spiderd).
- **`poorsdr/services`** — 12 servicios con `start`/`stop`/`reconfigure` que
  envuelven el hardware y los procesos externos, comunicándose por el bus:
  `radio`, `audio`, `rigctld`, `n1m`, `filter-relays`, `autocall`,
  `owrx-backend`, `owrx-client`, `owrx-control`, `spiderd`, `web`, `memory`.
  Fábricas inyectables → tests sin hardware.
- **`poorsdr/ui`** — Tkinter fino. `main_window` implementa la consola
  (layout fijo, selección de fuente digital del sistema, `DialControl`,
  cascada embebida con el colormap del tema); `settings/` genera la ventana
  de Ajustes por pestañas desde datos y guarda con hot-apply; `panels/` idem.
- **`poorsdr/viewers`** — `waterfall.py` / `digi.py` (GTK) + `launcher.py`.
- **`poorsdr/runtime`** — composition root (`AppContext` = bus + config +
  `ServiceManager`).
- **`poorsdr/_vendor`** — DSP de audio, `webserver.py`, `rigctld_proxy.py`,
  `cat.py`, `ts480_emulator.py`, `owrx_client.py`… No es API pública (ver su
  README).

### Comportamiento

- Consola (`python -m poorsdr`) con cascada embebida siguiendo la señal, 6
  temas seleccionables que tiñen consola y cascada (Executive, Devil Power,
  Bannana Cream, Acid Jungle, Mizuno Night, Fresh Squishee), cierre limpio
  (mata cascada/Digi y para `openwebrx.service`). La consola se reescala
  automáticamente a pantallas más pequeñas que su diseño de referencia,
  sin recortarse ni desordenarse. El
  frecuencímetro usa DSEG7 Classic (`OFL-1.1`, ver `THIRD_PARTY_NOTICES.md`)
  para el estilo de dígitos LED — se instala sola la primera vez que se
  arranca en Linux, sin depender de que el usuario tenga ya alguna fuente
  de ese estilo puesta. Si ya hay una fuente LED instalada por el usuario
  (p. ej. una de uso personal, puesta por su cuenta), esa se sigue
  prefiriendo sin tocarla — y por defecto se instala 7LED (dafont.com,
  descargada directo de su fuente oficial en el momento de instalar, no
  distribuida por este proyecto). La ventana de la cascada también se
  calcula a lo ancho de la pantalla real, acoplada justo debajo de la
  consola, y su contenido interno se reescala con el mismo factor que la
  consola, en vez de a un tamaño fijo pensado para una única pantalla de
  referencia — conservando siempre la barra de título y los bordes de
  redimensionado normales, para poder ajustarla a mano en cualquier
  escritorio corriente.
- Modos AM, FM, USB, LSB y CW seleccionables en la consola; en OpenWebRX+
  el modo CW usa un filtro de paso estrecho (300-700 Hz) en vez del de
  fonía/AM/FM.
- CAT: perfiles de radio (`custom` por defecto, `generic-ts480`,
  `trusdx-115200`) seleccionables en Ajustes → Radio/CAT; PTT siempre por
  CAT (`TX;`/`RX;`).
- Servidor web remoto (WebRTC): selector de banda con las diez bandas de la
  consola y estado de conexión de la radio reflejados de verdad en el panel;
  el PTT arma la radio en remoto aunque el navegador no consiga capturar el
  micrófono (permiso denegado, sin HTTPS/localhost…), avisando bajo el botón
  en vez de fallar en silencio.
- Los sliders de volumen y el ANR del panel web responden al instante; el
  ANR activado desde el panel queda sincronizado con la consola de
  escritorio y viceversa. El volumen del panel web es ahora la ganancia
  real del audio que viaja por WebRTC, independiente del dial de volumen
  de la consola (que solo afecta a la ruta de audio local del PC): las dos
  rutas son independientes a propósito, y el volumen del panel web no se
  sincroniza con el dial de la consola.
- El audio por WebRTC (enviar/recibir voz desde el navegador) requiere
  `pyopenssl>=26.0` — versiones anteriores rompen al negociar con
  `cryptography` reciente.
- Si la conexión de audio se cae en mitad de una sesión (red inestable,
  cambio de red del móvil...), el panel lo detecta y reconecta solo en vez
  de quedarse mudo sin avisar; solo hay que reconectar a mano si el propio
  aviso de "reconectando" bajo el botón de audio lo indica.
- El botón **WEB** de la consola ya no se puede quedar mostrando "ON" si el
  servidor no arrancó de verdad (contraseña sin configurar, puerto
  ocupado, fallo al arrancar…): ahora siempre refleja el estado real.
- El audio RX del panel web ya no suena a pulsos (partes con sonido y
  huecos de silencio intercalados), ni arrastra un retraso creciente
  frente al audio real ("relentizado" en el navegador mientras la consola
  suena bien a la vez): el envío de audio hacia el navegador respeta un
  ritmo de reloj real de 20 ms por fotograma, y el buffer interno recorta
  el backlog acumulado en vez de tolerarlo hasta un tope alto.
- Los huecos de audio que aún puedan darse (jitter normal de captura, o el
  propio PTT) ya no suenan a chasquido/petardeo: la transición a silencio
  y la vuelta a audio real llevan una rampa corta en vez de saltar en
  seco.
- Dos conexiones remotas a la vez (el mismo operador desde el móvil y el
  escritorio, por ejemplo) ya no se reparten mal el audio entre sí: cada
  una tiene su propia cola independiente en vez de competir por un único
  buffer pensado para un solo oyente.
- Soltar el PTT (TX a RX) ya no se nota lento ni con cortes: la
  confirmación de la radio por CAT (una lectura de puerto serie que tarda
  ~60 ms) ya no bloquea el envío de audio mientras espera, así que el
  cambio de sentido se oye instantáneo. Tampoco se oyen ya varios cortes
  seguidos ("pa, pa, pa") justo al salir de PTT: se confirma que el flujo
  está estable antes de servirlo, en vez de alternar entre silencio y
  audio real cada vez que llega un chunk suelto.
- El AGC de RX ya no recorta en seco los picos puntuales por encima de la
  media (voz con crest factor alto, típico de SSB) — un limitador de
  picos evita la distorsión que eso producía sin cambiar cómo suena el
  audio normal.
- El búfer que se le pide a PulseAudio para la captura de radio en modo
  remoto es ahora más corto (no hay monitor local que proteger en este
  modo, solo la cola propia de cada oyente conectado), así que las
  primeras muestras reales tras soltar PTT llegan antes.
- El selector de **Paso** del panel web ya funciona y está sincronizado de
  verdad con la consola: cambiarlo desde cualquiera de las dos interfaces
  se refleja también en la otra, igual que ya pasa con la frecuencia, el
  modo o el PTT.
- El botón **EDIT** de la consola (recolocar controles a mano) es una
  herramienta de desarrollo y está oculto por defecto; se activa arrancando
  con `POORSDR_DEV_LAYOUT=1` (ver `docs/ARCHITECTURE.md`).
- ANR/AGC de audio ajustados en todo el rango de intensidad (1-10), sin
  saturación ni parpadeo de ganancia.
- OWRX: cambio de banda → perfil SDR al visor; clic en la cascada → sintonía
  inversa a la consola; audio SDR por `owrx-control`. La plantilla inicial de
  OpenWebRX+ (`assets/owrx/settings.json`) es una configuración neutra y
  comprobable con las diez bandas exactas de la consola —
  `scripts/check_owrx_config.py` la valida contra el propio código en CI y en
  la instalación—; el supuesto de hardware (RTL-SDR clásico con muestreo
  directo) y qué ajustar para un RTL-SDR V4 o un upconverter están en
  `assets/owrx/README.md`. La cascada embebida de la consola (FFT y
  redibujado a ~30 Hz) solo consume CPU mientras el visor de OWRX está
  realmente abierto, no todo el rato que la consola está en marcha.
- S-metro: por defecto se autocalibra (el suelo de ruido de la banda se ve
  en una unidad S configurable — S5 por defecto, ajustable en Ajustes →
  OWRX al QRM ambiente real de cada estación, que no es el mismo en todas
  partes — sin lectura absoluta, no hay forma de calibrar sin conocer la
  ganancia real del SDR). Ajustes → OWRX permite en cambio fijar una
  calibración real: mide con una referencia conocida (generador de señales,
  emisora de potencia conocida...) con la ganancia del SDR fija, y activa
  "S-metro calibrado" con el dBFS medido como S9.
- Guardar Ajustes aplica en caliente vía `ServiceManager.reconfigure_all`.
- Interfaz traducida por completo en 12 idiomas — español, inglés, francés,
  alemán, italiano y portugués con revisión cuidada; turco, polaco, ruso,
  gallego, catalán y euskera como mejor esfuerzo, sin revisión de hablante
  nativo —, tanto en la ventana de Ajustes (etiquetas y ayuda contextual al
  pasar el ratón sobre cada campo) como en la consola principal y los
  visores externos de cascada/Digi. La consola tiene tamaño fijo y botones
  de ancho fijo en caracteres, así que sus etiquetas más cortas (Ajustes,
  Mem, PTT, MODE, BAND, MHz, kHz…) se mantienen iguales en todos los idiomas
  y en su lugar llevan un tooltip traducido; los diálogos sin esa
  restricción (menú de Spots, panel de Memorias, avisos y visores) se
  traducen enteros. Quedan sin traducir, a propósito: las palabras
  «entrada»/«salida» de los combos de audio, el nombre que cada plugin
  declara de sí mismo, y el texto de agradecimiento personal del panel
  «Acerca de», que se muestra siempre en español.

### Distribución

- `pyproject.toml` (hatchling) con entry points `poorsdr`, `poorsdr-waterfall`,
  `poorsdr-digi`; `ruff` + `mypy` + `pytest` configurados. El acelerador C se
  compila antes de la suite de pruebas, tanto en local como en CI, para que
  el decodificador nativo quede realmente probado.
- `scripts/install.sh` detecta Debian/Arch por `/etc/os-release` (soporta
  Raspberry Pi OS 64-bit); Windows dispone de instalación Python experimental.
  En Arch sincroniza el sistema completo (`pacman -Syu`) antes de instalar
  nada (evita una actualización parcial, la causa más común de que un
  sistema Arch quede inutilizable al instalar un paquete), reordena antes
  la lista de mirrors por velocidad real (con tope de 60s, para no
  bloquearse si hay muchos mirrors candidatos) y reintenta ante fallos de
  red pasajeros; instala OpenWebRX+/pycsdr en un entorno virtual propio
  (`/opt/poorsdr4-owrx/venv`), sin escribir nunca sobre el Python del
  sistema, y corrige los permisos de todo lo que instala bajo
  `/usr/local` y del propio venv para que sean legibles independientemente
  del umask de la sesión de sudo del equipo; el venv incluye `setuptools`/
  `wheel` (ya no vienen de serie en `python3 -m venv` desde Python 3.12),
  necesarios para compilar `pycsdr` con `--no-build-isolation`. También
  descarga por defecto la fuente "7LED" directo desde dafont.com (uso
  personal; nunca se distribuye una copia con el proyecto) —
  desactivable con `INSTALL_7LED_FONT=0`.
- Instalador gráfico (`.run` autoextraíble) que orquesta `install.sh` con
  una interfaz Tkinter; al terminar crea el icono y el acceso en el menú
  de aplicaciones (`~/.local/share/applications`), forzando el refresco
  de la caché de KDE/genérica para que aparezca sin tener que reiniciar
  sesión.
- Más de 400 pruebas automatizadas, `ruff` y `mypy`.
- Distribuciones fuente sin claves, configuraciones, bases de datos ni
  binarios locales; acelerador C compilable en Linux, macOS y Windows.
- Licencias y revisiones de OpenWebRX+, csdr, pycsdr, owrx_connector,
  owrx-spider y SpeexDSP documentadas.
- **Nunca Más, Ni Una Más (NMN1M)**, el libro de guardia, es un proyecto
  independiente que se instala aparte y se integra opcionalmente con esta
  consola (botón «Log»); no forma parte de este repositorio.
