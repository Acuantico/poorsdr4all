# Instalación desde el código fuente

PoorSDR4All no distribuye bibliotecas compiladas. El paquete principal funciona
con Python y dispone de un acelerador C opcional que se compila en el equipo del
usuario. OpenWebRX+ y su pila se descargan desde sus repositorios oficiales en
revisiones fijadas y conservan sus licencias GPL/AGPL.

## Estado de soporte

| Sistema | Instalación Python | Instalador OpenWebRX+ | Validación física |
|---|---|---|---|
| Arch Linux | Sí | `scripts/install.sh` | Sí, plataforma principal |
| Debian/Ubuntu y Raspberry Pi OS 64-bit | Sí | `scripts/install.sh` | Pendiente de colaboradores |
| Windows 10/11 | Experimental | No nativo | Pendiente de colaboradores |

## Instalación mínima y aislada

### Arch Linux

```sh
sudo pacman -S --needed python tk portaudio git base-devel
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python scripts/build_native.py       # acelerador opcional
python -m poorsdr
```

### Debian/Ubuntu

```sh
sudo apt update
sudo apt install python3 python3-venv python3-tk portaudio19-dev git build-essential
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python scripts/build_native.py       # acelerador opcional
python -m poorsdr
```

Estas instrucciones se someten a CI, pero la Alpha todavía necesita pruebas de
audio, CAT y SDR realizadas por usuarios de Debian.

### Windows 10/11

Instala Python 3.11 o posterior y Git. Para el acelerador opcional instala
Visual Studio Build Tools con la carga de trabajo de C++, clang o MinGW.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
python scripts\build_native.py
python -m poorsdr
```

En Windows se usa WASAPI mediante PyAudioWPatch. CAT utiliza puertos `COM`.
OpenWebRX+ no se instala de forma nativa: configura un servidor OpenWebRX+
remoto o ejecútalo en WSL2. Este soporte es experimental hasta disponer de
pruebas comunitarias con hardware real.

## Instalador completo para Linux

```sh
scripts/install.sh
```

El script detecta Arch o Debian, instala dependencias del sistema, compila el
acelerador, clona la pila OpenWebRX+ en revisiones exactas, aplica los parches
publicados en `patches/` y configura sus servicios. Requiere `sudo` y modifica
paquetes, grupos, udev, polkit y systemd; revisa el script antes de ejecutarlo.

Opciones:

```sh
SKIP_OWRX_BUILD=1 scripts/install.sh
SKIP_SPIDER=1 scripts/install.sh
INSTALL_WEB_EXTRAS=0 scripts/install.sh
OWRX_BUILD_JOBS=4 scripts/install.sh
RESET_OWRX_CONFIG=1 scripts/install.sh
```

Una actualización normal conserva `settings.json`, usuarios y marcadores de
OpenWebRX. `RESET_OWRX_CONFIG=1` crea primero una copia fechada en
`/var/lib/openwebrx/backup-poorsdr-*` y después instala la plantilla limpia.
La plantilla y sus supuestos de RTL-SDR están descritos en
[`assets/owrx/README.md`](../assets/owrx/README.md). Valídala antes de instalar
con `python scripts/check_owrx_config.py`.

## Plugins

```sh
python -m pip install ./plugins/filter-relays
```

**Nunca Más, Ni Una Más (NMN1M)**, el cuaderno de estación / contest logger que
aporta el botón «Log», es un proyecto independiente con su propio
repositorio — instálalo aparte en el mismo entorno. Almacena preferencias en
el directorio de configuración de PoorSDR y logs/bases de datos en su
directorio de datos. En Linux son, por defecto, `~/.config/poorsdr/libro-guardia`
y `~/.local/share/poorsdr/libro-guardia`; en Windows usa `APPDATA` y
`LOCALAPPDATA`.

## Configuración y ejecución

- Configuración: `~/.config/poorsdr/config.json` en Linux.
- Datos: `~/.local/share/poorsdr/` en Linux.
- Caché: `~/.cache/poorsdr/` en Linux.
- Ejecutar: `python -m poorsdr` o el comando instalado `poorsdr`.

El primer arranque puede importar la configuración legacy indicada por
`POORSDR_LEGACY_HOME`. Los puertos serie comunes en Linux son `/dev/ttyUSB0` y
`/dev/ttyACM0`; en Windows son `COM1`, `COM2`, etc.

## Funciones opcionales

- Servidor remoto: `python -m pip install ".[web]"`.
- FT8/FT4/JT65/WSPR: requiere los decodificadores oficiales de WSJT-X.
- ANR: requiere SpeexDSP 1.2.1 instalado en el sistema.
- Visores GTK: son opcionales; la cascada dispone de fallback Tkinter.
