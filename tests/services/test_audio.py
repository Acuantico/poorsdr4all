"""AudioService: fachada de ciclo de vida sobre el módulo audio (con doble)."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig, AudioDevice  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.audio import AudioService  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402


class FakeAudioModule:
    """Registra cualquier función llamada como (nombre, *args)."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, *args))
            return -42.0 if name == "get_rx_meter_dbfs" else None

        return _rec


class AudioServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.status: list[dict] = []
        self.bus.subscribe("audio.status", lambda ev: self.status.append(ev.data))
        self.mod = FakeAudioModule()

    def _svc(self, cfg=None, factory=None):
        return AudioService(
            self.bus, cfg or AppConfig(), module_factory=factory or (lambda: self.mod)
        )

    def test_start_loads_module_and_applies_rx_source(self):
        svc = self._svc()
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.RUNNING)
        self.assertIs(svc.module, self.mod)
        self.assertIn(("set_rx_source", "sdr"), self.mod.calls)
        self.assertEqual(self.status[-1], {"ready": True})

    def test_sdr_source_starts_internal_pipeline(self):
        # El visor nativo empuja PCM ya decodificado: sin enable_owrx_sdr_anr
        # los chunks se encolan y no suenan.
        svc = self._svc(cfg=replace(AppConfig(), audio=replace(AppConfig().audio, rx_source="sdr")))
        svc.start()
        names = [c[0] for c in self.mod.calls]
        self.assertIn("enable_owrx_sdr_anr", names)
        self.assertIn(("set_sdr_output_active", True), self.mod.calls)

    def test_radio_source_stops_internal_pipeline(self):
        svc = self._svc(
            cfg=replace(AppConfig(), audio=replace(AppConfig().audio, rx_source="radio"))
        )
        svc.start()
        names = [c[0] for c in self.mod.calls]
        self.assertIn("disable_owrx_sdr_anr", names)
        self.assertIn(("set_sdr_output_active", False), self.mod.calls)

    def test_rx_volume_routes_by_source(self):
        sdr = self._svc(cfg=replace(AppConfig(), audio=replace(AppConfig().audio, rx_source="sdr")))
        sdr.start()
        self.mod.calls.clear()
        sdr.set_rx_volume(30.0)
        self.assertIn(("set_volumen_rx", 0.0), self.mod.calls)
        self.assertIn(("set_volumen_sdr", 66.0), self.mod.calls)  # 30 * 2.2

        radio = self._svc(
            cfg=replace(AppConfig(), audio=replace(AppConfig().audio, rx_source="radio"))
        )
        radio.start()
        self.mod.calls.clear()
        radio.set_rx_volume(40.0)
        self.assertIn(("set_volumen_rx", 40.0), self.mod.calls)
        self.assertIn(("set_volumen_sdr", 0.0), self.mod.calls)

    def test_set_volume_publishes_bus_event(self):
        events: list = []
        self.bus.subscribe("audio.volume", lambda ev: events.append(ev.data))
        svc = self._svc(AppConfig())
        svc.start()
        events.clear()

        svc.set_rx_volume(70.0, source="web")
        self.assertEqual(events[-1], {"rx": 70.0, "tx": 100.0, "source": "web"})

        svc.set_tx_volume(55.0)
        self.assertEqual(events[-1], {"rx": 70.0, "tx": 55.0, "source": "app"})
        self.assertIn(("set_volumen_tx", 55.0), self.mod.calls)
        self.assertEqual(svc.rx_volume, 70.0)
        self.assertEqual(svc.tx_volume, 55.0)

    def test_switching_source_reapplies_last_volume_without_touching_dial(self):
        # Bug: al cambiar de fuente RX, la ruta recién activada se quedaba a 0
        # (mudo) hasta que el usuario tocaba el dial de volumen.
        cfg = AppConfig()  # por defecto rx_source="sdr"
        svc = self._svc(cfg)
        svc.start()
        svc.set_rx_volume(60.0)  # el usuario sube el volumen en modo SDR
        self.mod.calls.clear()

        svc.reconfigure(replace(cfg, audio=replace(cfg.audio, rx_source="radio")))
        self.assertIn(("set_volumen_rx", 60.0), self.mod.calls)  # se reaplica solo
        self.assertIn(("set_volumen_sdr", 0.0), self.mod.calls)

        self.mod.calls.clear()
        svc.reconfigure(replace(cfg, audio=replace(cfg.audio, rx_source="sdr")))
        self.assertIn(("set_volumen_sdr", 100.0), self.mod.calls)  # 60*2.2 -> tope 100, no 0
        self.assertIn(("set_volumen_rx", 0.0), self.mod.calls)

    def test_start_tolerates_missing_audio(self):
        def boom():
            raise ImportError("no pyaudio")

        svc = self._svc(factory=boom)
        svc.start()
        self.assertEqual(svc.status.state, ServiceState.ERROR)
        self.assertIsNone(svc.module)
        self.assertEqual(self.status[-1], {"ready": False})

    def test_stop_calls_teardown(self):
        svc = self._svc()
        svc.start()
        svc.stop()
        names = [c[0] for c in self.mod.calls]
        self.assertIn("detener_rx_tx", names)
        self.assertIn("desactivar_audio", names)
        self.assertEqual(svc.status.state, ServiceState.STOPPED)

    def test_call_forwards_and_tolerates_unknown(self):
        svc = self._svc()
        svc.start()
        self.assertEqual(svc.call("get_rx_meter_dbfs", window_s=0.5), -42.0)
        self.assertIsNone(svc.call("no_existe", 1, 2))

    def test_play_file_delegates_to_reproducir_audio_en_radio(self):
        svc = self._svc()
        svc.start()
        self.mod.calls.clear()
        # FakeAudioModule devuelve None para cualquier función -> False.
        self.assertFalse(svc.play_file("beep.mp3"))
        self.assertIn(("reproducir_audio_en_radio", "beep.mp3"), self.mod.calls)

    def test_play_file_refleja_el_resultado_real(self):
        class _Mod(FakeAudioModule):
            def reproducir_audio_en_radio(self, path, wait=True, stop_checker=None):
                self.calls.append(("reproducir_audio_en_radio", path))
                return True

        svc = self._svc(factory=lambda: _Mod())
        svc.start()
        self.assertTrue(svc.play_file("beep.mp3"))

    def test_play_file_reenvia_el_stop_checker(self):
        # Es lo que permite que cancelar una macro corte la reproducción al
        # momento en vez de esperar a que acabe el archivo.
        received = {}

        class _Mod(FakeAudioModule):
            def reproducir_audio_en_radio(self, path, wait=True, stop_checker=None):
                received["stop_checker"] = stop_checker
                return True

        svc = self._svc(factory=lambda: _Mod())
        svc.start()
        marker = lambda: True  # noqa: E731
        svc.play_file("beep.mp3", stop_checker=marker)
        self.assertIs(received["stop_checker"], marker)

    def test_reconfigure_rx_source_change(self):
        cfg = AppConfig()
        svc = self._svc(cfg)
        svc.start()
        self.mod.calls.clear()
        svc.reconfigure(replace(cfg, audio=replace(cfg.audio, rx_source="radio")))
        self.assertIn(("set_rx_source", "radio"), self.mod.calls)

    def test_start_applies_anr_and_rx_mode(self):
        cfg = replace(AppConfig(), dsp=replace(AppConfig().dsp, anr_enabled=True, anr_intensity=4))
        svc = self._svc(cfg)
        svc.start()
        self.assertIn(("habilitar_audio_en_modo", "rx"), self.mod.calls)
        self.assertIn(("establecer_anr", True), self.mod.calls)
        self.assertIn(("establecer_intensidad_anr", 4), self.mod.calls)

    def test_reconfigure_anr_change(self):
        cfg = AppConfig()
        svc = self._svc(cfg)
        svc.start()
        self.mod.calls.clear()
        svc.reconfigure(replace(cfg, dsp=replace(cfg.dsp, anr_enabled=True)))
        self.assertIn(("establecer_anr", True), self.mod.calls)

    def test_reactivating_anr_resets_its_internal_state(self):
        # "Desactivar y activar" es la forma de resetear el ANR si su estado
        # interno queda degradado (audio distorsionado tras una señal muy
        # fuerte): no hace falta un control aparte, reconfigure() ya lo hace.
        cfg = replace(AppConfig(), dsp=replace(AppConfig().dsp, anr_enabled=False))
        svc = self._svc(cfg)
        svc.start()

        class _Manager:
            _sample_rate, _channels, _frame_size = 48000, 1, 480

        calls = self._install_fake_dsp_filters({"gui": _Manager()})
        svc.reconfigure(replace(cfg, dsp=replace(cfg.dsp, anr_enabled=True)))
        self.assertEqual(calls, [("gui", 48000, 1, 480)])

    def test_just_changing_intensity_does_not_reset_anr(self):
        cfg = replace(AppConfig(), dsp=replace(AppConfig().dsp, anr_enabled=True, anr_intensity=3))
        svc = self._svc(cfg)
        svc.start()

        class _Manager:
            _sample_rate, _channels, _frame_size = 48000, 1, 480

        calls = self._install_fake_dsp_filters({"gui": _Manager()})
        svc.reconfigure(replace(cfg, dsp=replace(cfg.dsp, anr_intensity=7)))
        self.assertEqual(calls, [])  # ya estaba activado: no se resetea solo

    def test_tx_and_tune_helpers(self):
        svc = self._svc()
        svc.start()
        self.mod.calls.clear()
        svc.start_tx()
        self.assertIn(("habilitar_audio_en_modo", "tx"), self.mod.calls)
        svc.stop_tx()
        self.assertIn(("habilitar_audio_en_modo", "rx"), self.mod.calls)
        self.mod.calls.clear()
        svc.start_tune_tone()
        names = [c[0] for c in self.mod.calls]
        self.assertIn("habilitar_audio_en_modo", names)
        self.assertIn("start_tx_test_tone", names)
        svc.stop_tune_tone()
        self.assertIn("stop_tx_test_tone", [c[0] for c in self.mod.calls])

    def test_reconfigure_device_change_flags_restart(self):
        cfg = AppConfig()
        svc = self._svc(cfg)
        svc.start()
        self.status.clear()
        new = replace(
            cfg,
            audio=replace(cfg.audio, speaker_pc=AudioDevice(label="otro", index=9)),
        )
        svc.reconfigure(new)
        self.assertTrue(self.status[-1].get("needs_restart"))

    # ---- reset_anr: recuperación tras sobrecarga fuerte de entrada ---- #
    def _install_fake_dsp_filters(self, managers):
        """``dsp_filters`` como atributo real (gana a __getattr__ del fake)."""
        calls: list[tuple] = []

        class _FakeDspFilters:
            _MANAGERS = managers

            @staticmethod
            def configure_ctx(ctx, rate, channels, frame_size, config=None):
                calls.append((ctx, rate, channels, frame_size))

        self.mod.dsp_filters = _FakeDspFilters()
        return calls

    def test_reset_anr_reconfigures_every_context_with_its_own_params(self):
        svc = self._svc()
        svc.start()

        class _Manager:
            def __init__(self, rate, channels, frame_size):
                self._sample_rate = rate
                self._channels = channels
                self._frame_size = frame_size

        calls = self._install_fake_dsp_filters(
            {"gui": _Manager(48000, 1, 480), "web": _Manager(8000, 1, 160)}
        )
        svc.reset_anr()
        self.assertEqual(
            sorted(calls), sorted([("gui", 48000, 1, 480), ("web", 8000, 1, 160)])
        )

    def test_reset_anr_skips_a_broken_manager_without_stopping_the_rest(self):
        svc = self._svc()
        svc.start()

        class _Manager:
            def __init__(self, rate, channels, frame_size):
                self._sample_rate = rate
                self._channels = channels
                self._frame_size = frame_size

        class _Broken:
            pass  # sin _sample_rate/_channels/_frame_size

        calls = self._install_fake_dsp_filters(
            {"broken": _Broken(), "gui": _Manager(48000, 1, 480)}
        )
        svc.reset_anr()
        self.assertEqual(calls, [("gui", 48000, 1, 480)])

    def test_reset_anr_tolerates_missing_dsp_filters(self):
        # El fake por defecto (FakeAudioModule.__getattr__) no expone un
        # dsp_filters real: reset_anr no debe explotar.
        svc = self._svc()
        svc.start()
        svc.reset_anr()

    def test_reset_anr_without_loaded_module_is_a_noop(self):
        def boom():
            raise ImportError("no pyaudio")

        svc = self._svc(factory=boom)
        svc.start()
        svc.reset_anr()


if __name__ == "__main__":
    unittest.main()
