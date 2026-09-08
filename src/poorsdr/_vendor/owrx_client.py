import base64
import json
import os
import queue
import socket
import threading
import time
import urllib.request
from typing import Optional


class OwrxClient:
    def __init__(self, host: str, port: int, enabled: bool, magic_key: str = ""):
        self.host = (host or "").strip()
        self.port = int(port) if port else 0
        self.enabled = bool(enabled)
        self.magic_key = magic_key or ""
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._connected = False
        self._last_freq: Optional[int] = None
        self._last_mode: Optional[str] = None
        self._last_profile: Optional[str] = None
        self._last_profile_ts = 0.0
        self._center_freq: Optional[int] = None
        self._pending_freq: Optional[int] = None
        self._recv_buffer = b""

    @classmethod
    def from_config(cls, config: dict) -> "OwrxClient":
        host = str(config.get("OWRX_HOST", "") or "")
        try:
            port = int(config.get("OWRX_PORT", 8073))
        except (TypeError, ValueError):
            port = 8073
        enabled = bool(config.get("OWRX_ENABLED", False))
        magic_key = str(config.get("OWRX_KEY", "") or "")
        return cls(host, port, enabled, magic_key)

    def start(self) -> None:
        if not self.enabled or not self.host or self.port <= 0:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._close_socket()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def send_frequency(self, hz: int) -> None:
        if not self.enabled:
            return
        try:
            freq = int(hz)
        except (TypeError, ValueError):
            return
        if freq == self._last_freq:
            return
        self._last_freq = freq
        if self._center_freq is None:
            self._pending_freq = freq
            return
        offset = freq - self._center_freq
        self._enqueue_json({"type": "dspcontrol", "params": {"offset_freq": int(offset)}})

    def send_mode(self, mode: str) -> None:
        if not self.enabled:
            return
        modulation = self._map_mode_to_modulation(mode)
        if not modulation or modulation == self._last_mode:
            return
        self._last_mode = modulation
        params = self._default_bandpass(modulation)
        params["mod"] = modulation
        self._enqueue_json({"type": "dspcontrol", "params": params})

    def send_profile(self, profile: str) -> None:
        if not self.enabled:
            return
        prof = str(profile or "").strip()
        if not prof:
            return
        now = time.time()
        if prof == self._last_profile and (now - self._last_profile_ts) < 0.5:
            return
        self._last_profile = prof
        self._last_profile_ts = now
        params = {"profile": prof}
        if self.magic_key:
            params["key"] = self.magic_key
        self._enqueue_json({"type": "selectprofile", "params": params})

    def _enqueue_json(self, payload: dict) -> None:
        try:
            self._queue.put_nowait(json.dumps(payload))
        except queue.Full:
            pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self.enabled or not self.host or self.port <= 0:
                time.sleep(0.5)
                continue
            if not self._connected:
                try:
                    self._connect()
                except Exception:
                    self._close_socket()
                    time.sleep(1.5)
                    continue
            self._send_pending()
            self._drain_incoming()

    def _send_pending(self) -> None:
        while not self._stop_event.is_set():
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._send_text(message)
            except Exception:
                self._close_socket()
                return

    def _drain_incoming(self) -> None:
        if not self._sock:
            return
        try:
            self._sock.settimeout(0.05)
            chunk = self._sock.recv(4096)
        except socket.timeout:
            return
        except Exception:
            self._close_socket()
            return
        if not chunk:
            return
        self._recv_buffer += chunk
        while True:
            parsed = self._try_parse_frame(self._recv_buffer)
            if not parsed:
                break
            opcode, payload, remainder = parsed
            self._recv_buffer = remainder
            if opcode == 0x1:
                self._handle_text(payload.decode("utf-8", errors="ignore"))
            elif opcode == 0x9:
                self._send_control_frame(0xA, payload)
            elif opcode == 0x8:
                self._close_socket()
                break

    def _connect(self) -> None:
        self._close_socket()
        sock = socket.create_connection((self.host, self.port), timeout=2.0)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        paths = ["/ws/", "/ws"]
        response = ""
        for path in paths:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            )
            sock.sendall(request.encode("ascii"))
            response = self._read_http_response(sock)
            if "101" in response.split("\r\n", 1)[0]:
                break
        if "101" not in response.split("\r\n", 1)[0]:
            sock.close()
            raise ConnectionError("WebSocket upgrade failed")
        self._sock = sock
        self._connected = True
        self._recv_buffer = b""
        self._send_text("SERVER DE CLIENT client=PoorSDR4All type=receiver")
        self._enqueue_json({"type": "dspcontrol", "action": "start"})
        self._enqueue_json({"type": "connectionproperties", "params": {"output_rate": 48000, "hd_output_rate": 48000}})
        if self._center_freq is None:
            threading.Thread(target=self._fetch_center_freq_http, daemon=True).start()

    def _read_http_response(self, sock: socket.socket) -> str:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
            if len(data) > 8192:
                break
        try:
            return data.decode("latin-1", errors="ignore")
        except Exception:
            return ""

    def _send_text(self, message: str) -> None:
        if not self._sock:
            raise ConnectionError("Socket not connected")
        payload = message.encode("utf-8")
        self._send_control_frame(0x1, payload)

    def _send_control_frame(self, opcode: int, payload: bytes) -> None:
        if not self._sock:
            raise ConnectionError("Socket not connected")
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        length = len(payload)
        mask_bit = 0x80
        if length <= 125:
            header.append(mask_bit | length)
        elif length < (1 << 16):
            header.append(mask_bit | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(mask_bit | 127)
            header.extend(length.to_bytes(8, "big"))
        mask_key = os.urandom(4)
        header.extend(mask_key)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(header + masked)

    def _close_socket(self) -> None:
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._recv_buffer = b""
        self._center_freq = None

    def _map_mode_to_modulation(self, mode: str) -> str:
        if not mode:
            return ""
        mode = str(mode).strip().upper()
        if mode == "AM":
            return "am"
        if mode == "FM":
            return "nfm"
        if mode == "USB":
            return "usb"
        if mode == "LSB":
            return "lsb"
        return ""

    def _default_bandpass(self, modulation: str) -> dict:
        if modulation == "am":
            return {"low_cut": -4000, "high_cut": 4000}
        if modulation == "nfm":
            return {"low_cut": -4000, "high_cut": 4000}
        if modulation == "usb":
            return {"low_cut": 150, "high_cut": 2750}
        if modulation == "lsb":
            return {"low_cut": -2750, "high_cut": -150}
        return {}

    def _fetch_center_freq_http(self) -> None:
        if not self.host or self.port <= 0:
            return
        url = f"http://{self.host}:{self.port}/status.json"
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                raw = response.read()
            data = json.loads(raw.decode("utf-8", errors="ignore"))
        except Exception:
            return
        try:
            sdrs = data.get("sdrs") or []
            if not sdrs:
                return
            profiles = sdrs[0].get("profiles") or []
            if not profiles:
                return
            center = profiles[0].get("center_freq")
            if center is None:
                return
            self._center_freq = int(center)
            if self._pending_freq is not None:
                pending = self._pending_freq
                self._pending_freq = None
                self.send_frequency(pending)
        except Exception:
            return

    def _handle_text(self, message: str) -> None:
        if not message or message.startswith("CLIENT DE SERVER"):
            return
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        msg_type = payload.get("type")
        value = payload.get("value")
        if msg_type in ("config", "update") and isinstance(value, dict):
            center = value.get("center_freq")
            if center is not None:
                try:
                    self._center_freq = int(center)
                except (TypeError, ValueError):
                    pass
                else:
                    if self._pending_freq is not None:
                        pending = self._pending_freq
                        self._pending_freq = None
                        self.send_frequency(pending)

    def _try_parse_frame(self, buffer: bytes):
        if len(buffer) < 2:
            return None
        b1 = buffer[0]
        b2 = buffer[1]
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        idx = 2
        if length == 126:
            if len(buffer) < idx + 2:
                return None
            length = int.from_bytes(buffer[idx:idx + 2], "big")
            idx += 2
        elif length == 127:
            if len(buffer) < idx + 8:
                return None
            length = int.from_bytes(buffer[idx:idx + 8], "big")
            idx += 8
        mask_key = b""
        if masked:
            if len(buffer) < idx + 4:
                return None
            mask_key = buffer[idx:idx + 4]
            idx += 4
        if len(buffer) < idx + length:
            return None
        payload = buffer[idx:idx + length]
        remainder = buffer[idx + length:]
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return opcode, payload, remainder
