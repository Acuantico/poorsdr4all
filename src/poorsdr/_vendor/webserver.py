import asyncio
import base64
import contextlib
import contextvars
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from paths import runtime_path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

try:
    import pyotp
except Exception:
    pyotp = None

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
    try:
        from aiortc import RTCConfiguration, RTCIceServer
    except Exception:
        RTCConfiguration = None
        RTCIceServer = None
    import av
    import numpy as np
except Exception:
    RTCPeerConnection = None
    RTCSessionDescription = None
    MediaStreamTrack = object
    RTCConfiguration = None
    RTCIceServer = None
    av = None
    np = None

# Búfer de jitter de audio directo (mismo arreglo que en IRCB Pro): el de aiortc
# retiene 4 paquetes (80 ms) y, si se pierde uno, se atasca hasta 16 (320 ms)
# sin recuperar luego el retraso. Aquí cada paquete se entrega al llegar
# (descartando duplicados y atrasados); el jitter lo absorbe el colchón acotado
# de la voz remota en audio.py (REMOTE_TX_BUFFER_MS / REMOTE_TX_MAX_MS).
try:
    import aiortc.rtcrtpreceiver as _aiortc_receiver
    from aiortc.jitterbuffer import JitterBuffer as _JitterBufferOriginal
    from aiortc.jitterbuffer import JitterFrame as _JitterFrame
    from aiortc.jitterbuffer import uint16_add as _uint16_add

    class _DirectAudioJitterBuffer:
        def __init__(self, capacity: int = 16, prefetch: int = 0, is_video: bool = False):
            self._capacity = capacity
            self._last = None
            self._late = 0

        @property
        def capacity(self) -> int:
            return self._capacity

        def add(self, packet):
            sn = packet.sequence_number
            if self._last is not None:
                delta = _uint16_add(sn, -self._last)
                if delta == 0:
                    return False, None
                if delta >= 0x8000:
                    self._late += 1
                    if self._late < 50:
                        return False, None
                    # Muchos "atrasados" seguidos: la numeración se reinició.
            self._late = 0
            self._last = sn
            return False, _JitterFrame(data=packet._data, timestamp=packet.timestamp)

    def _jitter_buffer_factory(capacity, prefetch=0, is_video=False):
        if is_video:
            return _JitterBufferOriginal(capacity=capacity, prefetch=prefetch, is_video=True)
        return _DirectAudioJitterBuffer(capacity)

    _aiortc_receiver.JitterBuffer = _jitter_buffer_factory
except Exception:  # aiortc ausente o con otra estructura interna: se deja el original
    pass

# Audio WebRTC por la VPN (vpn.py, mismo arreglo que IRCB Pro): si el navegador
# entra por el túnel (https://10.9.0.1:puerto), el audio también debe ir por
# dentro. Se ofrece un único candidato ICE en 127.0.0.1, en un puerto fijo que
# el ayudante WireGuard reenvía desde la IP del túnel, y en la respuesta SDP se
# anuncia esa IP. Sin esto el audio intentaría salir por fuera del túnel.
_TUNNEL_MODE = contextvars.ContextVar("poorsdr_audio_via_tunnel", default=False)
try:
    from vpn import AUDIO_PORTS as _TUNNEL_AUDIO_PORTS
    from vpn import SERVER_IP as _TUNNEL_IP
except Exception:  # sin vpn.py
    _TUNNEL_AUDIO_PORTS = tuple(range(51840, 51850))
    _TUNNEL_IP = "10.9.0.1"

try:
    import aioice.ice as _aioice_ice
    import aiortc.rtcicetransport as _aiortc_ice

    class _TunnelIceConnection(_aioice_ice.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._via_tunnel = _TUNNEL_MODE.get()

        async def get_component_candidates(self, component, addresses, timeout=5):
            if not self._via_tunnel:
                return await super().get_component_candidates(component, addresses, timeout)
            loop = asyncio.get_event_loop()
            for port in _TUNNEL_AUDIO_PORTS:
                try:
                    _transport, protocol = await loop.create_datagram_endpoint(
                        lambda: _aioice_ice.StunProtocol(self), local_addr=("127.0.0.1", port)
                    )
                except OSError:
                    continue  # puerto ocupado por una sesión anterior que aún se cierra
                candidate = _aioice_ice.Candidate(
                    foundation=_aioice_ice.candidate_foundation("host", "udp", "127.0.0.1"),
                    component=component,
                    transport="udp",
                    priority=_aioice_ice.candidate_priority(component, "host"),
                    host="127.0.0.1",
                    port=port,
                    type="host",
                )
                protocol.local_candidate = candidate
                self._protocols.append(protocol)
                return [candidate]
            raise ConnectionError("No quedan puertos libres para el audio por la VPN")

    _aiortc_ice.Connection = _TunnelIceConnection
except Exception:  # aiortc/aioice ausentes o con otra estructura interna
    pass


def _request_via_tunnel(request) -> bool:
    """True si el navegador entró por la VPN (https://10.9.0.1:puerto)."""
    try:
        host = str(request.headers.get("host") or "")
        return host.rsplit(":", 1)[0].strip("[]") == _TUNNEL_IP
    except Exception:
        return False

try:
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except Exception:
    x509 = None
    default_backend = None
    hashes = None
    serialization = None
    rsa = None
    NameOID = None

import audio
import audio_remote


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 600_000
    ).hex()


