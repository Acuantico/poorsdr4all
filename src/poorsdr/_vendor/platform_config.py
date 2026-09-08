from __future__ import annotations

import json
import re
import sys
from pathlib import Path


WINDOWS_DEVICE_MARKERS = (
    "voicemeeter",
    "fxsound",
    "wasapi",
    "vb-audio",
    "usb pnp sound device",
)

USER_CONFIG_KEYS = {
    "CAT_COM",
    "CAT_BAUD",
    "Altavoz_PC",
    "Microfono_PC",
    "Altavoz_Radio",
    "Microfono_Radio",
    "Altavoz_PC_Pulse",
    "Microfono_PC_Pulse",
    "Altavoz_Radio_Pulse",
    "Microfono_Radio_Pulse",
    "Altavoz_PC_Index",
    "Microfono_PC_Index",
    "Altavoz_Radio_Index",
    "Microfono_Radio_Index",
    "Altavoz_PC_Channels",
    "Altavoz_PC_Framerate",
    "Microfono_PC_Channels",
    "Microfono_PC_Framerate",
    "Altavoz_Radio_Channels",
    "Altavoz_Radio_Framerate",
    "Microfono_Radio_Channels",
    "Microfono_Radio_Framerate",
    "Intervalo",
    "Repeticiones",
    "Imagen_Fondo",
    "Roger_Beep",
    "Roger_Beep_Enabled",
    "Audio_Llamada_Automatica",
    "Idioma",
    "AutoCallProfiles",
    "HOTKEYS",
    "OWRX_ENABLED",
    "OWRX_HOST",
    "OWRX_PORT",
    "OWRX_KEY",
    "OWRX_DATA_DIR",
    "OWRX_BAND_PROFILES",
    "OWRX_SPOTS_ENABLED",
    "OWRX_SPOTS_FILTER_CW",
    "OWRX_SPOTS_FILTER_DIGI",
    "OWRX_SPOTS_FILTER_SSB",
    "OWRX_SPOTS_FILTER_OFF",
    "OWRX_WINDOW_GEOMETRY",
    "OWRX_QPA_PLATFORM",
    "OWRX_WINDOW_GEOMETRY_BACKEND",
    "DIGI_WINDOW_GEOMETRY",
    "OWRX_RUNTIME",
    "OWRX_STOP_ON_EXIT",
    "OWRX_AUTO_OPEN_ON_START",
    "OWRX_SDR_HINT",
    "OWRX_FOLLOW_APP_ONLY",
    "SPIDER_SOURCE",
    "SPIDER_MQTT_URL",
    "SPIDER_MQTT_TOPICS",
    "SPIDER_MQTT_USER",
    "SPIDER_MQTT_PASS",
    "SPIDER_TELNET_HOST",
    "SPIDER_TELNET_PORT",
    "SPIDER_TELNET_CALL",
    "SPIDER_TELNET_PASS",
    "RX_AUDIO_SOURCE",
    "GUI_WINDOW_GEOMETRY",
    "GUI_WINDOW_FRAME_DX",
    "GUI_WINDOW_FRAME_DY",
    "WEB_SERVER_ENABLED",
    "WEB_SERVER_HOST",
    "WEB_SERVER_PORT",
    "WEB_SERVER_ALLOW_WAN",
    "WEB_SERVER_AUTO_HTTPS",
    "WEB_SERVER_USER",
    "WEB_SERVER_TOTP_SECRET",
    "WEB_SERVER_SECRET",
    "WEB_SERVER_ALLOW_LEGACY_ADMIN",
    "WEB_SERVER_SSL_CERT",
    "WEB_SERVER_SSL_KEY",
    "WEB_SERVER_PASSWORD_SALT",
    "WEB_SERVER_PASSWORD_HASH",
    "RADIO_CONTROL_MODE",
    "HAMLIB_SERVER_ENABLED",
    "HAMLIB_BIN",
    "HAMLIB_MODEL",
    "HAMLIB_COM",
    "HAMLIB_BAUD",
    "HAMLIB_TCP_HOST",
    "HAMLIB_TCP_PORT",
    "HAMLIB_EXTRA_ARGS",
    "HAMLIB_FORCE_USB",
    "N1M_TCP_ENABLED",
    "N1M_TCP_HOST",
    "N1M_TCP_PORT",
    "RIGCTLD_PROXY_ENABLED",
    "RIGCTLD_PROXY_HOST",
    "RIGCTLD_PROXY_PORT",
    "FILTER_RELAY_WIFI_ENABLED",
    "FILTER_RELAY_WIFI_URL",
    "FILTER_RELAY_WIFI_API_KEY",
    "FILTER_RELAY_WIFI_TIMEOUT_MS",
    "FILTER_RELAY_BAND_GROUPS",
    "ANR_Enabled",
    "ANR_Intensity",
    "DSPFilters",
    "CAT_START_FREQ_HZ",
    "CAT_STEP_HZ",
    "Display_Mode",
}


def is_windows_serial_port(value: object) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"COM\d+", text, flags=re.IGNORECASE))


def sanitize_serial_port(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if sys.platform.startswith("win"):
        return text
    if is_windows_serial_port(text):
        return ""
    return text


def looks_like_windows_audio_label(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in WINDOWS_DEVICE_MARKERS)


def sanitize_config_platform(config: dict) -> tuple[dict, bool]:
    if not isinstance(config, dict):
        return {}, False

    changed = False
    data = dict(config)

    for key in ("CAT_COM", "HAMLIB_COM"):
        sanitized = sanitize_serial_port(data.get(key, ""))
        if sanitized != str(data.get(key, "") or ""):
            data[key] = sanitized
            changed = True

    if not sys.platform.startswith("win"):
        for key in ("Altavoz_PC", "Microfono_PC", "Altavoz_Radio", "Microfono_Radio"):
            if looks_like_windows_audio_label(data.get(key, "")):
                data[key] = ""
                changed = True

    return data, changed


def filter_user_config(config: dict) -> dict:
    if not isinstance(config, dict):
        return {}
    filtered = {key: value for key, value in config.items() if key in USER_CONFIG_KEYS}
    filtered.pop("UILayout", None)
    return filtered


def load_platform_config(path: str | Path, persist: bool = False) -> dict:
    config_path = Path(path)
    if persist and not config_path.exists():
        try:
            config_path.write_text("{}\n", encoding="utf-8")
        except Exception:
            pass
    try:
        with config_path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except Exception:
        return {}

    data, changed = sanitize_config_platform(raw)
    if persist and changed:
        try:
            with config_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4, ensure_ascii=False)
        except Exception:
            pass
    return data
