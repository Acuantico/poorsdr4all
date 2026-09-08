"""Generación del fichero de configuración de spiderd (feed de spots DX).

spiderd lee un INI con secciones [source] [mqtt] [cluster] [server] [reconnect]
[logging]. PoorSDR guarda los valores en config.json con claves ``SPIDER_*`` y
regenera ese INI cada vez que se cambian los ajustes.
"""

from __future__ import annotations

DEFAULT_MQTT_URL = "wss://ws.ure.es:443/mqtt"
DEFAULT_MQTT_TOPICS = "spider/spots/dx,spider/spots/rbn-cw,spider/spots/rbn-dig"
DEFAULT_TELNET_PORT = 7300
SERVER_BIND = "127.0.0.1"
SERVER_PORT = 7373
SERVER_PATH = "/spots"


def _s(cfg: dict, key: str, default: str = "") -> str:
    value = cfg.get(key, default)
    if value is None:
        return ""
    return str(value).strip()


def normalize_spider_source(value: object) -> str:
    text = str(value or "mqtt").strip().lower()
    return "telnet" if text == "telnet" else "mqtt"


def render_spiderd_conf(cfg: dict) -> str:
    """Devuelve el contenido completo de spiderd.conf a partir de claves SPIDER_*."""
    cfg = cfg or {}
    source = normalize_spider_source(cfg.get("SPIDER_SOURCE"))

    mqtt_url = _s(cfg, "SPIDER_MQTT_URL") or DEFAULT_MQTT_URL
    mqtt_topics = _s(cfg, "SPIDER_MQTT_TOPICS") or DEFAULT_MQTT_TOPICS
    mqtt_user = _s(cfg, "SPIDER_MQTT_USER")
    mqtt_pass = _s(cfg, "SPIDER_MQTT_PASS")

    telnet_host = _s(cfg, "SPIDER_TELNET_HOST")
    try:
        telnet_port = int(_s(cfg, "SPIDER_TELNET_PORT") or DEFAULT_TELNET_PORT)
    except (TypeError, ValueError):
        telnet_port = DEFAULT_TELNET_PORT
    telnet_call = _s(cfg, "SPIDER_TELNET_CALL")
    telnet_pass = _s(cfg, "SPIDER_TELNET_PASS")

    lines = [
        "# Generado por PoorSDR4All. No editar a mano: usa Ajustes > Cluster DX / Spots.",
        "",
        "[source]",
        f"kind = {source}",
        "",
        "[mqtt]",
        f"url = {mqtt_url}",
        f"topics = {mqtt_topics}",
        f"username = {mqtt_user}",
        f"password = {mqtt_pass}",
        "client_id =",
        "qos = 0",
        "keepalive = 30",
        "",
        "[cluster]",
        f"host = {telnet_host}",
        f"port = {telnet_port}",
        f"user = {telnet_call}",
        f"password = {telnet_pass}",
        "read_timeout = 120",
        "",
        "[server]",
        f"bind = {SERVER_BIND}",
        f"port = {SERVER_PORT}",
        f"path = {SERVER_PATH}",
        "",
        "[reconnect]",
        "initial_delay = 3",
        "max_delay = 60",
        "",
        "[logging]",
        "level = INFO",
        "",
    ]
    return "\n".join(lines)


__all__ = ["render_spiderd_conf", "normalize_spider_source",
           "DEFAULT_MQTT_URL", "DEFAULT_MQTT_TOPICS", "DEFAULT_TELNET_PORT"]
