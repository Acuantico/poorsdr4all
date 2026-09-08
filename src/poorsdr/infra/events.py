"""Bus de eventos mínimo, síncrono y thread-safe.

Sustituye a las decenas de *reach-ins* del proyecto original, donde un subsistema
tocaba directamente atributos de otro a través del objeto ``RadioCBApp`` (God
object). Aquí cada servicio publica hechos (``radio.frequency``, ``owrx.band``,
``config.changed``, …) y quien necesite reaccionar se suscribe.

Contrato:
- ``publish`` invoca a los suscriptores en el hilo que publica, bajo un lock.
- Una excepción en un suscriptor se registra y **no** interrumpe al resto ni se
  propaga a quien publicó.
- ``subscribe`` devuelve un callable que cancela la suscripción.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from poorsdr.infra.logging import get_logger

_log = get_logger("events")


@dataclass(frozen=True, slots=True)
class Event:
    """Un evento publicado en el bus."""

    topic: str
    data: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


Subscriber = Callable[[Event], None]
Unsubscribe = Callable[[], None]


class EventBus:
    """Pub/sub por temas exactos."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[Subscriber]] = {}

    def subscribe(self, topic: str, callback: Subscriber) -> Unsubscribe:
        """Registra ``callback`` para ``topic`` y devuelve su cancelador."""
        with self._lock:
            self._subscribers.setdefault(topic, []).append(callback)

        def _cancel() -> None:
            self.unsubscribe(topic, callback)

        return _cancel

    def unsubscribe(self, topic: str, callback: Subscriber) -> None:
        with self._lock:
            handlers = self._subscribers.get(topic)
            if not handlers:
                return
            try:
                handlers.remove(callback)
            except ValueError:
                return
            if not handlers:
                del self._subscribers[topic]

    def publish(self, topic: str, /, **data: Any) -> Event:
        """Emite un :class:`Event` a los suscriptores de ``topic``."""
        event = Event(topic=topic, data=dict(data))
        with self._lock:
            handlers = list(self._subscribers.get(topic, ()))
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - un suscriptor no debe tumbar el bus
                _log.exception("suscriptor de %r falló", topic)
        return event

    def topics(self) -> list[str]:
        with self._lock:
            return sorted(self._subscribers)

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()


__all__ = ["Event", "EventBus", "Subscriber", "Unsubscribe"]
