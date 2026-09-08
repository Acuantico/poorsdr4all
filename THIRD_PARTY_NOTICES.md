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

## Fuente LED (DSEG7 Classic)

- Origen: https://github.com/keshikan/DSEG
- Versión: 0.46 (`fonts-DSEG_v046.zip`)
- Licencia: `OFL-1.1` (SIL Open Font License 1.1) — permite explícitamente
  embeber y redistribuir la fuente junto con otro software (cláusula 2),
  siempre que se conserve el aviso de copyright y la licencia.
- Copyright: (c) 2017, keshikan (http://www.keshikan.net); "DSEG" es
  Reserved Font Name.
- Ubicación: `src/poorsdr/ui/assets/fonts/` (solo los 4 estilos básicos:
  Regular, Bold, Italic, BoldItalic — sin las variantes Light/Mini/Modern
  ni los `.woff`/`.woff2`, pensados para web, que este proyecto no usa).
- Uso: `poorsdr.ui.fonts.install_led_font()` la copia al directorio de
  fuentes del usuario (`~/.local/share/fonts/` en Linux) en el primer
  arranque y refresca la caché de fontconfig; la consola la usa para el
  frecuencímetro si no hay ya instalada otra fuente de estilo LED.

Antes se intentó con "7LED" (dafont.com), pero es "gratis solo para uso
personal": esa licencia no permite redistribuirla embebida en software, así
que se retiró sin sustituto durante un tiempo — la consola caía a una fuente
normal. DSEG7 Classic cubre el mismo propósito (dígitos de estilo LED/LCD)
con una licencia que sí lo permite.

## Nunca Más, Ni Una Más (NMN1M)

El cuaderno de estación / contest logger (integrable con el botón «Log») es un
proyecto independiente — https://github.com/Acuantico/nmn1m —, con su propia
licencia y `DATA_PROVENANCE.md` (datos de GeoNames bajo CC-BY-4.0, recursos de
flag-icons bajo MIT). No se distribuye dentro de este repositorio.

## Dependencias de Python, Node.js y del sistema

Las dependencias declaradas en los manifiestos son proyectos independientes y
se descargan desde sus repositorios oficiales durante la instalación. No se
relicencian ni se incluyen sus binarios en el código fuente. Para cada release
se debe generar y revisar el SBOM de los artefactos realmente distribuidos.

## Regla para futuras incorporaciones

No se incorporará código, binario, fuente, imagen o conjunto de datos de
terceros sin registrar nombre, versión, autor, URL, licencia, ubicación,
modificaciones y obligaciones de redistribución.
