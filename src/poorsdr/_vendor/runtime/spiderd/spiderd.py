#!/usr/bin/env python3
"""
spiderd: DX spots bridge to WebSocket for OpenWebRX.

Supports two sources:
- telnet (classic DXSpider / CC-Cluster)
- mqtt (e.g. URE broker topics)
"""

import argparse
import asyncio
import configparser
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import ssl
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from websockets.legacy.server import serve

DX_RE = re.compile(r"^DX\s+de\s+(\S+):\s*([0-9.]+)\s+(\S+)\s+(.*)$", re.IGNORECASE)

MODE_TOKENS = {
    "CW",
    "SSB",
    "USB",
    "LSB",
    "AM",
    "FM",
    "FT8",
    "FT4",
    "RTTY",
    "PSK",
    "DIGI",
    "JT65",
    "JT9",
}

BANDS = [
    ("160m", 1800000, 2000000),
    ("80m", 3500000, 4000000),
    ("60m", 5300000, 5400000),
    ("40m", 7000000, 7300000),
    ("30m", 10100000, 10150000),
    ("20m", 14000000, 14350000),
    ("17m", 18068000, 18168000),
    ("15m", 21000000, 21450000),
    ("12m", 24890000, 24990000),
    ("10m", 28000000, 29700000),
    ("6m", 50000000, 54000000),
    ("4m", 70000000, 70500000),
    ("2m", 144000000, 148000000),
]


def parse_frequency(value) -> Optional[int]:
    if isinstance(value, str):
        # Accept decimal comma formats often seen in spot payloads.
        value = value.strip().replace(",", ".")
    try:
        freq = float(value)
    except (TypeError, ValueError):
        return None

    if freq <= 0:
        return None

    # Heuristics:
    # < 1000  -> MHz
    # < 1e6   -> kHz
    # else    -> Hz
    if freq < 1000:
        return int(freq * 1_000_000)
    if freq < 1_000_000:
        return int(freq * 1000)

    return int(freq)


