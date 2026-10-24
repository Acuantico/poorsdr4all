# Componentes y recursos de terceros

La licencia PolyForm de la raíz cubre únicamente el código original cuyos
derechos controla Acuantico Power. Cada componente de esta lista conserva su
licencia, autoría y avisos. Los textos completos acompañan las distribuciones
en `LICENSES/`.

## Código incluido en la distribución fuente

### owrx-spider / spiderd

- Origen: https://github.com/Acuantico/owrx-spider
- Revisión base: `7741d530a18a3f5aae08a2e3435fc6ed1d1f6126`
- Licencia: `AGPL-3.0-or-later`
- Ubicación: `src/poorsdr/_vendor/runtime/spiderd/`
- Cambios: configuración integrada, puente Node.js/Python y recursos de UI
  adaptados para PoorSDR4All.

Este subdirectorio no está cubierto por PolyForm. Su procedencia también se
documenta en el `UPSTREAM.md` y el `LICENSE` que contiene. Se conserva en el
sdist para que el instalador de Linux pueda copiarlo como servicio separado,
pero se excluye del wheel de PoorSDR4All; no se relicencia ni se combina con el
código propio bajo PolyForm.

### makeself

- Origen: https://makeself.io/ (https://github.com/megastep/makeself)
- Versión: 2.7.2
- Autor: Stéphane Peter
- Licencia: `GPL-2.0-or-later`
- Ubicación: `installer-build/tools/makeself.sh`,
  `installer-build/tools/makeself-header.sh`
- Uso: sin modificar; genera el instalador `.run` autoextraíble para Linux a
  partir de `installer-build/build.sh`. El propio proyecto makeself aclara que
  los archivos autoextraíbles que produce no quedan sujetos a la GPL — solo la
  herramienta en sí.

## Proyectos descargados y compilados por el instalador

Estos proyectos no se copian en el repositorio ni en el wheel de PoorSDR4All.
El instalador descarga las revisiones exactas y las compila separadamente.

