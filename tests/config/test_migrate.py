"""Migración y round-trip del modelo de configuración tipado."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from poorsdr.config import migrate  # noqa: E402
from poorsdr.config.model import (  # noqa: E402
    RETIRED_LEGACY_KEYS,
    SCHEMA_VERSION,
    AppConfig,
    known_legacy_keys,
)
from poorsdr.infra import paths  # noqa: E402

_REAL_VENDOR_CONFIG = paths.legacy_config_file()

# Copia embebida del config.json real del usuario (2026-09), por si el original
# deja de estar disponible en la máquina de CI.
_SAMPLE_LEGACY: dict = {
    "ANR_Enabled": False,
    "ANR_Intensity": 1,
    "Altavoz_PC": "39: Easy Effects Sink (salida)",
    "Altavoz_PC_Channels": 2,
    "Altavoz_PC_Framerate": 48000,
    "Altavoz_PC_Index": 39,
    "Altavoz_PC_Pulse": "easyeffects_sink",
    "Altavoz_Radio": "28: Radio Altavoz (entrada)",
    "Altavoz_Radio_Channels": 1,
    "Altavoz_Radio_Framerate": 48000,
    "Altavoz_Radio_Index": 28,
    "Altavoz_Radio_Pulse": "alsa_input.usb-xxx.mono-fallback",
    "Audio_Llamada_Automatica": "/home/operador/Audio/CQ-Contest.wav",
    "AutoCallProfiles": [
        {"Audio": "/home/operador/Audio/CQ-Contest.wav", "Intervalo": "5", "Repeticiones": "10"},
        {"Audio": "/home/operador/Audio/EA0TEST.wav", "Intervalo": "0", "Repeticiones": "1"},
        {},
        {},
    ],
    "CAT_BAUD": "38400",
    "CAT_COM": "/dev/ttyUSB0",
    "CAT_START_FREQ_HZ": 7074000,
    "CAT_STEP_HZ": 500,
    "DIGI_WINDOW_GEOMETRY": "1284x760+1920+0",
    "DSPFilters": {"anr": {"enabled": False, "intensity": 1}},
    "Display_Mode": "USB",
    "FILTER_RELAY_BAND_GROUPS": {"10_15": ["10m", "11m", "15m"], "40": ["40m"]},
    "FILTER_RELAY_WIFI_API_KEY": "",
    "FILTER_RELAY_WIFI_ENABLED": False,
    "FILTER_RELAY_WIFI_TIMEOUT_MS": 700,
    "FILTER_RELAY_WIFI_URL": "http://192.0.2.117",
    "GUI_WINDOW_FRAME_DX": 0,
    "GUI_WINDOW_FRAME_DY": 0,
    "GUI_WINDOW_GEOMETRY": "620x760+3216+23",
    "HAMLIB_BAUD": "38400",
    "HAMLIB_BIN": "",
    "HAMLIB_COM": "/dev/ttyS31",
    "HAMLIB_EXTRA_ARGS": "",
    "HAMLIB_FORCE_USB": False,
    "HAMLIB_MODEL": "",
    "HAMLIB_SERVER_ENABLED": True,
    "HAMLIB_TCP_HOST": "127.0.0.1",
    "HAMLIB_TCP_PORT": "4532",
    "HOTKEYS": {"ptt_toggle": "space", "ch_plus": "KP_Add", "open_settings": ""},
    "Idioma": "es",
    "Imagen_Fondo": "back.jpg",
    "Intervalo": "5",
    "Microfono_PC": "40: Easy Effects Source (entrada)",
    "Microfono_PC_Channels": 2,
    "Microfono_PC_Framerate": 48000,
    "Microfono_PC_Index": 40,
    "Microfono_PC_Pulse": "easyeffects_source",
    "Microfono_Radio": "Radio Micrófono (salida)",
    "Microfono_Radio_Channels": 2,
    "Microfono_Radio_Framerate": 48000,
    "Microfono_Radio_Index": -1,
    "Microfono_Radio_Pulse": "alsa_output.usb-xxx.analog",
    "N1M_TCP_ENABLED": False,
    "N1M_TCP_HOST": "127.0.0.1",
    "N1M_TCP_PORT": "4532",
    "OWRX_AUTO_OPEN_ON_START": False,
    "OWRX_BAND_PROFILES": {"40m": "RTL 40m", "20m": "RTL 20m"},
    "OWRX_DATA_DIR": ".owrx-data",
    "OWRX_ENABLED": True,
    "OWRX_FOLLOW_APP_ONLY": False,
    "OWRX_HOST": "127.0.0.1",
    "OWRX_KEY": "PoorSDR",
    "OWRX_PORT": 8073,
    "OWRX_RUNTIME": "native",
    "OWRX_SPOTS_ENABLED": True,
    "OWRX_SPOTS_FILTER_CW": False,
    "OWRX_SPOTS_FILTER_DIGI": False,
    "OWRX_SPOTS_FILTER_OFF": False,
    "OWRX_SPOTS_FILTER_SSB": True,
    "OWRX_WINDOW_GEOMETRY": "1912x262+1920+789",
    "PTT_COM": "",
    "PTT_VIA_CAT": True,
    "RADIO_CONTROL_MODE": "direct",
    "RIGCTLD_PROXY_ENABLED": True,
    "RIGCTLD_PROXY_HOST": "127.0.0.1",
    "RIGCTLD_PROXY_PORT": "4536",
    "RX_AUDIO_SOURCE": "sdr",
    "Repeticiones": "10",
    "WEB_SERVER_ALLOW_WAN": True,
    "WEB_SERVER_AUTO_HTTPS": True,
    "WEB_SERVER_ENABLED": False,
    "WEB_SERVER_HOST": "192.0.2.102",
    "WEB_SERVER_PORT": 8080,
    "WEB_SERVER_SECRET": "test-secret-not-for-production-0001",
    "WEB_SERVER_TOTP_SECRET": "",
    "WEB_SERVER_USER": "admin",
}


def _semantic(value: object) -> object:
    """Normaliza para comparar ignorando str-vs-int en puertos/baudios."""
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return value


class MigrateRoundTripTests(unittest.TestCase):
    def _samples(self):
        yield "embebido", _SAMPLE_LEGACY
        if _REAL_VENDOR_CONFIG.exists():
            yield str(_REAL_VENDOR_CONFIG), json.loads(
                _REAL_VENDOR_CONFIG.read_text(encoding="utf-8-sig")
            )

    def test_no_key_is_lost_and_values_survive(self):
        for label, flat in self._samples():
            with self.subTest(sample=label):
                cfg = AppConfig.from_legacy(flat)
                back = cfg.to_legacy()
                # Las claves retiradas (funciones eliminadas, p. ej. Roger
                # Beep) se descartan a propósito: no cuentan como "perdidas".
                self.assertEqual(
                    set(flat) - set(back) - RETIRED_LEGACY_KEYS, set(), "claves perdidas"
                )
                for key, original in flat.items():
                    if key in RETIRED_LEGACY_KEYS:
                        continue
                    self.assertEqual(
                        _semantic(original),
                        _semantic(back[key]),
                        f"cambió el valor de {key!r}",
                    )

    def test_real_config_has_no_unknown_keys(self):
        for label, flat in self._samples():
            with self.subTest(sample=label):
                self.assertEqual(migrate.unknown_keys(flat), [])

    def test_native_round_trip(self):
        for label, flat in self._samples():
            with self.subTest(sample=label):
                cfg = AppConfig.from_legacy(flat)
                native = migrate.to_native(cfg)
                self.assertEqual(native["schema_version"], SCHEMA_VERSION)
                self.assertTrue(migrate.is_native(native))
                cfg2 = AppConfig.from_native(native)
                self.assertEqual(cfg2.to_legacy(), cfg.to_legacy())

    def test_unknown_keys_are_kept_in_extra(self):
        flat = dict(_SAMPLE_LEGACY)
        flat["UNA_CLAVE_RARA"] = "conservame"
        flat["OTRA"] = {"x": 1}
        cfg = migrate.from_legacy(flat, warn=False)
        self.assertEqual(cfg.extra["UNA_CLAVE_RARA"], "conservame")
        self.assertEqual(cfg.extra["OTRA"], {"x": 1})
        self.assertEqual(cfg.to_legacy()["UNA_CLAVE_RARA"], "conservame")
        cfg2 = AppConfig.from_native(migrate.to_native(cfg))
        self.assertEqual(cfg2.extra["OTRA"], {"x": 1})

    def test_retired_keys_no_se_marcan_como_desconocidas_ni_se_conservan(self):
        # Roger Beep y el PTT por línea serie (RTS) se eliminaron por
        # completo; un config real antiguo que aún tenga estas claves no
        # debe verse como "config con claves sin modelar" (no es un fallo de
        # migración) ni conservarlas en 'extra' (la función ya no existe, no
        # hay nada que hacer con el valor).
        flat = dict(_SAMPLE_LEGACY)
        flat["Roger_Beep"] = "beep5.mp3"
        flat["Roger_Beep_Enabled"] = True
        flat["PTT_COM"] = "/dev/ttyUSB1"
        flat["PTT_VIA_CAT"] = False
        self.assertEqual(migrate.unknown_keys(flat), [])
        cfg = migrate.from_legacy(flat, warn=False)
        self.assertNotIn("Roger_Beep", cfg.extra)
        self.assertNotIn("Roger_Beep_Enabled", cfg.extra)
        self.assertNotIn("PTT_COM", cfg.extra)
        self.assertNotIn("PTT_VIA_CAT", cfg.extra)

    def test_typed_access(self):
        cfg = AppConfig.from_legacy(_SAMPLE_LEGACY)
        self.assertEqual(cfg.cat.port, "/dev/ttyUSB0")
        self.assertEqual(cfg.cat.baud, 38400)
        self.assertEqual(cfg.rigctld.port, 4536)
        self.assertTrue(cfg.owrx.spots.enabled)
        self.assertTrue(cfg.owrx.spots.filter_ssb)
        self.assertEqual(cfg.audio.speaker_pc.index, 39)
        self.assertEqual(cfg.audio.mic_radio.index, -1)
        self.assertEqual(cfg.ui.language, "es")

    def test_defaults_are_native_v2(self):
        cfg = AppConfig()
        self.assertEqual(cfg.schema_version, SCHEMA_VERSION)
        self.assertEqual(migrate.to_native(cfg)["schema_version"], SCHEMA_VERSION)
        # el modelo por defecto también hace round-trip
        self.assertEqual(
            AppConfig.from_legacy(cfg.to_legacy()).to_legacy(), cfg.to_legacy()
        )

    def test_known_keys_cover_defaults(self):
        from poorsdr.config.defaults import LEGACY_DEFAULTS

        self.assertEqual(set(LEGACY_DEFAULTS) | RETIRED_LEGACY_KEYS, set(known_legacy_keys()))

    def test_default_mqtt_topics_include_rbn_feeds(self):
        # Sin las dos colas RBN casi no hay spots (regresión de "poco tráfico").
        topics = AppConfig().spider.mqtt_topics
        self.assertIn("spider/spots/rbn-cw", topics)
        self.assertIn("spider/spots/rbn-dig", topics)

    def test_dsp_filters_anr_stays_in_sync_with_typed_fields(self):
        # Bug real: dsp_pipeline.py (el backend del ANR) trata "DSPFilters.anr"
        # como fuente de verdad al configurar cada contexto de audio. Si se
        # desincroniza de ANR_Enabled/ANR_Intensity (p.ej. al mover el slider
        # de la consola, que solo tocaba esos dos campos), el DSP aplicaba en
        # silencio una intensidad distinta a la que mostraba la consola.
        from dataclasses import replace

        cfg = AppConfig()
        cfg = replace(cfg, dsp=replace(cfg.dsp, anr_enabled=True, anr_intensity=10))
        self.assertEqual(cfg.dsp.filters["anr"], {"enabled": True, "intensity": 10})
        self.assertEqual(cfg.to_legacy()["DSPFilters"]["anr"]["intensity"], 10)
        self.assertEqual(migrate.to_native(cfg)["dsp"]["filters"]["anr"]["intensity"], 10)

    def test_dsp_filters_anr_resync_on_migration_from_a_drifted_legacy_config(self):
        # Un config.json real con el desfase ya presente (visto en producción):
        # ANR_Intensity=10 en la consola pero DSPFilters.anr.intensity=5 aún
        # sin resincronizar de una migración/edición anterior.
        flat = dict(_SAMPLE_LEGACY)
        flat["ANR_Enabled"] = True
        flat["ANR_Intensity"] = 10
        flat["DSPFilters"] = {"anr": {"enabled": True, "intensity": 5}}
        cfg = AppConfig.from_legacy(flat)
        self.assertEqual(cfg.dsp.filters["anr"]["intensity"], 10)

    def test_dsp_filters_preserves_other_unmodeled_filters(self):
        from dataclasses import replace

        cfg = AppConfig()
        cfg = replace(cfg, dsp=replace(cfg.dsp, filters={"otro_filtro": {"x": 1}}))
        cfg = replace(cfg, dsp=replace(cfg.dsp, anr_intensity=7))
        self.assertEqual(cfg.dsp.filters["otro_filtro"], {"x": 1})
        self.assertEqual(cfg.dsp.filters["anr"]["intensity"], 7)

    def test_dsp_filters_intensity_is_clamped_to_valid_range(self):
        from dataclasses import replace

        cfg = AppConfig()
        cfg = replace(cfg, dsp=replace(cfg.dsp, anr_intensity=99))
        self.assertEqual(cfg.dsp.filters["anr"]["intensity"], 10)


if __name__ == "__main__":
    unittest.main()
