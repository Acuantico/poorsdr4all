#!/bin/bash
# Construye el instalador de Windows en una máquina virtual Windows (libvirt, «win11-ltsc») gobernada por
# lab/vm-run.sh. El código es el de la referencia git indicada: nada del árbol de trabajo.
#   construir.sh [referencia-git]      (por defecto HEAD; p. ej. v1.0.0a4)
#   PARCHES_NMN1M=<dir>                parches opcionales (.patch) que se aplican a NMN1M antes de empaquetarlo
#   SOLO_PAQUETE=1 construir.sh        solo prepara y lista el paquete de construcción (sin usar la VM)
# Salida: installer-windows/dist/poorsdr4all-installer-<versión>-windows-x64.exe (+ .sha256)
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/.." && pwd)"                      # installer-windows/
REPO="${REPO:-$(cd "$RAIZ/.." && pwd)}"             # raíz del repositorio
ETIQUETA="${1:-HEAD}"
DIST="$RAIZ/dist"

git -C "$REPO" rev-parse --verify -q "$ETIQUETA^{commit}" >/dev/null || { echo "No existe la referencia $ETIQUETA en $REPO"; exit 1; }
VERSION="$(git -C "$REPO" show "$ETIQUETA:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)"
echo ">> Versión $VERSION (etiqueta $ETIQUETA)"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/s/payload" "$TMP/s/poorsdr4all"
# Código publicado, tal cual está en la etiqueta (nada del árbol de trabajo).
git -C "$REPO" archive --format=tar --prefix=poorsdr4all/ "$ETIQUETA" | tar -x -C "$TMP/s"
git -C "$REPO" archive --format=tar.gz --prefix=poorsdr4all/ -o "$TMP/s/payload/poorsdr4all-$VERSION.tar.gz" "$ETIQUETA"
# NMN1M (libro de guardia): misma versión fijada que usa install.sh en Linux.
PIN_NMN1M="$(git -C "$REPO" show "$ETIQUETA:scripts/install.sh" | sed -n 's/^PIN_NMN1M="${PIN_NMN1M:-\(.*\)}"/\1/p' | head -1)"
[ -n "$PIN_NMN1M" ] || { echo "No pude leer PIN_NMN1M de install.sh"; exit 1; }
mkdir -p "$RAIZ/cache" "$TMP/s/addons-src"
NMN1M_TGZ="$RAIZ/cache/nmn1m-$PIN_NMN1M.tar.gz"
[ -s "$NMN1M_TGZ" ] || curl -fsSL -o "$NMN1M_TGZ" "https://github.com/Acuantico/nmn1m/archive/refs/tags/$PIN_NMN1M.tar.gz"
# Correcciones de NMN1M (parches sobre la versión fijada): opcional: directorio indicado en PARCHES_NMN1M. Se aplican al paquete descargado.
mkdir -p "$TMP/nmn1m-x" && tar -xzf "$NMN1M_TGZ" -C "$TMP/nmn1m-x"
NMN1M_DIR="$(find "$TMP/nmn1m-x" -mindepth 1 -maxdepth 1 -type d | head -1)"
for parche in "${PARCHES_NMN1M:-$RAIZ/patches-nmn1m}"/*.patch; do
    [ -f "$parche" ] || continue
    patch -p1 -s -d "$NMN1M_DIR" < "$parche" || { echo "El parche de NMN1M $parche no aplica sobre $PIN_NMN1M"; exit 1; }
    echo ">> Parche de NMN1M aplicado: $(basename "$parche")"
done
tar -czf "$TMP/s/addons-src/nmn1m.tar.gz" -C "$TMP/nmn1m-x" "$(basename "$NMN1M_DIR")"
echo ">> NMN1M $PIN_NMN1M (sha256 $(sha256sum "$NMN1M_TGZ" | cut -c1-16)…)"
rsync -a --exclude __pycache__ --exclude '*.pyc' --exclude cache --exclude dist --exclude lab --exclude "patches*" "$RAIZ/" "$TMP/s/installer/"
python3 -I - "$TMP/s" "$TMP/build-src.zip" <<'PY'
import os, sys, zipfile
raiz, destino = sys.argv[1:]
with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for c, _, fs in os.walk(raiz):
        for f in fs:
            r = os.path.join(c, f)
            z.write(r, os.path.relpath(r, raiz))
PY
echo ">> Paquete de construcción: $(du -h "$TMP/build-src.zip" | cut -f1)"
if [ "${SOLO_PAQUETE:-0}" = "1" ]; then
    python3 -I -c "import sys, zipfile; n = zipfile.ZipFile(sys.argv[1]).namelist(); print(len(n), 'ficheros'); print('\n'.join(x for x in n if x.startswith('installer/') and x.count('/') <= 2))" "$TMP/build-src.zip"
    exit 0
fi

mkdir -p "$DIST"
SALIDA="$("$RAIZ/lab/vm-run.sh" "$AQUI/construir.ps1" -t 3600 -f "$TMP/build-src.zip" -o "$DIST")"
echo "$SALIDA"
EXE="$DIST/poorsdr4all-installer-$VERSION-windows-x64.exe"
[ -f "$EXE" ] || { echo "No llegó el instalador a $DIST"; exit 1; }
( cd "$DIST" && sha256sum "$(basename "$EXE")" > "$(basename "$EXE").sha256" )
ls -lh "$EXE" "$EXE.sha256"
