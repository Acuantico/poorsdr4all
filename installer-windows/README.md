# Instalador de PoorSDR4All para Windows

Genera un único `poorsdr4all-installer-<versión>-windows-x64.exe` (Inno Setup + PyInstaller) que instala
PoorSDR4All en Windows 10 (2004 o posterior) y 11, 64 bits.

## Qué hace

1. Instala la aplicación (PyInstaller, carpeta `Program Files\PoorSDR4All`) con sus accesos directos.
2. **Prepara WSL2** (si falta): instala el paquete de WSL desde GitHub (comprueba la firma digital de Microsoft),
   activa los componentes de Windows y, si hace falta reiniciar, el asistente continúa solo después.
3. **Asistente de OpenWebRX+** (`PoorSDR4All.exe --asistente-wsl`): descarga Ubuntu 24.04 (la imagen oficial, con
   comprobación SHA-256), crea una distribución WSL **propia y privada** llamada `PoorSDR4All` y ejecuta dentro el
   `scripts/install.sh` oficial del proyecto, que compila OpenWebRX+ y el servicio de spots (`spiderd`). Nada de eso
   se distribuye compilado: se descarga y compila en el equipo del usuario.
4. Al abrir la aplicación se arrancan WSL, OpenWebRX+ y spiderd; al cerrarla se detienen (y WSL se apaga). Si la
   aplicación muriese de golpe, WSL se apaga sola.
5. Componentes opcionales, marcados por defecto: **RTTY Power**, **Libro de guardia (NMN1M)** (también como programa
   independiente, con su icono) y **soporte para SDR por USB** (`usbipd-win` + autorización de ~60 SDR habituales).

La fuente LED es `7LED.ttf`, incluida en el paquete junto al `readme.txt` de su autor.

## Contenido

| Carpeta | Qué es |
|---|---|
| `src/launch_poorsdr.py` | Punto de entrada del `.exe` (aplicación, asistente, libro de guardia, avisos). |
| `src/poorsdr_win/` | WSL (arranque/parada, sesión viva), instalación en WSL, spiderd, USB (`usbipd`) y ventanas (Tk). |
| `inno/` | Guion de Inno Setup, `preparar-wsl.ps1` (administrador) y `sdr-ids.txt` (VID:PID de los SDR autorizados). |
| `build/` | Construcción: `construir.sh` (en el anfitrión) y `construir.ps1` (dentro de la máquina Windows). |
| `lab/` | Pequeño laboratorio para construir en una VM Windows de libvirt sin ventanas ni contraseñas. |
| `tests/` | Pruebas de la lógica (no necesitan Windows ni WSL). |

## Construir

Necesita una máquina virtual Windows (libvirt, dominio `win11-ltsc`) con Python 3.12 y el agente de `lab/`
(`lab-agente.ps1`, instalado una vez). El código es el de una referencia git, nada del árbol de trabajo:

```sh
installer-windows/build/construir.sh v1.0.0a4      # → installer-windows/dist/*.exe y .sha256
SOLO_PAQUETE=1 installer-windows/build/construir.sh  # solo prepara el paquete, sin usar la VM
```

La construcción **falla** si falta algún módulo que usan los complementos (RTTY, libro de guardia) o los scripts
que el asistente ejecuta dentro de WSL, en lugar de descubrirlo en el equipo del usuario.

## Pruebas

```sh
python -m pytest installer-windows/tests
```

## Limitaciones conocidas

- Probado en una máquina virtual con Windows 11; **sin SDR real** ni en equipos de usuarios todavía.
- Mientras un SDR está conectado a WSL, Windows no puede usarlo; al cerrar PoorSDR4All vuelve a Windows.
- El `.exe` no está firmado: SmartScreen puede mostrar un aviso.
