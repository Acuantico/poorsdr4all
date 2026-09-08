# Plugins de PoorSDR4All

Cada carpeta es un **proyecto Python independiente** (su propio `pyproject.toml`)
que declara un *entry point* del grupo `poorsdr.plugins`. PoorSDR los detecta al
arrancar; sin ninguno instalado la consola funciona igual (sin botón «Log», sin
relés y sin la pestaña «Relés» en Ajustes).

## Instalar

Desde el árbol fuente se instalan después del paquete principal:

```sh
python -m pip install ./plugins/filter-relays
```

Para desarrollar un plugin se puede añadir `-e`. Los datos mutables no se
guardan en el árbol fuente ni dentro de `site-packages`.

### Nunca Más, Ni Una Más (NMN1M)

El cuaderno de estación / contest logger que aporta el botón «Log» **no** vive
en este repositorio — es un proyecto independiente, con su propio repositorio,
licencia y ciclo de publicación. Instálalo por separado (en el mismo entorno
que PoorSDR4All) para que la consola lo descubra; sin él, la consola funciona
igual, solo sin ese botón.

## Activar / desactivar

Ajustes → pestaña **Plugins**: un check por plugin detectado. El estado se guarda
en `config.json` bajo la clave `PLUGINS` (`{id: bool}`); lo no listado se
considera activo. Los cambios se aplican al reiniciar PoorSDR.

## Escribir un plugin

```python
class MiPlugin:
    id = "mi_plugin"
    name = "Mi plugin"

    def register(self, ctx):
        ctx.add_service(MiServicio(ctx.bus, ctx.config))      # servicio en 2º plano
        ctx.add_console_button("mi_boton", "Etiqueta", self._abrir)  # botón en la consola
        ctx.add_settings_tab("Mi pestaña", (                  # pestaña en Ajustes
            Field("mi_seccion", "algo", "Etiqueta del campo", "bool"),
        ))

    def shutdown(self):  # opcional
        ...

PLUGIN = MiPlugin()
```

`pyproject.toml` del plugin:

```toml
[project.entry-points."poorsdr.plugins"]
mi_plugin = "mi_paquete.plugin:PLUGIN"
```
