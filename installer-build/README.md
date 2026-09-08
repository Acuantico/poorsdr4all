# Instalador de escritorio de PoorSDR4All (Linux)

Genera un único fichero `.run` (autoextraíble, [makeself](https://makeself.io/))
que instala PoorSDR4All con una interfaz gráfica desatendida: logo, licencia
con casilla de aceptación, opciones, progreso con registro en vivo y fin.

No reimplementa la instalación: por debajo ejecuta literalmente
`scripts/install.sh` del propio proyecto. OpenWebRX+ y su pila (csdr,
pycsdr, owrx_connector) son GPL/AGPL y **nunca** se empaquetan compilados
aquí — el instalador los clona en las revisiones fijadas y los compila en
el equipo del usuario, exactamente igual que `install.sh` a mano.

## Uso (para quien vaya a instalar PoorSDR4All)

```sh
chmod +x poorsdr4all-installer-<versión>-linux.run
./poorsdr4all-installer-<versión>-linux.run
```

Comprobar antes que el fichero no se corrompió al copiarlo (si tienes el
`.sha256` al lado):

```sh
sha256sum -c poorsdr4all-installer-<versión>-linux.run.sha256
```

Necesita sesión gráfica (X11/Wayland), Arch Linux o Debian/Ubuntu/Raspberry
Pi OS de 64 bits, y **conexión a Internet durante la instalación** — el
propio código de PoorSDR4All va dentro del `.run`, pero `install.sh` todavía
tiene que descargar paquetes del sistema y, si se elige OpenWebRX+, clonar y
compilar su pila desde GitHub en el momento (ver más arriba: nunca se
empaqueta precompilada).

## Generar el `.run`

```sh
installer-build/build.sh
```

Produce `installer-build/dist/poorsdr4all-installer-<versión>-linux.run`
(la versión se lee de `pyproject.toml`). El script:

1. Empaqueta los ficheros trackeados por git (`git ls-files`) con su
   contenido ACTUAL del árbol de trabajo — incluye cambios sin confirmar
   todavía, nunca ficheros sin trackear ni gitignorados — en
   `archive/payload/`, y retira `plugins/` (los plugins van totalmente
   aparte: no se incluye ninguno, no se instalan, no se mencionan).
2. Comprueba sintaxis (`bash -n`, `python3 -m py_compile`).
3. Llama a `tools/makeself.sh` (vendorizado desde el proyecto oficial
   [megastep/makeself](https://github.com/megastep/makeself), GPL-2.0+;
   `tools/makeself.sh` + `tools/makeself-header.sh`).

## Cómo funciona por dentro

```
archive/
  run_installer.sh   <- lo ejecuta makeself tras autoextraerse
  gui/
    wizard.py         <- asistente Tkinter (stdlib only, sin dependencias)
    sudo_askpass.py   <- ventana de contraseña usada como SUDO_ASKPASS
    assets/sdrlogo.png
  payload/             <- snapshot de todo el repo (git archive)
```

- `run_installer.sh` comprueba que hay sesión gráfica y que `python3` tiene
  `tkinter`; si falta, lo instala una vez con `pkexec` (permiso gráfico) y
  arranca `gui/wizard.py`.
- `install.sh` está pensado para correr como el usuario normal (usa
  `${USER}`/`${HOME}` para `pip install --user`, grupos del sistema y el
  `systemd --user` de spiderd) y llama a `sudo` en los puntos concretos que
  lo necesitan. El asistente **no** se relanza entero con pkexec/sudo (eso
  rompería esos entornos): en vez de eso antepone al `PATH` del subproceso
  un `sudo` de mentira que delega en el real con `-A`, con `SUDO_ASKPASS`
  apuntando a `sudo_askpass.py` — cada `sudo algo` que haga `install.sh`
  pide la contraseña en una ventana en vez de fallar por falta de terminal.
- Las casillas de la pantalla "Componentes" se traducen 1:1 a las variables
  de entorno que ya entiende `install.sh` (`SKIP_OWRX_BUILD`, `SKIP_SPIDER`,
  `INSTALL_WEB_EXTRAS`). El plugin Filter Relays no lo instala `install.sh`
  (es un paquete pip aparte, ver `plugins/README.md`) — lo hace el asistente
  después, si se marcó.
- Al terminar bien, crea `~/.local/share/applications/poorsdr4all.desktop`
  apuntando a `~/.local/bin/poorsdr` (lo deja ahí `pip install --user .`) y
  copia el logo a `~/.local/share/poorsdr4all-installer/` como icono — no
  depende de que el directorio extraído por makeself siga existiendo.

## Verificado en este entorno / pendiente de probar en un escritorio real

Este árbol se generó y se comprobó en un entorno sandbox sin `pacman`, sin
`tkinter`, sin `pkexec` y sin sesión gráfica real, así que **no se ha podido
ejecutar el asistente de verdad ni una instalación completa**. Lo que sí se
verificó aquí:

- El `.run` se construye, pasa `--check` (SHA256/MD5) y se autoextrae con la
  estructura de carpetas correcta y los permisos ejecutables intactos.
- `run_installer.sh` falla limpiamente (sin tocar el sistema) cuando no hay
  `$DISPLAY`/`$WAYLAND_DISPLAY`.
- `detect_os()` distingue correctamente Arch / Debian-Ubuntu / no soportado
  contra varios `/etc/os-release` de prueba.
- `build_sudo_shim()` genera un `sudo` que delega en el real con `-A` sin
  recursión (probado con un `sudo` falso).
- Sintaxis Python y Bash válidas.

Falta, en un escritorio real con Arch o Debian/Ubuntu:

- Ver el asistente en pantalla (maquetación, textos, tamaños).
- Confirmar que `pkexec` instala `tk`/`python3-tk` cuando falta.
- Confirmar que la ventana de `SUDO_ASKPASS` aparece y que `install.sh`
  completa una instalación real (esto modifica el sistema de verdad: instala
  paquetes, puede crear el usuario `openwebrx` y servicios systemd — no es
  algo para probar a la ligera en una máquina que ya uses).

## Para una nueva versión

Vuelve a ejecutar `installer-build/build.sh` después de subir `version` en
`pyproject.toml`. El `.run` empaqueta el contenido ACTUAL del árbol de
trabajo de los ficheros trackeados — para una release de verdad, confirma
antes todos los cambios y comprueba que el árbol está limpio (`git status`),
igual que exige `docs/RELEASING.md` para el resto de artefactos.