def make_token(secret: str, payload: Dict[str, Any], ttl_sec: int = 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(payload)
    payload["exp"] = int(time.time()) + int(ttl_sec)
    header_b64 = _base64url(json.dumps(header).encode("utf-8"))
    payload_b64 = _base64url(json.dumps(payload).encode("utf-8"))
    sig = _base64url(_hmac_sha256(secret.encode("utf-8"), f"{header_b64}.{payload_b64}".encode("utf-8")))
    return f"{header_b64}.{payload_b64}.{sig}"


def verify_token(secret: str, token: str) -> Optional[Dict[str, Any]]:
    try:
        # Validate token format
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig = parts

        # Validate algorithm in header
        try:
            header = json.loads(_base64url_decode(header_b64))
            if header.get("alg") != "HS256":
                return None
        except Exception:
            return None

        # Verify signature
        expected = _base64url(_hmac_sha256(secret.encode("utf-8"), f"{header_b64}.{payload_b64}".encode("utf-8")))
        if not hmac.compare_digest(expected, sig):
            return None

        # Validate payload
        payload = json.loads(_base64url_decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
    except Exception:
        return None


def _is_private_ipv4(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_private
    except Exception:
        return False


def _is_virtual_iface(name: str) -> bool:
    n = str(name or "").lower()
    prefixes = (
        "lo",
        "docker",
        "br-",
        "veth",
        "virbr",
        "tun",
        "tap",
        "wg",
        "zt",
        "tailscale",
        "cloudflare",
    )
    return any(n.startswith(prefix) for prefix in prefixes)


def _iface_ipv4(name: str) -> Optional[str]:
    if not name or fcntl is None:
        return None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ifreq = struct.pack("256s", name.encode("utf-8")[:15])
        result = fcntl.ioctl(sock.fileno(), 0x8915, ifreq)  # SIOCGIFADDR
        sock.close()
        return socket.inet_ntoa(result[20:24])
    except Exception:
        return None


def _default_route_iface() -> Optional[str]:
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()[1:]
        for line in lines:
            cols = line.split()
            if len(cols) < 8:
                continue
            iface, destination, _gateway, flags = cols[0], cols[1], cols[2], cols[3]
            if destination == "00000000" and (int(flags, 16) & 0x2):
                return iface
    except Exception:
        return None
    return None


def _detect_local_ip() -> Optional[str]:
    # 1) Prefer IPv4 from the default route interface, excluding virtual/tunnel links.
    try:
        iface = _default_route_iface()
        if iface and not _is_virtual_iface(iface):
            ip = _iface_ipv4(iface)
            if ip and _is_private_ipv4(ip):
                return ip
    except Exception:
        pass
    # 2) Fallback to UDP route probing.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and _is_private_ipv4(ip):
            return ip
    except Exception:
        pass
    return None


def _normalize_web_bind_host(host: str, allow_wan: bool) -> str:
    value = str(host or "").strip()
    if allow_wan:
        # Distribution mode: always listen on all interfaces in LAN/WAN mode.
        return "0.0.0.0"
    if value.lower() in {"", "localhost", "127.0.0.1", "::1"}:
        return "127.0.0.1"
    return value


def _collect_access_hosts(bind_host: str, configured_host: str, allow_wan: bool) -> list[str]:
    hosts: list[str] = []

    def _add(value: Optional[str]) -> None:
        item = str(value or "").strip()
        if not item or item in hosts:
            return
        hosts.append(item)

    configured = str(configured_host or "").strip()
    if allow_wan:
        local_ip = _detect_local_ip()
        _add(local_ip)
        # Keep configured host as secondary hint only if it looks like a concrete host.
        if configured and configured not in {"0.0.0.0", "*", "::", "localhost", "127.0.0.1"}:
            _add(configured)
        _add(socket.gethostname())
        _add("localhost")
        _add("127.0.0.1")
    else:
        _add(bind_host)
        if bind_host in {"127.0.0.1", "localhost"}:
            _add("localhost")
            _add("127.0.0.1")
    return hosts


def _format_access_urls(hosts: list[str], port: int, secure: bool) -> list[str]:
    scheme = "https" if secure else "http"
    urls: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        value = str(host or "").strip()
        if not value or value in {"0.0.0.0", "*", "::"}:
            continue
        url = f"{scheme}://{value}:{int(port)}"
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _can_bind(host: str, port: int) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, int(port)))
        sock.close()
        return True
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return False


def _append_web_request_log(line: str) -> None:
    try:
        path = runtime_path("web_server_requests.log")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
    except Exception:
        pass


async def _wait_for_ice_gathering_complete(pc, timeout_s: float = 3.0) -> None:
    if pc is None:
        return
    try:
        if str(getattr(pc, "iceGatheringState", "") or "").lower() == "complete":
            return
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    done = loop.create_future()

    def _mark_complete() -> None:
        try:
            state = str(getattr(pc, "iceGatheringState", "") or "").lower()
        except Exception:
            state = ""
        if state == "complete" and not done.done():
            done.set_result(True)

    try:
        @pc.on("icegatheringstatechange")
        async def _on_ice_gathering_state_change():
            _mark_complete()
    except Exception:
        pass

    _mark_complete()
    if done.done():
        return
    try:
        await asyncio.wait_for(done, timeout=max(0.05, float(timeout_s)))
    except asyncio.TimeoutError:
        pass


def _ensure_self_signed_cert(cert_path: str, key_path: str, hosts: list[str]) -> bool:
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return True
    if x509 is None:
        print("ERROR: No se puede generar HTTPS autom\u00e1tico (falta cryptography).")
        return False
    try:
        os.makedirs(os.path.dirname(cert_path), exist_ok=True)
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "ES"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PoorSDR4All"),
                x509.NameAttribute(NameOID.COMMON_NAME, hosts[0] if hosts else "localhost"),
            ]
        )
        san_list = []
        for h in hosts:
            item = str(h or "").strip()
            if not item:
                continue
            try:
                san_list.append(x509.IPAddress(ipaddress.ip_address(item)))
            except Exception:
                san_list.append(x509.DNSName(item))
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow() - timedelta(days=1))
            .not_valid_after(datetime.utcnow() + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256(), default_backend())
        )
        with open(key_path, "wb") as f:
            f.write(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        with contextlib.suppress(OSError):
            os.chmod(key_path, 0o600)
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception as exc:
        print(f"ERROR: No se pudo generar certificado HTTPS: {exc}")
        return False


def _runtime_data_dir() -> str:
    custom = str(os.environ.get("POORSDR_RUNTIME_DIR", "") or "").strip()
    if custom:
        path = os.path.abspath(custom)
    else:
        # Portable default: keep runtime artifacts inside app runtime tree.
        path = str(runtime_path("runtime"))
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class WebCallbacks:
    get_state: Callable[[], Dict[str, Any]]
    set_frequency: Callable[[int], None]
    set_mode: Callable[[str], None]
    set_band: Callable[[str], None]
    set_step: Callable[[float], None]
    set_ptt: Callable[[bool], None]
    set_volumes: Callable[[float, float], None]
    toggle_audio: Callable[[bool], None]
    set_anr: Callable[[bool], None]
    set_anr_intensity: Callable[[int], None]


class RxAudioTrack(MediaStreamTrack):
    kind = "audio"
    # Audio normalization constants (unified for RX and TX)
    AUDIO_SCALE_DIVISOR = 32768.0
    AUDIO_SCALE_THRESHOLD = 1.5
    AUDIO_MAX_ABS_THRESHOLD = 2.0
    # Duración de la rampa al entrar/salir de un hueco de silencio (underrun
    # o PTT): saltar en seco de audio real a silencio (o al revés) es un
    # escalón brusco en la forma de onda — exactamente lo que se oye como
    # "petardeo"/chasquido, sea cual sea la causa del hueco. 5 ms es
    # audible como transición pero no como un tono/warble aparte.
    _FADE_SAMPLES = 240
    # Frames reales consecutivos que hay que confirmar tras soltar PTT antes
    # de servirlos de verdad — ver el comentario junto a _ptt_recovering en
    # recv().
    _PTT_RECOVERY_TARGET = 2

    def __init__(self, sample_rate: int = 48000):
        super().__init__()
        self.sample_rate = sample_rate
        # Opus expects 20 ms frames at 48 kHz -> 960 samples.
        self.samples_per_frame = 960
        self._pts = 0
        self._buffer = np.zeros(0, dtype=np.float32) if np is not None else None
        self._last_audio_time = 0.0
        self._empty_warn_at = 0.0
        self._last_rms_log = 0.0
        self._last_rms = 0.0
        self._last_data_time = time.time()
        self._last_remote_chunk_at = 0.0
        self._timeout_threshold = 10.0  # 10 seconds timeout
        self._underrun_count = 0
        # Keep polling tight to reduce jitter/latency on LAN/mobile.
        self._poll_slice = 0.002
        self._max_wait_for_chunk = 0.025
        # Diagnóstico incondicional (no depende del aviso "WARN: ... > 2 en
        # 10 s", que puede no dispararse nunca con huecos ya audibles: un
        # frame de 20 ms en silencio de vez en cuando ya suena como un
        # "tirón", y podía quedarse por debajo de ese umbral sin avisar
        # nunca). Escribe cada ~2 s en web_server_requests.log cuántos
        # frames se sirvieron de verdad frente a cuántos se rellenaron con
        # silencio, para poder diagnosticar sin depender de pegar la
        # consola a mano.
        self._diag_frames = 0
        self._diag_underruns = 0
        self._diag_log_at = 0.0
        # Reloj de tiempo real propio del track: ver el comentario junto al
        # `await asyncio.sleep(wait)` al final de recv().
        self._clock_start: Optional[float] = None
        # Alineación de ese reloj con la captura: ver _align_clock().
        self._chunk_age: Optional[float] = None
        self._age_min = 1.0
        self._age_frames = 0
        # Declick: ver el comentario junto a _FADE_SAMPLES en recv(). Guarda
        # la última muestra real servida y si el frame anterior fue relleno
        # de silencio (underrun o PTT), para poder atenuar/recuperar en
        # rampa en vez de saltar en seco.
        self._last_sample = 0.0
        self._prev_frame_was_silence = False
        # Cada conexión WebRTC tiene su propia cola RX en audio_remote (ver
        # el comentario al principio de audio_remote.py): antes todos los
        # oyentes competían por vaciar el mismo buffer compartido, y con dos
        # conexiones a la vez (confirmado en real: el mismo operador desde
        # el móvil y el escritorio) cada una se quedaba con ~35-40% de sus
        # frames en underrun de forma sostenida, no puntual. El que cierre
        # esta conexión (el handler de `connectionstatechange` en
        # `webrtc_offer`) debe llamar a `audio_remote.unregister_listener`
        # con este id — si no, la cola queda huérfana en el registro.
        self._listener_id = audio_remote.register_listener()
        # Ver el comentario junto a _PTT_RECOVERY_TARGET y la rama de
        # recuperación en recv().
        self._ptt_recovering = False
        self._ptt_recovery_hits = 0
        self._silence_was_ptt = False

    def _normalize_samples(self, samples: np.ndarray, src_rate: int, target_rate: int) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32).flatten()
        if samples.size == 0:
            return samples
        max_abs = float(np.max(np.abs(samples)))
        if max_abs > self.AUDIO_SCALE_THRESHOLD:
            samples = samples / self.AUDIO_SCALE_DIVISOR
        samples = np.clip(samples, -1.0, 1.0)
        if src_rate > 0 and src_rate != target_rate and len(samples) > 1:
            ratio = float(target_rate) / float(src_rate)
            out_len = max(1, int(len(samples) * ratio))
            x = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=out_len, endpoint=False)
            samples = np.interp(x_new, x, samples).astype(np.float32)
        return samples

    def _pull_samples_once(self, target_rate: int) -> Optional[np.ndarray]:
        samples = None
        src_rate = target_rate
        # Prefer dedicated remote buffer first to avoid multi-second drift from legacy queues.
        if audio_remote.is_active():
            samples = audio_remote.pop_rx_audio(self._listener_id, timeout_ms=10)
            src_rate = target_rate
            if samples is not None:
                self._last_remote_chunk_at = time.time()
                self._chunk_age = audio_remote.last_rx_age(self._listener_id)
            # Antes, si el buffer remoto estaba vacío pero había dado datos
            # hacía menos de 300 ms, se devolvía None sin más — ni siquiera se
            # probaba el buffer heredado — "para no alternar entre fuentes en
            # huecos breves". En la práctica eso convertía CUALQUIER hueco
            # momentáneo del buffer remoto en ~300 ms garantizados de
            # silencio (unos 15 frames de 20 ms, uno tras otro), en vez de
            # aprovechar el dato que sí pudiera tener el buffer heredado en
            # ese instante. Confirmado en real: RX a pulsos ("partes bien y
            # partes vacías") con "WebRTC RX RMS: 0.0000" repetido varias
            # veces seguidas nada más conectar. Un cambio de fuente ocasional
            # es mucho menos audible que un hueco de silencio garantizado.
        if samples is None:
            try:
                if hasattr(audio, "pop_rx_raw_chunk"):
                    samples = audio.pop_rx_raw_chunk()
                    if samples is not None and hasattr(audio, "get_rx_sample_rate"):
                        src_rate = int(audio.get_rx_sample_rate() or target_rate)
            except Exception:
                samples = None
                src_rate = target_rate
        if samples is None:
            return None
        self._last_data_time = time.time()
        return self._normalize_samples(samples, src_rate, target_rate)

    async def recv(self):
        if av is None or np is None:
            await asyncio.sleep(0.02)
            raise asyncio.CancelledError()
        target_rate = self.sample_rate
        if self._buffer is None:
            self._buffer = np.zeros(0, dtype=np.float32)
        while self._buffer.size < self.samples_per_frame:
            samples = self._pull_samples_once(target_rate)
            if samples is not None and samples.size:
                self._buffer = np.concatenate([self._buffer, samples])
                if self._buffer.size >= self.samples_per_frame:
                    break
            waited = 0.0
            while samples is None and waited < self._max_wait_for_chunk:
                await asyncio.sleep(self._poll_slice)
                waited += self._poll_slice
                samples = self._pull_samples_once(target_rate)
                if samples is not None and samples.size:
                    self._buffer = np.concatenate([self._buffer, samples])
                    break
            if samples is None:
                break
        self._diag_frames += 1
        if audio_remote.is_active() and audio_remote.get_ptt_state():
            chunk = np.zeros(self.samples_per_frame, dtype=np.float32)
            # Declick: la primera vez que entra PTT, atenúa en rampa desde
            # la última muestra real en vez de saltar a 0 de golpe.
            fade_len = min(self._FADE_SAMPLES, self.samples_per_frame)
            if not self._prev_frame_was_silence and fade_len > 0:
                chunk[:fade_len] = np.linspace(
                    self._last_sample, 0.0, fade_len, endpoint=False, dtype=np.float32
                )
            self._buffer = None
            self._prev_frame_was_silence = True
            # Salir de PTT es un "arranque en frío" a propósito:
            # audio_remote.set_ptt(False) vacía la cola de este oyente, así
            # que justo después hay que rellenarla desde cero otra vez. Sin
            # esta marca, en cuanto llegara el primer chunk real se serviría
            # ya mismo — y si el segundo chunk todavía no está listo (muy
            # probable, la captura acaba de arrancar a rellenar), el
            # siguiente frame volvía a underrun, luego otro real, luego
            # underrun... Cada transición individual ya lleva su rampa (no
            # es un clic seco), pero varias seguidas en un segundo suenan a
            # "pa, pa, pa" (como un motor renqueando) en vez de un solo
            # corte limpio. Confirmar unos pocos frames reales seguidos
            # antes de fiarse evita esa alternancia.
            self._ptt_recovering = True
            self._ptt_recovery_hits = 0
            self._silence_was_ptt = True
        elif (
            self._ptt_recovering
            and self._buffer is not None
            and self._buffer.size >= self.samples_per_frame
        ):
            # Hay datos reales listos, pero todavía no se han confirmado
            # suficientes seguidos tras salir de PTT (ver el comentario de
            # arriba) — se consumen (no se acumulan de más) pero se sigue
            # sirviendo el mismo silencio de antes, sin una rampa nueva:
            # _prev_frame_was_silence no cambia, así que cuando por fin se
            # sirva audio real de verdad solo habrá una transición, limpia.
            self._ptt_recovery_hits += 1
            self._buffer = self._buffer[self.samples_per_frame :]
            chunk = np.zeros(self.samples_per_frame, dtype=np.float32)
            if self._ptt_recovery_hits >= self._PTT_RECOVERY_TARGET:
                self._ptt_recovering = False
        elif self._buffer is None or self._buffer.size < self.samples_per_frame:
            self._underrun_count += 1
            self._diag_underruns += 1
            if self._ptt_recovering:
                # Racha rota: hay que volver a confirmar desde cero antes de
                # servir audio real, en vez de arrastrar una cuenta que ya
                # no refleja un flujo estable.
                self._ptt_recovery_hits = 0
            else:
                self._silence_was_ptt = False
            chunk = self._buffer if self._buffer is not None else np.zeros(0, dtype=np.float32)
            have = chunk.size
            if have < self.samples_per_frame:
                pad = np.zeros(self.samples_per_frame - have, dtype=np.float32)
                # Declick: si el hueco empieza en seco (sin ni un resto real
                # en `chunk`), atenúa en rampa desde la última muestra
                # servida en vez de rellenar directamente con ceros — un
                # salto brusco a silencio es justo lo que se oye como
                # "petardeo", más allá de que el hueco en sí sea audible.
                if have == 0:
                    fade_len = min(self._FADE_SAMPLES, pad.size)
                    if fade_len > 0 and not self._prev_frame_was_silence:
                        pad[:fade_len] = np.linspace(
                            self._last_sample, 0.0, fade_len, endpoint=False, dtype=np.float32
                        )
                chunk = np.concatenate([chunk, pad])
            chunk = chunk[: self.samples_per_frame]
            self._buffer = np.zeros(0, dtype=np.float32)
            self._prev_frame_was_silence = True
            now = time.time()
            if now - self._empty_warn_at > 10.0:
                self._empty_warn_at = now
                if self._last_audio_time and self._underrun_count > 2:
                    print(f"WARN: WebRTC RX audio buffer underruns: {self._underrun_count}")
                    self._underrun_count = 0
        else:
            chunk = self._buffer[: self.samples_per_frame].copy()
            self._buffer = self._buffer[self.samples_per_frame :]
            # Declick: si el frame anterior era silencio (underrun o PTT),
            # sube en rampa desde 0 en vez de arrancar de golpe a plena
            # amplitud — el mismo escalón que al entrar en silencio, pero
            # al revés.
            if self._prev_frame_was_silence:
                fade_len = min(self._FADE_SAMPLES, chunk.size)
                if fade_len > 0:
                    chunk[:fade_len] *= np.linspace(
                        0.0, 1.0, fade_len, endpoint=False, dtype=np.float32
                    )
            self._prev_frame_was_silence = False
            self._silence_was_ptt = False
            self._ptt_recovering = False
            self._ptt_recovery_hits = 0
            self._last_audio_time = time.time()
            self._align_clock()
            if self._underrun_count > 0:
                self._underrun_count = 0
        self._last_sample = float(chunk[-1]) if chunk.size else self._last_sample
        out = (np.clip(chunk, -1.0, 1.0) * 32767.0).astype(np.int16)
        diag_now = time.time()
        if diag_now - self._diag_log_at > 2.0:
            self._diag_log_at = diag_now
            if self._diag_frames > 0:
                _append_web_request_log(
                    f"ts={int(diag_now)} media=webrtc_rx_diag "
                    f"frames={self._diag_frames} underruns={self._diag_underruns} "
                    f"rms={self._last_rms:.4f}"
                )
            self._diag_frames = 0
            self._diag_underruns = 0
        frame = av.AudioFrame(format="s16", layout="mono", samples=self.samples_per_frame)
        frame.planes[0].update(out.tobytes())
        frame.sample_rate = self.sample_rate
        frame.pts = self._pts
        frame.time_base = Fraction(1, self.sample_rate)
        self._pts += self.samples_per_frame
        try:
            rms = float(np.sqrt(np.mean((out.astype(np.float32) / 32768.0) ** 2)))
            self._last_rms = rms
            now = time.time()
            if now - self._last_rms_log > 5.0:
                self._last_rms_log = now
                print(f"WebRTC RX RMS: {rms:.4f}")
        except Exception:
            pass
        # Check for timeout - if no data received for too long, raise error
        if time.time() - self._last_data_time > self._timeout_threshold:
            print(f"WARNING: RxAudioTrack timeout - no data for {self._timeout_threshold}s")
            # Reset timer to avoid spam
            self._last_data_time = time.time()

        # El comentario que había aquí ("aiortc pacing already controls
        # outbound RTP timing") era falso: aiortc llama a recv() otra vez en
        # cuanto esta corrutina devuelve, sin esperar a que transcurran los
        # 20 ms que el pts del frame dice que representa — no hay ningún
        # pacing de tiempo real por su parte para un track "pull" como este.
        # Confirmado con el diagnóstico `webrtc_rx_diag` en real: recv() se
        # invocaba ~140-178 veces cada 2 s (debería ser ~100, un frame de
        # 20 ms), es decir, a ritmo real de ~11-14 ms/frame en vez de 20 —
        # casi el doble de rápido de lo que representa el audio que se envía.
        # Esto vaciaba el buffer compartido de audio_remote/legacy más rápido
        # de lo que la captura real podía rellenarlo, y eso — no la ganancia
        # ni la tasa de muestreo — era la causa de los huecos/"relentizado":
        # cada recv() cuenta como 20 ms de audio en el pts que lleva el
        # paquete RTP, así que producir frames más rápido que cada 20 ms de
        # reloj real equivale a intentar transmitir el audio a una velocidad
        # de reproducción mayor que 1x, sin que exista tanto audio real que
        # transmitir a ese ritmo. Todos los ejemplos de aiortc con una fuente
        # de audio sintética (no un `MediaPlayer` con su propio hilo de
        # decodificación) se autopacean así, así que este track pull-based
        # necesitaba hacer lo mismo.
        if self._clock_start is None:
            self._clock_start = time.time() - (self._pts - self.samples_per_frame) / self.sample_rate
        target = self._clock_start + self._pts / self.sample_rate
        wait = target - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        return frame

    # Margen que se deja entre la llegada de un bloque y su recogida.
    _ALIGN_MARGIN_S = 0.002
    _ALIGN_WINDOW = 50  # ~1 s de frames

    def _align_clock(self) -> None:
        """Pone la recogida justo detrás de la captura.

        El reloj propio de recv() arranca con una fase cualquiera respecto a
        la captura, y cada bloque esperaba en la cola hasta ~20 ms a que
        recv() pasara a por él (medido: ~26 ms de media con
        scripts/bench_remoto.py). Si en ``_ALIGN_WINDOW`` frames hasta el
        bloque más fresco ya llevaba esperando más del margen, el reloj se
        adelanta esa diferencia. Pasarse no corta nada: si el bloque aún no
        ha llegado, recv() lo espera como siempre.
        """
        age, self._chunk_age = self._chunk_age, None
        if age is None or self._clock_start is None:
            return
        self._age_min = min(self._age_min, age)
        self._age_frames += 1
        if self._age_frames >= self._ALIGN_WINDOW:
            if self._age_min > 2 * self._ALIGN_MARGIN_S:
                self._clock_start -= self._age_min - self._ALIGN_MARGIN_S
            self._age_min, self._age_frames = 1.0, 0



