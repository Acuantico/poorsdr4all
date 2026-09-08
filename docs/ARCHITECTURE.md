# Arquitectura

PoorSDR4All es una consola Tkinter que orquesta varios subsistemas (radio CAT,
DSP de audio, backend OpenWebRX+, proxy rigctld, servidor web, cluster DX…).
La arquitectura separa **lógica pura**, **servicios con estado** y **vista**.

## Capas

```
poorsdr/
  infra/     Sin dependencias del dominio.
             paths (rutas XDG) · logging (RotatingFileHandler, un logger "poorsdr")
             · events (EventBus pub/sub síncrono y thread-safe).

  config/    Modelo tipado: dataclasses frozen anidadas (AppConfig → cat, audio,
             owrx, spider, web…). migrate.py convierte el config.json plano
             antiguo (~120 claves) sin pérdida; las claves no modeladas van a
             AppConfig.extra. loader.py: carga/guardado atómico + import del
             ~/Apps/PoorSDR4/config.json en el primer arranque.

  core/      Functional core: funciones puras, sin IO ni estado global.
             cat/ (modos, tramas, parsers, perfiles de radio uSDX) · bands · tuning (freq ↔ MHz·kHz·cHz,
             paso) · waterfall (FFT del audio RX → fila) · theme (paletas +
             colormap de la cascada) · memory · autocall · owrx/ (backend,
             process, state, launch, spiderd) · smeter (dBFS de OWRX ↔
             unidades de aguja / ángulo, para el S-metro).  Cobertura alta.

  services/  Imperative shell: un objeto con estado por subsistema.
             Contrato: start() · stop() · reconfigure(cfg) · status.
             Se comunican por el EventBus; nunca tocan atributos de otro servicio.
             Fábricas inyectables (controller_factory, runner, http_probe…) →
             testeables sin hardware.

  ui/        Tkinter fino. main_window reproduce la consola original
             (layout fijo, fuente LED, DialControl); panels/ y settings/ generan
             widgets a partir de datos; state.py son reducers puros.
             Los command= van a un objeto Callbacks que PoorSDRApp cablea a
             los servicios; los eventos del bus se marshalan al hilo Tk.

  viewers/   Cascada (waterfall.py) y panel digi (digi.py): procesos GTK aparte.
             launcher.py construye args/entorno; owrx-control les habla por un
             socket TCP local.

  i18n/      strings.py con los textos en 12 idiomas + helper t(key, lang).
             Ojo: la UI de main_window/ajustes todavía no lo consume (sigue
             con literales en español); "language" en Ajustes por ahora solo
             queda guardado en config, no cambia los textos de la consola.

  runtime.py Composition root: AppContext = bus + config + ServiceManager;
             build_context() instancia y ordena los servicios.

  _vendor/   DSP y protocolo de bajo nivel tomados del proyecto original y
             envueltos por services/. No es API pública. Ver _vendor/README.md.
```

**Dependencias:** `ui` → `services` → `core` / `config` / `infra`.
`core` no importa `services`, `ui`, `runtime` ni `_vendor` (solo tipos).
`_vendor` no importa nada de `poorsdr`.

## EventBus

`bus.publish("radio.frequency", hz=…, source="ui")` → dispatch síncrono bajo
lock a los suscriptores del tema exacto. Una excepción en un suscriptor se
registra y no rompe a los demás ni al que publica.

Temas principales: `radio.frequency` · `radio.mode` · `radio.ptt` ·
`radio.status` · `owrx.status` · `owrx.tune` · `owrx.band` · `owrx.smeter`
(nivel de señal en dBFS, dentro de la banda de paso; el µSDX no lo da por CAT
así que el S-metro de la consola se alimenta de aquí) · `audio.status` ·
`web.status` · `memory.changed` · `autocall.started` / `autocall.finished` ·
`service.status`.

