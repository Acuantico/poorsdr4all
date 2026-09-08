"""Única fuente de valores por defecto de la configuración.

En el proyecto original los defaults estaban repartidos entre
``platform_config.USER_CONFIG_KEYS``, ``ajustes.py``, ``gui_app/app.py`` y
``cargar_configuracion``. Aquí viven en un solo sitio, expresados en el
vocabulario *legacy* (claves planas) para que la migración sea directa.
"""

from __future__ import annotations

from typing import Any

# Perfiles de banda OWRX de la plantilla virgen RTL-SDR (assets/owrx).
DEFAULT_OWRX_BAND_PROFILES: dict[str, str] = {
    "160m": "RTL 160m",
    "80m": "RTL 80m",
    "60m": "RTL 60m",
    "40m": "RTL 40m",
    "30m": "RTL 30m",
    "20m": "RTL 20m",
    "17m": "RTL 17m",
    "15m": "RTL 15m",
    "11m": "RTL 11m",
    "10m": "RTL 10m",
}

DEFAULT_HOTKEYS: dict[str, str] = {
    "ptt_toggle": "space",
    "tune_tone": "",
    "vfo_up": "Up",
    "vfo_down": "Down",
    "ch_plus": "KP_Add",
    "ch_minus": "KP_Subtract",
    "mode_next": "",
    "mode_prev": "",
    "band_next": "Next",   # Av Pág
    "band_prev": "Prior",  # Re Pág
    "step_next": "",
    "step_prev": "",
    "anr_toggle": "",
    "anr_up": "",
    "anr_down": "",
    "rx_vol_up": "",
    "rx_vol_down": "",
    "tx_gain_up": "",
    "tx_gain_down": "",
    "rx_source_radio": "",
    "rx_source_sdr": "",
    "toggle_spots": "s",
    "open_digi": "d",
    "open_owrx": "c",
    "open_libro": "l",
    "open_mem": "m",
    "auto_call_1": "1",
    "auto_call_2": "2",
    "auto_call_3": "3",
    "auto_call_4": "4",
}

DEFAULT_DSP_FILTERS: dict[str, Any] = {"anr": {"enabled": False, "intensity": 1}}

DEFAULT_FILTER_RELAY_BAND_GROUPS: dict[str, list[str]] = {}

