#!/usr/bin/env bash
# Arranca PoorSDR4All con el primer Python del sistema que tenga tkinter.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "${PYTHON_BIN}" ]]; then
  for candidate in python python3; do
    if command -v "${candidate}" >/dev/null 2>&1 \
       && "${candidate}" -c 'import tkinter' >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "${candidate}")"
      break
    fi
  done
fi

if [[ -z "${PYTHON_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
  echo "No se encontró un Python con tkinter. Exporta PYTHON_BIN con una ruta válida." >&2
  exit 1
fi

export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="${REPO_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PYTHON_BIN}" -X faulthandler -m poorsdr "$@"
