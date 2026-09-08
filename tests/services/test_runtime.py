"""Composition root: build_context y el puente con la app heredada."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr import runtime  # noqa: E402
from poorsdr.config.model import AppConfig  # noqa: E402


class BuildContextTests(unittest.TestCase):
    def test_default_registers_all_services_in_order(self):
        ctx = runtime.build_context(AppConfig())
        names = [s.name for s in ctx.services]
        self.assertEqual(
            names,
            [
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
            ],
        )
        # radio único aunque lo pidan varios servicios
        self.assertEqual(sum(1 for n in names if n == "radio"), 1)

    def test_radio_registered_before_rigctld_even_if_omitted(self):
        ctx = runtime.build_context(AppConfig(), services=("rigctld",))
        names = [s.name for s in ctx.services]
        self.assertEqual(names, ["radio", "rigctld"])

    def test_subset_selection(self):
        ctx = runtime.build_context(AppConfig(), services=("owrx-backend",))
        self.assertEqual([s.name for s in ctx.services], ["owrx-backend"])

    def test_context_has_bus_and_config(self):
        cfg = AppConfig()
        ctx = runtime.build_context(cfg, services=())
        self.assertIs(ctx.config, cfg)
        self.assertIsNotNone(ctx.bus)

    def test_radio_and_audio_are_shared_singletons(self):
        ctx = runtime.build_context(AppConfig())
        names = [s.name for s in ctx.services]
        self.assertEqual(names.count("radio"), 1)
        self.assertEqual(names.count("audio"), 1)

    def test_autocall_gets_real_play_audio_not_the_noop_placeholder(self):
        # Regresión: si "play_audio" no se conecta, AutocallService cae en su
        # placeholder interno (siempre devuelve False, no suena nada) y las
        # macros parecen "no funcionar" aunque el resto del flujo esté bien.
        ctx = runtime.build_context(AppConfig())
        autocall = next(s for s in ctx.services if s.name == "autocall")
        audio = next(s for s in ctx.services if s.name == "audio")
        self.assertEqual(autocall._play.__func__, audio.play_file.__func__)  # noqa: SLF001


class BridgeTests(unittest.TestCase):
    def tearDown(self):
        runtime.set_active(None)

    def test_active_and_get_service(self):
        self.assertIsNone(runtime.active())
        self.assertIsNone(runtime.get_service("radio"))
        ctx = runtime.build_context(AppConfig(), services=("owrx-backend",))
        runtime.set_active(ctx)
        self.assertIs(runtime.active(), ctx)
        self.assertIsNotNone(runtime.get_service("owrx-backend"))
        self.assertIsNone(runtime.get_service("radio"))
        runtime.set_active(None)
        self.assertIsNone(runtime.get_service("owrx-backend"))

    def test_start_stop_delegate_to_manager(self):
        calls: list[str] = []

        ctx = runtime.build_context(AppConfig(), services=())

        class Fake:
            name = "fake"

            def start(self):
                calls.append("start")

            def stop(self):
                calls.append("stop")

            def reconfigure(self, cfg):
                calls.append("reconfigure")

            @property
            def status(self):  # pragma: no cover - no usado aquí
                return None

        ctx.services.register(Fake())
        ctx.start()
        ctx.stop()
        self.assertEqual(calls, ["start", "stop"])

    def test_reconfigure_persists_and_propagates(self):
        saved: list = []
        vendor_written: list = []
        seen: list = []
        ctx = runtime.build_context(AppConfig(), services=())

        class Fake:
            name = "fake"

            def start(self):
                pass

            def stop(self):
                pass

            def reconfigure(self, cfg):
                seen.append(cfg)

            @property
            def status(self):  # pragma: no cover
                return None

        ctx.services.register(Fake())
        from poorsdr import runtime as rt

        orig_save = rt.loader.save
        orig_write_vendor = rt.write_vendor_config
        rt.loader.save = lambda cfg, *a, **k: saved.append(cfg)  # type: ignore[assignment]
        rt.write_vendor_config = vendor_written.append  # type: ignore[assignment]
        try:
            new_cfg = AppConfig()
            ctx.reconfigure(new_cfg)
        finally:
            rt.loader.save = orig_save  # type: ignore[assignment]
            rt.write_vendor_config = orig_write_vendor  # type: ignore[assignment]
        self.assertEqual(saved, [new_cfg])
        # El puente de runtime también se rehace en cada reconfigure (no solo
        # al arrancar), porque los visores externos vigilan su mtime para
        # detectar en caliente cambios como el tema activo.
        self.assertEqual(vendor_written, [new_cfg])
        self.assertEqual(seen, [new_cfg])
        self.assertIs(ctx.config, new_cfg)

    def test_reconfigure_without_persist_skips_vendor_config(self):
        ctx = runtime.build_context(AppConfig(), services=())
        from poorsdr import runtime as rt

        orig_save = rt.loader.save
        orig_write_vendor = rt.write_vendor_config
        save_calls: list = []
        vendor_calls: list = []
        rt.loader.save = lambda cfg, *a, **k: save_calls.append(cfg)  # type: ignore[assignment]
        rt.write_vendor_config = vendor_calls.append  # type: ignore[assignment]
        try:
            ctx.reconfigure(AppConfig(), persist=False)
        finally:
            rt.loader.save = orig_save  # type: ignore[assignment]
            rt.write_vendor_config = orig_write_vendor  # type: ignore[assignment]
        self.assertEqual(save_calls, [])
        self.assertEqual(vendor_calls, [])


class WriteVendorConfigTests(unittest.TestCase):
    def test_writes_legacy_json_atomically(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "config.json"
            cfg = AppConfig()
            runtime.write_vendor_config(cfg, out)
            self.assertTrue(out.is_file())
            self.assertFalse(out.with_suffix(".json.tmp").exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data, cfg.to_legacy())


if __name__ == "__main__":
    unittest.main()
