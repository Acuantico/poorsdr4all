"""Servicio del cluster DX (spiderd).

spiderd corre como servicio de usuario (``systemctl --user spiderd.service``) y
sirve los spots en ``ws://127.0.0.1:7373/spots``. Este servicio solo se ocupa de
su **configuración**: renderiza ``~/.config/poorsdr/spiderd.conf`` a partir de las
claves ``SPIDER_*`` y reinicia la unidad de usuario cuando cambian.

Sustituye a ``RadioCBApp._ensure_spiderd_running`` (309 líneas de scripts shell).
El render puro vive en :mod:`poorsdr.core.owrx.spiderd`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from poorsdr.core.owrx.spiderd import render_spiderd_conf
from poorsdr.infra import paths
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus

_UNIT = "spiderd.service"
_SPIDER_KEYS = (
    "SPIDER_SOURCE",
    "SPIDER_MQTT_URL",
    "SPIDER_MQTT_TOPICS",
    "SPIDER_MQTT_USER",
    "SPIDER_MQTT_PASS",
    "SPIDER_TELNET_HOST",
    "SPIDER_TELNET_PORT",
    "SPIDER_TELNET_CALL",
    "SPIDER_TELNET_PASS",
)


def _default_runner(cmd: list[str], timeout: float) -> tuple[int, str]:
    import subprocess

    try:
        proc = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


class SpiderdService(BaseService):
    name = "spiderd"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        conf_path: Path | None = None,
        runner: Callable[[list[str], float], tuple[int, str]] | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._conf_path = conf_path or (paths.config_dir() / "spiderd.conf")
        self._run = runner or _default_runner

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        if not self._cfg.owrx.spots.enabled:
            self._set_status(ServiceState.STOPPED, "spots deshabilitados")
            return
        self._write_conf()
        self._systemctl("restart")
        rc, out = self._systemctl("is-active")
        active = out.strip() == "active"
        self._set_status(
            ServiceState.RUNNING if active else ServiceState.ERROR,
            "activo" if active else f"is-active={out.strip() or rc}",
        )

    def stop(self) -> None:
        # La unidad de usuario es persistente (spots también con la app cerrada);
        # no se detiene aquí.
        self._set_status(ServiceState.STOPPED, "unidad de usuario sigue activa")

    def reconfigure(self, cfg: AppConfig) -> None:
        old = {k: v for k, v in self._cfg.to_legacy().items() if k in _SPIDER_KEYS}
        self._cfg = cfg
        new = {k: v for k, v in cfg.to_legacy().items() if k in _SPIDER_KEYS}
        if new != old:
            self.log.info("config de spiderd cambiada; re-render + restart")
            self.start()

    # ---- internos --------------------------------------------------- #
    def _write_conf(self) -> None:
        text = render_spiderd_conf(self._cfg.to_legacy())
        paths.ensure_dir(self._conf_path.parent)
        tmp = self._conf_path.with_suffix(".conf.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._conf_path)

    def _systemctl(self, action: str) -> tuple[int, str]:
        return self._run(["systemctl", "--user", action, _UNIT], 8.0)


__all__ = ["SpiderdService"]
