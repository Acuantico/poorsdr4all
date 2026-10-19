#!/bin/bash
# Prepara la distribución de PoorSDR4All: usuario sin contraseña con sudo y systemd activado.
# Se ejecuta como root dentro de la distribución (la distribución es privada de PoorSDR4All).
set -e
id poorsdr >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo poorsdr
echo 'poorsdr ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/poorsdr
chmod 440 /etc/sudoers.d/poorsdr
printf '[boot]\nsystemd=true\n[user]\ndefault=poorsdr\n' > /etc/wsl.conf
# Servicio de usuario de systemd sin sesión abierta (spiderd): equivale a «loginctl enable-linger poorsdr».
mkdir -p /var/lib/systemd/linger && touch /var/lib/systemd/linger/poorsdr
echo "usuario, linger y systemd listos"
