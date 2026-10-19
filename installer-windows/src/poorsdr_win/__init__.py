"""Soporte de Windows para PoorSDR4All: OpenWebRX+ dentro de WSL2.

PoorSDR4All usa OpenWebRX+, que solo funciona en Linux. En Windows corre en una
distribución WSL2 propia (``PoorSDR4All``) que este paquete instala y controla.
No modifica el código de PoorSDR4All: solo lo envuelve (arranque y parada).
"""

DISTRO = "PoorSDR4All"
SERVICE = "openwebrx.service"
OWRX_PORT = 8073
