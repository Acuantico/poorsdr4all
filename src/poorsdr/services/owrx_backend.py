"""Servicio del backend OpenWebRX+ (systemd).

Con runtime nativo, PoorSDR gobierna el ciclo de vida de ``openwebrx.service``:
lo arranca al abrirse (``sudo -n systemctl start``, sin contraseña gracias a la
regla de sudoers de ``install.sh``) y lo detiene al cerrarse, salvo
``OWRX_STOP_ON_EXIT=false`` o backend remoto.

Portado de ``RadioCBApp._ensure_internal_owrx_server`` /
``_stop_internal_owrx_server``. La lógica pura vive en
:mod:`poorsdr.core.owrx.backend`.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from poorsdr.core.owrx.backend import (
    backend_http_url,
    body_looks_like_owrx,
    service_command,
    should_manage_backend,
    should_stop_on_exit,
)
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus

def _default_runner(cmd: list[str], timeout: float) -> tuple[int, str]:
    import subprocess

    try:
        proc = subprocess.run(  # noqa: S603 - comando fijo de core.owrx.backend
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _default_http_probe(url: str, timeout: float) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - http local
            return resp.read(65536).decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError, ValueError):
        return None


class OwrxBackendService(BaseService):
    name = "owrx-backend"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        runner: Callable[[list[str], float], tuple[int, str]] | None = None,
        http_probe: Callable[[str, float], str | None] | None = None,
        sleep: Callable[[float], None] | None = None,
        ready_timeout_s: float = 20.0,
        poll_interval_s: float = 1.0,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._run = runner or _default_runner
        self._probe = http_probe or _default_http_probe
        self._sleep = sleep or time.sleep
        self._ready_timeout_s = ready_timeout_s
        self._poll_interval_s = poll_interval_s

    # ---- helpers ----------------------------------------------------- #
    def _manage(self, cfg: AppConfig) -> bool:
        return should_manage_backend(
            enabled=cfg.owrx.enabled, runtime=cfg.owrx.runtime, host=cfg.owrx.host
        )

    def _url(self, cfg: AppConfig) -> str:
        return backend_http_url(cfg.owrx.host, cfg.owrx.port)

    def _ready(self, url: str, timeout: float = 1.8) -> bool:
        return body_looks_like_owrx(self._probe(url, timeout))

    def _wait_ready(self, url: str) -> bool:
        interval = max(0.01, self._poll_interval_s)
        attempts = max(1, int(self._ready_timeout_s / interval))
        for i in range(attempts):
            if self._ready(url):
                return True
            if i < attempts - 1:
                self._sleep(interval)
        return False

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        cfg = self._cfg
        if not cfg.owrx.enabled:
            self._set_status(ServiceState.STOPPED, "deshabilitado")
            self._publish(ready=False)
            return

        self._set_status(ServiceState.STARTING)
        url = self._url(cfg)

        if self._ready(url):
            self._set_status(ServiceState.RUNNING, "ya en marcha")
            self._publish(ready=True)
            return

        if not self._manage(cfg):
            # Backend remoto / runtime no nativo: solo se observa.
            self._set_status(ServiceState.ERROR, "backend remoto sin responder")
            self._publish(ready=False)
            return

        rc, out = self._run(service_command("start"), 8.0)
        if rc != 0:
            self.log.warning("systemctl start %s devolvió %s: %s", "openwebrx.service", rc, out.strip())

        if self._wait_ready(url):
            self._set_status(ServiceState.RUNNING)
            self._publish(ready=True)
        else:
            self._set_status(ServiceState.ERROR, "openwebrx.service no responde")
            self._publish(ready=False)

    def stop(self) -> None:
        cfg = self._cfg
        if should_stop_on_exit(manage=self._manage(cfg), stop_on_exit=cfg.owrx.stop_on_exit):
            rc, out = self._run(service_command("stop"), 8.0)
            if rc != 0:
                self.log.debug("systemctl stop devolvió %s: %s", rc, out.strip())
        self._set_status(ServiceState.STOPPED)
        self._publish(ready=False)

    def reconfigure(self, cfg: AppConfig) -> None:
        keys = (
            cfg.owrx.enabled,
            cfg.owrx.host,
            cfg.owrx.port,
            cfg.owrx.runtime,
            cfg.owrx.stop_on_exit,
        )
        old = self._cfg.owrx
        old_keys = (old.enabled, old.host, old.port, old.runtime, old.stop_on_exit)
        self._cfg = cfg
        if keys != old_keys:
            self.log.info("config OWRX backend cambiada; reiniciando")
            self.stop()
            self.start()

    # ---- eventos ---------------------------------------------------- #
    def _publish(self, *, ready: bool) -> None:
        self.bus.publish(
            "owrx.status",
            component="backend",
            ready=ready,
            url=self._url(self._cfg),
        )


__all__ = ["OwrxBackendService"]
