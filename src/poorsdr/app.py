"""Punto de entrada de PoorSDR4All.

Arranca la interfaz (``poorsdr.ui``) sobre el composition root
(``poorsdr.runtime``). Los subsistemas de bajo nivel (DSP de audio, CAT,
proxy rigctld, servidor web…) viven vendorizados en ``poorsdr._vendor`` y los
envuelve la capa de servicios.
"""

from __future__ import annotations

import logging

from poorsdr.config import loader
from poorsdr.infra import logging as plog
from poorsdr.infra import paths


def main(argv: list[str] | None = None) -> int:
    plog.configure(level=logging.INFO)
    paths.ensure_runtime_dirs()
    log = plog.get_logger("app")

    from poorsdr import __version__, runtime

    log.info("PoorSDR4All %s — arrancando", __version__)

    runtime.install_vendor_path()
    # El módulo _vendor/audio.py (y los visores externos, vía OWRX_CONFIG_PATH)
    # leen su config de este JSON plano; runtime.write_vendor_config() también
    # lo rehace en cada AppContext.reconfigure(), no solo aquí al arrancar.
    runtime.write_vendor_config(loader.load())

    try:
        from poorsdr.ui.app import main as ui_main
    except ImportError:
        log.exception("no se pudo cargar la interfaz (¿falta tkinter?)")
        return 1
    return ui_main()


if __name__ == "__main__":
    raise SystemExit(main())
