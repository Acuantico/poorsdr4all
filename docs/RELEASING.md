# Preparación de una release

Una release oficial se genera desde un árbol limpio. No se publican binarios
compilados localmente ni archivos de configuración del operador.

1. Ejecutar `python scripts/check_release.py` y
   `python scripts/check_owrx_config.py`.
2. Ejecutar `ruff check src tests`, `mypy src` y `pytest -q`.
3. Construir en un entorno limpio:
   `python -m build` y, por separado, cada directorio de `plugins/`.
4. Ejecutar `python scripts/write_checksums.py` y después
   `python scripts/check_artifacts.py`. Los wheel y sdist deben contener licencias
   y avisos, pero ninguna clave, configuración, log, base de datos o biblioteca
   nativa.
5. Instalar cada wheel en un entorno virtual vacío y repetir las pruebas smoke.
6. Esperar a que la CI de Linux, Arch y Windows termine correctamente.
7. Crear el tag `v1.0.0a1` y adjuntar los sdists/wheels generados por CI.

La prueba en Arch del mantenedor es la validación funcional principal. Los
resultados automatizados de otras plataformas deben etiquetarse como tales; no
sustituyen una prueba de hardware real.
