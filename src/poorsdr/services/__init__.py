"""Servicios de subsistema (imperative shell)."""

from __future__ import annotations

from poorsdr.services.audio import AudioService
from poorsdr.services.autocall import AutocallService
from poorsdr.services.base import (
    BaseService,
    Service,
    ServiceManager,
    ServiceState,
    ServiceStatus,
)
from poorsdr.services.filter_relays import FilterRelayService
from poorsdr.services.memory import MemoryService
from poorsdr.services.n1m import N1mService
from poorsdr.services.owrx_backend import OwrxBackendService
from poorsdr.services.owrx_client import OwrxClientService
from poorsdr.services.owrx_control import OwrxControlService
from poorsdr.services.radio import RadioService
from poorsdr.services.rigctld import RigctldService
from poorsdr.services.spiderd import SpiderdService
from poorsdr.services.web import WebServerService

__all__ = [
    "AudioService",
    "AutocallService",
    "BaseService",
    "FilterRelayService",
    "MemoryService",
    "N1mService",
    "OwrxBackendService",
    "OwrxClientService",
    "OwrxControlService",
    "RadioService",
    "RigctldService",
    "SpiderdService",
    "Service",
    "ServiceManager",
    "ServiceState",
    "ServiceStatus",
    "WebServerService",
]
