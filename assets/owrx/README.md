# Plantilla OpenWebRX+ de PoorSDR4All

`settings.json` es una configuración inicial neutra para OpenWebRX+ 1.2.119
(esquema 8). El instalador sólo la copia cuando aún no existe una configuración
o cuando se solicita expresamente `RESET_OWRX_CONFIG=1`.

La plantilla contiene exactamente los diez perfiles que selecciona la consola:
160, 80, 60, 40, 30, 20, 17, 15, 11 y 10 metros. El nombre visible de cada
perfil (`RTL 40m`, por ejemplo), su frecuencia inicial y su modo se validan con
`scripts/check_owrx_config.py` para evitar que PoorSDR y OpenWebRX+ diverjan.

## Supuesto de hardware

El receptor inicial es el primer RTL-SDR (`device: "0"`). Los perfiles por
debajo de 24 MHz activan el muestreo directo por la rama Q
(`direct_sampling: 2`), igual que los perfiles HF de referencia de OpenWebRX+.
Los perfiles de 10 y 11 metros usan el sintonizador normal.

Esto es apropiado para un RTL-SDR clásico conectado para muestreo directo, pero
no puede ser universal:

- RTL-SDR Blog V4: puede necesitar `direct_sampling: 0` y sus controladores
  actuales para utilizar la ruta HF interna.
- Upconverter: debe usarse `direct_sampling: 0` y configurar `lfo_offset` con la
  frecuencia del oscilador del conversor.
- Otro SDR: hay que crear el dispositivo correspondiente y conservar nombres de
  perfil que coincidan con `OWRX_BAND_PROFILES` en PoorSDR.

La ganancia inicial es 29 dB y la corrección es 0 ppm; ambas deben calibrarse en
la interfaz administrativa de OpenWebRX+. Los niveles del waterfall se ajustan
automáticamente para no distribuir una calibración particular del mantenedor.

## Actualizaciones seguras

Una instalación normal conserva `/var/lib/openwebrx/settings.json`, usuarios y
marcadores. `RESET_OWRX_CONFIG=1 scripts/install.sh` crea primero una copia
fechada y después instala esta plantilla. No uses el reset sin revisar la copia
de seguridad si ya tienes varios SDR o perfiles propios.
