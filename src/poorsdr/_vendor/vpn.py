"""Acceso remoto seguro desde internet mediante un servidor WireGuard integrado.

El túnel lo levanta ``poorsdrvpn`` (wireguard-go en modo "netstack", fuente en
``scripts/vpn/poorsdrvpn``): no necesita driver TUN ni permisos de
administrador. Escucha en la IP del túnel (``SERVER_IP``) y reenvía al
servidor web local, que con la VPN activa solo escucha en 127.0.0.1; el audio
WebRTC también va por dentro (puertos UDP ``AUDIO_PORTS``, ver
``webserver._TunnelIceConnection``).

Reparto de datos:
  * ``vpn.json`` (runtime, permisos 600): claves del servidor y dispositivos
    autorizados, más la IP pública detectada;
  * config de la app (``WEB_VPN_*``): activada, puerto UDP, dirección pública
    fijada a mano y si se permite además el acceso por la red local.

Red y puertos distintos de los de IRCB Pro (10.8.0.0/24, 51820) para que los
dos puedan funcionar a la vez en el mismo equipo. No se toca el router: el
usuario debe reenviar a este equipo el puerto UDP (por defecto 51821).
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import platform
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from paths import resource_path, runtime_path

SERVER_IP = "10.9.0.1"
NETWORK = "10.9.0.0/24"
DEFAULT_UDP_PORT = 51821
# Puertos UDP del túnel por los que viaja el audio WebRTC: el servidor web los
# usa como candidatos ICE en 127.0.0.1 y el ayudante los reenvía desde SERVER_IP.
AUDIO_PORTS = tuple(range(51840, 51850))
MTU = 1380
MAX_DEVICES = 20
HANDSHAKE_FRESH_S = 180  # un dispositivo cuenta como conectado si negoció hace menos


def _store_path() -> str:
    return str(runtime_path("vpn.json"))


# --------------------------------------------------------------------------- #
# Claves
# --------------------------------------------------------------------------- #
def generate_keypair() -> tuple[str, str]:
    """(privada, pública) WireGuard en base64 (Curve25519)."""
    priv = X25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw_priv).decode(), base64.b64encode(raw_pub).decode()


def public_key_of(private_b64: str) -> str:
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    raw_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw_pub).decode()


# --------------------------------------------------------------------------- #
# Almacén (vpn.json)
# --------------------------------------------------------------------------- #
_DEFAULTS = {
    "server_private_key": "",
    "server_public_key": "",
    "detected_endpoint": "",  # IP pública detectada (si no se fija una a mano)
    "peers": [],              # {name, ip, private_key, public_key, created}
}
_lock = threading.RLock()


def load() -> dict:
    with _lock:
        data: dict = {}
        try:
            with open(_store_path(), "r", encoding="utf-8-sig") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        for key, value in _DEFAULTS.items():
            data.setdefault(key, list(value) if isinstance(value, list) else value)
        return data


def save(data: dict) -> None:
    with _lock:
        path = _store_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
        try:
            os.chmod(tmp, 0o600)  # contiene claves privadas
        except OSError:
            pass
        os.replace(tmp, path)


def ensure_server_keys(data: dict) -> dict:
    if not data.get("server_private_key"):
        priv, pub = generate_keypair()
        data["server_private_key"] = priv
        data["server_public_key"] = pub
        save(data)
    return data


def _next_ip(peers: list[dict]) -> Optional[str]:
    used = {p.get("ip") for p in peers}
    for n in range(2, 255):
        ip = f"10.9.0.{n}"
        if ip not in used:
            return ip
    return None


def add_device(name: str) -> dict:
    """Crea un dispositivo autorizado (claves + IP del túnel) y lo guarda."""
    name = (name or "").strip()[:40] or "Móvil"
    with _lock:
        data = ensure_server_keys(load())
        peers = data["peers"]
        if len(peers) >= MAX_DEVICES:
            raise ValueError("Se alcanzó el máximo de dispositivos")
        ip = _next_ip(peers)
        if ip is None:
            raise ValueError("No quedan direcciones libres en el túnel")
        priv, pub = generate_keypair()
        peer = {"name": name, "ip": ip, "private_key": priv, "public_key": pub, "created": int(time.time())}
        peers.append(peer)
        save(data)
    get_manager().reload_devices()
    return peer


def remove_device(public_key: str) -> None:
    with _lock:
        data = load()
        data["peers"] = [p for p in data["peers"] if p.get("public_key") != public_key]
        save(data)
    get_manager().reload_devices()


def endpoint_for(manual_endpoint: str, data: Optional[dict] = None) -> str:
    """Dirección pública que verá el móvil: la fijada a mano o la detectada."""
    manual = str(manual_endpoint or "").strip()
    if manual:
        return manual
    return str((data or load()).get("detected_endpoint") or "").strip()


def client_config(peer: dict, endpoint: str, port: int, data: Optional[dict] = None) -> str:
    """Texto ``.conf`` que importa la app WireGuard (también en forma de QR)."""
    data = data or load()
    endpoint = str(endpoint or "").strip()
    if endpoint and endpoint.count(":") > 1 and not endpoint.startswith("["):
        endpoint = f"[{endpoint}]"  # IPv6 sin corchetes
    if endpoint and not re.search(r":\d+$", endpoint):
        endpoint = f"{endpoint}:{int(port or DEFAULT_UDP_PORT)}"
    return (
        "[Interface]\n"
        f"PrivateKey = {peer['private_key']}\n"
        f"Address = {peer['ip']}/32\n"
        f"MTU = {MTU}\n"
        "\n[Peer]\n"
        f"PublicKey = {data['server_public_key']}\n"
        f"Endpoint = {endpoint}\n"
        f"AllowedIPs = {SERVER_IP}/32\n"
        "PersistentKeepalive = 25\n"
    )


def access_url(web_port: int) -> str:
    return f"https://{SERVER_IP}:{int(web_port)}"


def detect_public_ip(timeout: float = 6.0) -> Optional[str]:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                text = resp.read().decode().strip()
            ipaddress.ip_address(text)
            return text
        except Exception:
            continue
    return None


def is_shared_or_private(ip: str) -> bool:
    """Privada, loopback o compartida por el operador (CG-NAT, 100.64.0.0/10)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (not addr.is_global) or addr in ipaddress.ip_network("100.64.0.0/10")


