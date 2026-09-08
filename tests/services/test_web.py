"""WebServerService: envuelve WebServerController y cablea callbacks a servicios."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402
from poorsdr.services.web import WebServerService  # noqa: E402


class FakeThread:
    def is_alive(self):
        return True


class FakeController:
    def __init__(self, callbacks):
        self.callbacks = callbacks
        self.started_with = None
        self.stopped = False
        self._thread = FakeThread()

    def start(self, config):
        self.started_with = config

    def stop(self):
        self.stopped = True
        self._thread = None


class FakeRadio:
    def __init__(self):
        self.frequency_hz = 27_555_000
        self.mode = "USB"
        self.ptt = False
        self.connected = True
        self.step_hz = 500
        self.calls: list[tuple] = []

    def set_frequency(self, hz, *, source="app"):
        self.calls.append(("freq", hz, source))
        self.frequency_hz = hz

    def set_mode(self, m, *, source="app"):
        self.calls.append(("mode", m, source))

    def set_ptt(self, a, *, source="app"):
        self.calls.append(("ptt", a, source))
        self.ptt = a

    def set_step(self, hz, *, source="app"):
        self.calls.append(("step", hz, source))
        self.step_hz = hz


class FakeAudio:
    def __init__(self):
        self.calls: list[tuple] = []
        self.anr_enabled = False
        self.anr_intensity = 3
        self.rx_volume = 25.0
        self.tx_volume = 100.0
        self.web_rx_gain = 1.0
        self.web_tx_gain = 1.0

    def call(self, fn, *args):
        self.calls.append((fn, *args))

    def start_tx(self):
        self.calls.append(("start_tx",))

    def stop_tx(self):
        self.calls.append(("stop_tx",))

    def set_rx_volume(self, value, *, source="app"):
        self.calls.append(("set_rx_volume", value, source))
        self.rx_volume = float(value)

    def set_tx_volume(self, value, *, source="app"):
        self.calls.append(("set_tx_volume", value, source))
        self.tx_volume = float(value)

    def set_web_rx_gain(self, value):
        self.calls.append(("set_web_rx_gain", value))
        self.web_rx_gain = float(value)

    def set_web_tx_gain(self, value):
        self.calls.append(("set_web_tx_gain", value))
        self.web_tx_gain = float(value)

    def set_anr(self, enabled, *, source="app"):
        self.calls.append(("set_anr", enabled, source))
        self.anr_enabled = bool(enabled)

    def set_anr_intensity(self, intensity, *, source="app"):
        self.calls.append(("set_anr_intensity", intensity, source))
        self.anr_intensity = int(intensity)


def _cfg(**web):
    base = AppConfig()
    if web.get("enabled"):
        web.setdefault("password_salt", "test-salt")
        web.setdefault("password_hash", "test-hash")
        web.setdefault("secret", "x" * 64)
    return replace(base, web=replace(base.web, **web)) if web else base


class WebServerServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.radio = FakeRadio()
        self.audio = FakeAudio()
        self.made: list[FakeController] = []

    def _svc(self, cfg):
        return WebServerService(
            self.bus, cfg, self.radio, self.audio,  # type: ignore[arg-type]
            controller_factory=lambda cb: self.made.append(FakeController(cb)) or self.made[-1],
            callbacks_factory=lambda m: m,  # el "callbacks" es el propio dict
            settle_delay_s=0,
        )

    def test_disabled(self):
        svc = self._svc(_cfg(enabled=False))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertEqual(self.made, [])

    def test_refuses_insecure_auth_configuration(self):
        base = AppConfig()
        svc = self._svc(replace(base, web=replace(base.web, enabled=True)))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.ERROR)
        self.assertEqual(self.made, [])

    def test_start_passes_legacy_config(self):
        svc = self._svc(_cfg(enabled=True, host="0.0.0.0", port=8899))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        cfg = self.made[0].started_with
        self.assertEqual(cfg["WEB_SERVER_HOST"], "0.0.0.0")
        self.assertEqual(cfg["WEB_SERVER_PORT"], 8899)

    def test_callbacks_route_to_services(self):
        svc = self._svc(_cfg(enabled=True))
        svc.start()
        cb = self.made[0].callbacks
        cb["set_frequency"](14_074_000)
        cb["set_mode"]("cw")
        cb["set_ptt"](True)
        cb["set_band"]("40m")
        cb["set_volumes"](0.5, 0.8)
        cb["set_anr"](True)
        cb["set_anr_intensity"](7)
        self.assertIn(("freq", 14_074_000, "web"), self.radio.calls)
        self.assertIn(("mode", "cw", "web"), self.radio.calls)
        self.assertIn(("ptt", True, "web"), self.radio.calls)
        self.assertIn(("freq", 7_074_000, "web"), self.radio.calls)  # centro de 40m
        self.assertIn(("start_tx",), self.audio.calls)
        # El volumen del panel web es la ganancia del audio remoto
        # (WEB_RX_GAIN/WEB_TX_GAIN), no el dial de la consola
        # (set_rx_volume/set_tx_volume, ruta de audio local del PC).
        self.assertIn(("set_web_rx_gain", 0.5), self.audio.calls)
        self.assertIn(("set_web_tx_gain", 0.8), self.audio.calls)
        self.assertIn(("set_anr", True, "web"), self.audio.calls)
        self.assertIn(("set_anr_intensity", 7, "web"), self.audio.calls)

    def test_get_state_reflects_live_volume(self):
        svc = self._svc(_cfg(enabled=True))
        svc.start()
        cb = self.made[0].callbacks
        cb["set_volumes"](0.5, 0.8)
        state = cb["get_state"]()
        self.assertAlmostEqual(state["rx_volume"], 0.5)
        self.assertAlmostEqual(state["tx_volume"], 0.8)

    def test_get_state(self):
        svc = self._svc(_cfg(enabled=True))
        svc.start()
        state = self.made[0].callbacks["get_state"]()
        self.assertEqual(state["frequency_hz"], 27_555_000)
        self.assertEqual(state["mode"], "USB")
        self.assertEqual(state["band"], "11m")
        self.assertIn("11m", state["bands"])
        self.assertEqual(len(state["bands"]), 10)
        self.assertTrue(state["radio_on"])

    def test_get_state_reflects_live_step(self):
        # Regresión: "set_step" estaba sin cablear (`lambda _khz: None`) —
        # elegir un paso en el panel no se guardaba en ningún sitio, así
        # que el estado que devuelve get_state() nunca lo reflejaba y el
        # selector "no funcionaba" (volvía a 1 kHz solo en cuanto llegaba
        # el siguiente estado por WebSocket). Ahora comparte el mismo
        # estado que la consola (RadioService.step_hz), no una copia
        # suelta — cambiarlo desde el panel debe verse también en el
        # propio RadioService (y de ahí, en la consola).
        svc = self._svc(_cfg(enabled=True))
        svc.start()
        cb = self.made[0].callbacks
        state_before = cb["get_state"]()
        self.assertEqual(state_before["step_khz"], 0.5)  # FakeRadio.step_hz = 500
        cb["set_step"](5.0)
        self.assertIn(("step", 5000, "web"), self.radio.calls)
        self.assertEqual(self.radio.step_hz, 5000)
        state_after = cb["get_state"]()
        self.assertEqual(state_after["step_khz"], 5.0)

    def test_get_state_reflects_live_anr(self):
        svc = self._svc(_cfg(enabled=True))
        svc.start()
        cb = self.made[0].callbacks
        cb["set_anr"](True)
        cb["set_anr_intensity"](8)
        state = cb["get_state"]()
        self.assertTrue(state["anr_enabled"])
        self.assertEqual(state["anr_intensity"], 8)

    def test_get_state_radio_disconnected(self):
        svc = self._svc(_cfg(enabled=True))
        svc.start()
        self.radio.connected = False
        state = self.made[0].callbacks["get_state"]()
        self.assertFalse(state["radio_on"])

    def test_stop(self):
        svc = self._svc(_cfg(enabled=True))
        svc.start()
        events: list = []
        self.bus.subscribe("web.status", lambda ev: events.append(ev.data))
        svc.stop()
        self.assertTrue(self.made[0].stopped)
        self.assertEqual(svc.status.state, ServiceState.STOPPED)
        self.assertEqual(events[-1], {"running": False})

    def test_reconfigure_restarts_on_port_change(self):
        svc = self._svc(_cfg(enabled=True, port=8080))
        svc.start()
        svc.reconfigure(_cfg(enabled=True, port=8081))
        self.assertTrue(self.made[0].stopped)
        self.assertEqual(self.made[1].started_with["WEB_SERVER_PORT"], 8081)

    def test_start_error_when_thread_not_alive(self):
        # Regresión: el botón WEB de la consola se pone en "ON" de forma
        # optimista y confía en "web.status" para corregirse si el arranque
        # falla — antes solo se publicaba en el camino de éxito, así que un
        # fallo aquí (puerto ocupado, etc.) dejaba el botón mostrando "ON"
        # para siempre aunque el servidor nunca llegó a escuchar.
        class DeadController(FakeController):
            def start(self, config):
                self._thread = None

        svc = WebServerService(
            self.bus, _cfg(enabled=True), self.radio, self.audio,  # type: ignore[arg-type]
            controller_factory=DeadController,
            callbacks_factory=lambda m: m,
            settle_delay_s=0,
        )
        events: list = []
        self.bus.subscribe("web.status", lambda ev: events.append(ev.data))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.ERROR)
        self.assertEqual(events, [{"running": False}])

    def test_start_error_when_password_missing_publishes_status(self):
        base = AppConfig()
        svc = self._svc(replace(base, web=replace(base.web, enabled=True)))
        events: list = []
        self.bus.subscribe("web.status", lambda ev: events.append(ev.data))
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.ERROR)
        self.assertEqual(events, [{"running": False}])


if __name__ == "__main__":
    unittest.main()
