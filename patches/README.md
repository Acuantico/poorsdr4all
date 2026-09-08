# Parches a dependencias

Los parches se aplican sobre las revisiones fijadas en `scripts/install.sh` y
forman parte del código fuente correspondiente de las modificaciones GPL/AGPL.

- `pycsdr/0001-*`: compatibilidad con GCC 15; conserva GPL-3.0-or-later.
- `openwebrx/0001-*`: sustituye la API retirada `pkg_resources` por
  `importlib.resources`; conserva AGPL-3.0-or-later.

El instalador comprueba que cada parche aplica limpiamente. Si cambia una
revisión upstream, se debe regenerar y revisar el parche antes de actualizarla.
