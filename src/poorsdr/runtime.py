"""Composition root: ensambla bus + config + servicios.

Punto único donde se instancian y conectan los subsistemas. ``poorsdr.ui.app``
construye aquí su :class:`AppContext` y lo publica con :func:`set_active` para que
cualquier componente pueda alcanzar los servicios por :func:`get_service`.
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from poorsdr.config import loader
from poorsdr.config.model import AppConfig
from poorsdr.infra import paths
from poorsdr.infra.events import EventBus
from poorsdr.infra.logging import get_logger
from poorsdr.plugins import PluginContext, PluginManager
from poorsdr.services.audio import AudioService
from poorsdr.services.autocall import AutocallService
from poorsdr.services.base import ServiceManager
from poorsdr.services.memory import MemoryService
from poorsdr.services.n1m import N1mService
from poorsdr.services.owrx_backend import OwrxBackendService
from poorsdr.services.owrx_client import OwrxClientService
from poorsdr.services.owrx_control import OwrxControlService
from poorsdr.services.radio import RadioService
from poorsdr.services.rigctld import RigctldService
from poorsdr.services.spiderd import SpiderdService
from poorsdr.services.web import WebServerService

if TYPE_CHECKING:
    from collections.abc import Iterable

    from poorsdr.services.base import Service

_log = get_logger("runtime")

VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"
VENDOR_CONFIG_PATH = paths.runtime_dir() / "config.json"


def install_vendor_path() -> None:
    """Deja ``poorsdr/_vendor`` importable — lo necesitan las fábricas de servicios
    que envuelven los módulos de bajo nivel (``cat``, ``audio``, ``rigctld_proxy``,
    ``webserver``, ``owrx_client``…)."""
    vendor = str(VENDOR_DIR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def write_vendor_config(cfg: AppConfig, path: Path | None = None) -> None:
    """Vuelca ``cfg`` en un puente plano dentro del directorio de datos.

    Lo leen dos cosas: ``_vendor/audio.py`` al importarse (una vez, config de
    arranque) y los visores externos por ``OWRX_CONFIG_PATH`` (vigilan su
    mtime para detectar en caliente, p. ej., el tema activo). Por eso no
    basta con escribirlo solo al arrancar — hay que rehacerlo en cada
    ``AppContext.reconfigure()`` o un cambio de tema en Ajustes no llega a
    los visores hasta reiniciar la app entera.
    """
    target = path or VENDOR_CONFIG_PATH
    paths.ensure_dir(target.parent)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg.to_legacy(), indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    with contextlib.suppress(OSError):
        target.chmod(0o600)


@dataclass
class AppContext:
    """Estado vivo de la aplicación: bus, config, servicios y plugins."""

    config: AppConfig
    bus: EventBus = field(default_factory=EventBus)
    services: ServiceManager = field(init=False)
    plugins: PluginManager = field(init=False)

    def __post_init__(self) -> None:
        self.services = ServiceManager(self.bus)
        self.plugins = PluginManager()

    # ---- ciclo de vida ---------------------------------------------- #
    def start(self) -> None:
        _log.info("arrancando %d servicio(s)", sum(1 for _ in self.services))
        self.services.start_all()

    def stop(self) -> None:
        self.services.stop_all()
        self.plugins.shutdown_all()

    def reconfigure(self, config: AppConfig, *, persist: bool = True) -> None:
        self.config = config
        if persist:
            loader.save(config)
            write_vendor_config(config)
        self.services.reconfigure_all(config)


_DEFAULT_SERVICE_NAMES = (
    "radio",
    "audio",
    "rigctld",
    "n1m",
    "autocall",
    "owrx-backend",
    "owrx-client",
    "owrx-control",
    "spiderd",
    "web",
    "memory",
)


def build_context(
    config: AppConfig | None = None,
    *,
    services: Iterable[str] = _DEFAULT_SERVICE_NAMES,
    plugins: bool = True,
) -> AppContext:
    """Crea el ``AppContext`` con los servicios indicados registrados en orden.

    El orden importa: ``radio`` antes que ``rigctld`` (el proxy lee el controlador
    de la radio) y antes que ``owrx-client`` (que sigue a ``radio.*``).
    """
    ctx = AppContext(config=config or loader.load())
    wanted = list(services)

    radio: RadioService | None = None
    audio: AudioService | None = None
    if "radio" in wanted:
        radio = RadioService(ctx.bus, ctx.config)
        ctx.services.register(radio)
    if "audio" in wanted:
        audio = AudioService(ctx.bus, ctx.config)
        ctx.services.register(audio)
    if "rigctld" in wanted:
        if radio is None:
            radio = RadioService(ctx.bus, ctx.config)
            ctx.services.register(radio)
        ctx.services.register(RigctldService(ctx.bus, ctx.config, radio))
    if "n1m" in wanted:
        ctx.services.register(N1mService(ctx.bus, ctx.config))
    if "autocall" in wanted:
        if radio is None:
            radio = RadioService(ctx.bus, ctx.config)
            ctx.services.register(radio)
        if audio is None:
            audio = AudioService(ctx.bus, ctx.config)
            ctx.services.register(audio)
        ctx.services.register(
            AutocallService(ctx.bus, ctx.config, radio, play_audio=audio.play_file)
        )
    if "owrx-backend" in wanted:
        ctx.services.register(OwrxBackendService(ctx.bus, ctx.config))
    if "owrx-client" in wanted:
        ctx.services.register(OwrxClientService(ctx.bus, ctx.config))
    if "owrx-control" in wanted:
        if audio is None:
            audio = AudioService(ctx.bus, ctx.config)
            ctx.services.register(audio)
        ctx.services.register(
            OwrxControlService(ctx.bus, ctx.config, audio_push=audio.push_owrx_chunk)
        )
    if "spiderd" in wanted:
        ctx.services.register(SpiderdService(ctx.bus, ctx.config))
    if "web" in wanted:
        if radio is None:
            radio = RadioService(ctx.bus, ctx.config)
            ctx.services.register(radio)
        if audio is None:
            audio = AudioService(ctx.bus, ctx.config)
            ctx.services.register(audio)
        ctx.services.register(WebServerService(ctx.bus, ctx.config, radio, audio))
    if "memory" in wanted:
        ctx.services.register(MemoryService(ctx.bus, ctx.config))

    if plugins:
        enabled = ctx.config.extra.get("PLUGINS")
        ctx.plugins = PluginManager(enabled if isinstance(enabled, dict) else {})
        ctx.plugins.discover()
        ctx.plugins.register_all(
            PluginContext(bus=ctx.bus, config=ctx.config, services=ctx.services)
        )

    return ctx


# --------------------------------------------------------------------------- #
# Acceso al contexto activo
# --------------------------------------------------------------------------- #
_active: AppContext | None = None


def set_active(ctx: AppContext | None) -> None:
    """Registra (o limpia) el contexto activo de la aplicación."""
    global _active
    _active = ctx


def active() -> AppContext | None:
    """Contexto activo, o ``None`` si la app aún no ha arrancado."""
    return _active


def get_service(name: str) -> Service | None:
    ctx = _active
    return ctx.services.get(name) if ctx is not None else None


__all__ = [
    "VENDOR_DIR",
    "VENDOR_CONFIG_PATH",
    "AppContext",
    "active",
    "build_context",
    "get_service",
    "install_vendor_path",
    "set_active",
    "write_vendor_config",
]
