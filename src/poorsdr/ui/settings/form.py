"""Definición declarativa de los campos de Ajustes y la aplicación a ``AppConfig``.

Sin tkinter: puro y testeable. La ventana (``window.py``) genera los widgets a
partir de :data:`TABS` y guarda con :func:`build_config`.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import fields, replace
from typing import TYPE_CHECKING, Any, NamedTuple

from poorsdr.config.model import AudioDevice
from poorsdr.core.cat.modes import MODE_TO_CAT
from poorsdr.core.cat.profiles import profile_choices
from poorsdr.core.theme import THEME_OPTIONS, background_for_label, theme_label

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from poorsdr.config.model import AppConfig
    from poorsdr.infra.devices import AudioEndpoint

_MODES = tuple(MODE_TO_CAT)

#: Atributos de ``AudioConfig`` que guardan un ``AudioDevice`` (no un escalar).
AUDIO_DEVICE_ATTRS: frozenset[str] = frozenset(
    {"speaker_pc", "speaker_radio", "mic_pc", "mic_radio"}
)

#: rol mostrado en la etiqueta del dispositivo, según el tipo de campo.
AUDIO_ROLE: dict[str, str] = {"sink": "salida", "source": "entrada"}


class Field(NamedTuple):
    section: str          # atributo de AppConfig ("cat", "owrx"…) o "owrx.spots"
    attr: str
    label_key: str         # clave en poorsdr.i18n.settings_labels.LABELS
    # str | int | float | bool | choice | json | password | theme
    # serial       -> combo editable con los puertos serie del sistema
    # sink/source  -> combo con salidas / entradas de audio (PulseAudio)
    # web_password -> entrada oculta; al guardar se sala + hashea
    kind: str = "str"
    choices: tuple[str, ...] = ()
    help_key: str = ""     # clave en poorsdr.i18n.settings_help.HELP


TABS: dict[str, tuple[Field, ...]] = {
    "Radio / CAT": (
        Field("cat", "port", "label_cat_port", "serial", help_key="help_cat_port"),
        Field("cat", "rig_profile", "label_cat_rig_profile", "choice", profile_choices(),
              help_key="help_cat_rig_profile"),
        Field("cat", "baud", "label_cat_baud", "int", help_key="help_cat_baud"),
        Field("cat", "control_mode", "label_cat_control_mode", "choice", ("direct", "hamlib"),
              help_key="help_cat_control_mode"),
        Field("cat", "start_freq_hz", "label_cat_start_freq_hz", "int",
              help_key="help_cat_start_freq_hz"),
        Field("cat", "step_hz", "label_cat_step_hz", "int", help_key="help_cat_step_hz"),
        Field("rigctld", "enabled", "label_rigctld_enabled", "bool",
              help_key="help_rigctld_enabled"),
        Field("rigctld", "host", "label_rigctld_host", help_key="help_rigctld_host"),
        Field("rigctld", "port", "label_rigctld_port", "int", help_key="help_rigctld_port"),
        Field("n1m", "enabled", "label_n1m_enabled", "bool", help_key="help_n1m_enabled"),
        Field("n1m", "host", "label_host", help_key="help_n1m_host"),
        Field("n1m", "port", "label_port", "int", help_key="help_n1m_port"),
    ),
    "Audio": (
        Field("audio", "rx_source", "label_audio_rx_source", "choice", ("sdr", "radio"),
              help_key="help_audio_rx_source"),
        Field("audio", "speaker_pc", "label_audio_speaker_pc", "sink",
              help_key="help_audio_speaker_pc"),
        Field("audio", "mic_pc", "label_audio_mic_pc", "source",
              help_key="help_audio_mic_pc"),
        Field("audio", "speaker_radio", "label_audio_speaker_radio", "source",
              help_key="help_audio_speaker_radio"),
        Field("audio", "mic_radio", "label_audio_mic_radio", "sink",
              help_key="help_audio_mic_radio"),
    ),
    "OWRX": (
        Field("owrx", "enabled", "label_owrx_enabled", "bool", help_key="help_owrx_enabled"),
        Field("owrx", "host", "label_host", help_key="help_owrx_host"),
        Field("owrx", "port", "label_port", "int", help_key="help_owrx_port"),
        Field("owrx", "key", "label_owrx_key", "password", help_key="help_owrx_key"),
        Field("owrx", "runtime", "label_owrx_runtime", "choice", ("native", "docker"),
              help_key="help_owrx_runtime"),
        Field("owrx", "auto_open_on_start", "label_owrx_auto_open", "bool",
              help_key="help_owrx_auto_open_on_start"),
        Field("owrx", "follow_app_only", "label_owrx_follow_app_only", "bool",
              help_key="help_owrx_follow_app_only"),
        Field("owrx", "sdr_hint", "label_owrx_sdr_hint", "str", help_key="help_owrx_sdr_hint"),
        Field("owrx", "smeter_calibrated", "label_owrx_smeter_calibrated", "bool",
              help_key="help_owrx_smeter_calibrated"),
        Field("owrx", "smeter_s9_dbfs", "label_owrx_smeter_s9_dbfs", "int",
              help_key="help_owrx_smeter_s9_dbfs"),
        Field("owrx", "smeter_noise_floor_s", "label_owrx_smeter_noise_floor_s", "int",
              help_key="help_owrx_smeter_noise_floor_s"),
        Field("owrx", "band_profiles", "label_owrx_band_profiles", "json",
              help_key="help_owrx_band_profiles"),
    ),
    "Spots / Cluster": (
        # Qué tipos de spot se pintan se elige desde el botón Spots de la consola;
        # aquí solo queda la duración y la fuente del cluster DX.
        Field("owrx.spots", "retention_min", "label_spots_retention_min", "int",
              help_key="help_spots_retention_min"),
        Field("spider", "source", "label_spider_source", "choice", ("mqtt", "telnet"),
              help_key="help_spider_source"),
        Field("spider", "mqtt_url", "label_spider_mqtt_url", help_key="help_spider_mqtt_url"),
        Field("spider", "mqtt_topics", "label_spider_mqtt_topics",
              help_key="help_spider_mqtt_topics"),
        Field("spider", "mqtt_user", "label_spider_mqtt_user",
              help_key="help_spider_mqtt_user"),
        Field("spider", "mqtt_pass", "label_spider_mqtt_pass", "password",
              help_key="help_spider_mqtt_pass"),
        Field("spider", "telnet_host", "label_spider_telnet_host",
              help_key="help_spider_telnet_host"),
        Field("spider", "telnet_port", "label_spider_telnet_port", "int",
              help_key="help_spider_telnet_port"),
        Field("spider", "telnet_call", "label_spider_telnet_call",
              help_key="help_spider_telnet_call"),
        Field("spider", "telnet_pass", "label_spider_telnet_pass", "password",
              help_key="help_spider_telnet_pass"),
    ),
    # La pestaña "Relés" ya no es fija: la aporta el plugin ``filter_relays``
    # (ver plugins/filter-relays) vía ``PluginContext.add_settings_tab``, y
    # solo aparece si ese plugin está instalado y activo.
    "Web": (
        Field("web", "enabled", "label_web_enabled", "bool", help_key="help_web_enabled"),
        Field("web", "host", "label_host", help_key="help_web_host"),
        Field("web", "port", "label_port", "int", help_key="help_web_port"),
        Field("web", "allow_wan", "label_web_allow_wan", "bool",
              help_key="help_web_allow_wan"),
        Field("web", "auto_https", "label_web_auto_https", "bool",
              help_key="help_web_auto_https"),
        Field("web", "user", "label_web_user", help_key="help_web_user"),
        Field("web", "password_hash", "label_web_password", "web_password",
              help_key="help_web_password"),
    ),
    "Interfaz": (
        Field("ui", "language", "label_ui_language", "choice",
              ("es", "en", "fr", "de", "it", "pt", "tr", "pl", "ru", "gl", "ca", "eu"),
              help_key="help_ui_language"),
        Field("ui", "background_image", "label_ui_theme", "theme", tuple(THEME_OPTIONS),
              help_key="help_ui_theme"),
        Field("ui", "display_mode", "label_ui_display_mode", "choice", _MODES,
              help_key="help_ui_display_mode"),
    ),
    # La pestaña "Autollamada" la dibuja window.py con un editor propio
    # (hasta 10 macros + asignación a los 4 botones); estos campos son la vía
    # de guardado y validación pero no se muestran uno a uno (sin label_key).
    "Autollamada": (
        Field("autocall", "profiles", "", "json"),
        Field("autocall", "buttons", "", "json"),
    ),
    # La pestaña "Atajos" también tiene editor propio (una tecla por acción).
    "Atajos": (
        Field("ui", "hotkeys", "", "json"),
    ),
    # "Plugins": editor propio; el estado se guarda en ``extra["PLUGINS"]``.
    "Plugins": (),
    # "Acerca de": puramente informativa (autor, versión, web, agradecimientos).
    "Acerca de": (),
}

#: Clave de traducción (poorsdr.i18n.settings_labels) del título de cada pestaña.
#: Las que no aparecen aquí (OWRX, Web, Plugins) son términos técnicos/marca
#: que no se traducen.
TAB_LABEL_KEY: dict[str, str] = {
    "Radio / CAT": "label_tab_radio_cat",
    "Audio": "label_tab_audio",
    "Spots / Cluster": "label_tab_spots_cluster",
    "Interfaz": "label_tab_interface",
    "Autollamada": "label_tab_autocall",
    "Atajos": "label_tab_hotkeys",
    "Acerca de": "label_tab_about",
    "Relés": "label_tab_relays",
}

ALL_FIELDS: tuple[Field, ...] = tuple(f for tab in TABS.values() for f in tab)

#: Pestañas con editor propio en window.py (no se generan campo a campo).
CUSTOM_TABS: frozenset[str] = frozenset({"Autollamada", "Atajos", "Plugins", "Acerca de"})

#: Clave especial que emite el editor de plugins (mapa ``{id: bool}`` JSON).
PLUGINS_KEY = ("__plugins__", "map")

MACRO_LIMIT = 10


def get_value(cfg: AppConfig, field: Field) -> Any:
    obj: Any = cfg
    for part in field.section.split("."):
        obj = getattr(obj, part)
    value = getattr(obj, field.attr)
    if field.kind == "theme":
        return theme_label(str(value))
    if field.kind in ("sink", "source"):
        return value.label or value.pulse  # value es un AudioDevice
    if field.kind == "web_password":
        return ""  # nunca se muestra el hash
    return value


def _compose_label(number: int, name: str, role: str) -> str:
    text = f"{name} ({role})" if role else name
    return f"{number}: {text}" if number is not None and number >= 0 else text


def audio_label(endpoint: AudioEndpoint, role: str = "") -> str:
    """Etiqueta al estilo del original: ``"39: Descripción (salida)"``."""
    return _compose_label(endpoint.display_index, endpoint.description or endpoint.name, role)


def audio_label_for(dev: AudioDevice, endpoint: AudioEndpoint, role: str = "") -> str:
    """Como :func:`audio_label` pero conserva el **nombre elegido por el usuario**
    (el de la config) y solo le injerta el número del dispositivo actual."""
    chosen = label_core(dev.label or "", role).strip()
    return _compose_label(endpoint.display_index, chosen or endpoint.description or endpoint.name, role)


def label_core(text: str, role: str) -> str:
    """Quita el prefijo ``"N: "`` y el sufijo ``" (rol)"`` de una etiqueta."""
    core = text.strip()
    if ":" in core and core.split(":", 1)[0].strip().isdigit():
        core = core.split(":", 1)[1].strip()
    for suffix in (f" ({role})", " (salida)", " (entrada)"):
        if suffix and core.endswith(suffix):
            core = core[: -len(suffix)].strip()
            break
    return core


def audio_device_from_pick(
    pick: str,
    catalog: Sequence[AudioEndpoint],
    previous: AudioDevice,
    *,
    role: str = "",
) -> AudioDevice:
    """Traduce la elección del combo a un ``AudioDevice``.

    ``pick`` suele ser la etiqueta al estilo del original
    (``"39: Descripción (salida)"``), pero también vale un ``name`` a secas o
    una descripción.

    - vacío            → ``AudioDevice()`` ("ninguno")
    - sin cambios      → se devuelve ``previous`` tal cual
    - está en catálogo → name + descripción + índice + canales/tasa reales
    - no está          → se respeta el texto (pactl caído o equipo desconectado)
    """
    pick = (pick or "").strip()
    if not pick:
        return AudioDevice()
    if (previous.pulse or previous.label) and pick in (previous.pulse, previous.label):
        return previous
    core = label_core(pick, role)
    # Mismo dispositivo que ya estaba (solo cambió el número mostrado o se le
    # injertó): conserva el pulse/index reales, actualiza la etiqueta.
    if previous.pulse and core and core == label_core(previous.label or "", role):
        return replace(previous, label=pick)
    for endpoint in catalog:
        if pick in (endpoint.name, audio_label(endpoint, role)) or core in (
            endpoint.name,
            endpoint.description,
        ):
            return AudioDevice(
                label=audio_label(endpoint, role),
                pulse=endpoint.name,
                index=endpoint.pa_index if endpoint.pa_index is not None else -1,
                channels=endpoint.channels or previous.channels,
                framerate=endpoint.rate or previous.framerate,
            )
    return replace(previous, label=pick, pulse=core or pick, index=-1)


def hash_web_password(password: str, previous_salt: str, salt_factory: Callable[[], str]) -> tuple[str, str]:
    """``(salt, hash)`` para una contraseña nueva mediante PBKDF2-SHA256."""
    salt = previous_salt or salt_factory()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 600_000
    ).hex()
    return salt, digest


def coerce_value(field: Field, raw: Any) -> Any:
    if field.kind == "bool":
        return bool(raw)
    if field.kind == "int":
        return int(float(str(raw).strip() or 0))
    if field.kind == "float":
        return float(str(raw).strip() or 0)
    if field.kind == "json":
        return json.loads(str(raw))
    if field.kind == "theme":
        return background_for_label(str(raw))
    return str(raw)


def build_config(
    cfg: AppConfig,
    raw_values: dict[tuple[str, str], Any],
    *,
    audio_catalog: Sequence[AudioEndpoint] = (),
    salt_factory: Callable[[], str] = lambda: secrets.token_hex(8),
    extra_fields: Sequence[Field] = (),
) -> AppConfig:
    """Aplica los valores del formulario (crudos) a ``cfg`` y devuelve uno nuevo.

    ``raw_values`` va indexado por ``(sección, atributo)``. ``audio_catalog`` es
    la lista de sinks+sources del sistema, para resolver los campos de audio.
    ``extra_fields`` son campos que no viven en :data:`TABS` (p. ej. los que
    aporta un plugin con ``PluginContext.add_settings_tab``). Pura salvo por
    ``salt_factory`` (inyectable).
    """
    plugins_raw = raw_values.get(PLUGINS_KEY)
    if plugins_raw is not None:
        try:
            pmap = json.loads(str(plugins_raw))
        except (ValueError, TypeError):
            pmap = None
        if isinstance(pmap, dict):
            cfg = replace(
                cfg,
                extra={**cfg.extra, "PLUGINS": {str(k): bool(v) for k, v in pmap.items()}},
            )

    by_section: dict[str, dict[str, Any]] = {}
    audio_devices: dict[str, Any] = {}
    field_by_key = {(f.section, f.attr): f for f in (*ALL_FIELDS, *extra_fields)}
    for key, raw in raw_values.items():
        field = field_by_key.get(key)
        if field is None:
            continue
        if field.section == "audio" and field.attr in AUDIO_DEVICE_ATTRS:
            audio_devices[field.attr] = audio_device_from_pick(
                str(raw), audio_catalog, getattr(cfg.audio, field.attr),
                role=AUDIO_ROLE.get(field.kind, ""),
            )
            continue
        if field.kind == "web_password":
            typed = str(raw or "").strip()
            if typed:
                salt, digest = hash_web_password(typed, cfg.web.password_salt, salt_factory)
                by_section.setdefault("web", {})["password_salt"] = salt
                by_section.setdefault("web", {})["password_hash"] = digest
                if not cfg.web.secret:
                    by_section.setdefault("web", {})["secret"] = secrets.token_hex(32)
            continue
        by_section.setdefault(field.section, {})[field.attr] = coerce_value(field, raw)

    spots_changes = by_section.pop("owrx.spots", None)
    if spots_changes:
        cfg = replace(cfg, owrx=replace(cfg.owrx, spots=replace(cfg.owrx.spots, **spots_changes)))
    if audio_devices:
        cfg = replace(cfg, audio=replace(cfg.audio, **audio_devices))
    for section, changes in by_section.items():
        current = getattr(cfg, section)
        valid = {f.name for f in fields(current)}
        cfg = replace(
            cfg, **{section: replace(current, **{k: v for k, v in changes.items() if k in valid})}
        )
    return cfg


__all__ = [
    "ALL_FIELDS",
    "AUDIO_DEVICE_ATTRS",
    "AUDIO_ROLE",
    "CUSTOM_TABS",
    "MACRO_LIMIT",
    "PLUGINS_KEY",
    "TABS",
    "Field",
    "audio_device_from_pick",
    "audio_label",
    "audio_label_for",
    "build_config",
    "coerce_value",
    "get_value",
    "hash_web_password",
    "label_core",
]
