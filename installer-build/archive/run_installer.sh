#!/usr/bin/env bash
# Punto de entrada del instalador de PoorSDR4All (lo ejecuta makeself justo
# después de autoextraerse; el directorio actual es la carpeta extraída, que
# contiene gui/ y payload/ como hermanos).
#
# Este script solo hace de "bootstrap": comprueba que hay un python3 con
# tkinter (instalándolo una vez, con permiso gráfico, si falta) y le pasa el
# control al asistente real (gui/wizard.py). Toda la lógica de instalación
# vive en payload/scripts/install.sh, sin tocar.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "PoorSDR4All — preparando el instalador gráfico..."

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "ERROR: no se detecta una sesión gráfica (\$DISPLAY / \$WAYLAND_DISPLAY vacíos)." >&2
  echo "Este instalador necesita un escritorio gráfico. Para una instalación" >&2
  echo "por terminal, ejecuta directamente: ${HERE}/payload/scripts/install.sh" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: no se encontró 'python3'. Instálalo y vuelve a ejecutar este instalador." >&2
  exit 1
fi

if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  echo "Falta el módulo gráfico de Python (tkinter, paquete del sistema); se instala una sola vez."
  if ! command -v pkexec >/dev/null 2>&1; then
    echo "ERROR: no se encontró 'pkexec' para instalarlo con permiso gráfico." >&2
    echo "Instala manualmente 'tk' (Arch) o 'python3-tk' (Debian/Ubuntu/Raspberry Pi OS) y reintenta." >&2
    exit 1
  fi

  OS_FAMILY=""
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" == "arch" || "${ID_LIKE:-}" == *arch* ]]; then
      OS_FAMILY="arch"
    elif [[ "${ID:-}" == "debian" || "${ID:-}" == "ubuntu" || "${ID_LIKE:-}" == *debian* ]]; then
      OS_FAMILY="debian"
    fi
  fi

  case "${OS_FAMILY}" in
    arch)
      pkexec pacman -S --needed --noconfirm tk
      ;;
    debian)
      pkexec sh -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3-tk'
      ;;
    *)
      echo "ERROR: distribución no reconocida automáticamente para instalar tkinter." >&2
      echo "Instala manualmente 'tk' (Arch) o 'python3-tk' (Debian/Ubuntu) y reintenta." >&2
      exit 1
      ;;
  esac

  if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    echo "ERROR: tkinter sigue sin estar disponible tras el intento de instalación." >&2
    exit 1
  fi
fi

exec python3 "${HERE}/gui/wizard.py" --payload "${HERE}/payload"
