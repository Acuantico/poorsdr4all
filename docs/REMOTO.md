# Control remoto (panel web) y acceso desde internet

El panel web (botón **WEB** de la consola, Ajustes → Web) permite manejar la
radio desde el navegador: frecuencia, modo, banda, PTT y audio en los dos
sentidos por WebRTC.

## PTT seguro

El botón PTT del panel es de **conmutación** (un toque TX, otro toque RX). Por
debajo:

- Mientras transmite, la página confirma el TX cada 100 ms por el canal de
  datos WebRTC (o cada 250 ms por HTTP si el canal no está abierto).
- Si las confirmaciones dejan de llegar (se cae la red, se cierra la pestaña,
  se bloquea el móvil...), el servidor suelta el PTT a los
  `REMOTE_PTT_DEADMAN_MS` (700 ms).
- Tope de transmisión continua: `REMOTE_PTT_MAX_S` (300 s).
- Al soltar se mantiene una cola de `REMOTE_PTT_TAIL_MS` (150 ms) para que
  salga el final de la voz.
- Si la conexión vuelve tras un corte, el TX no se reanuda solo: hay que
  volver a pulsar.

## Acceso desde internet (VPN)

PoorSDR4All lleva un servidor WireGuard propio (no necesita permisos de
administrador ni instalar nada en el equipo). El panel web **no** se abre a
internet: solo se llega a él a través del túnel cifrado.

1. Ajustes → **Web**: pon contraseña y activa el servidor.
2. Ajustes → **VPN**: marca *Acceso desde internet por VPN* y guarda.
3. En el **router**, reenvía el puerto **51821 UDP** (UDP, no TCP) a la IP de
   este equipo que muestra la pestaña VPN. PoorSDR4All no toca el router.
4. *Añadir dispositivo…* → escanea el QR con la app **WireGuard** del móvil
   (Android/iOS).
5. Fuera de casa: activa el túnel en el móvil y abre
   `https://10.9.0.1:8080` (acepta el aviso del certificado: es propio).

Notas:

- La dirección pública del QR se detecta sola. Si tienes un nombre DDNS o la IP
  cambia, escríbelo en *Dirección pública*.
- Si la pestaña avisa de **CG-NAT**, tu operador comparte la IP pública y desde
  fuera no se podrá entrar con ningún reenvío de puertos.
- Con la VPN activa la web solo escucha en local; *Permitir también la red
  local* la deja accesible además desde casa sin VPN.
- Red del túnel: 10.9.0.0/24 (10.9.0.1 es este equipo). Audio WebRTC por los
  puertos UDP 51840-51849 **dentro** del túnel (no hay que abrirlos).
- Las claves y dispositivos se guardan en `vpn.json` (carpeta runtime, solo
  legible por el usuario).

## Medir el remoto sin radio

`scripts/bench_remoto.py` monta salidas virtuales de PipeWire y un cliente
WebRTC y mide RX, TX, PTT→voz, huecos de RX y el hombre muerto, en un entorno
aislado que no toca tu configuración:

```sh
uv run --extra web python scripts/bench_remoto.py --ptt canal
uv run --extra web python scripts/bench_remoto.py --ptt canal --vpn   # todo por el túnel
```

`--vpn` necesita el cliente WireGuard de pruebas:
`cd scripts/vpn/wgrelay && go build -o ~/.cache/psdr-bench/wgrelay .`
El ayudante del producto se compila con `scripts/vpn/build.sh`.
