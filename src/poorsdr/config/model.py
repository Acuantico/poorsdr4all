"""Modelo de configuración tipado.

Dataclasses ``frozen`` anidadas que sustituyen al diccionario plano del proyecto
original y a su whitelist ``USER_CONFIG_KEYS`` (que descartaba en silencio
cualquier clave nueva). La correspondencia con las claves *legacy* se declara en
``_FIELDS`` de cada sección; la coerción de tipos se deriva del tipo del valor
por defecto en :data:`poorsdr.config.defaults.LEGACY_DEFAULTS`.

- ``AppConfig.from_legacy(flat)`` construye el modelo desde un dict plano.
- ``AppConfig.to_legacy()`` reproduce el dict plano (round-trip sin pérdida).
- Las claves no reconocidas se conservan en ``AppConfig.extra`` (nunca se pierden).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from poorsdr.config.defaults import LEGACY_DEFAULTS, LEGACY_STRING_NUMBERS, legacy_defaults

SCHEMA_VERSION = 2

_T = TypeVar("_T", bound="_Section")


# --------------------------------------------------------------------------- #
# Coerción
# --------------------------------------------------------------------------- #
def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _coerce(legacy_key: str, value: Any) -> Any:
    default = LEGACY_DEFAULTS[legacy_key]
    if isinstance(default, bool):
        return as_bool(value, default)
    if isinstance(default, int):
        return as_int(value, default)
    if isinstance(default, str):
        return as_str(value, default)
    # dict / list: se conserva tal cual (copia defensiva).
    if value is None:
        return copy.deepcopy(default)
    return copy.deepcopy(value)


def _dump(legacy_key: str, value: Any) -> Any:
    if legacy_key in LEGACY_STRING_NUMBERS:
        return "" if value is None else str(value)
    default = LEGACY_DEFAULTS[legacy_key]
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, (dict, list)):
        return copy.deepcopy(value)
    return value


# --------------------------------------------------------------------------- #
# Base de sección
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Section:
    #: pares (clave_legacy, nombre_atributo)
    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = ()

    @classmethod
    def legacy_keys(cls) -> tuple[str, ...]:
        return tuple(legacy for legacy, _ in cls._FIELDS)

    @classmethod
    def from_legacy(cls: type[_T], flat: Mapping[str, Any]) -> _T:
        kwargs: dict[str, Any] = {}
        for legacy_key, attr in cls._FIELDS:
            raw = flat[legacy_key] if legacy_key in flat else LEGACY_DEFAULTS[legacy_key]
            kwargs[attr] = _coerce(legacy_key, raw)
        return cls(**kwargs)

    def to_legacy(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for legacy_key, attr in self._FIELDS:
            out[legacy_key] = _dump(legacy_key, getattr(self, attr))
        return out


# --------------------------------------------------------------------------- #
# Secciones
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AudioDevice:
    """Un dispositivo de audio (altavoz o micrófono, PC o radio)."""

    label: str = ""
    pulse: str = ""
    index: int = -1
    channels: int = 2
    framerate: int = 48000


@dataclass(frozen=True)
class AudioConfig(_Section):
    speaker_pc: AudioDevice = field(default_factory=AudioDevice)
    speaker_radio: AudioDevice = field(default_factory=lambda: AudioDevice(channels=1))
    mic_pc: AudioDevice = field(default_factory=AudioDevice)
    mic_radio: AudioDevice = field(default_factory=AudioDevice)
    rx_source: str = "sdr"

    _DEVICE_PREFIX: ClassVar[dict[str, str]] = {
        "speaker_pc": "Altavoz_PC",
        "speaker_radio": "Altavoz_Radio",
        "mic_pc": "Microfono_PC",
        "mic_radio": "Microfono_Radio",
    }
    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (("RX_AUDIO_SOURCE", "rx_source"),)

    @classmethod
    def from_legacy(cls, flat: Mapping[str, Any]) -> AudioConfig:
        def device(prefix: str, default: AudioDevice) -> AudioDevice:
            return AudioDevice(
                label=as_str(flat.get(prefix, ""), ""),
                pulse=as_str(flat.get(f"{prefix}_Pulse", ""), ""),
                index=as_int(flat.get(f"{prefix}_Index", -1), -1),
                channels=as_int(flat.get(f"{prefix}_Channels", default.channels), default.channels),
                framerate=as_int(
                    flat.get(f"{prefix}_Framerate", default.framerate), default.framerate
                ),
            )

        defaults = cls()
        return cls(
            speaker_pc=device("Altavoz_PC", defaults.speaker_pc),
            speaker_radio=device("Altavoz_Radio", defaults.speaker_radio),
            mic_pc=device("Microfono_PC", defaults.mic_pc),
            mic_radio=device("Microfono_Radio", defaults.mic_radio),
            rx_source=as_str(flat.get("RX_AUDIO_SOURCE", "sdr"), "sdr"),
        )

    def to_legacy(self) -> dict[str, Any]:
        out: dict[str, Any] = {"RX_AUDIO_SOURCE": self.rx_source}
        for attr, prefix in self._DEVICE_PREFIX.items():
            dev: AudioDevice = getattr(self, attr)
            out[prefix] = dev.label
            out[f"{prefix}_Pulse"] = dev.pulse
            out[f"{prefix}_Index"] = dev.index
            out[f"{prefix}_Channels"] = dev.channels
            out[f"{prefix}_Framerate"] = dev.framerate
        return out

    @classmethod
    def legacy_keys(cls) -> tuple[str, ...]:
        keys = ["RX_AUDIO_SOURCE"]
        for prefix in cls._DEVICE_PREFIX.values():
            keys += [prefix, f"{prefix}_Pulse", f"{prefix}_Index", f"{prefix}_Channels", f"{prefix}_Framerate"]
        return tuple(keys)


@dataclass(frozen=True)
class CatConfig(_Section):
    port: str = ""
    baud: int = 38400
    rig_profile: str = "custom"
    start_freq_hz: int = 7074000
    step_hz: int = 500
    control_mode: str = "direct"

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("CAT_COM", "port"),
        ("CAT_BAUD", "baud"),
        ("CAT_RIG_PROFILE", "rig_profile"),
        ("CAT_START_FREQ_HZ", "start_freq_hz"),
        ("CAT_STEP_HZ", "step_hz"),
        ("RADIO_CONTROL_MODE", "control_mode"),
    )


@dataclass(frozen=True)
class RigctldConfig(_Section):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 4536

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("RIGCTLD_PROXY_ENABLED", "enabled"),
        ("RIGCTLD_PROXY_HOST", "host"),
        ("RIGCTLD_PROXY_PORT", "port"),
    )


@dataclass(frozen=True)
class HamlibConfig(_Section):
    enabled: bool = False
    binary: str = ""
    model: str = ""
    port: str = ""
    baud: int = 38400
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 4532
    extra_args: str = ""
    force_usb: bool = False

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("HAMLIB_SERVER_ENABLED", "enabled"),
        ("HAMLIB_BIN", "binary"),
        ("HAMLIB_MODEL", "model"),
        ("HAMLIB_COM", "port"),
        ("HAMLIB_BAUD", "baud"),
        ("HAMLIB_TCP_HOST", "tcp_host"),
        ("HAMLIB_TCP_PORT", "tcp_port"),
        ("HAMLIB_EXTRA_ARGS", "extra_args"),
        ("HAMLIB_FORCE_USB", "force_usb"),
    )


@dataclass(frozen=True)
class N1mConfig(_Section):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4532

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("N1M_TCP_ENABLED", "enabled"),
        ("N1M_TCP_HOST", "host"),
        ("N1M_TCP_PORT", "port"),
    )


@dataclass(frozen=True)
class SpotsConfig(_Section):
    # ``filter_*`` = "mostrar spots de ese tipo" (nombre heredado del original).
    enabled: bool = True
    filter_cw: bool = True
    filter_digi: bool = True
    filter_ssb: bool = True
    filter_off: bool = False
    retention_min: int = 10  # minutos que un spot permanece visible

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("OWRX_SPOTS_ENABLED", "enabled"),
        ("OWRX_SPOTS_FILTER_CW", "filter_cw"),
        ("OWRX_SPOTS_FILTER_DIGI", "filter_digi"),
        ("OWRX_SPOTS_FILTER_SSB", "filter_ssb"),
        ("OWRX_SPOTS_FILTER_OFF", "filter_off"),
        ("OWRX_SPOTS_RETENTION_MIN", "retention_min"),
    )

    def __post_init__(self) -> None:
        if self.retention_min < 1:
            object.__setattr__(self, "retention_min", 1)


@dataclass(frozen=True)
class OwrxConfig(_Section):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8073
    key: str = "PoorSDR"
    data_dir: str = ".owrx-data"
    runtime: str = "native"
    stop_on_exit: bool = True
    auto_open_on_start: bool = False
    follow_app_only: bool = False
    sdr_hint: str = ""
    smeter_calibrated: bool = False
    smeter_s9_dbfs: int = -30
    # Con el S-metro autocalibrado (por defecto, `smeter_calibrated=False`):
    # el suelo de ruido detectado (QRM ambiente de banda, sin señal) se
    # coloca en esta unidad S, no en una fija a ciegas — cada estación tiene
    # su propio QRM de fondo (antena, ubicación, banda...), así que "S5" no
    # vale para todo el mundo por igual. Ver poorsdr.core.smeter.
    smeter_noise_floor_s: int = 5
    band_profiles: dict[str, str] = field(default_factory=dict)
    spots: SpotsConfig = field(default_factory=SpotsConfig)

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("OWRX_ENABLED", "enabled"),
        ("OWRX_HOST", "host"),
        ("OWRX_PORT", "port"),
        ("OWRX_KEY", "key"),
        ("OWRX_DATA_DIR", "data_dir"),
        ("OWRX_RUNTIME", "runtime"),
        ("OWRX_STOP_ON_EXIT", "stop_on_exit"),
        ("OWRX_AUTO_OPEN_ON_START", "auto_open_on_start"),
        ("OWRX_FOLLOW_APP_ONLY", "follow_app_only"),
        ("OWRX_SDR_HINT", "sdr_hint"),
        ("OWRX_SMETER_CALIBRATED", "smeter_calibrated"),
        ("OWRX_SMETER_S9_DBFS", "smeter_s9_dbfs"),
        ("OWRX_SMETER_NOISE_FLOOR_S", "smeter_noise_floor_s"),
        ("OWRX_BAND_PROFILES", "band_profiles"),
    )

    @classmethod
    def from_legacy(cls, flat: Mapping[str, Any]) -> OwrxConfig:
        kwargs: dict[str, Any] = {
            attr: _coerce(legacy_key, flat.get(legacy_key, LEGACY_DEFAULTS[legacy_key]))
            for legacy_key, attr in cls._FIELDS
        }
        kwargs["spots"] = SpotsConfig.from_legacy(flat)
        return cls(**kwargs)

    def to_legacy(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            legacy_key: _dump(legacy_key, getattr(self, attr))
            for legacy_key, attr in self._FIELDS
        }
        out.update(self.spots.to_legacy())
        return out

    @classmethod
    def legacy_keys(cls) -> tuple[str, ...]:
        return tuple(legacy for legacy, _ in cls._FIELDS) + SpotsConfig.legacy_keys()


@dataclass(frozen=True)
class SpiderConfig(_Section):
    source: str = "mqtt"
    mqtt_url: str = "wss://ws.ure.es:443/mqtt"
    mqtt_topics: str = "spider/spots/dx,spider/spots/rbn-cw,spider/spots/rbn-dig"
    mqtt_user: str = ""
    mqtt_pass: str = ""
    telnet_host: str = ""
    telnet_port: int = 7300
    telnet_call: str = ""
    telnet_pass: str = ""

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("SPIDER_SOURCE", "source"),
        ("SPIDER_MQTT_URL", "mqtt_url"),
        ("SPIDER_MQTT_TOPICS", "mqtt_topics"),
        ("SPIDER_MQTT_USER", "mqtt_user"),
        ("SPIDER_MQTT_PASS", "mqtt_pass"),
        ("SPIDER_TELNET_HOST", "telnet_host"),
        ("SPIDER_TELNET_PORT", "telnet_port"),
        ("SPIDER_TELNET_CALL", "telnet_call"),
        ("SPIDER_TELNET_PASS", "telnet_pass"),
    )


@dataclass(frozen=True)
class RelayConfig(_Section):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    timeout_ms: int = 700
    band_groups: dict[str, list[str]] = field(default_factory=dict)

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("FILTER_RELAY_WIFI_ENABLED", "enabled"),
        ("FILTER_RELAY_WIFI_URL", "url"),
        ("FILTER_RELAY_WIFI_API_KEY", "api_key"),
        ("FILTER_RELAY_WIFI_TIMEOUT_MS", "timeout_ms"),
        ("FILTER_RELAY_BAND_GROUPS", "band_groups"),
    )


@dataclass(frozen=True)
class WebServerConfig(_Section):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    allow_wan: bool = False
    auto_https: bool = False
    user: str = "admin"
    totp_secret: str = ""
    secret: str = ""
    allow_legacy_admin: bool = False
    ssl_cert: str = ""
    ssl_key: str = ""
    password_salt: str = ""
    password_hash: str = ""

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("WEB_SERVER_ENABLED", "enabled"),
        ("WEB_SERVER_HOST", "host"),
        ("WEB_SERVER_PORT", "port"),
        ("WEB_SERVER_ALLOW_WAN", "allow_wan"),
        ("WEB_SERVER_AUTO_HTTPS", "auto_https"),
        ("WEB_SERVER_USER", "user"),
        ("WEB_SERVER_TOTP_SECRET", "totp_secret"),
        ("WEB_SERVER_SECRET", "secret"),
        ("WEB_SERVER_ALLOW_LEGACY_ADMIN", "allow_legacy_admin"),
        ("WEB_SERVER_SSL_CERT", "ssl_cert"),
        ("WEB_SERVER_SSL_KEY", "ssl_key"),
        ("WEB_SERVER_PASSWORD_SALT", "password_salt"),
        ("WEB_SERVER_PASSWORD_HASH", "password_hash"),
    )


@dataclass(frozen=True)
class AutocallConfig(_Section):
    profiles: list[dict[str, Any]] = field(default_factory=list)
    interval: int = 5
    repeats: int = 10
    default_audio: str = ""
    #: macro (índice en ``profiles``) que dispara cada uno de los 4 botones de la
    #: consola; ``-1`` = botón sin asignar.
    buttons: list[int] = field(default_factory=lambda: [0, 1, 2, 3])

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("AutoCallProfiles", "profiles"),
        ("Intervalo", "interval"),
        ("Repeticiones", "repeats"),
        ("Audio_Llamada_Automatica", "default_audio"),
        ("AutoCallButtons", "buttons"),
    )

    def __post_init__(self) -> None:
        raw = list(self.buttons or [])[:4]
        while len(raw) < 4:
            raw.append(-1)
        object.__setattr__(self, "buttons", [int(x) for x in raw])


@dataclass(frozen=True)
class UiConfig(_Section):
    language: str = "es"
    background_image: str = "back.jpg"
    display_mode: str = "USB"
    hotkeys: dict[str, str] = field(default_factory=dict)
    window_geometry: str = ""
    window_frame_dx: int = 0
    window_frame_dy: int = 0
    owrx_window_geometry: str = ""
    owrx_window_geometry_backend: str = ""
    owrx_qpa_platform: str = ""
    digi_window_geometry: str = ""

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Idioma", "language"),
        ("Imagen_Fondo", "background_image"),
        ("Display_Mode", "display_mode"),
        ("HOTKEYS", "hotkeys"),
        ("GUI_WINDOW_GEOMETRY", "window_geometry"),
        ("GUI_WINDOW_FRAME_DX", "window_frame_dx"),
        ("GUI_WINDOW_FRAME_DY", "window_frame_dy"),
        ("OWRX_WINDOW_GEOMETRY", "owrx_window_geometry"),
        ("OWRX_WINDOW_GEOMETRY_BACKEND", "owrx_window_geometry_backend"),
        ("OWRX_QPA_PLATFORM", "owrx_qpa_platform"),
        ("DIGI_WINDOW_GEOMETRY", "digi_window_geometry"),
    )


@dataclass(frozen=True)
class DspConfig(_Section):
    anr_enabled: bool = False
    anr_intensity: int = 1
    filters: dict[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("ANR_Enabled", "anr_enabled"),
        ("ANR_Intensity", "anr_intensity"),
        ("DSPFilters", "filters"),
    )

    def __post_init__(self) -> None:
        # dsp_pipeline.py (el backend del ANR) trata "DSPFilters.anr" como
        # fuente de verdad al configurar cada contexto de audio (gui/web/
        # sdr_*) — si se desincroniza de anr_enabled/anr_intensity (p.ej. al
        # mover el slider de la consola, que solo toca esos dos campos), el
        # DSP aplica en silencio una intensidad distinta a la que muestra la
        # consola. Se resincroniza aquí en cada construcción/`replace()`,
        # conservando cualquier otro filtro no modelado.
        filters = dict(self.filters) if isinstance(self.filters, dict) else {}
        entry = dict(filters.get("anr") or {})
        entry["enabled"] = bool(self.anr_enabled)
        entry["intensity"] = max(1, min(10, int(self.anr_intensity)))
        filters["anr"] = entry
        object.__setattr__(self, "filters", filters)


# --------------------------------------------------------------------------- #
# Config raíz
# --------------------------------------------------------------------------- #
_SECTION_TYPES: tuple[tuple[str, type[_Section]], ...] = (
    ("audio", AudioConfig),
    ("cat", CatConfig),
    ("rigctld", RigctldConfig),
    ("hamlib", HamlibConfig),
    ("n1m", N1mConfig),
    ("owrx", OwrxConfig),
    ("spider", SpiderConfig),
    ("relays", RelayConfig),
    ("web", WebServerConfig),
    ("autocall", AutocallConfig),
    ("ui", UiConfig),
    ("dsp", DspConfig),
)


#: Claves legacy de funciones eliminadas por completo (p. ej. Roger Beep, el
#: PTT por línea serie/RTS). Un config real antiguo puede seguir
#: teniéndolas; se aceptan como "conocidas" para no dispararlas como clave
#: desconocida, pero se descartan sin más — no tiene sentido conservarlas en
#: ``AppConfig.extra`` si la función ya no existe en absoluto.
RETIRED_LEGACY_KEYS: frozenset[str] = frozenset(
    {"Roger_Beep", "Roger_Beep_Enabled", "PTT_COM", "PTT_VIA_CAT"}
)


def known_legacy_keys() -> frozenset[str]:
    keys: set[str] = set()
    for _, section_type in _SECTION_TYPES:
        keys.update(section_type.legacy_keys())
    return frozenset(keys) | RETIRED_LEGACY_KEYS


@dataclass(frozen=True)
class AppConfig:
    """Configuración completa de la aplicación."""

    schema_version: int = SCHEMA_VERSION
    audio: AudioConfig = field(default_factory=AudioConfig)
    cat: CatConfig = field(default_factory=CatConfig)
    rigctld: RigctldConfig = field(default_factory=RigctldConfig)
    hamlib: HamlibConfig = field(default_factory=HamlibConfig)
    n1m: N1mConfig = field(default_factory=N1mConfig)
    owrx: OwrxConfig = field(default_factory=OwrxConfig)
    spider: SpiderConfig = field(default_factory=SpiderConfig)
    relays: RelayConfig = field(default_factory=RelayConfig)
    web: WebServerConfig = field(default_factory=WebServerConfig)
    autocall: AutocallConfig = field(default_factory=AutocallConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    dsp: DspConfig = field(default_factory=DspConfig)
    #: claves legacy no reconocidas por ninguna sección (se conservan intactas)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy(cls, flat: Mapping[str, Any]) -> AppConfig:
        merged: dict[str, Any] = legacy_defaults()
        merged.update({k: v for k, v in flat.items() if k != "schema_version"})
        known = known_legacy_keys()
        extra = {
            k: copy.deepcopy(v)
            for k, v in flat.items()
            if k not in known and k != "schema_version"
        }
        return cls(
            schema_version=SCHEMA_VERSION,
            audio=AudioConfig.from_legacy(merged),
            cat=CatConfig.from_legacy(merged),
            rigctld=RigctldConfig.from_legacy(merged),
            hamlib=HamlibConfig.from_legacy(merged),
            n1m=N1mConfig.from_legacy(merged),
            owrx=OwrxConfig.from_legacy(merged),
            spider=SpiderConfig.from_legacy(merged),
            relays=RelayConfig.from_legacy(merged),
            web=WebServerConfig.from_legacy(merged),
            autocall=AutocallConfig.from_legacy(merged),
            ui=UiConfig.from_legacy(merged),
            dsp=DspConfig.from_legacy(merged),
            extra=extra,
        )

    def to_legacy(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, _ in _SECTION_TYPES:
            out.update(getattr(self, name).to_legacy())
        out.update(copy.deepcopy(self.extra))
        return out

    def to_native(self) -> dict[str, Any]:
        """Representación anidada para el ``config.json`` nuevo."""
        from dataclasses import asdict

        data = asdict(self)
        return data

    @classmethod
    def from_native(cls, data: Mapping[str, Any]) -> AppConfig:
        """Reconstruye desde la representación anidada de :meth:`to_native`.

        Se apoya en el round-trip legacy para no duplicar la lógica de coerción.
        """
        flat = _native_to_legacy(data)
        cfg = cls.from_legacy(flat)
        raw_extra = data.get("extra")
        if isinstance(raw_extra, Mapping):
            merged_extra = dict(cfg.extra)
            merged_extra.update({k: copy.deepcopy(v) for k, v in raw_extra.items()})
            cfg = replace_extra(cfg, merged_extra)
        return cfg


def replace_extra(cfg: AppConfig, extra: dict[str, Any]) -> AppConfig:
    from dataclasses import replace

    return replace(cfg, extra=extra)


def _native_to_legacy(data: Mapping[str, Any]) -> dict[str, Any]:
    """Aplana la representación anidada a claves legacy usando ``_FIELDS``."""
    flat: dict[str, Any] = legacy_defaults()
    # audio
    audio = data.get("audio", {})
    prefixes = {
        "speaker_pc": "Altavoz_PC",
        "speaker_radio": "Altavoz_Radio",
        "mic_pc": "Microfono_PC",
        "mic_radio": "Microfono_Radio",
    }
    for attr, prefix in prefixes.items():
        dev = audio.get(attr, {}) if isinstance(audio, Mapping) else {}
        flat[prefix] = dev.get("label", "")
        flat[f"{prefix}_Pulse"] = dev.get("pulse", "")
        flat[f"{prefix}_Index"] = dev.get("index", -1)
        flat[f"{prefix}_Channels"] = dev.get("channels", 2)
        flat[f"{prefix}_Framerate"] = dev.get("framerate", 48000)
    if isinstance(audio, Mapping) and "rx_source" in audio:
        flat["RX_AUDIO_SOURCE"] = audio["rx_source"]

    for name, section_type in _SECTION_TYPES:
        if name == "audio":
            continue
        section = data.get(name, {})
        if not isinstance(section, Mapping):
            continue
        for legacy_key, attr in section_type._FIELDS:  # noqa: SLF001
            if attr in section:
                flat[legacy_key] = section[attr]
        if name == "owrx":
            spots = section.get("spots", {})
            if isinstance(spots, Mapping):
                for legacy_key, attr in SpotsConfig._FIELDS:  # noqa: SLF001
                    if attr in spots:
                        flat[legacy_key] = spots[attr]
    return flat


__all__ = [
    "SCHEMA_VERSION",
    "AppConfig",
    "AudioConfig",
    "AudioDevice",
    "AutocallConfig",
    "CatConfig",
    "DspConfig",
    "HamlibConfig",
    "N1mConfig",
    "OwrxConfig",
    "RelayConfig",
    "RigctldConfig",
    "SpiderConfig",
    "SpotsConfig",
    "UiConfig",
    "WebServerConfig",
    "as_bool",
    "as_int",
    "as_str",
    "known_legacy_keys",
    "RETIRED_LEGACY_KEYS",
    "replace_extra",
]