# Interfaces que no llevan al router de casa (mismos prefijos que webserver.py).
_VIRTUAL_IFACES = ("lo", "docker", "br-", "veth", "virbr", "tun", "tap", "wg", "zt", "tailscale", "cloudflare")


def lan_addresses() -> list[str]:
    """IPv4 privadas de las interfaces físicas: a ellas apunta el reenvío del router.

    No vale la de la ruta por defecto: con otra VPN activa en el equipo sería la
    de esa VPN, no la de la red de casa.
    """
    found: list[str] = []
    try:
        import fcntl

        for _index, name in socket.if_nameindex():
            if name.lower().startswith(_VIRTUAL_IFACES):
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    ifreq = struct.pack("256s", name.encode("utf-8")[:15])
                    ip = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8915, ifreq)[20:24])  # SIOCGIFADDR
            except OSError:
                continue
            if ipaddress.ip_address(ip).is_private and ip not in found:
                found.append(ip)
    except Exception:  # Windows (sin fcntl) u otro sistema
        pass
    if not found:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("192.0.2.1", 9))  # no envía nada: solo elige la interfaz
                found.append(str(sock.getsockname()[0]))
        except OSError:
            pass
    return found


# --------------------------------------------------------------------------- #
# Proceso poorsdrvpn
# --------------------------------------------------------------------------- #
def binary_name() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
    if sys.platform.startswith("win"):
        return f"poorsdrvpn-windows-{arch}.exe"
    return f"poorsdrvpn-linux-{arch}"


def binary_path() -> str:
    return str(resource_path("bin", binary_name()))


