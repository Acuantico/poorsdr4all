"""Servicio de memorias de frecuencia.

Estado + persistencia JSON en ``~/.config/poorsdr/memories.json`` (XDG). En el
primer arranque importa el ``memo.json`` del proyecto original si existe. La
lógica de validación es pura (:mod:`poorsdr.core.memory`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from poorsdr.core import memory as m
from poorsdr.infra import paths
from poorsdr.services.base import BaseService, ServiceState

if TYPE_CHECKING:
    from poorsdr.config.model import AppConfig
    from poorsdr.core.memory import MemoryEntry
    from poorsdr.infra.events import EventBus


class MemoryService(BaseService):
    name = "memory"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        *,
        path: Path | None = None,
        import_from: Path | None = None,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._path = path or (paths.config_dir() / "memories.json")
        # Fuente para importar en el primer arranque; los tests apuntan a un
        # fichero inexistente para aislarse del memo.json real del usuario.
        self._import_from = import_from or (paths.LEGACY_HOME / "memo.json")
        self._entries: list[MemoryEntry] = []

    # ---- ciclo de vida -------------------------------------------------- #
    def start(self) -> None:
        self._entries = self._read()
        self._set_status(ServiceState.RUNNING, f"{len(self._entries)} memoria(s)")
        self._publish()

    def stop(self) -> None:
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    # ---- API ------------------------------------------------------- #
    @property
    def entries(self) -> list[MemoryEntry]:
        return list(self._entries)

    def add(self, entry: MemoryEntry) -> None:
        self._entries = m.upsert(self._entries, entry)
        self._write()

    def remove(self, index: int) -> None:
        self._entries = m.remove_at(self._entries, index)
        self._write()

    def get(self, index: int) -> MemoryEntry | None:
        return self._entries[index] if 0 <= index < len(self._entries) else None

    # ---- IO ------------------------------------------------------ #
    def _read(self) -> list[MemoryEntry]:
        source = self._path
        if not source.exists():
            if self._import_from.exists():
                self.log.info("importando memorias de %s", self._import_from)
                source = self._import_from
            else:
                return []
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.log.error("no se pudo leer %s: %s", source, exc)
            return []
        entries = m.normalize_entries(raw)
        if source != self._path:  # migración: persistir en la ruta nueva
            self._entries = entries
            self._write()
        return entries

    def _write(self) -> None:
        paths.ensure_dir(self._path.parent)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(m.to_json_list(self._entries), indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)
        self._publish()

    def _publish(self) -> None:
        self.bus.publish("memory.changed", count=len(self._entries))


__all__ = ["MemoryService"]
