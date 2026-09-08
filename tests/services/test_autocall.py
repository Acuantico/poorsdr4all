"""AutocallService: bucle de macro contra RadioService (con dobles)."""

from __future__ import annotations

import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.autocall import AutocallService  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402
from poorsdr.services.radio import RadioService  # noqa: E402


def _cfg_with_profiles(*profiles, buttons=None):
    base = AppConfig()
    ac = replace(base.autocall, profiles=list(profiles))
    if buttons is not None:
        ac = replace(ac, buttons=list(buttons))
    return replace(base, autocall=ac)


class AutocallServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.radio = RadioService(self.bus, AppConfig(), controller_factory=lambda c: None)
        self.radio.start()
        self.ptt_events: list[bool] = []
        self.bus.subscribe("radio.ptt", lambda ev: self.ptt_events.append(ev["active"]))
        self.lifecycle: list[str] = []
        self.bus.subscribe("autocall.started", lambda ev: self.lifecycle.append("started"))
        self.bus.subscribe("autocall.finished", lambda ev: self.lifecycle.append("finished"))

    def _svc(self, cfg, played=None):
        return AutocallService(
            self.bus, cfg, self.radio,
            play_audio=played if played is not None else (lambda p, stop_checker: True),
            sleep=lambda _s: None,
        )

    def test_loads_profiles_on_start(self):
        cfg = _cfg_with_profiles(
            {"Audio": "a.wav", "Repeticiones": "2", "Intervalo": "0"},
        )
        svc = self._svc(cfg)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertEqual(len(svc.profiles), 1)

    def test_run_profile_toggles_ptt_per_repeat(self):
        cfg = _cfg_with_profiles({"Audio": "a.wav", "Repeticiones": "3", "Intervalo": "0"})
        plays: list[str] = []
        svc = self._svc(cfg, played=lambda p, stop_checker: plays.append(p) or True)
        svc.start()
        self.assertTrue(svc.run_profile(0))
        for _ in range(200):
            if not svc.running:
                break
            time.sleep(0.005)
        self.assertFalse(svc.running)
        self.assertEqual(plays, ["a.wav", "a.wav", "a.wav"])
        # PTT: True/False por cada repetición
        self.assertEqual(self.ptt_events, [True, False, True, False, True, False])
        self.assertEqual(self.lifecycle, ["started", "finished"])

    def test_run_profile_rejects_bad_index_or_while_running(self):
        cfg = _cfg_with_profiles({"Audio": "a.wav", "Repeticiones": "1"})
        svc = self._svc(cfg)
        svc.start()
        self.assertFalse(svc.run_profile(5))
        self.assertFalse(svc.run_profile(-1))

    def test_events_carry_the_button_that_fired(self):
        # Regresión: la UI iluminaba los 4 círculos a la vez porque el evento
        # no decía qué botón lo había disparado.
        cfg = _cfg_with_profiles(
            {"Audio": "a.wav", "Repeticiones": "1", "Intervalo": "0"},
            {"Audio": "b.wav", "Repeticiones": "1", "Intervalo": "0"},
        )
        buttons: list[int | None] = []
        self.bus.subscribe("autocall.started", lambda ev: buttons.append(ev.get("button")))
        svc = self._svc(cfg)
        svc.start()
        self.assertTrue(svc.run_button(1))
        for _ in range(200):
            if not svc.running:
                break
            time.sleep(0.005)
        self.assertEqual(buttons, [1])

    def test_run_profile_directo_sin_boton_no_lleva_button(self):
        cfg = _cfg_with_profiles({"Audio": "a.wav", "Repeticiones": "1", "Intervalo": "0"})
        buttons: list[int | None] = []
        self.bus.subscribe("autocall.started", lambda ev: buttons.append(ev.get("button")))
        svc = self._svc(cfg)
        svc.start()
        self.assertTrue(svc.run_profile(0))
        for _ in range(200):
            if not svc.running:
                break
            time.sleep(0.005)
        self.assertEqual(buttons, [None])

    def test_run_button_maps_to_assigned_macro(self):
        cfg = _cfg_with_profiles(
            {"Audio": "a.wav", "Nombre": "A", "Repeticiones": "1", "Intervalo": "0"},
            {"Audio": "b.wav", "Nombre": "B", "Repeticiones": "1", "Intervalo": "0"},
            buttons=[1, -1, 0, 0],
        )
        plays: list[str] = []
        svc = self._svc(cfg, played=lambda p, stop_checker: plays.append(p) or True)
        svc.start()
        self.assertEqual(svc.button_labels, ["B", "", "A", "A"])
        self.assertFalse(svc.run_button(1))  # sin asignar
        self.assertTrue(svc.run_button(0))   # → macro 1 ("b.wav")
        for _ in range(200):
            if not svc.running:
                break
            time.sleep(0.005)
        self.assertEqual(plays, ["b.wav"])

    def test_cancel_stops_loop_and_releases_ptt(self):
        cfg = _cfg_with_profiles({"Audio": "a.wav", "Repeticiones": "100", "Intervalo": "10"})
        blocker = {"n": 0}

        def slow_play(_p, stop_checker):
            blocker["n"] += 1
            time.sleep(0.02)
            return True

        svc = self._svc(cfg, played=slow_play)
        svc.start()
        svc.run_profile(0)
        time.sleep(0.03)
        svc.cancel()
        for _ in range(200):
            if not svc.running:
                break
            time.sleep(0.005)
        self.assertFalse(svc.running)
        self.assertLess(blocker["n"], 100)
        self.assertFalse(self.ptt_events[-1])  # último evento: RX

    def test_stop_cancels(self):
        cfg = _cfg_with_profiles({"Audio": "a.wav", "Repeticiones": "50", "Intervalo": "5"})
        svc = self._svc(cfg, played=lambda p, stop_checker: (time.sleep(0.02), True)[1])
        svc.start()
        svc.run_profile(0)
        time.sleep(0.02)
        svc.stop()
        self.assertFalse(svc.running)
        self.assertEqual(svc.status.state, ServiceState.STOPPED)

    def test_cancel_interrumpe_la_reproduccion_en_curso_no_solo_entre_repeticiones(self):
        # Regresión: cancel() cortaba el PTT pero la reproducción en curso
        # seguía hasta el final del archivo porque nadie miraba el
        # stop_checker durante el bloque en marcha, solo entre repeticiones.
        cfg = _cfg_with_profiles({"Audio": "a.wav", "Repeticiones": "1", "Intervalo": "0"})
        polls = {"n": 0}

        def blocking_play(_path, stop_checker):
            # Simula el bucle real (lee "bloques" y consulta stop_checker
            # entre cada uno) para comprobar que cancel() lo corta al momento.
            for _ in range(500):
                polls["n"] += 1
                if stop_checker():
                    return True
                time.sleep(0.01)
            return True  # no debería llegarse aquí si cancel() funciona

        svc = self._svc(cfg, played=blocking_play)
        svc.start()
        svc.run_profile(0)
        time.sleep(0.03)
        svc.cancel()
        self.assertLess(polls["n"], 500)
        self.assertFalse(self.ptt_events[-1])


if __name__ == "__main__":
    unittest.main()