class VpnManager:
    """Arranca/para el túnel y consulta qué dispositivos están conectados."""

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.web_port: Optional[int] = None
        self.udp_port: Optional[int] = None
        self.error: Optional[str] = None
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._status: dict[str, dict] = {}
        self._status_evt = threading.Event()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, web_port: int, udp_port: int = DEFAULT_UDP_PORT, detect_endpoint: bool = True) -> bool:
        with self._lock:
            if self.running:
                return True
            self.error = None
            binary = binary_path()
            if not os.path.isfile(binary):
                self.error = f"Falta el componente VPN: {os.path.basename(binary)}"
                return False
            if not sys.platform.startswith("win"):
                try:
                    os.chmod(binary, 0o755)
                except OSError:
                    pass
            data = ensure_server_keys(load())
            self.web_port = int(web_port)
            self.udp_port = int(udp_port or DEFAULT_UDP_PORT)
            config = {
                "private_key": data["server_private_key"],
                "listen_port": self.udp_port,
                "address": SERVER_IP,
                "mtu": MTU,
                "forwards": [{"listen_port": self.web_port, "target": f"127.0.0.1:{self.web_port}"}],
                "udp_forwards": [{"listen_port": p, "target": f"127.0.0.1:{p}"} for p in AUDIO_PORTS],
                "peers": self._helper_peers(data),
            }
            try:
                self.process = subprocess.Popen(
                    [binary],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._ready.clear()
                self.process.stdin.write(json.dumps(config) + "\n")
                self.process.stdin.flush()
            except Exception as exc:
                self.error = f"No se pudo iniciar la VPN: {exc}"
                self.process = None
                return False
            threading.Thread(target=self._read_stdout, args=(self.process,), daemon=True).start()
            threading.Thread(target=self._read_stderr, args=(self.process,), daemon=True).start()

        if not self._ready.wait(10.0) or not self.running:
            self.error = self.error or "La VPN no llegó a arrancar."
            self.stop()
            return False
        if detect_endpoint:
            threading.Thread(target=self._detect_endpoint, daemon=True).start()
        return True

    def stop(self) -> None:
        with self._lock:
            process, self.process = self.process, None
        if process is not None:
            try:
                process.stdin.close()  # el ayudante sale al cerrarse stdin
            except Exception:
                pass
            try:
                process.wait(timeout=3)
            except Exception:
                process.kill()

    # -- dispositivos --------------------------------------------------- #
    @staticmethod
    def _helper_peers(data: dict) -> list[dict]:
        return [{"public_key": p["public_key"], "allowed_ip": f"{p['ip']}/32"} for p in data.get("peers", [])]

    def _send(self, message: dict) -> bool:
        with self._lock:
            if not self.running:
                return False
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
                return True
            except Exception:
                return False

    def reload_devices(self) -> None:
        """Aplica en caliente los cambios de dispositivos autorizados."""
        if self.running:
            self._send({"cmd": "peers", "peers": self._helper_peers(load())})

    def device_status(self, wait: float = 1.5) -> dict[str, dict]:
        """{clave_publica: {connected, last_handshake, rx, tx}}"""
        if not self.running:
            return {}
        self._status_evt.clear()
        if self._send({"cmd": "status"}):
            self._status_evt.wait(wait)
        now = time.time()
        return {
            key: {
                "connected": bool(info.get("handshake")) and now - info["handshake"] < HANDSHAKE_FRESH_S,
                "last_handshake": info.get("handshake") or 0,
                "rx": info.get("rx", 0),
                "tx": info.get("tx", 0),
            }
            for key, info in self._status.items()
        }

    # -- hilos ---------------------------------------------------------- #
    def _read_stdout(self, process: subprocess.Popen) -> None:
        try:
            for line in process.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("event") == "ready":
                    self._ready.set()
                elif msg.get("event") == "status":
                    self._status = {
                        p["public_key"]: {
                            "handshake": p.get("last_handshake_time_sec", 0),
                            "rx": p.get("rx_bytes", 0),
                            "tx": p.get("tx_bytes", 0),
                        }
                        for p in msg.get("peers") or []
                    }
                    self._status_evt.set()
        except Exception:
            pass

    def _read_stderr(self, process: subprocess.Popen) -> None:
        try:
            for line in process.stderr:
                text = line.strip()
                if text:
                    print(text)
                    if not self._ready.is_set():
                        self.error = text
                        self._ready.set()
        except Exception:
            pass
        if process is self.process:
            self._ready.set()

    def _detect_endpoint(self) -> None:
        """Guarda la IP pública para el QR (si no se fijó una dirección a mano)."""
        process = self.process
        public = detect_public_ip()
        if not public or self.process is not process:
            return
        data = load()
        if data.get("detected_endpoint") != public:
            data["detected_endpoint"] = public
            save(data)


_manager: Optional[VpnManager] = None


def get_manager() -> VpnManager:
    global _manager
    if _manager is None:
        _manager = VpnManager()
    return _manager
