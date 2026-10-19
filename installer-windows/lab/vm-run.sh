#!/bin/bash
# Ejecuta un script PowerShell dentro de la VM (win11-ltsc) y muestra su salida.
#   vm-run.sh tarea.ps1 [-t SEGUNDOS] [-f fichero ...] [-o DIR]
#     -t  tiempo máximo de espera (por defecto 600)
#     -f  ficheros extra que la tarea puede descargar de http://192.168.122.1:8099/<nombre>
#     -o  carpeta donde copiar lo que la tarea suba con PUT /subir/<nombre>
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
IP=192.168.122.1; PUERTO=8099
V="virsh -c qemu:///system"
TAREA="${1:?Uso: vm-run.sh tarea.ps1 [-t seg] [-f fichero ...] [-o dir]}"; shift
ESPERA=600; SALIDA="$AQUI/salida"; EXTRAS=()
while [ $# -gt 0 ]; do
    case "$1" in
        -t) ESPERA="$2"; shift 2 ;;
        -o) SALIDA="$2"; shift 2 ;;
        -f) EXTRAS+=("$2"); shift 2 ;;
        *) echo "Argumento desconocido: $1"; exit 2 ;;
    esac
done
[ -f "$TAREA" ] || { echo "No existe $TAREA"; exit 1; }

# Sin consultar firewalld: esa consulta pasa por polkit y puede abrir un diálogo de contraseña en el escritorio.
[ "$($V domstate win11-ltsc)" = "ejecutando" ] || { echo ">> Arrancando la VM..."; $V start win11-ltsc >/dev/null; }

TMP="$(mktemp -d)"; SERVIDOR=""
limpiar() { [ -n "$SERVIDOR" ] && kill "$SERVIDOR" 2>/dev/null || true; rm -rf "$TMP"; }
trap limpiar EXIT
cp "$TAREA" "$TMP/tarea.ps1"
for f in "${EXTRAS[@]}"; do cp -r "$f" "$TMP/"; done

python3 "$AQUI/lab-servidor.py" "$TMP" "$IP" "$PUERTO" &
SERVIDOR=$!; sleep 1
kill -0 "$SERVIDOR" 2>/dev/null || { echo "No pude abrir el puerto $PUERTO (¿otro servidor lo usa?)"; exit 1; }

for _ in $(seq 1 60); do [ -f "$TMP/agente-visto" ] && break; sleep 3; done
[ -f "$TMP/agente-visto" ] || { echo "El agente de la VM no responde."; exit 1; }

# Cada orden lleva un id único y el agente devuelve resultado-<id>.txt: así nunca se confunde con el de otra tarea.
ID="$(date +%s%N)"
RESULTADO="$TMP/subidas/resultado-$ID.txt"
echo "$ID" > "$TMP/orden-lab.txt"
for _ in $(seq 1 $((ESPERA / 3))); do
    [ -f "$RESULTADO" ] && break
    sleep 3
done
[ -f "$RESULTADO" ] || { echo "Se agotó la espera (${ESPERA}s) sin respuesta de la VM."; exit 1; }

mkdir -p "$SALIDA"
find "$TMP/subidas" -type f ! -name 'resultado-*.txt' -exec cp {} "$SALIDA/" \;
# iconv -c devuelve 1 si descarta bytes inválidos (la consola de Windows usa otra codificación): no es un fallo
{ iconv -f UTF-8 -t UTF-8 -c "$RESULTADO" || true; } | tr -d '\r\0'
