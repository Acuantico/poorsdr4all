#!/bin/bash
# Instala OpenWebRX+ en la distribución ejecutando el install.sh OFICIAL de PoorSDR4All, sin tocarlo.
# Argumentos: $1 = ruta (de WSL) del paquete poorsdr4all-<versión>.tar.gz
# OpenWebRX+ y su pila (csdr, pycsdr, owrx_connector) se clonan en revisiones fijadas y se compilan
# aquí, en el equipo del usuario: nunca se distribuyen compilados (licencias GPL/AGPL).
set -u
PAYLOAD="${1:?falta la ruta del paquete}"
VERSION="${2:-desconocida}"
cd ~ || exit 1
rm -rf poorsdr4all
tar -xzf "$PAYLOAD" || { echo "ERROR: no se pudo extraer el paquete"; exit 1; }
cd poorsdr4all || exit 1
# Aquí hace falta OpenWebRX+ y spiderd (spots); la aplicación de escritorio corre en Windows.
export INSTALL_WEB_EXTRAS=0 INSTALL_7LED_FONT=0 INSTALL_PLUGIN_RTTY=0 INSTALL_PLUGIN_NMN1M=0
export DEBIAN_FRONTEND=noninteractive
bash scripts/install.sh 2>&1
rc=$?
if [ $rc -eq 0 ]; then
    echo "$VERSION" > ~/.poorsdr_owrx_ok
fi
echo "install.sh terminó con código $rc"
exit $rc