# Claves legacy → valor por defecto. La migración parte de esta base y encima
# aplica lo que traiga el ``config.json`` del usuario.
LEGACY_DEFAULTS: dict[str, Any] = {
    # -- Audio ---------------------------------------------------------------
    "Altavoz_PC": "",
    "Altavoz_PC_Pulse": "",
    "Altavoz_PC_Index": -1,
    "Altavoz_PC_Channels": 2,
    "Altavoz_PC_Framerate": 48000,
    "Altavoz_Radio": "",
    "Altavoz_Radio_Pulse": "",
    "Altavoz_Radio_Index": -1,
    "Altavoz_Radio_Channels": 1,
    "Altavoz_Radio_Framerate": 48000,
    "Microfono_PC": "",
    "Microfono_PC_Pulse": "",
    "Microfono_PC_Index": -1,
    "Microfono_PC_Channels": 2,
    "Microfono_PC_Framerate": 48000,
    "Microfono_Radio": "",
    "Microfono_Radio_Pulse": "",
    "Microfono_Radio_Index": -1,
    "Microfono_Radio_Channels": 2,
    "Microfono_Radio_Framerate": 48000,
    "RX_AUDIO_SOURCE": "sdr",
    # -- CAT / control radio ----------------------------------------------------
    "CAT_COM": "",
    "CAT_BAUD": 38400,
    "CAT_RIG_PROFILE": "custom",
    "CAT_START_FREQ_HZ": 7074000,
    "CAT_STEP_HZ": 500,
    "RADIO_CONTROL_MODE": "direct",
    # -- Proxy rigctld --------------------------------------------------------
    "RIGCTLD_PROXY_ENABLED": True,
    "RIGCTLD_PROXY_HOST": "127.0.0.1",
    "RIGCTLD_PROXY_PORT": 4536,
    # -- Servidor Hamlib ----------------------------------------------------
    "HAMLIB_SERVER_ENABLED": False,
    "HAMLIB_BIN": "",
    "HAMLIB_MODEL": "",
    "HAMLIB_COM": "",
    "HAMLIB_BAUD": 38400,
    "HAMLIB_TCP_HOST": "127.0.0.1",
    "HAMLIB_TCP_PORT": 4532,
    "HAMLIB_EXTRA_ARGS": "",
    "HAMLIB_FORCE_USB": False,
    # -- Emulador N1MM (TS-480) --------------------------------------------
    "N1M_TCP_ENABLED": False,
    "N1M_TCP_HOST": "127.0.0.1",
    "N1M_TCP_PORT": 4532,
    # -- OWRX --------------------------------------------------------------
    "OWRX_ENABLED": True,
    "OWRX_HOST": "127.0.0.1",
    "OWRX_PORT": 8073,
    "OWRX_KEY": "PoorSDR",
    "OWRX_DATA_DIR": ".owrx-data",
    "OWRX_RUNTIME": "native",
    "OWRX_STOP_ON_EXIT": True,
    "OWRX_AUTO_OPEN_ON_START": False,
    "OWRX_FOLLOW_APP_ONLY": False,
    "OWRX_SDR_HINT": "",
    "OWRX_SMETER_CALIBRATED": False,
    "OWRX_SMETER_S9_DBFS": -30,
    "OWRX_SMETER_NOISE_FLOOR_S": 5,
    "OWRX_BAND_PROFILES": DEFAULT_OWRX_BAND_PROFILES,
    "OWRX_SPOTS_ENABLED": True,
    "OWRX_SPOTS_FILTER_CW": True,
    "OWRX_SPOTS_FILTER_DIGI": True,
    "OWRX_SPOTS_FILTER_SSB": True,
    "OWRX_SPOTS_FILTER_OFF": False,
    "OWRX_SPOTS_RETENTION_MIN": 10,
    # -- Cluster DX (spiderd) --------------------------------------------
    "SPIDER_SOURCE": "mqtt",
    "SPIDER_MQTT_URL": "wss://ws.ure.es:443/mqtt",
    "SPIDER_MQTT_TOPICS": "spider/spots/dx,spider/spots/rbn-cw,spider/spots/rbn-dig",
    "SPIDER_MQTT_USER": "",
    "SPIDER_MQTT_PASS": "",
    "SPIDER_TELNET_HOST": "",
    "SPIDER_TELNET_PORT": 7300,
    "SPIDER_TELNET_CALL": "",
    "SPIDER_TELNET_PASS": "",
    # -- Relés de filtros WiFi -------------------------------------------
    "FILTER_RELAY_WIFI_ENABLED": False,
    "FILTER_RELAY_WIFI_URL": "",
    "FILTER_RELAY_WIFI_API_KEY": "",
    "FILTER_RELAY_WIFI_TIMEOUT_MS": 700,
    "FILTER_RELAY_BAND_GROUPS": DEFAULT_FILTER_RELAY_BAND_GROUPS,
    # -- Servidor web remoto -------------------------------------------
    "WEB_SERVER_ENABLED": False,
    "WEB_SERVER_HOST": "127.0.0.1",
    "WEB_SERVER_PORT": 8080,
    "WEB_SERVER_ALLOW_WAN": False,
    "WEB_SERVER_AUTO_HTTPS": False,
    "WEB_SERVER_USER": "admin",
    "WEB_SERVER_TOTP_SECRET": "",
    "WEB_SERVER_SECRET": "",
    "WEB_SERVER_ALLOW_LEGACY_ADMIN": False,
    "WEB_SERVER_SSL_CERT": "",
    "WEB_SERVER_SSL_KEY": "",
    "WEB_SERVER_PASSWORD_SALT": "",
    "WEB_SERVER_PASSWORD_HASH": "",
    # -- Llamada automática ---------------------------------------------
    "AutoCallProfiles": [],
    "AutoCallButtons": [0, 1, 2, 3],
    "Intervalo": 5,
    "Repeticiones": 10,
    "Audio_Llamada_Automatica": "",
    # -- Interfaz / ventana / hotkeys ---------------------------------
    "Idioma": "es",
    "Imagen_Fondo": "back.jpg",
    "Display_Mode": "USB",
    "HOTKEYS": DEFAULT_HOTKEYS,
    "GUI_WINDOW_GEOMETRY": "",
    "GUI_WINDOW_FRAME_DX": 0,
    "GUI_WINDOW_FRAME_DY": 0,
    "OWRX_WINDOW_GEOMETRY": "",
    "OWRX_WINDOW_GEOMETRY_BACKEND": "",
    "OWRX_QPA_PLATFORM": "",
    "DIGI_WINDOW_GEOMETRY": "",
    # -- DSP -----------------------------------------------------------
    "ANR_Enabled": False,
    "ANR_Intensity": 1,
    "DSPFilters": DEFAULT_DSP_FILTERS,
}

# Claves legacy que se guardaban como cadena aunque representen un número.
# ``to_legacy`` las vuelca como str para no romper el código que hace
# ``config["X"] == "4536"``.
LEGACY_STRING_NUMBERS: frozenset[str] = frozenset(
    {
        "CAT_BAUD",
        "RIGCTLD_PROXY_PORT",
        "HAMLIB_BAUD",
        "HAMLIB_TCP_PORT",
        "N1M_TCP_PORT",
        "SPIDER_TELNET_PORT",
        "Intervalo",
        "Repeticiones",
    }
)


def legacy_defaults() -> dict[str, Any]:
    """Copia profunda-ligera de :data:`LEGACY_DEFAULTS`."""
    import copy

    return copy.deepcopy(LEGACY_DEFAULTS)


__all__ = [
    "DEFAULT_DSP_FILTERS",
    "DEFAULT_FILTER_RELAY_BAND_GROUPS",
    "DEFAULT_HOTKEYS",
    "DEFAULT_OWRX_BAND_PROFILES",
    "LEGACY_DEFAULTS",
    "LEGACY_STRING_NUMBERS",
    "legacy_defaults",
]
