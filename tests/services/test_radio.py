"""RadioService: arranque tolerante, comandos y eventos de bus."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402
from poorsdr.services.radio import RadioService, resolve_legacy_cat_config  # noqa: E402


class FakeCat:
    def __init__(self, *, connected=True, state=None):
        self._connected = connected
        self._state = state or {"frequency_hz": 0, "mode": None}
        self.calls: list[tuple] = []
        self.closed = False

    def is_connected(self):
        return self._connected

    def set_frequency_hz(self, hz):
        self.calls.append(("freq", hz))

    def set_mode(self, mode):
        self.calls.append(("mode", mode))

    def set_ptt(self, active):
        self.calls.append(("ptt", active))

    def get_state(self):
        return dict(self._state)

    def close(self):
        self.closed = True


def _cfg(**over):
    base = AppConfig()
    from dataclasses import replace

    cat = replace(base.cat, **over) if over else base.cat
    return replace(base, cat=cat)


class RadioServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.events: list[tuple] = []
        for topic in ("radio.frequency", "radio.mode", "radio.ptt", "radio.status", "radio.step"):
            self.bus.subscribe(topic, lambda ev, t=topic: self.events.append((t, ev.data)))

    def test_starts_even_without_controller(self):
        svc = RadioService(self.bus, _cfg(), controller_factory=lambda c: None)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertFalse(svc.connected)
        self.assertIn(("radio.status", {"connected": False}), self.events)

    def test_start_swallows_factory_exception(self):
        def boom(_c):
            raise RuntimeError("sin puerto")

        svc = RadioService(self.bus, _cfg(), controller_factory=boom)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertFalse(svc.connected)

    def test_commands_hit_controller_and_publish(self):
        fake = FakeCat()
        svc = RadioService(self.bus, _cfg(), controller_factory=lambda c: fake)
        svc.start()
        svc.set_frequency(14074000)
        svc.set_mode("cw")
        svc.set_ptt(True)
        self.assertEqual(fake.calls, [("freq", 14074000), ("mode", "CW"), ("ptt", True)])
        self.assertEqual(svc.frequency_hz, 14074000)
        self.assertEqual(svc.mode, "CW")
        self.assertTrue(svc.ptt)
        topics = [t for t, _ in self.events]
        self.assertIn("radio.frequency", topics)
        self.assertIn("radio.mode", topics)
        self.assertIn("radio.ptt", topics)

    def test_commands_without_controller_still_publish(self):
        svc = RadioService(self.bus, _cfg(), controller_factory=lambda c: None)
        svc.start()
        svc.set_frequency(7100000)
        self.assertEqual(svc.frequency_hz, 7100000)
        self.assertIn(("radio.frequency", {"hz": 7100000, "source": "app"}), self.events)

    def test_read_state_syncs_from_cat(self):
        fake = FakeCat(state={"frequency_hz": 21074000, "mode": "USB"})
        svc = RadioService(self.bus, _cfg(), controller_factory=lambda c: fake)
        svc.start()
        self.assertEqual(svc.frequency_hz, 21074000)
        self.assertEqual(svc.mode, "USB")

    def test_reconfigure_recreates_controller_on_port_change(self):
        made: list[str] = []

        def factory(c):
            made.append(c.cat.port)
            return FakeCat()

        svc = RadioService(self.bus, _cfg(port="/dev/ttyUSB0"), controller_factory=factory)
        svc.start()
        svc.reconfigure(_cfg(port="/dev/ttyUSB1"))
        self.assertEqual(made, ["/dev/ttyUSB0", "/dev/ttyUSB1"])

    def test_reconfigure_noop_when_cat_unchanged(self):
        made = []
        svc = RadioService(
            self.bus, _cfg(port="/dev/ttyUSB0"), controller_factory=lambda c: made.append(1) or FakeCat()
        )
        svc.start()
        svc.reconfigure(_cfg(port="/dev/ttyUSB0"))
        self.assertEqual(len(made), 1)

    def test_set_step_publishes_and_updates_state(self):
        # El paso de sintonía no tiene comando CAT (es estado compartido
        # consola/panel web, no algo que se le mande a la radio), así que
        # set_step no debe tocar el controlador en absoluto.
        fake = FakeCat()
        svc = RadioService(self.bus, _cfg(), controller_factory=lambda c: fake)
        svc.start()
        svc.set_step(5000, source="web")
        self.assertEqual(svc.step_hz, 5000)
        self.assertEqual(fake.calls, [])  # nada de CAT para esto
        self.assertIn(("radio.step", {"hz": 5000, "source": "web"}), self.events)

    def test_reconfigure_detects_step_change_without_recreating_controller(self):
        # Regresión: la consola y el panel web tenían cada uno su propio
        # paso de sintonía sin relacionar — cambiarlo en la consola (que
        # pasa por reconfigure, no por set_step directamente) no se veía
        # reflejado en el panel web ni al revés. reconfigure() debe
        # detectar el cambio iguel que set_step, sin recrear el
        # controlador CAT (cambiar el paso no es un cambio de hardware).
        made: list[str] = []
        svc = RadioService(
            self.bus, _cfg(step_hz=500),
            controller_factory=lambda c: made.append(1) or FakeCat(),
        )
        svc.start()
        svc.reconfigure(_cfg(step_hz=5000))
        self.assertEqual(svc.step_hz, 5000)
        self.assertEqual(len(made), 1)  # controlador no recreado
        self.assertIn(("radio.step", {"hz": 5000, "source": "app"}), self.events)

    def test_reconfigure_noop_when_step_unchanged(self):
        svc = RadioService(self.bus, _cfg(step_hz=500), controller_factory=lambda c: FakeCat())
        svc.start()
        svc.reconfigure(_cfg(step_hz=500))
        step_events = [ev for t, ev in self.events if t == "radio.step"]
        self.assertEqual(step_events, [])

    def test_stop_closes_controller(self):
        fake = FakeCat()
        svc = RadioService(self.bus, _cfg(), controller_factory=lambda c: fake)
        svc.start()
        svc.stop()
        self.assertTrue(fake.closed)
        self.assertEqual(svc.status.state, ServiceState.STOPPED)


class ResolveLegacyCatConfigTests(unittest.TestCase):
    """El perfil de radio (``cat.rig_profile``) sobre ``CAT_BAUD``."""

    def test_custom_profile_leaves_baud_as_configured(self):
        legacy = resolve_legacy_cat_config(_cfg(baud=19200))
        self.assertEqual(legacy["CAT_BAUD"], 19200)

    def test_named_profile_overrides_baud(self):
        legacy = resolve_legacy_cat_config(_cfg(baud=19200, rig_profile="generic-ts480"))
        self.assertEqual(legacy["CAT_BAUD"], 38400)

    def test_trusdx_115200_profile_overrides_baud(self):
        legacy = resolve_legacy_cat_config(_cfg(rig_profile="trusdx-115200"))
        self.assertEqual(legacy["CAT_BAUD"], 115200)

    def test_unknown_profile_behaves_like_custom(self):
        legacy = resolve_legacy_cat_config(_cfg(baud=57600, rig_profile="no-existe"))
        self.assertEqual(legacy["CAT_BAUD"], 57600)


class ReconfigureRigProfileTests(unittest.TestCase):
    """Cambiar solo el perfil de radio también debe recrear el controlador."""

    def setUp(self):
        self.bus = EventBus()

    def test_rig_profile_change_recreates_controller(self):
        made = []
        svc = RadioService(
            self.bus,
            _cfg(rig_profile="custom"),
            controller_factory=lambda c: made.append(1) or FakeCat(),
        )
        svc.start()
        svc.reconfigure(_cfg(rig_profile="generic-ts480"))
        self.assertEqual(len(made), 2)


if __name__ == "__main__":
    unittest.main()