class RemotePttControl:
    """Única autoridad sobre el PTT que piden los clientes web (como en IRCB Pro).

    Cada pulsación de la web lleva un número creciente ``n``. Mientras el
    operador está en TX la página repite la orden como latido: cada 100 ms por
    el canal de datos WebRTC ``ptt`` (``P1:<n>``), o cada 250 ms por
    ``/api/ptt`` si el canal aún no está abierto. Si dejan de llegar latidos
    (red caída, pestaña cerrada, móvil bloqueado...) el PTT se suelta solo a los
    ``REMOTE_PTT_DEADMAN_MS``; además hay un tope de TX continua
    (``REMOTE_PTT_MAX_S``). Una pulsación soltada (a mano o a la fuerza) queda
    cerrada: un latido suyo que llegue tarde ya no vuelve a transmitir.

    Al soltar se mantiene una cola corta (``REMOTE_PTT_TAIL_MS``) para que salga
    por la radio el final de la voz que aún viene de camino.
    """

    WATCH_PERIOD_S = 0.05

    def __init__(self, controller: "WebServerController", config: Dict[str, Any]):
        self._ctl = controller
        cfg = config or {}
        self.tail_s = max(0, int(cfg.get("REMOTE_PTT_TAIL_MS", 150) or 0)) / 1000.0
        self.deadman_s = max(250, int(cfg.get("REMOTE_PTT_DEADMAN_MS", 700) or 700)) / 1000.0
        self.max_tx_s = max(10, int(cfg.get("REMOTE_PTT_MAX_S", 300) or 300))
        self.active = False
        self._client: Optional[str] = None  # sesión web que tiene el PTT
        self._press: Optional[int] = None   # número de su pulsación
        self._link: Optional[str] = None    # conexión WebRTC que lleva sus latidos
        self._ended: Dict[str, int] = {}    # por sesión: última pulsación cerrada
        self._last_beat = 0.0
        self._since = 0.0
        self._release_task: Optional[asyncio.Task] = None
        self._watcher: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def releasing(self) -> bool:
        return self._release_task is not None and not self._release_task.done()

    def _close_press(self) -> None:
        if self._client is not None and self._press is not None:
            self._ended[self._client] = max(self._press, self._ended.get(self._client, -1))

    async def request(self, on: bool, client: str, press: Optional[int] = None, link: Optional[str] = None) -> None:
        """Orden o latido de la sesión ``client`` para su pulsación ``press``."""
        if press is not None and press <= self._ended.get(client, -1):
            return  # pulsación ya cerrada (o una orden vieja que llega tarde)
        if not on:
            if press is not None:
                self._ended[client] = max(press, self._ended.get(client, -1))
            if self.active and not self.releasing():
                self._release_task = asyncio.ensure_future(self._release("soltado", tail=True))
            return
        if self.active and not self.releasing() and (client, press) != (self._client, self._press):
            # Otra pulsación mientras ya se transmite: la nueva toma el relevo.
            self._close_press()
        self._client, self._press = client, press
        if link is not None:
            self._link = link
        self._last_beat = time.monotonic()
        if self.releasing():
            # Se volvió a pulsar mientras salía la cola: se sigue transmitiendo.
            self._release_task.cancel()
            self._release_task = None
            return
        if not self.active:
            self.active = True
            self._since = time.monotonic()
            if self._watcher is None or self._watcher.done():
                self._watcher = asyncio.ensure_future(self.watch())
            await self._apply(True)
            _append_web_request_log(f"ts={int(time.time())} media=ptt state=on client={client} press={press}")

    def release_now(self, reason: str, link: Optional[str] = None) -> None:
        """Suelta sin cola (sin latido, tope, conexión perdida, servidor parándose).
        Con ``link`` solo suelta si los latidos venían por esa conexión WebRTC."""
        if not self.active or (link is not None and link != self._link):
            return
        if self.releasing():
            self._release_task.cancel()
        self._close_press()
        self._release_task = asyncio.ensure_future(self._release(reason, tail=False))

    async def _release(self, reason: str, tail: bool) -> None:
        if tail and self.tail_s:
            await asyncio.sleep(self.tail_s)  # aún llega el final de la voz
        self.active = False
        self._client = self._press = self._link = None
        await self._apply(False)
        _append_web_request_log(f"ts={int(time.time())} media=ptt state=off reason={reason.replace(' ', '_')}")

    async def _apply(self, state: bool) -> None:
        async with self._lock:
            ctl = self._ctl
            try:
                with ctl._remote_lock:
                    remote_clients = int(ctl._remote_clients or 0)
                if remote_clients > 0:
                    ctl._set_remote_mode(True)
            except Exception:
                pass
            try:
                if hasattr(audio, "clear_tx_inject_buffer"):
                    audio.clear_tx_inject_buffer()
            except Exception:
                pass
            # Mutear/desmutear el audio remoto es en memoria: se hace ya, antes de
            # la E/S de la radio, para que el cambio de sentido se oiga al instante.
            try:
                if audio_remote.is_active():
                    audio_remote.set_ptt(state)
            except Exception:
                pass
            # callbacks.set_ptt llega hasta la E/S serie (CAT), síncrona y
            # bloqueante: en un hilo, para no frenar el ritmo del audio WebRTC.
            await asyncio.to_thread(ctl.callbacks.set_ptt, state)

    async def watch(self) -> None:
        """Vigila los latidos mientras dura la transmisión."""
        while self.active:
            await asyncio.sleep(self.WATCH_PERIOD_S)
            if not self.active or self.releasing():
                continue
            now = time.monotonic()
            silent = now - self._last_beat
            if silent > self.deadman_s:
                print(f"PTT remoto: soltado, la web dejó de confirmar el TX ({silent * 1000:.0f} ms)")
                self.release_now("sin latido")
            elif now - self._since > self.max_tx_s:
                print(f"PTT remoto: soltado, superado el tiempo máximo de TX ({self.max_tx_s} s)")
                self.release_now("tiempo maximo")

    def attach_channel(self, channel, client: str, link: str) -> None:
        """Canal de datos ``ptt``: 'P1:<n>' TX (y latido), 'P0:<n>' RX, 'T...' eco."""

        @channel.on("message")
        def on_message(message):
            if not isinstance(message, str) or not message:
                return
            if message[0] == "P":
                try:
                    value, press = message[1:].split(":", 1)
                    press = int(press)
                except ValueError:
                    return
                asyncio.ensure_future(self.request(value == "1", client, press, link))
            elif message[0] == "T":
                try:
                    channel.send(message)  # eco: la web mide la ida y vuelta
                except Exception:
                    pass

        @channel.on("close")
        def on_close():
            self.release_now("canal de PTT cerrado", link=link)

    def web_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Estado para la web: durante la cola de cierre ya se muestra RX."""
        if self.releasing() and state.get("ptt"):
            state = dict(state)
            state["ptt"] = False
        return state


def _client_key(token: str) -> str:
    """Identifica la sesión web (la misma por HTTP y por WebRTC) sin guardar el token."""
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()[:12]


class WebServerController:
    def __init__(self, callbacks: WebCallbacks):
        self.callbacks = callbacks
        self._server = None
        self._thread = None
        self._loop = None
        self._stop_event = threading.Event()
        self._config = {}
        self._pcs = set()
        self._remote_clients = 0
        self._remote_lock = threading.Lock()
        # Rate limiting for login attempts
        self._login_attempts = {}  # {ip: [(timestamp, success), ...]}
        self._login_lock = threading.Lock()
        self._max_failed_attempts = 5
        self._lockout_duration = 300  # 5 minutes in seconds
        self._ptt_ctl: Optional[RemotePttControl] = None

    async def _close_all_pcs_async(self, timeout_s: float = 0.6) -> None:
        pcs = list(self._pcs)
        if not pcs:
            return
        for pc in pcs:
            try:
                for sender in pc.getSenders():
                    track = getattr(sender, "track", None)
                    if track:
                        try:
                            track.stop()
                        except Exception:
                            pass
                for receiver in pc.getReceivers():
                    track = getattr(receiver, "track", None)
                    if track:
                        try:
                            track.stop()
                        except Exception:
                            pass
            except Exception:
                pass
        for pc in pcs:
            try:
                await asyncio.wait_for(pc.close(), timeout=max(0.1, float(timeout_s)))
            except Exception:
                pass
            finally:
                self._pcs.discard(pc)

    def start(self, config: Dict[str, Any]):
        if self._thread and self._thread.is_alive():
            return
        # Clean stale remote-audio state before each fresh server start.
        with self._remote_lock:
            self._remote_clients = 0
        try:
            audio_remote.stop_remote_audio()
        except Exception:
            pass
        self._set_remote_mode(False)
        self._config = dict(config or {})
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._server:
            try:
                self._server.should_exit = True
                self._server.force_exit = True
            except Exception:
                pass
        # Close all active peer connections with bounded timeouts.
        try:
            loop = self._loop
            if loop and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    self._close_all_pcs_async(timeout_s=0.4), loop
                )
                try:
                    fut.result(timeout=1.2)
                except Exception:
                    pass
            else:
                tmp_loop = asyncio.new_event_loop()
                try:
                    tmp_loop.run_until_complete(self._close_all_pcs_async(timeout_s=0.3))
                finally:
                    tmp_loop.close()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.5)
            if self._thread.is_alive() and self._server:
                try:
                    self._server.force_exit = True
                except Exception:
                    pass
                self._thread.join(timeout=1.5)
        if self._thread and self._thread.is_alive():
            print("WARN: parada del servidor web incompleta; continuando sin bloquear UI.")
        self._server = None
        self._loop = None
        self._thread = None
        try:
            self.callbacks.set_ptt(False)
        except Exception:
            pass
        with self._remote_lock:
            self._remote_clients = 0
        try:
            audio_remote.stop_remote_audio()
        except Exception:
            pass
        self._set_remote_mode(False)

    def _set_remote_mode(self, enabled: bool) -> None:
        try:
            if hasattr(audio, "set_remote_mode"):
                audio.set_remote_mode(bool(enabled))
        except Exception:
            pass
        if enabled:
            try:
                audio.habilitar_audio_para_radio(True)
            except Exception:
                pass

    def _remote_client_inc(self) -> None:
        with self._remote_lock:
            self._remote_clients += 1
            if self._remote_clients == 1:
                # Start dedicated remote audio module for low-latency WebRTC
                if not audio_remote.start_remote_audio():
                    print("ERROR: Failed to start remote audio")
                self._set_remote_mode(True)
                try:
                    audio.habilitar_audio_para_radio(True)
                except Exception:
                    pass

    def _remote_client_dec(self) -> int:
        with self._remote_lock:
            if self._remote_clients > 0:
                self._remote_clients -= 1
            if self._remote_clients == 0:
                # Stop dedicated remote audio module
                audio_remote.stop_remote_audio()
                self._set_remote_mode(False)
            return self._remote_clients

    def _run_server(self):
        import uvicorn

        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        except Exception:
            self._loop = None

        app = self._create_app()
        allow_wan = bool(self._config.get("WEB_SERVER_ALLOW_WAN", False))
        auto_https = bool(self._config.get("WEB_SERVER_AUTO_HTTPS", True))
        configured_host = str(self._config.get("WEB_SERVER_HOST", "127.0.0.1") or "127.0.0.1")
        host = _normalize_web_bind_host(configured_host, allow_wan)
        vpn_enabled = bool(self._config.get("WEB_VPN_ENABLED", False))
        if vpn_enabled:
            # Con la VPN solo se llega por el túnel (el ayudante reenvía a
            # 127.0.0.1), salvo que se permita también la red local.
            allow_wan = False
            host = "0.0.0.0" if bool(self._config.get("WEB_VPN_ALLOW_LAN", False)) else "127.0.0.1"
        port = int(self._config.get("WEB_SERVER_PORT", 8080) or 8080)
        if not _can_bind(host, port):
            if allow_wan and host != "0.0.0.0" and _can_bind("0.0.0.0", port):
                print(
                    f"WARN: No se pudo bindear {host}:{port}. Usando 0.0.0.0:{port}."
                )
                host = "0.0.0.0"
            else:
                print(
                    f"ERROR: No se pudo bindear {host}:{port}. "
                    "Revisa WEB_SERVER_HOST/PORT y puertos en uso."
                )
                return
        cert = str(self._config.get("WEB_SERVER_SSL_CERT", "") or "")
        key = str(self._config.get("WEB_SERVER_SSL_KEY", "") or "")
        external_bind = bool(allow_wan or host == "0.0.0.0")
        if vpn_enabled and (not cert or not key):
            # El micrófono del móvil exige HTTPS: con la VPN siempre, con un
            # certificado propio que incluye la IP del túnel.
            ssl_dir = os.path.join(_runtime_data_dir(), "ssl")
            os.makedirs(ssl_dir, exist_ok=True)
            cert = os.path.join(ssl_dir, "poorsdr_vpn_cert.pem")
            key = os.path.join(ssl_dir, "poorsdr_vpn_key.pem")
            hosts = [_TUNNEL_IP] + _collect_access_hosts(host, configured_host, external_bind)
            if not _ensure_self_signed_cert(cert, key, hosts):
                cert = key = ""
                print("WARN: HTTPS no configurado. El micr\u00f3fono en m\u00f3vil requiere HTTPS.")
        elif external_bind and auto_https and (not cert or not key):
            ssl_dir = os.path.join(_runtime_data_dir(), "ssl")
            os.makedirs(ssl_dir, exist_ok=True)
            cert = os.path.join(ssl_dir, "poorsdr_cert.pem")
            key = os.path.join(ssl_dir, "poorsdr_key.pem")
            created = _ensure_self_signed_cert(
                cert,
                key,
                _collect_access_hosts(host, configured_host, True),
            )
            if not created:
                print("WARN: HTTPS no configurado. El micr\u00f3fono en m\u00f3vil requiere HTTPS.")
        elif external_bind and not auto_https and (not cert or not key):
            print("INFO: HTTPS automático desactivado. Sirviendo por HTTP en LAN.")
        access_urls = _format_access_urls(
            ([_TUNNEL_IP] if vpn_enabled else []) + _collect_access_hosts(host, configured_host, external_bind),
            port,
            secure=bool(cert and key),
        )
        print(f"Servidor web remoto escuchando en {host}:{port}")
        if access_urls:
            print("Acceso remoto disponible en:")
            for url in access_urls:
                print(f"  {url}")
        try:
            access_log = runtime_path("web_server_access.log")
            lines = [
                f"host={host}",
                f"port={port}",
                f"secure={int(bool(cert and key))}",
            ]
            lines.extend([f"url={u}" for u in access_urls])
            with open(access_log, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except Exception:
            pass
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            # La app no tiene eventos de arranque/parada; con lifespan activo,
            # stop() (force_exit) dejaba una traza de CancelledError al cerrar.
            lifespan="off",
            ssl_certfile=cert or None,
            ssl_keyfile=key or None,
        )
        self._server = uvicorn.Server(config)
        try:
            if self._loop and self._loop.is_running() is False:
                self._loop.run_until_complete(self._server.serve())
            else:
                self._server.run()
        finally:
            self._server = None
            try:
                if self._loop and self._loop.is_running():
                    self._loop.stop()
            except Exception:
                pass
            try:
                if self._loop:
                    self._loop.close()
            except Exception:
                pass
            self._loop = None

    def _auth_config(self):
        user = str(self._config.get("WEB_SERVER_USER", "admin") or "admin")
        salt = str(self._config.get("WEB_SERVER_PASSWORD_SALT", "") or "")
        passwd_hash = str(self._config.get("WEB_SERVER_PASSWORD_HASH", "") or "")
        secret = str(self._config.get("WEB_SERVER_SECRET", "") or "")
        totp_secret = str(self._config.get("WEB_SERVER_TOTP_SECRET", "") or "")
        allow_legacy = False
        return user, salt, passwd_hash, secret, totp_secret, allow_legacy

    def _check_auth(self, token: str) -> bool:
        _user, _salt, _hash, secret, _totp, _legacy = self._auth_config()
        payload = verify_token(secret, token)
        return bool(payload)

    def _is_ip_locked(self, ip: str) -> bool:
        """Check if IP is locked out due to failed attempts"""
        with self._login_lock:
            if ip not in self._login_attempts:
                return False
            now = time.time()
            # Clean old attempts (older than lockout duration)
            self._login_attempts[ip] = [
                (ts, success) for ts, success in self._login_attempts[ip]
                if now - ts < self._lockout_duration
            ]
            # Count recent failed attempts
            failed = [ts for ts, success in self._login_attempts[ip] if not success]
            return len(failed) >= self._max_failed_attempts

    def _record_login_attempt(self, ip: str, success: bool) -> None:
        """Record a login attempt"""
        with self._login_lock:
            if ip not in self._login_attempts:
                self._login_attempts[ip] = []
            now = time.time()
            self._login_attempts[ip].append((now, success))
            # Keep only recent attempts
            self._login_attempts[ip] = [
                (ts, s) for ts, s in self._login_attempts[ip]
                if now - ts < self._lockout_duration
            ]
            # If success, clear all failed attempts
            if success:
                self._login_attempts[ip] = [(now, True)]

    def _create_app(self) -> FastAPI:
        ptt_ctl = RemotePttControl(self, self._config)
        self._ptt_ctl = ptt_ctl
        app = FastAPI()
        webui_path = os.path.join(os.path.dirname(__file__), "webui")
        app.mount("/static", StaticFiles(directory=webui_path), name="static")

        @app.middleware("http")
        async def _request_trace(request: Request, call_next):
            started = time.time()
            client_ip = request.client.host if request.client else "unknown"
            method = str(request.method or "")
            path = str(request.url.path or "")
            host = str(request.headers.get("host", "") or "")
            ua = str(request.headers.get("user-agent", "") or "")
            try:
                response = await call_next(request)
                status = int(getattr(response, "status_code", 0) or 0)
            except Exception:
                elapsed_ms = int((time.time() - started) * 1000)
                _append_web_request_log(
                    f"ts={int(started)} ip={client_ip} host={host} method={method} path={path} status=500 ms={elapsed_ms} ua={ua}"
                )
                raise
            elapsed_ms = int((time.time() - started) * 1000)
            _append_web_request_log(
                f"ts={int(started)} ip={client_ip} host={host} method={method} path={path} status={status} ms={elapsed_ms} ua={ua}"
            )
            return response

        def _get_token_from_request(request: Request) -> str:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                return auth.split(" ", 1)[1].strip()
            return str(request.cookies.get("poorsdr_token", "") or "").strip()

        def _get_token_from_ws(ws: WebSocket) -> str:
            cookie_token = str(ws.cookies.get("poorsdr_token", "") or "").strip()
            if cookie_token:
                return cookie_token
            # Compatibilidad con clientes antiguos.
            query_token = str(ws.query_params.get("token", "") or "").strip()
            if query_token:
                print("WARN: token de WS via query string (legacy).")
            return query_token

        @app.get("/")
        async def index():
            return FileResponse(os.path.join(webui_path, "index.html"))

        @app.post("/api/auth/login")
        async def login(request: Request, payload: Dict[str, Any] = Body(...)):
            # Get client IP
            client_ip = request.client.host if request.client else "unknown"

            # Check if IP is locked out
            if self._is_ip_locked(client_ip):
                print(f"LOGIN BLOCKED: IP {client_ip} locked due to too many failed attempts")
                raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

            username = str(payload.get("username", "") or "")
            password = str(payload.get("password", "") or "")
            otp = str(payload.get("otp", "") or "")
            user, salt, passwd_hash, secret, totp_secret, _allow_legacy = self._auth_config()

            # Validate credentials
            try:
                if username != user:
                    self._record_login_attempt(client_ip, False)
                    raise HTTPException(status_code=401, detail="Invalid credentials")
                if not salt or not passwd_hash or not secret:
                    self._record_login_attempt(client_ip, False)
                    raise HTTPException(status_code=503, detail="Web authentication is not configured")
                if not hmac.compare_digest(hash_password(password, salt), passwd_hash):
                    self._record_login_attempt(client_ip, False)
                    raise HTTPException(status_code=401, detail="Invalid credentials")
                if totp_secret:
                    if pyotp is None:
                        self._record_login_attempt(client_ip, False)
                        raise HTTPException(status_code=503, detail="2FA configured but pyotp not available")
                    else:
                        totp = pyotp.TOTP(totp_secret)
                        if not totp.verify(otp or ""):
                            self._record_login_attempt(client_ip, False)
                            raise HTTPException(status_code=401, detail="Invalid OTP")

                # Success - record and return token
                self._record_login_attempt(client_ip, True)
                token = make_token(secret, {"sub": username}, ttl_sec=3600)
                print(f"LOGIN SUCCESS: {username} from {client_ip}")
                response = JSONResponse({"token": token})
                is_https = str(getattr(request.url, "scheme", "") or "").lower() == "https"
                response.set_cookie(
                    key="poorsdr_token",
                    value=token,
                    max_age=3600,
                    httponly=True,
                    secure=is_https,
                    samesite="lax",
                    path="/",
                )
                return response
            except HTTPException:
                # Re-raise HTTP exceptions
                raise

        def _require_auth(request: Request):
            token = _get_token_from_request(request)
            if not token:
                raise HTTPException(status_code=401, detail="Unauthorized")
            if not self._check_auth(token):
                raise HTTPException(status_code=401, detail="Unauthorized")

        @app.get("/api/status")
        async def status(request: Request):
            _require_auth(request)
            return ptt_ctl.web_state(self.callbacks.get_state())

        @app.post("/api/tune")
        async def tune(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            freq = int(payload.get("frequency", 0))
            if freq > 0:
                self.callbacks.set_frequency(freq)
            return {"ok": True}

        @app.post("/api/mode")
        async def mode(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            mode = str(payload.get("mode", "") or "").upper()
            if mode:
                self.callbacks.set_mode(mode)
            return {"ok": True}

        @app.post("/api/band")
        async def band(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            band_name = str(payload.get("band", "") or "").strip()
            if band_name:
                self.callbacks.set_band(band_name)
            return {"ok": True}

        @app.post("/api/step")
        async def step(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            try:
                step_khz = float(payload.get("step_khz", 0))
            except Exception:
                step_khz = 0.0
            if step_khz > 0:
                self.callbacks.set_step(step_khz)
            return {"ok": True}

        @app.post("/api/ptt")
        async def ptt(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            state = bool(payload.get("state", False))
            try:
                press = int(payload["press"]) if "press" in payload else None
            except (TypeError, ValueError):
                press = None
            # Orden y latido a la vez: mientras la web siga en TX repite
            # {"state": true, "press": n} cada 250 ms (o usa el canal 'ptt').
            await ptt_ctl.request(state, _client_key(_get_token_from_request(request)), press)
            return {"ok": True, "applied": True, "ptt": bool(ptt_ctl.active and not ptt_ctl.releasing()),
                    "deadman_ms": int(ptt_ctl.deadman_s * 1000)}

        @app.post("/api/volume")
        async def volume(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            rx = float(payload.get("rx", 0.6))
            tx = float(payload.get("tx", 1.0))
            self.callbacks.set_volumes(rx, tx)
            return {"ok": True}

        @app.post("/api/audio")
        async def audio_toggle(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            enabled = bool(payload.get("enabled", False))
            if self._remote_clients > 0 and not enabled:
                return {"ok": True}
            self.callbacks.toggle_audio(enabled)
            return {"ok": True}

        @app.post("/api/anr")
        async def anr_toggle(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            has_enabled = "enabled" in payload
            has_intensity = "intensity" in payload
            if has_enabled:
                self.callbacks.set_anr(bool(payload.get("enabled", False)))
            if has_intensity:
                try:
                    intensity = int(payload.get("intensity", 1))
                except Exception:
                    intensity = 1
                intensity = max(1, min(10, intensity))
                self.callbacks.set_anr_intensity(intensity)
            return {"ok": True}

        @app.websocket("/api/ws")
        async def ws_endpoint(ws: WebSocket):
            token = _get_token_from_ws(ws)
            if not self._check_auth(token):
                await ws.close(code=4401)
                return
            await ws.accept()
            last_state = None
            last_ping = time.time()
            ping_interval = 8.0  # keepalive
            state_interval = 0.03  # faster UI reaction for web controls
            periodic_state_push = 0.10
            timeout = 30.0  # Close connection if no pong for 30 seconds
            last_state_sent_at = 0.0

            try:
                while True:
                    now = time.time()
                    # Send ping if needed
                    if now - last_ping > ping_interval:
                        try:
                            await asyncio.wait_for(ws.send_json({"type": "ping"}), timeout=2.0)
                            last_ping = now
                        except asyncio.TimeoutError:
                            print("WebSocket ping timeout, closing connection")
                            break

                    # Get current state
                    current_state = ptt_ctl.web_state(self.callbacks.get_state())

                    # Only send if state changed or it's time for periodic update
                    if current_state != last_state or (now - last_state_sent_at) > periodic_state_push:
                        await ws.send_json({"type": "state", "data": current_state})
                        last_state = current_state
                        last_state_sent_at = now

                    await asyncio.sleep(state_interval)
            except WebSocketDisconnect:
                return
            except Exception as e:
                print(f"WebSocket error: {e}")
                try:
                    await ws.close()
                except Exception:
                    pass

        @app.post("/api/webrtc/offer")
        async def webrtc_offer(request: Request, payload: Dict[str, Any] = Body(...)):
            _require_auth(request)
            if RTCPeerConnection is None:
                raise HTTPException(status_code=500, detail="WebRTC not available")
            t0 = time.time()
            via_tunnel = _request_via_tunnel(request)
            _TUNNEL_MODE.set(via_tunnel)
            offer = RTCSessionDescription(sdp=payload["sdp"], type=payload["type"])
            if RTCConfiguration is not None:
                # Force host-only ICE gathering for LAN to avoid multi-second STUN delays.
                pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            else:
                pc = RTCPeerConnection()
            self._pcs.add(pc)
            self._remote_client_inc()
            try:
                self.callbacks.toggle_audio(True)
            except Exception:
                pass

            # Asignado más abajo, justo antes de pc.addTrack(...). on_state_change
            # es un closure y solo lo lee (no lo reasigna), así que ve el valor
            # real de todos modos cuando de verdad se ejecuta (siempre después).
            rx_audio_track = None

            pc_link = f"rtc:{id(pc):x}"
            pc_client = _client_key(_get_token_from_request(request))

            @pc.on("datachannel")
            def on_datachannel(channel):
                if getattr(channel, "label", "") == "ptt":
                    ptt_ctl.attach_channel(channel, pc_client, pc_link)

            @pc.on("connectionstatechange")
            async def on_state_change():
                if pc.connectionState in ("failed", "closed", "disconnected"):
                    # Sin conexión no hay voz ni latido de quien tenía el PTT.
                    ptt_ctl.release_now(f"conexion {pc.connectionState}", link=pc_link)
                    # Cancel all background tasks (audio RX + stats logging).
                    for task in rx_tasks:
                        if not task.done():
                            task.cancel()
                    rx_tasks.clear()
                    # Dar de baja la cola RX de este oyente — si no, se queda
                    # huérfana en audio_remote._listeners para siempre (ver
                    # el comentario junto a self._listener_id en RxAudioTrack).
                    if rx_audio_track is not None:
                        try:
                            audio_remote.unregister_listener(rx_audio_track._listener_id)
                        except Exception:
                            pass
                    try:
                        await pc.close()
                    except Exception:
                        pass
                    self._pcs.discard(pc)
                    remaining = self._remote_client_dec()
                    if remaining == 0:
                        try:
                            self.callbacks.toggle_audio(False)
                        except Exception:
                            pass

            # Store tasks for cleanup
            rx_tasks = []

            @pc.on("track")
            async def on_track(track):
                if track.kind == "audio":
                    last_tx_log = {"ts": 0.0}

                    def _frame_to_mono_float32(frame) -> Optional["np.ndarray"]:
                        if np is None:
                            return None
                        try:
                            raw = frame.to_ndarray()
                        except Exception:
                            return None
                        if raw is None:
                            return None
                        try:
                            samples = np.asarray(raw)
                        except Exception:
                            return None
                        if samples.size == 0:
                            return None
                        try:
                            ch_count = int(len(getattr(getattr(frame, "layout", None), "channels", []) or []))
                        except Exception:
                            ch_count = 1
                        if ch_count <= 0:
                            ch_count = 1
                        # Handle common AV layouts:
                        # - planar: (channels, frames)
                        # - packed: (frames, channels) or (1, interleaved)
                        # - flattened/interleaved: (frames * channels,)
                        try:
                            if samples.ndim == 2:
                                if samples.shape[0] == ch_count and ch_count > 1:
                                    samples = samples.mean(axis=0)
                                elif samples.shape[1] == ch_count and ch_count > 1:
                                    samples = samples.mean(axis=1)
                                elif samples.shape[0] == 1 and ch_count > 1:
                                    flat = samples.reshape(-1)
                                    usable = (flat.size // ch_count) * ch_count
                                    if usable > 0:
                                        samples = flat[:usable].reshape(-1, ch_count).mean(axis=1)
                                    else:
                                        samples = flat
                                else:
                                    samples = samples.reshape(-1)
                            elif samples.ndim == 1 and ch_count > 1:
                                usable = (samples.size // ch_count) * ch_count
                                if usable > 0:
                                    samples = samples[:usable].reshape(-1, ch_count).mean(axis=1)
                            else:
                                samples = samples.reshape(-1)
                        except Exception:
                            samples = np.asarray(raw).reshape(-1)
                        if samples.dtype.kind in ("f",):
                            mono = samples.astype("float32")
                        else:
                            mono = samples.astype("float32") / RxAudioTrack.AUDIO_SCALE_DIVISOR
                        try:
                            max_abs = float(np.max(np.abs(mono))) if mono.size else 0.0
                            if max_abs > RxAudioTrack.AUDIO_MAX_ABS_THRESHOLD:
                                mono = mono / RxAudioTrack.AUDIO_SCALE_DIVISOR
                        except Exception:
                            pass
                        return np.clip(mono, -1.0, 1.0)

                    async def _rx():
                        try:
                            while True:
                                frame = await track.recv()
                                samples = _frame_to_mono_float32(frame)
                                if samples is not None:
                                    try:
                                        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
                                        now = time.time()
                                        if now - last_tx_log["ts"] > 5.0:
                                            last_tx_log["ts"] = now
                                            print(f"WebRTC TX RMS: {rms:.4f}")
                                            try:
                                                sr_dbg = int(getattr(frame, "sample_rate", 0) or 0)
                                                try:
                                                    ch_dbg = int(len(getattr(getattr(frame, "layout", None), "channels", []) or []))
                                                except Exception:
                                                    ch_dbg = 0
                                                _append_web_request_log(
                                                    f"ts={int(now)} media=webrtc_tx_rms value={rms:.6f} samples={int(samples.size)} sr={sr_dbg} ch={ch_dbg}"
                                                )
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                    # Inject directly into main TX buffer (single path).
                                    try:
                                        if hasattr(audio, "inject_tx_audio"):
                                            # Use frame rate from decoder when available.
                                            # Some mobile/browser paths negotiate non-48k rates.
                                            sample_rate = int(getattr(frame, "sample_rate", 48000) or 48000)
                                            audio.inject_tx_audio(samples, sample_rate)
                                    except Exception:
                                        pass
                        except Exception as e:
                            print(f"WebRTC RX track error: {e}")
                            return
                    # Store task for proper cleanup
                    task = asyncio.create_task(_rx())
                    rx_tasks.append(task)

            rx_audio_track = RxAudioTrack()
            pc.addTrack(rx_audio_track)

            t_set_remote_0 = time.time()
            await pc.setRemoteDescription(offer)
            t_set_remote_1 = time.time()
            answer = await pc.createAnswer()
            t_create_answer_1 = time.time()
            await pc.setLocalDescription(answer)
            t_set_local_1 = time.time()
            # Do not wait for full ICE gathering; keep offer/answer path immediate.
            try:
                print(
                    "WebRTC offer timing ms "
                    f"setRemote={int((t_set_remote_1 - t_set_remote_0)*1000)} "
                    f"createAnswer={int((t_create_answer_1 - t_set_remote_1)*1000)} "
                    f"setLocal={int((t_set_local_1 - t_create_answer_1)*1000)} "
                    f"total={int((t_set_local_1 - t0)*1000)}"
                )
            except Exception:
                pass
            answer_sdp = pc.localDescription.sdp
            if via_tunnel:
                answer_sdp = answer_sdp.replace("127.0.0.1", _TUNNEL_IP)
            return JSONResponse({"sdp": answer_sdp, "type": pc.localDescription.type})

        return app
