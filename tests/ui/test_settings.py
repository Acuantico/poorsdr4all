"""poorsdr.ui.settings.build_config: aplica valores de formulario a AppConfig."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.config.model import AppConfig, AudioDevice  # noqa: E402
from poorsdr.infra.devices import AudioEndpoint  # noqa: E402
from poorsdr.ui.settings import TABS, Field, build_config  # noqa: E402
from poorsdr.ui.settings.form import audio_device_from_pick, audio_label_for  # noqa: E402


class BuildConfigTests(unittest.TestCase):
    def test_str_int_bool_choice(self):
        cfg = build_config(
            AppConfig(),
            {
                ("cat", "port"): "/dev/ttyUSB1",
                ("cat", "baud"): "9600",
                ("rigctld", "enabled"): False,
                ("owrx", "runtime"): "docker",
            },
        )
        self.assertEqual(cfg.cat.port, "/dev/ttyUSB1")
        self.assertEqual(cfg.cat.baud, 9600)
        self.assertFalse(cfg.rigctld.enabled)
        self.assertEqual(cfg.owrx.runtime, "docker")

    def test_nested_owrx_spots(self):
        cfg = build_config(
            AppConfig(),
            {("owrx.spots", "retention_min"): "7", ("owrx", "host"): "10.0.0.9"},
        )
        self.assertEqual(cfg.owrx.spots.retention_min, 7)
        # los filtros por tipo ya no están en Ajustes: se mantienen intactos
        self.assertTrue(cfg.owrx.spots.filter_cw)
        self.assertEqual(cfg.owrx.host, "10.0.0.9")

    def test_serial_field_is_plain_string(self):
        cfg = build_config(AppConfig(), {("cat", "port"): "/dev/ttyUSB2"})
        self.assertEqual(cfg.cat.port, "/dev/ttyUSB2")

    def test_audio_device_from_catalog(self):
        cat = [
            AudioEndpoint("alsa_output.usb-x.analog-stereo", "USB Codec", 2, 44100, 39),
            AudioEndpoint("alsa_input.usb-x.analog-mono", "USB Codec mic", 1, 48000),
        ]
        cfg = build_config(
            AppConfig(),
            {("audio", "speaker_pc"): "39: USB Codec (salida)"},
            audio_catalog=cat,
        )
        dev = cfg.audio.speaker_pc
        self.assertEqual(dev.pulse, "alsa_output.usb-x.analog-stereo")
        self.assertEqual(dev.label, "39: USB Codec (salida)")  # estilo del original
        self.assertEqual(dev.index, 39)
        self.assertEqual(dev.channels, 2)
        self.assertEqual(dev.framerate, 44100)

    def test_audio_device_empty_pick_clears(self):
        base = AppConfig()
        base = replace(
            base,
            audio=replace(base.audio, speaker_pc=AudioDevice(label="algo", pulse="algo.sink")),
        )
        cfg = build_config(base, {("audio", "speaker_pc"): ""})
        self.assertEqual(cfg.audio.speaker_pc, AudioDevice())

    def test_audio_device_unknown_pick_kept_as_text(self):
        prev = AudioDevice(label="viejo", pulse="viejo.sink", channels=2, framerate=48000)
        got = audio_device_from_pick("dispositivo.desconectado", [], prev)
        self.assertEqual(got.pulse, "dispositivo.desconectado")
        self.assertEqual(got.channels, 2)  # se conserva lo que no cambió

    def test_audio_device_unchanged_pick_returns_previous(self):
        prev = AudioDevice(label="X salida", pulse="x.sink", index=7)
        self.assertIs(audio_device_from_pick("x.sink", [], prev), prev)

    def test_audio_device_from_original_style_label(self):
        cat = [AudioEndpoint("easyeffects_sink", "Easy Effects Sink", 2, 48000, 39)]
        got = audio_device_from_pick(
            "39: Easy Effects Sink (salida)", cat, AudioDevice(), role="salida"
        )
        self.assertEqual(got.pulse, "easyeffects_sink")
        self.assertEqual(got.label, "39: Easy Effects Sink (salida)")
        self.assertEqual(got.index, 39)

    def test_audio_device_pick_by_bare_description(self):
        cat = [AudioEndpoint("easyeffects_source", "Easy Effects Source", 1, 48000)]
        got = audio_device_from_pick("Easy Effects Source", cat, AudioDevice(), role="entrada")
        self.assertEqual(got.pulse, "easyeffects_source")
        self.assertEqual(got.label, "Easy Effects Source (entrada)")

    def test_user_name_kept_and_number_grafted(self):
        # El sink C-Media perdió su nombre bonito en PipeWire (queda "CM108…"),
        # pero el usuario lo llamó "Radio Micrófono": se conserva su nombre y
        # se le pone el número actual.
        ep = AudioEndpoint("alsa_output.usb-C-Media.analog-stereo", "CM108 Audio Controller", 2,
                           48000, -1, 8)
        dev = AudioDevice(label="Radio Micrófono (salida)",
                          pulse="alsa_output.usb-C-Media.analog-stereo", index=-1)
        self.assertEqual(audio_label_for(dev, ep, "salida"), "8: Radio Micrófono (salida)")

    def test_unchanged_device_by_name_keeps_pulse(self):
        dev = AudioDevice(label="Radio Micrófono (salida)", pulse="cmedia.sink", index=-1)
        got = audio_device_from_pick("8: Radio Micrófono (salida)", [], dev, role="salida")
        self.assertEqual(got.pulse, "cmedia.sink")  # no se pierde el pulse real
        self.assertEqual(got.label, "8: Radio Micrófono (salida)")

    def test_web_password_hashed_only_when_typed(self):
        base = AppConfig()
        unchanged = build_config(base, {("web", "password_hash"): ""})
        self.assertEqual(unchanged.web.password_hash, base.web.password_hash)

        changed = build_config(
            base,
            {("web", "password_hash"): "s3cr3t"},
            salt_factory=lambda: "FIXEDSALT",
        )
        self.assertEqual(changed.web.password_salt, "FIXEDSALT")
        self.assertEqual(
            changed.web.password_hash,
            __import__("hashlib").pbkdf2_hmac(
                "sha256", b"s3cr3t", b"FIXEDSALT", 600_000
            ).hex(),
        )
        self.assertGreaterEqual(len(changed.web.secret), 32)

    def test_autocall_buttons_json_field(self):
        cfg = build_config(AppConfig(), {("autocall", "buttons"): "[2, -1, 0, 1]"})
        self.assertEqual(cfg.autocall.buttons, [2, -1, 0, 1])

    def test_plugins_map_goes_to_extra(self):
        cfg = build_config(
            AppConfig(), {("__plugins__", "map"): '{"libro_guardia": false, "otro": true}'}
        )
        self.assertEqual(cfg.extra["PLUGINS"], {"libro_guardia": False, "otro": True})

    def test_json_fields(self):
        cfg = build_config(
            AppConfig(),
            {
                ("owrx", "band_profiles"): '{"40m": "RTL 40m", "20m": "RTL 20m"}',
                ("autocall", "profiles"): '[{"Audio": "cq.wav", "Repeticiones": "3"}]',
            },
        )
        self.assertEqual(cfg.owrx.band_profiles["40m"], "RTL 40m")
        self.assertEqual(cfg.autocall.profiles[0]["Audio"], "cq.wav")

    def test_extra_fields_from_a_plugin_tab(self):
        # "Relés" ya no está en TABS: la aporta el plugin filter_relays vía
        # PluginContext.add_settings_tab, con sus propios Field.
        relay_field = Field("relays", "band_groups", "Grupos de banda (JSON)", "json")
        cfg = build_config(
            AppConfig(),
            {("relays", "band_groups"): '{"40": ["40m"]}'},
            extra_fields=[relay_field],
        )
        self.assertEqual(cfg.relays.band_groups["40"], ["40m"])

    def test_unknown_field_without_extra_fields_is_ignored(self):
        # Sin declarar el Field del plugin, la clave se descarta sin más
        # (la pestaña "Relés" no aparece si el plugin no está instalado).
        cfg = build_config(AppConfig(), {("relays", "band_groups"): '{"40": ["40m"]}'})
        self.assertEqual(cfg.relays.band_groups, {})

    def test_bad_json_raises(self):
        with self.assertRaises(ValueError):
            build_config(AppConfig(), {("owrx", "band_profiles"): "{no json"})

    def test_unknown_keys_ignored(self):
        cfg = build_config(AppConfig(), {("nope", "nope"): "x"})
        self.assertEqual(cfg.to_legacy(), AppConfig().to_legacy())

    def test_round_trips_through_typed_model(self):
        # Todo lo que sale de build_config debe seguir siendo serializable.
        raw = {}
        for field in (f for tab in TABS.values() for f in tab):
            if field.kind == "bool":
                raw[(field.section, field.attr)] = True
            elif field.kind in ("int", "float"):
                raw[(field.section, field.attr)] = "1"
            elif field.kind == "json":
                continue
            elif field.kind == "choice":
                raw[(field.section, field.attr)] = field.choices[0]
            else:
                raw[(field.section, field.attr)] = "x"
        cfg = build_config(AppConfig(), raw)
        # round-trip legacy sin excepción
        from poorsdr.config.model import AppConfig as AC

        self.assertEqual(AC.from_legacy(cfg.to_legacy()).to_legacy(), cfg.to_legacy())


if __name__ == "__main__":
    unittest.main()