El campo `source` (`"ui"`, `"web"`, `"rigctld"`, `"owrx"`, `"cat"`, `"autocall"`)
permite evitar bucles: un servicio ignora los eventos que él mismo originó.

## Servicios y "guardar en caliente"

Guardar en Ajustes → `AppContext.reconfigure(nueva_cfg)`:
persiste el JSON y llama a `ServiceManager.reconfigure_all(cfg)`. Cada servicio
compara lo que cambió y se reinicia internamente solo si hace falta (audio,
sockets TCP). No hay reinicio de la aplicación completa.

## Configuración

- `~/.config/poorsdr/config.json` — formato anidado con `schema_version`.
- Primer arranque sin ese fichero → se migra `~/Apps/PoorSDR4/config.json`
  (formato plano del proyecto original) si existe.
- `runtime.write_vendor_config()` vuelca un puente de compatibilidad a
  `~/.local/share/poorsdr/runtime/config.json` (o `LOCALAPPDATA` en Windows)
  (plano): `_vendor/audio.py` la lee al importarse, y los visores externos
  vigilan su mtime por `OWRX_CONFIG_PATH` (p. ej. para saber si el tema
  activo es Classic). Se vuelca al arrancar y en cada
  `AppContext.reconfigure()`, no solo una vez — si no, un cambio de tema en
  caliente no le llegaría a los visores hasta reiniciar la app.

## Plugins

`poorsdr.plugins` descubre plugins por *entry points* del grupo
`poorsdr.plugins` (cada plugin es un paquete pip aparte). Un plugin expone un
objeto con `id`, `name` y `register(ctx: PluginContext)`; en `register` puede
`ctx.add_service(...)` (servicio en 2.º plano), `ctx.add_console_button(id,
label, on_click)` (botón en la consola) y `ctx.add_settings_tab(nombre,
fields)` (pestaña de Ajustes, con los mismos `Field` de
`poorsdr.ui.settings.form`). `shutdown()` es opcional.

`build_context()` los descubre y registra tras los servicios internos.
`PoorSDRApp` añade a la consola los botones que hayan declarado y pasa sus
pestañas a `SettingsWindow`. Sin ningún plugin instalado la app funciona igual
(sin botón «Log», sin relés, sin la pestaña «Relés»).

Activación por usuario: Ajustes → **Plugins** (check por plugin); se guarda en
`config.json` bajo `PLUGINS` (`{id: bool}`, lo no listado = activo).

Plugins de este repo (proyectos independientes en `plugins/`):

- `plugins/filter-relays/` — `poorsdr-filter-relays`: registra
  `FilterRelayService` (relés de filtros por banda vía WiFi).

El botón «Log» lo aporta **Nunca Más, Ni Una Más (NMN1M)**, un cuaderno de
estación / contest logger que es su propio proyecto independiente (repositorio,
licencia y ciclo de publicación aparte) — no vive en `plugins/` de este repo.
Instálalo por separado en el mismo entorno para que la consola lo descubra.

## Modo de desarrollo del layout (botón EDIT)

El botón **EDIT** de la consola (`poorsdr.ui.layout.DEV_LAYOUT_MODE`) activa
un modo para recolocar los controles a mano con el botón derecho del ratón —
sirve para ajustar `LAYOUT_DEFAULTS` mientras se desarrolla, no es una función
para el usuario final, y está **oculto por defecto**.

Para que aparezca, arranca la consola con la variable de entorno
`POORSDR_DEV_LAYOUT` a `1`/`true`/`yes`/`on`:

```sh
POORSDR_DEV_LAYOUT=1 python -m poorsdr
```

Sin esa variable (o con cualquier otro valor, incluida cadena vacía) el botón
no se crea. Las posiciones movidas con EDIT activo se guardan en
`~/.config/poorsdr/layout.json` y se aplican por encima de `LAYOUT_DEFAULTS`
en el siguiente arranque, tenga o no el botón EDIT visible esa sesión.
