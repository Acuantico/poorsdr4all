# Seguridad

## Comunicar una vulnerabilidad

No publiques inicialmente detalles explotables en una incidencia pública.
Envía el informe mediante el canal privado **Security advisories** del
repositorio de GitHub. Incluye versión afectada, plataforma, impacto y pasos
mínimos para reproducirlo.

Si el repositorio aún no dispone de avisos privados, utiliza el formulario
https://acuanticopower.com/contacto/ indicando “PoorSDR4All security”.

Se acusará recibo tan pronto como sea posible. No se promete un plazo fijo para
una Alpha, pero se publicará una corrección y un aviso coordinados cuando el
problema esté confirmado.

## Alcance de soporte

Solo la versión más reciente recibe correcciones. OpenWebRX+, csdr, pycsdr,
owrx_connector, SpeexDSP y los demás proyectos externos mantienen sus propios
canales de seguridad.

El servidor web remoto permanece desactivado de forma predeterminada y se niega
a arrancar sin contraseña y secreto de firma configurados. No expongas CAT,
rigctld, spiderd ni OpenWebRX directamente a Internet.
