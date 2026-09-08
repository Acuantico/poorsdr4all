"""Configuración única de logging para toda la aplicación.

El proyecto original tenía ~80 llamadas a ``_owrx_control_log`` y ~40 ``print``
repartidos, más ficheros ``.log`` sin rotar que llegaron a 127 MB. Aquí se
define un solo árbol de loggers bajo ``poorsdr`` con un ``RotatingFileHandler``.
"""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path

from poorsdr.infra import paths

ROOT_LOGGER = "poorsdr"

_MAX_BYTES = 5_000_000
_BACKUP_COUNT = 3
_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure(level: int | str = logging.INFO, *, log_dir: Path | None = None) -> Path:
    """Instala consola + fichero rotativo bajo el logger ``poorsdr``.

    Idempotente: llamarla más de una vez no duplica handlers. Devuelve la ruta
    del fichero de log.
    """
    global _configured

    target_dir = paths.ensure_dir(log_dir or paths.log_dir())
    log_file = target_dir / "poorsdr.log"

    # dictConfig() no cierra por su cuenta los handlers de una configuración
    # previa: solo reemplaza la lista de la instancia de logging.Logger,
    # dejando el fichero anterior abierto y huérfano. Llamar a configure()
    # más de una vez (tests, recarga de Ajustes...) iba acumulando
    # descriptores de fichero sin cerrar — en Linux pasa desapercibido
    # (se puede borrar/mover un fichero abierto), pero en Windows impide
    # borrar o renombrar el propio fichero de log mientras el proceso siga
    # vivo con el handler antiguo aún abierto.
    for handler in list(logging.getLogger(ROOT_LOGGER).handlers):
        handler.close()

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"standard": {"format": _FMT, "datefmt": _DATEFMT}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "level": logging.DEBUG,
                    "filename": str(log_file),
                    "maxBytes": _MAX_BYTES,
                    "backupCount": _BACKUP_COUNT,
                    "encoding": "utf-8",
                },
            },
            "loggers": {
                ROOT_LOGGER: {
                    "handlers": ["console", "file"],
                    "level": logging.DEBUG,
                    "propagate": False,
                },
            },
        }
    )
    _configured = True
    return log_file


def get_logger(name: str | None = None) -> logging.Logger:
    """Devuelve ``poorsdr`` o ``poorsdr.<name>``.

    Si aún no se llamó a :func:`configure`, lo hace con valores por defecto para
    que ninguna traza se pierda (útil en tests e imports tempranos).
    """
    if not _configured:
        configure()
    if not name or name == ROOT_LOGGER:
        return logging.getLogger(ROOT_LOGGER)
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")


def is_configured() -> bool:
    return _configured


__all__ = ["ROOT_LOGGER", "configure", "get_logger", "is_configured"]
