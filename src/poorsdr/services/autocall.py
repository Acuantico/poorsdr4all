"""Servicio de llamada automática (macro de CQ).

Reescribe el bucle de ``_legacy/autocall.py`` sobre el bus: en vez de tocar
``cat_controller`` y el módulo ``audio`` globales, usa :class:`RadioService` para
el PTT y un callback ``play_audio`` inyectable (lo aportará ``services/audio``).
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import TYPE_CHECKING

from poorsdr.core.autocall import (
    BUTTON_COUNT,
    AutocallProfile,
    button_targets,
    slots_from_config,
)
from poorsdr.services.base import BaseService, ServiceState
from poorsdr.services.tx_playback import precise_wait

if TYPE_CHECKING:
    from collections.abc import Callable

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.events import EventBus
    from poorsdr.services.radio import RadioService


#: Pausa exacta (s) entre activar el PTT y emitir la primera muestra: la radio
#: necesita pasar a TX antes de que llegue audio, o se come el principio.
PTT_LEAD_S = 0.20
#: Cola (s) con el PTT activo tras la última muestra, para que no se corte el final.
PTT_TAIL_S = 0.40


def _noop_play(  # pragma: no cover
    path: str,
    stop_checker: Callable[[], bool],
    on_ready: Callable[[], bool] | None = None,
) -> bool:
    return False


class AutocallService(BaseService):
    name = "autocall"

    def __init__(
        self,
        bus: EventBus,
        cfg: AppConfig,
        radio: RadioService,
        *,
        play_audio: Callable[..., bool] | None = None,
        sleep: Callable[[float], None] | None = None,
        ptt_lead_s: float = PTT_LEAD_S,
        ptt_tail_s: float = PTT_TAIL_S,
    ) -> None:
        super().__init__(bus)
        self._cfg = cfg
        self._radio = radio
        self._play = play_audio or _noop_play
        self._sleep = sleep or time.sleep
        self._ptt_lead_s = max(0.0, float(ptt_lead_s))
        self._ptt_tail_s = max(0.0, float(ptt_tail_s))
        self._ptt_on = False
        self._profiles: list[AutocallProfile] = []
        self._buttons: list[int] = list(range(BUTTON_COUNT))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- ciclo de vida -------------------------------------------------- #
    def _load(self) -> None:
        legacy = self._cfg.to_legacy()
        self._profiles = slots_from_config(legacy)
        self._buttons = button_targets(legacy)

    def start(self) -> None:
        self._load()
        self._set_status(ServiceState.RUNNING, f"{len(self._profiles)} macro(s)")

    def stop(self) -> None:
        self.cancel()
        self._set_status(ServiceState.STOPPED)

    def reconfigure(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._load()

    # ---- API ------------------------------------------------------- #
    @property
    def profiles(self) -> list[AutocallProfile]:
        return list(self._profiles)

    @property
    def button_labels(self) -> list[str]:
        """Título de la macro asignada a cada botón (para pintar los círculos)."""
        out: list[str] = []
        for idx in self._buttons:
            prof = self._profiles[idx] if 0 <= idx < len(self._profiles) else None
            out.append(prof.title if prof and prof.valid else "")
        return out

    def run_button(self, button: int) -> bool:
        """Lanza la macro asignada al botón ``button`` (0-3) de la consola."""
        if not (0 <= button < len(self._buttons)):
            return False
        return self.run_profile(self._buttons[button], button=button)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_profile(self, index: int, *, button: int | None = None) -> bool:
        """Lanza el perfil ``index`` en un hilo. ``False`` si no es válido o ya corre.

        ``button`` (0-3) es el botón de la consola que lo disparó, si lo hay
        — viaja en los eventos ``autocall.started``/``finished`` para que la
        UI sepa cuál de los 4 círculos iluminar (no todos a la vez).
        """
        if self.running or not (0 <= index < len(self._profiles)):
            return False
        profile = self._profiles[index]
        if not profile.valid:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._execute, args=(profile, button), name="autocall", daemon=True
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        """Corta ya: suelta el PTT y hace que la reproducción en curso pare al
        momento (``_play`` recibe ``self._stop.is_set`` como *stop_checker* y
        corta el streaming a la radio en el siguiente bloque, no al acabar el
        archivo)."""
        self._stop.set()
        with contextlib.suppress(Exception):
            self._radio.set_ptt(False, source="autocall")
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)

    # ---- bucle ---------------------------------------------------- #
    def _execute(self, profile: AutocallProfile, button: int | None) -> None:
        self.bus.publish(
            "autocall.started", audio=profile.audio, repeats=profile.repeats, button=button
        )
        try:
            for i in range(profile.repeats):
                if self._stop.is_set():
                    break
                self._ptt_on = False
                try:
                    self._play(profile.audio, self._stop.is_set, on_ready=self._begin_tx)
                finally:
                    self._end_tx()
                if i < profile.repeats - 1 and not self._stop.is_set():
                    self._wait(profile.interval)
        finally:
            self.bus.publish("autocall.finished", stopped=self._stop.is_set(), button=button)

    def _begin_tx(self) -> bool:
        """Activa el PTT y espera la pausa exacta antes de que salga el audio.

        Lo invoca el reproductor cuando ya tiene el audio preparado, así que la
        pausa entre PTT y primera muestra es exactamente ``ptt_lead_s``, no
        "lo que tarde en arrancar ffmpeg". ``False`` si se cancela durante la
        pausa (entonces no sale nada).
        """
        self._radio.set_ptt(True, source="autocall")
        self._ptt_on = True
        return precise_wait(self._ptt_lead_s, self._stop.is_set)

    def _end_tx(self) -> None:
        """Mantiene el PTT la cola exacta tras el audio y lo suelta. Si no llegó a
        activarse (archivo inválido, cancelación previa) no toca el PTT."""
        if not self._ptt_on:
            return
        self._ptt_on = False
        if not self._stop.is_set():
            precise_wait(self._ptt_tail_s, self._stop.is_set)
        self._radio.set_ptt(False, source="autocall")

    def _wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        end = time.monotonic() + seconds
        while not self._stop.is_set() and time.monotonic() < end:
            self._sleep(min(0.2, end - time.monotonic()))


__all__ = ["AutocallService"]