def parse_isotime(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def band_for_freq(freq_hz: int) -> str:
    for name, start, end in BANDS:
        if start <= freq_hz <= end:
            return name
    return ""


def band_range_from_label(label: str) -> Optional[Tuple[int, int]]:
    text = str(label or "").strip().lower()
    if not text:
        return None
    for name, start, end in BANDS:
        if text == name.lower():
            return (start, end)
    return None


def normalize_freq_by_band(freq_hz: int, band_label: str) -> int:
    rng = band_range_from_label(band_label)
    if not rng:
        return int(freq_hz)
    lo, hi = rng
    if lo <= freq_hz <= hi:
        return int(freq_hz)
    # Some DX MQTT feeds publish qrg in tenths of kHz (x10 vs Hz conversion).
    for div in (10, 100, 1000):
        cand = int(freq_hz / div)
        if lo <= cand <= hi:
            return cand
    for mul in (10, 100, 1000):
        cand = int(freq_hz * mul)
        if lo <= cand <= hi:
            return cand
    return int(freq_hz)


def normalize_freq_generic(freq_hz: int) -> int:
    """
    Generic rescue for malformed MQTT qrg values (common x10/x100 scaling issues).
    Keep reducing by 10 until the value matches a known amateur band.
    """
    val = int(freq_hz)
    if band_for_freq(val):
        return val
    for _ in range(4):
        if val <= 0:
            break
        val = int(val / 10)
        if band_for_freq(val):
            return val
    return int(freq_hz)


def extract_mode_and_comment(rest: str) -> Tuple[str, str]:
    rest = rest.strip()
    if not rest:
        return "", ""

    parts = rest.split()
    if parts and parts[0].upper() in MODE_TOKENS:
        mode = parts[0].upper()
        comment = " ".join(parts[1:]).strip()
        return mode, comment

    for token in parts:
        t = token.upper()
        if t in MODE_TOKENS:
            return t, rest

    return "", rest


def sanitize_telnet(data: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 255:  # IAC
            i += 1
            if i < len(data) and data[i] in (251, 252, 253, 254):
                i += 2
            else:
                i += 1
            continue
        if b in (10, 13) or b >= 32:
            out.append(b)
        i += 1
    return out.decode("utf-8", errors="ignore")


class SpiderD:
    def __init__(self, cfg: configparser.ConfigParser) -> None:
        self.cfg = cfg
        self.ws_clients = set()
        self.stop_event = asyncio.Event()
        self.source_task = None
        self.ws_server = None

        self.bind_host = cfg.get("server", "bind", fallback="127.0.0.1")
        self.bind_port = cfg.getint("server", "port", fallback=7373)
        self.ws_path = cfg.get("server", "path", fallback="/spots")

        self.reconnect_initial = cfg.getfloat("reconnect", "initial_delay", fallback=3.0)
        self.reconnect_max = cfg.getfloat("reconnect", "max_delay", fallback=60.0)

        self.source_kind = cfg.get("source", "kind", fallback="mqtt").strip().lower()
        if self.source_kind not in ("mqtt", "telnet"):
            self.source_kind = "mqtt"

        self.cluster_host = cfg.get("cluster", "host", fallback="localhost")
        self.cluster_port = cfg.getint("cluster", "port", fallback=7300)
        self.cluster_user = cfg.get("cluster", "user", fallback="")
        self.cluster_password = cfg.get("cluster", "password", fallback="")
        self.read_timeout = cfg.getfloat("cluster", "read_timeout", fallback=120.0)

        self.mqtt_url = cfg.get("mqtt", "url", fallback="wss://ws.ure.es:443/mqtt")
        extra_urls_raw = cfg.get("mqtt", "urls", fallback="")
        self.mqtt_urls = [self.mqtt_url]
        for u in re.split(r"[,\n]", extra_urls_raw):
            u = u.strip()
            if u and u not in self.mqtt_urls:
                self.mqtt_urls.append(u)
        topics_raw = cfg.get(
            "mqtt",
            "topics",
            fallback="spider/spots/dx,spider/spots/rbn-cw,spider/spots/rbn-dig",
        )
        self.mqtt_topics = [
            topic.strip()
            for topic in re.split(r"[,\n]", topics_raw)
            if topic.strip()
        ]
        if not self.mqtt_topics:
            self.mqtt_topics = ["spider/spots/dx"]
        self.mqtt_username = cfg.get("mqtt", "username", fallback="")
        self.mqtt_password = cfg.get("mqtt", "password", fallback="")
        self.mqtt_client_id = cfg.get("mqtt", "client_id", fallback="")
        self.mqtt_qos = max(0, min(2, cfg.getint("mqtt", "qos", fallback=0)))
        self.mqtt_keepalive = max(10, cfg.getint("mqtt", "keepalive", fallback=30))
        self._mqtt_spot_count = 0

    async def start(self) -> None:
        self.ws_server = await serve(
            self.handle_ws,
            self.bind_host,
            self.bind_port,
            ping_interval=30,
            ping_timeout=30,
            max_size=1_000_000,
        )
        logging.info("WebSocket server listening on ws://%s:%s%s", self.bind_host, self.bind_port, self.ws_path)
        logging.info("Spider source selected: %s", self.source_kind)

        if self.source_kind == "telnet":
            self.source_task = asyncio.create_task(self.telnet_loop())
        else:
            self.source_task = asyncio.create_task(self.mqtt_loop())

        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        logging.info("Shutting down")

        if self.source_task:
            self.source_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.source_task

        if self.ws_server:
            self.ws_server.close()
            await self.ws_server.wait_closed()

        for ws in list(self.ws_clients):
            with contextlib.suppress(Exception):
                await ws.close()

    async def handle_ws(self, websocket, path) -> None:
        if path != self.ws_path:
            await websocket.close()
            return

        self.ws_clients.add(websocket)
        logging.info("WebSocket client connected (%d total)", len(self.ws_clients))
        try:
            await websocket.wait_closed()
        finally:
            self.ws_clients.discard(websocket)
            logging.info("WebSocket client disconnected (%d total)", len(self.ws_clients))

    async def broadcast(self, payload: Dict) -> None:
        if not self.ws_clients:
            return

        message = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        stale = []
        for ws in self.ws_clients:
            try:
                await asyncio.wait_for(ws.send(message), timeout=1.5)
            except Exception:
                stale.append(ws)

        for ws in stale:
            self.ws_clients.discard(ws)

    async def telnet_loop(self) -> None:
        delay = self.reconnect_initial
        while not self.stop_event.is_set():
            try:
                await self.run_telnet_once()
                delay = self.reconnect_initial
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.warning("Cluster connection error: %s", exc)
                await asyncio.sleep(delay)
                delay = min(self.reconnect_max, delay * 1.5)

    async def run_telnet_once(self) -> None:
        logging.info("Connecting to cluster %s:%d", self.cluster_host, self.cluster_port)
        reader, writer = await asyncio.open_connection(self.cluster_host, self.cluster_port)

        login_sent = False
        password_sent = False

        async def send_line(line: str) -> None:
            writer.write((line + "\n").encode("utf-8"))
            await writer.drain()

        async def delayed_login() -> None:
            nonlocal login_sent
            await asyncio.sleep(2.0)
            if self.cluster_user and not login_sent:
                await send_line(self.cluster_user)
                login_sent = True

        login_task = asyncio.create_task(delayed_login())

        try:
            while not self.stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(reader.readline(), timeout=self.read_timeout)
                except asyncio.TimeoutError:
                    logging.info("Cluster read timeout, reconnecting")
                    break

                if not raw:
                    logging.info("Cluster connection closed")
                    break

                line = sanitize_telnet(raw).strip()
                if not line:
                    continue

                lower = line.lower()
                if self.cluster_user and not login_sent and ("login" in lower or "call" in lower):
                    await send_line(self.cluster_user)
                    login_sent = True
                    continue

                if self.cluster_password and not password_sent and "password" in lower:
                    await send_line(self.cluster_password)
                    password_sent = True
                    continue

                spot = self.parse_telnet_spot(line)
                if spot:
                    await self.broadcast(spot)
        finally:
            login_task.cancel()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def parse_telnet_spot(self, line: str) -> Optional[Dict]:
        match = DX_RE.match(line)
        if not match:
            return None

        spotter = match.group(1)
        freq_raw = match.group(2)
        call = match.group(3)
        rest = match.group(4)

        freq_hz = parse_frequency(freq_raw)
        if freq_hz is None:
            return None

        mode, comment = extract_mode_and_comment(rest)

        return {
            "freq": int(freq_hz),
            "call": call.upper(),
            "mode": mode or "UNKNOWN",
            "comment": comment,
            "spotter": spotter.upper(),
            "band": band_for_freq(freq_hz),
            "time": int(time.time()),
            "source": "telnet",
        }

    async def mqtt_loop(self) -> None:
        delay = self.reconnect_initial
        while not self.stop_event.is_set():
            last_exc: Optional[Exception] = None
            try:
                urls = list(self._expand_mqtt_urls(self.mqtt_urls))
                for u in urls:
                    try:
                        logging.info("Trying MQTT URL: %s", u)
                        await self.run_mqtt_once(u)
                        delay = self.reconnect_initial
                        last_exc = None
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        last_exc = exc
                        logging.warning("MQTT URL failed (%s): %s", u, exc)
                if last_exc is None:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_exc = exc
            if last_exc is not None:
                logging.warning("MQTT connection error: %s", last_exc)
                await asyncio.sleep(delay)
                delay = min(self.reconnect_max, delay * 1.5)

    def _expand_mqtt_urls(self, base_urls):
        seen = set()
        for raw in base_urls:
            if not raw:
                continue
            u = raw.strip()
            if not u or u in seen:
                continue
            seen.add(u)
            yield u

            parsed = urlparse(u)
            if parsed.scheme not in ("ws", "wss"):
                continue
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            base = f"{parsed.scheme}://{host}{port}"
            # Fallback websocket paths for brokers/proxies that rewrite endpoints.
            for path in ("/mqtt", "/mqtt/", "/", "/ws"):
                cand = base + path
                if cand not in seen:
                    seen.add(cand)
                    yield cand

    async def run_mqtt_once(self, mqtt_url: str) -> None:
        try:
            import paho.mqtt.client as mqtt
        except Exception as exc:
            raise RuntimeError("paho-mqtt is required for MQTT source") from exc

        parsed = urlparse(mqtt_url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("mqtt", "mqtts", "ws", "wss"):
            raise RuntimeError(f"Unsupported MQTT URL scheme: {scheme}")

        host = parsed.hostname or "localhost"
        if parsed.port:
            port = parsed.port
        elif scheme in ("mqtts", "wss"):
            port = 443 if scheme == "wss" else 8883
        elif scheme == "ws":
            port = 80
        else:
            port = 1883

        transport = "websockets" if scheme in ("ws", "wss") else "tcp"
        ws_path = parsed.path or "/mqtt"
        if parsed.query:
            ws_path += "?" + parsed.query

        header_variants = [None]
        if transport == "websockets":
            base_origin = f"https://{host}" if scheme == "wss" else f"http://{host}"
            base_proto = {"Sec-WebSocket-Protocol": "mqtt"}
            header_variants.extend(
                [
                    base_proto,
                    {"Origin": base_origin, "Sec-WebSocket-Protocol": "mqtt"},
                    {"Origin": "https://ws.ure.es", "Sec-WebSocket-Protocol": "mqtt"},
                    {"Origin": "https://webcluster.ure.es", "Sec-WebSocket-Protocol": "mqtt"},
                ]
            )

        protocol_variants = [mqtt.MQTTv311, mqtt.MQTTv31]

        last_exc: Optional[Exception] = None
        for proto in protocol_variants:
            for headers in header_variants:
                try:
                    await self._run_mqtt_once_attempt(
                        mqtt=mqtt,
                        host=host,
                        port=port,
                        scheme=scheme,
                        transport=transport,
                        ws_path=ws_path,
                        ws_headers=headers,
                        proto=proto,
                    )
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    logging.warning(
                        "MQTT handshake attempt failed (proto=%s, headers=%s): %s",
                        "3.1.1" if proto == mqtt.MQTTv311 else "3.1",
                        headers if headers else "{}",
                        exc,
                    )
        if last_exc:
            raise last_exc

    async def _run_mqtt_once_attempt(self, mqtt, host, port, scheme, transport, ws_path, ws_headers, proto) -> None:
        client_id = self.mqtt_client_id or f"spiderd-{int(time.time() * 1000)}"
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        connected = asyncio.Event()
        disconnected = asyncio.Event()
        loop = asyncio.get_running_loop()

        client = mqtt.Client(client_id=client_id, clean_session=True, transport=transport, protocol=proto)

        username = self.mqtt_username or ""
        password = self.mqtt_password or ""
        if username:
            client.username_pw_set(username, password if password else None)

        if transport == "websockets":
            client.ws_set_options(path=ws_path, headers=ws_headers)

        if scheme in ("mqtts", "wss"):
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        def on_connect(_client, _userdata, _flags, rc):
            if rc != 0:
                loop.call_soon_threadsafe(disconnected.set)
                return
            logging.info("MQTT connected to %s:%d", host, port)
            for topic in self.mqtt_topics:
                _client.subscribe(topic, qos=self.mqtt_qos)
                logging.info("MQTT subscribed to %s (qos=%d)", topic, self.mqtt_qos)
            loop.call_soon_threadsafe(connected.set)

        def on_disconnect(_client, _userdata, rc):
            if rc != 0:
                logging.warning("MQTT disconnected (rc=%s)", rc)
            else:
                logging.info("MQTT disconnected")
            loop.call_soon_threadsafe(disconnected.set)

        def on_message(_client, _userdata, msg):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (msg.topic, bytes(msg.payload)))
            except asyncio.QueueFull:
                logging.warning("MQTT queue full, dropping message")
            except Exception:
                pass

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message

        client.connect(host, port, keepalive=self.mqtt_keepalive)
        client.loop_start()
        try:
            await asyncio.wait_for(connected.wait(), timeout=12)

            while not self.stop_event.is_set():
                if disconnected.is_set() and queue.empty():
                    raise RuntimeError("MQTT disconnected")

                try:
                    topic, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                spot = self.parse_mqtt_spot(topic, payload)
                if spot:
                    self._mqtt_spot_count += 1
                    if self._mqtt_spot_count <= 5 or (self._mqtt_spot_count % 50 == 0):
                        logging.info(
                            "MQTT spot #%d topic=%s call=%s freq=%s mode=%s",
                            self._mqtt_spot_count,
                            topic,
                            spot.get("call"),
                            spot.get("freq"),
                            spot.get("mode"),
                        )
                    await self.broadcast(spot)
        finally:
            with contextlib.suppress(Exception):
                client.disconnect()
            client.loop_stop()

    def parse_mqtt_spot(self, topic: str, payload: bytes) -> Optional[Dict]:
        try:
            raw = json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            return None

        if not isinstance(raw, dict):
            return None

        # Ignore non-spot frames such as solar/wcy.
        if topic.strip().lower() == "solar/wcy":
            return None

        freq_hz = parse_frequency(raw.get("qrg") or raw.get("frequency") or raw.get("freq"))
        call = raw.get("dx") or raw.get("call")
        if freq_hz is None or not call:
            return None
        raw_band = str(raw.get("band") or "").strip()
        freq_hz = normalize_freq_by_band(int(freq_hz), raw_band)
        freq_hz = normalize_freq_generic(int(freq_hz))

        mode = str(raw.get("mode") or raw.get("submode") or raw.get("md") or "").strip().upper()
        comment = str(raw.get("cmt") or raw.get("comment") or "")
        inferred_mode, inferred_comment = extract_mode_and_comment(comment)
        if inferred_mode and not mode:
            mode = inferred_mode
        if inferred_comment and inferred_comment != comment:
            comment = inferred_comment
        if not mode:
            tl = topic.lower()
            if "rbn-cw" in tl:
                mode = "CW"
            elif "rbn-dig" in tl:
                mode = "FT8"
            else:
                # Keep manual DX spots visible in default SSB/CW/FT8 filters.
                mode = "SSB"
        if mode == "DIGI":
            mode = "FT8"
        if mode in {"UNK", "UNKNOWN", "PHONE", "PH", "FONIA", "VOICE"}:
            mode = "SSB"
        spotter = str(raw.get("src") or raw.get("spotter") or "").upper()
        band = raw_band or band_for_freq(freq_hz)
        ts = (
            parse_isotime(raw.get("isots"))
            or parse_isotime(raw.get("utc"))
            or int(time.time())
        )

        return {
            "freq": int(freq_hz),
            "call": str(call).upper(),
            "mode": mode,
            "comment": comment,
            "spotter": spotter,
            "band": band,
            "time": int(ts),
            "source": "mqtt",
        }


def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(path)
    return cfg


def maybe_delegate_to_node(config_path: str) -> None:
    """
    Some container supervisors always launch spiderd.py directly.
    In MQTT mode we transparently re-exec the Node bridge to avoid paho
    websocket handshake incompatibilities on certain brokers.
    """
    try:
        cfg = load_config(config_path)
        source_kind = cfg.get("source", "kind", fallback="mqtt").strip().lower()
        if source_kind != "mqtt":
            return
        node_bin = shutil.which("node")
        node_bridge = "/opt/spiderd/spiderd_node.mjs"
        if not node_bin or not os.path.isfile(node_bridge):
            return
        os.execvp(node_bin, [node_bin, node_bridge, "--config", config_path])
    except Exception:
        # Fall back to Python implementation when delegation is not possible.
        return


def setup_logging(cfg: configparser.ConfigParser) -> None:
    level_name = cfg.get("logging", "level", fallback="INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")


async def main_async(args) -> None:
    cfg = load_config(args.config)
    setup_logging(cfg)

    service = SpiderD(cfg)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, service.stop_event.set)
        except NotImplementedError:
            pass

    await service.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="DX spots to WebSocket bridge")
    parser.add_argument("--config", default="spiderd.conf", help="Path to spiderd.conf")
    args = parser.parse_args()

    maybe_delegate_to_node(args.config)

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
