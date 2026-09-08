"""Contrato de servicio y gestor de servicios.

Cada subsistema (radio/CAT, proxy rigctld, backend OWRX, cliente OWRX, audio…)
se implementa como un objeto con estado que sabe arrancar, parar y
**reconfigurarse en caliente**. El ``ServiceManager`` los orquesta y, al guardar
Ajustes, les propaga la nueva ``AppConfig`` — así se absorbe el antiguo
"guardar y reiniciar la app entera".
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from poorsdr.infra.logging import get_logger

if TYPE_CHECKING:
    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus

_log = get_logger("services")


class ServiceState(enum.Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    state: ServiceState
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state is ServiceState.RUNNING


@runtime_checkable
class Service(Protocol):
    """Interfaz que implementa cada subsistema."""

    name: str

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def reconfigure(self, cfg: AppConfig) -> None:
        """Aplica ``cfg`` en caliente; reinicia internamente lo imprescindible."""

    @property
    def status(self) -> ServiceStatus: ...


class BaseService:
    """Base opcional con estado y logging listos; los servicios reales heredan."""

    name: str = "service"

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.log = get_logger(f"services.{self.name}")
        self._status = ServiceStatus(ServiceState.STOPPED)

    @property
    def status(self) -> ServiceStatus:
        return self._status

    def _set_status(self, state: ServiceState, detail: str = "") -> None:
        self._status = ServiceStatus(state, detail)
        self.bus.publish("service.status", name=self.name, state=state.value, detail=detail)

    # Métodos que los servicios concretos sobreescriben ------------------- #
    def start(self) -> None:  # pragma: no cover - contrato
        self._set_status(ServiceState.RUNNING)

    def stop(self) -> None:  # pragma: no cover - contrato
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:  # pragma: no cover - contrato
        """Por defecto: parar y volver a arrancar."""
        self.stop()
        self.start()


class ServiceManager:
    """Registra servicios y orquesta su ciclo de vida."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._services: list[Service] = []

    def register(self, service: Service) -> Service:
        self._services.append(service)
        return service

    def __iter__(self) -> Iterator[Service]:
        return iter(self._services)

    def get(self, name: str) -> Service | None:
        return next((s for s in self._services if s.name == name), None)

    def start_all(self) -> None:
        for service in self._services:
            self._guard(service, "start", service.start)

    def stop_all(self) -> None:
        for service in reversed(self._services):
            self._guard(service, "stop", service.stop)

    def reconfigure_all(self, cfg: AppConfig) -> None:
        for service in self._services:
            self._guard(service, "reconfigure", partial(service.reconfigure, cfg))
        self.bus.publish("config.changed")

    def statuses(self) -> dict[str, ServiceStatus]:
        return {s.name: s.status for s in self._services}

    @staticmethod
    def _guard(service: Service, action: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - un servicio no debe tumbar al resto
            _log.exception("servicio %r falló en %s()", getattr(service, "name", "?"), action)


__all__ = [
    "BaseService",
    "Service",
    "ServiceManager",
    "ServiceState",
    "ServiceStatus",
]
