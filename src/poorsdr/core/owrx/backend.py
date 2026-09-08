"""Lógica pura de gestión del backend OpenWebRX+.

En el proyecto original esto vivía inline en ``RadioCBApp._ensure_internal_owrx_server``
/ ``_stop_internal_owrx_server``. Aquí quedan como funciones puras y testeables;
la ejecución de ``systemctl`` y las peticiones HTTP las hace
:mod:`poorsdr.services.owrx_backend`.
"""

from __future__ import annotations

SERVICE_UNIT = "openwebrx.service"
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})
_VALID_BODY_MARKERS = ("openwebrx", "webrx", "receiver")


def is_local_host(host: str | None) -> bool:
    """``True`` si el backend corre en la misma máquina (PoorSDR gobierna su ciclo)."""
    return (host or "").strip().lower() in _LOCAL_HOSTS


def should_manage_backend(*, enabled: bool, runtime: str, host: str | None) -> bool:
    """¿Debe PoorSDR arrancar/parar el servicio systemd?

    Solo con OWRX habilitado, runtime ``native`` y backend local. Un backend
    remoto o el runtime Docker/otro no se tocan.
    """
    return bool(enabled) and (runtime or "native").strip().lower() == "native" and is_local_host(host)


def should_stop_on_exit(*, manage: bool, stop_on_exit: bool) -> bool:
    """¿Parar el servicio al cerrar PoorSDR?"""
    return bool(manage) and bool(stop_on_exit)


def service_command(action: str) -> list[str]:
    """Comando ``systemctl`` sin contraseña para ``start`` / ``stop`` / ``status``.

    ``sudo -n`` no cuelga en un diálogo si falta la regla de sudoers; simplemente
    falla, y el servicio se comprueba luego por HTTP.
    """
    if action not in {"start", "stop", "restart", "status"}:
        raise ValueError(f"acción systemctl no soportada: {action!r}")
    return ["sudo", "-n", "systemctl", action, SERVICE_UNIT]


def backend_http_url(host: str | None, port: int) -> str:
    resolved = (host or "").strip() or "127.0.0.1"
    return f"http://{resolved}:{int(port)}/"


def body_looks_like_owrx(body: str | bytes | None) -> bool:
    """Heurística del original: la home del backend menciona OpenWebRX."""
    if body is None:
        return False
    text = body.decode("utf-8", "ignore") if isinstance(body, bytes) else body
    text = text.lower()
    return any(marker in text for marker in _VALID_BODY_MARKERS)


__all__ = [
    "SERVICE_UNIT",
    "backend_http_url",
    "body_looks_like_owrx",
    "is_local_host",
    "service_command",
    "should_manage_backend",
    "should_stop_on_exit",
]
