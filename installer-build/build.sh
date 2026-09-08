#!/usr/bin/env bash
# Genera el instalador de escritorio de PoorSDR4All para Linux:
# un único fichero .run (makeself) que autoextrae el código fuente del
# proyecto + un asistente gráfico (Tkinter) que orquesta scripts/install.sh.
#
# Uso:
#   installer-build/build.sh
#
# Salida:
#   installer-build/dist/poorsdr4all-installer-<version>-linux.run
set -euo pipefail

BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${BUILD_DIR}/.." && pwd)"
ARCHIVE_DIR="${BUILD_DIR}/archive"
PAYLOAD_DIR="${ARCHIVE_DIR}/payload"
DIST_DIR="${BUILD_DIR}/dist"
TOOLS_DIR="${BUILD_DIR}/tools"

VERSION="$(grep -m1 '^version' "${REPO_DIR}/pyproject.toml" | sed -E 's/version *= *"([^"]+)"/\1/')"
[[ -n "${VERSION}" ]] || { echo "ERROR: no se pudo leer la versión de pyproject.toml" >&2; exit 1; }

echo "==> Proyecto:  ${REPO_DIR}"
echo "==> Versión:   ${VERSION}"

command -v git >/dev/null 2>&1 || { echo "ERROR: se necesita git." >&2; exit 1; }
[[ -x "${TOOLS_DIR}/makeself.sh" ]] || { echo "ERROR: falta ${TOOLS_DIR}/makeself.sh" >&2; exit 1; }

echo "==> Empaquetando el código fuente (ficheros trackeados por git, contenido actual del árbol de trabajo — incluye cambios sin confirmar; nunca ficheros sin trackear/gitignorados)..."
rm -rf "${PAYLOAD_DIR}"
mkdir -p "${PAYLOAD_DIR}"
( cd "${REPO_DIR}" && git ls-files -z | tar --null -T - -cf - ) | tar -x -C "${PAYLOAD_DIR}"

# Los plugins van totalmente aparte: este instalador no incluye ninguno, ni
# los instala, ni hace referencia a ellos. Cada plugin se distribuye e
# instala por su cuenta, como ya documenta plugins/README.md.
echo "==> Retirando plugins/ del paquete (van aparte, no se distribuyen aquí)..."
rm -rf "${PAYLOAD_DIR}/plugins"

echo "==> Fijando permisos ejecutables..."
chmod +x \
  "${PAYLOAD_DIR}/scripts/install.sh" \
  "${PAYLOAD_DIR}/scripts/run.sh" \
  "${PAYLOAD_DIR}/scripts/build_native.py" \
  "${ARCHIVE_DIR}/run_installer.sh" \
  "${ARCHIVE_DIR}/gui/wizard.py" \
  "${ARCHIVE_DIR}/gui/sudo_askpass.py"

echo "==> Comprobando sintaxis..."
bash -n "${ARCHIVE_DIR}/run_installer.sh"
python3 -m py_compile "${ARCHIVE_DIR}/gui/wizard.py" "${ARCHIVE_DIR}/gui/sudo_askpass.py"
find "${ARCHIVE_DIR}/gui" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "    OK"

mkdir -p "${DIST_DIR}"
OUT_FILE="${DIST_DIR}/poorsdr4all-installer-${VERSION}-linux.run"

echo "==> Construyendo ${OUT_FILE}..."
"${TOOLS_DIR}/makeself.sh" \
  --gzip \
  --sha256 \
  --header "${TOOLS_DIR}/makeself-header.sh" \
  "${ARCHIVE_DIR}" \
  "${OUT_FILE}" \
  "PoorSDR4All ${VERSION} — instalador" \
  ./run_installer.sh

echo "==> Listo: ${OUT_FILE}"