| Componente | Versión | Revisión fijada | Licencia efectiva |
|---|---:|---|---|
| [csdr](https://github.com/luarvique/csdr) | 0.18.37 | `c5d4224461267d67b1629821b179f95378477956` | Mixta BSD/GPL; la compilación predeterminada activa GPL, por lo que se trata como `GPL-3.0-or-later` |
| [pycsdr](https://github.com/luarvique/pycsdr) | 0.18.37 | `db2050bd02ddd1d630cee8d27aaa4432767717ca` | `GPL-3.0-or-later` |
| [owrx_connector](https://github.com/luarvique/owrx_connector) | 0.6.5 | `870285269143048f850151346980942a12ccf24b` | `GPL-3.0-or-later` |
| [OpenWebRX+](https://github.com/luarvique/openwebrx) | 1.2.119 | `55dae2e6d798e133e8ac25769a3d2a1ea4d27419` | `AGPL-3.0-or-later` |

El instalador aplica cambios de compatibilidad a pycsdr y OpenWebRX+. Quien
redistribuya esos resultados debe conservar los avisos y facilitar el código
fuente correspondiente, incluidos los cambios, conforme a GPL/AGPL.

### SpeexDSP

- Origen: https://gitlab.xiph.org/xiph/speexdsp
- Versión de sistema recomendada: 1.2.1
- Licencia: `BSD-3-Clause`
- Uso: biblioteca del sistema cargada dinámicamente para el ANR.

PoorSDR4All no incluye una DLL ni una biblioteca SpeexDSP precompilada. Si una
distribución futura la incluye, deberá registrar versión, origen y hash, además
de conservar el aviso BSD.

### PyAV y FFmpeg (audio del acceso web y mp3 de las macros)

- Origen: https://pypi.org/project/av/ (PyAV, https://github.com/PyAV-Org/PyAV); FFmpeg: https://ffmpeg.org
- Licencia: PyAV es `BSD-3-Clause`. Su rueda binaria incluye FFmpeg y otras bibliotecas (LGPL-2.1+ y, en
  las compilaciones con códecs como x264 o x265, GPL-2.0+), cada una con su licencia y su código fuente.
- Uso: `aiortc` lo necesita para codificar/decodificar el audio Opus del acceso web remoto, y es el
  respaldo para decodificar los mp3 de las macros de llamada cuando no hay un `ffmpeg` instalado. Los WAV
  se reproducen con un lector propio, sin FFmpeg ni PyAV.
- **No se redistribuye.** En Linux lo instala `pip` en la máquina del usuario (extra `[web]`) y `ffmpeg`
  lo aporta el gestor de paquetes del sistema. En Windows el instalador lo descarga de PyPI en el equipo del
  usuario, comprobando su SHA-256 (PyAV 17.1.0, `av-17.1.0-cp311-abi3-win_amd64.whl`), y lo deja en la
  carpeta `extras` junto al programa; el ejecutable no lo contiene y la compilación falla si lo contuviera.
  Para retirarlo basta borrar la carpeta `extras` (el acceso web remoto dejará de funcionar).

## Instalador de Windows

El ejecutable de Windows se construye con PyInstaller e Inno Setup y empaqueta Python y las dependencias de
Python de PoorSDR4All. **No** incluye PyAV/FFmpeg, ni `ffmpeg.exe`, ni WSL, ni usbipd-win, ni la imagen de
Ubuntu: todo eso se descarga en el equipo del usuario.

| Componente | Licencia | Cómo se distribuye |
|---|---|---|
| Python 3.12 y Tcl/Tk | PSF-2.0 / licencia Tcl (tipo BSD) | dentro del ejecutable (PyInstaller) |
| Dependencias de Python (numpy, matplotlib, Pillow, cryptography, fastapi, aiortc…) | BSD, MIT, Apache-2.0, PSF, ISC | dentro del ejecutable; sus avisos y textos se generan en cada compilación y se instalan en `licenses\LICENCIAS-DEPENDENCIAS.txt` |
| [PyInstaller](https://pyinstaller.org) | GPL-2.0-or-later con excepción que permite distribuir el programa empaquetado bajo cualquier licencia | herramienta de construcción; su cargador (*bootloader*) va dentro del ejecutable |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Inno Setup License (permite redistribuir los instaladores generados) | herramienta de construcción |
| WSL2, imagen de Ubuntu 24.04 para WSL, usbipd-win (GPL-3.0) | Microsoft / Canonical / GPL-3.0 | se descargan al instalar; no van en el instalador |
| OpenWebRX+ y su pila | ver arriba | el código fuente viaja en `payload\` y se compila dentro de WSL |

El instalador instala `THIRD_PARTY_NOTICES.md`, `LICENSES\` y `LICENCIAS-DEPENDENCIAS.txt` en la carpeta
`licenses` de la instalación.

## Fuente LED (7LED)

- Origen: https://www.dafont.com/7-led.font (fichero `7led.zip`).
- Autor: Philippe Blondel (philing.net), según el `readme.txt` que acompaña a la fuente.
- Licencia: *freeware* según ese `readme.txt` del autor — puede distribuirse a quien se quiera siempre que el
  `readme.txt` la acompañe, y se pide no modificarla ni cambiarle el nombre. Sin garantía.
- Ubicación: `src/poorsdr/ui/assets/fonts/` — `7LED.ttf` sin modificar, con los textos originales del autor
  `7LED-readme.txt` y `7LED-lisezmoi.txt` (deben viajar siempre con la fuente; `scripts/check_release.py` lo comprueba).
- Uso: `poorsdr.ui.fonts.install_led_font()` la deja visible para la consola (Linux: copia a
  `~/.local/share/fonts/`; Windows: registro privado del proceso) y la consola la usa para el frecuencímetro.
- Nota: dafont.com muestra esta fuente como «gratis para uso personal», mientras que el texto del propio autor que la
  acompaña es el que se ha tomado como referencia. Si el autor indicara otra cosa, habría que retirarla.

## Imágenes

`src/poorsdr/ui/assets/images/` (`back.png`, `image.png`, `image.ico`), `installer-build/archive/gui/assets/sdrlogo.png`
y las capturas de `docs/images/` son obra de Acuantico Power, creadas con modelos de IA ejecutados en local por el
autor, y se distribuyen bajo la misma licencia que el código original (PolyForm Noncommercial).

## Nunca Más, Ni Una Más (NMN1M)

El cuaderno de estación / contest logger (integrable con el botón «Log») es un
proyecto independiente — https://github.com/Acuantico/nmn1m —, con su propia
licencia y `DATA_PROVENANCE.md` (datos de GeoNames bajo CC-BY-4.0, recursos de
flag-icons bajo MIT). No se distribuye dentro de este repositorio.

## Dependencias de Python, Node.js y del sistema

Las dependencias declaradas en los manifiestos son proyectos independientes y
se descargan desde sus repositorios oficiales durante la instalación. No se
relicencian ni se incluyen sus binarios en el código fuente. La única
excepción es el ejecutable de Windows, que empaqueta las de Python con sus
avisos (ver «Instalador de Windows»). Para cada release
se debe generar y revisar el SBOM de los artefactos realmente distribuidos.

## Regla para futuras incorporaciones

No se incorporará código, binario, fuente, imagen o conjunto de datos de
terceros sin registrar nombre, versión, autor, URL, licencia, ubicación,
modificaciones y obligaciones de redistribución.
