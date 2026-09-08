import logging
import threading
import time
import re
import glob
from typing import Optional
import sys

import serial
import subprocess
import os
from platform_config import sanitize_serial_port
from paths import runtime_path

_CAT_LOGGER = logging.getLogger("CatController")


def _ignore_exception(context: str) -> None:
    _CAT_LOGGER.debug(context, exc_info=True)

MODE_TO_CAT = {
    "LSB": 1,
    "USB": 2,
    "CW": 3,
    "FM": 4,
    "AM": 5,
    "DIGU": 6,
}

CAT_TO_MODE = {
    1: "LSB",
    2: "USB",
    3: "CW",
    4: "FM",
    5: "AM",
    6: "DIGU",
}


class CatController:
    def __init__(
        self,
        port: Optional[str],
        baudrate: int = 38400,
        timeout: float = 0.5,
        debug: bool = False,
    ):
        self.logger = logging.getLogger("CatController")
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.debug = debug
        self._lock = threading.Lock()
        self.ser = None
        self._runtime_log_path = str(runtime_path("cat_runtime.log"))
        self._last_ptt_runtime_log_ts = 0.0
        self._last_reconnect_ts = 0.0
        self._reconnect_cooldown_s = 1.0
        if not port:
            self.logger.warning("CAT sin puerto configurado.")
            return
        self._open_serial(initial=True)

    def _open_serial(self, initial: bool = False) -> bool:
        port = self.port
        baudrate = self.baudrate
        timeout = self.timeout
        if not port:
            return False
        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
                write_timeout=timeout,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self._set_modem_lines(active=False)
            self._log_runtime(("CAT open ok" if initial else "CAT reopen ok") + f" port={port} baud={baudrate}")
            self.logger.info("CAT abierto en %s @ %s", port, baudrate)
            self._last_reconnect_ts = time.monotonic()
            return True
        except Exception as exc:
            # Retry once if Windows still has rigctld holding the port
            if os.name == "nt" and isinstance(exc, PermissionError):
                try:
                    subprocess.run(
                        ["taskkill", "/IM", "rigctld.exe", "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                    time.sleep(0.5)
                    self.ser = serial.Serial(
                        port=port,
                        baudrate=baudrate,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        timeout=timeout,
                        write_timeout=timeout,
                        xonxoff=False,
                        rtscts=False,
                        dsrdtr=False,
                    )
                    self._set_modem_lines(active=False)
                    self._log_runtime(f"CAT open retry ok port={port} baud={baudrate}")
                    self.logger.info("CAT abierto en %s @ %s (reintento)", port, baudrate)
                    self._last_reconnect_ts = time.monotonic()
                    return True
                except Exception:
                    _ignore_exception("ignored exception")
            if os.name != "nt" and isinstance(exc, PermissionError):
                self.logger.error(
                    "Sin permisos para abrir CAT en %s. Revisa grupos/permisos del puerto serie (uucp/lock).",
                    port,
                )
            self.logger.error("No se pudo abrir CAT en %s: %s", port, exc)
            self._log_runtime(f"CAT open failed port={port} err={exc!r}")
            self.ser = None
            return False

    def _reconnect(self) -> bool:
        now = time.monotonic()
        if (now - float(self._last_reconnect_ts or 0.0)) < float(self._reconnect_cooldown_s):
            return bool(self.is_connected())
        self._last_reconnect_ts = now
        try:
            if self.ser is not None:
                try:
                    if self.ser.is_open:
                        self.ser.close()
                except Exception:
                    _ignore_exception("ignored exception")
        finally:
            self.ser = None
        self._log_runtime(f"CAT reconnect attempt port={self.port} baud={self.baudrate}")
        return self._open_serial(initial=False)

    @classmethod
    def from_config(cls, config: dict) -> "CatController":
        port = sanitize_serial_port(config.get("CAT_COM"))
        # Prefer stable udev path when CAT_COM points to a volatile ttyUSB node.
        if port and port.startswith("/dev/ttyUSB"):
            try:
                target = os.path.realpath(port)
                by_id = sorted(glob.glob("/dev/serial/by-id/*"))
                for candidate in by_id:
                    try:
                        if os.path.realpath(candidate) == target:
                            port = candidate
                            break
                    except Exception:
                        _ignore_exception("ignored exception")
            except Exception:
                _ignore_exception("ignored exception")
        baudrate = int(config.get("CAT_BAUD", 38400))
        timeout = float(config.get("CAT_TIMEOUT", 0.5))
        debug = bool(config.get("CAT_DEBUG", False))
        return cls(port, baudrate=baudrate, timeout=timeout, debug=debug)

    def is_connected(self) -> bool:
        return bool(self.ser and self.ser.is_open)

    def close(self) -> None:
        if not self.ser:
            return
        self._log_runtime("CAT close start")
        # Leave radio in RX before releasing CAT to avoid sticky TX/audio states.
        try:
            self.set_ptt(False)
            time.sleep(0.03)
            self.set_ptt(False)
        except Exception:
            _ignore_exception("ignored exception")
        try:
            if self.ser.is_open:
                self._set_modem_lines(active=False)
                try:
                    self.ser.flush()
                except Exception:
                    _ignore_exception("ignored exception")
                try:
                    self.ser.reset_input_buffer()
                except Exception:
                    _ignore_exception("ignored exception")
                try:
                    self.ser.reset_output_buffer()
                except Exception:
                    _ignore_exception("ignored exception")
                self.ser.close()
                self.ser = None
                self._log_runtime("CAT close done")
        except Exception as exc:
            self.logger.error("Error al cerrar CAT: %s", exc)
            self._log_runtime(f"CAT close error err={exc!r}")

    def _set_modem_lines(self, active: bool) -> None:
        if not self.is_connected():
            return
        state = bool(active)
        try:
            self.ser.dtr = state
        except Exception:
            _ignore_exception("ignored exception")
        try:
            self.ser.rts = state
        except Exception:
            _ignore_exception("ignored exception")

    def _log_runtime(self, message: str) -> None:
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            ms = int((time.time() % 1.0) * 1000)
            with open(self._runtime_log_path, "a", encoding="utf-8") as handle:
                handle.write(f"{stamp}.{ms:03d} {message}\n")
        except Exception:
            _ignore_exception("ignored exception")

    def _drain_rx_buffer(self, timeout_s: float = 0.05) -> None:
        if not self.is_connected():
            return
        end_ts = time.monotonic() + max(0.0, float(timeout_s))
        while time.monotonic() < end_ts:
            try:
                waiting = int(getattr(self.ser, "in_waiting", 0) or 0)
            except Exception:
                waiting = 0
            if waiting <= 0:
                time.sleep(0.003)
                continue
            try:
                self.ser.read(waiting)
            except Exception:
                break

    def _send(self, command: str, expect_response: bool = False) -> Optional[str]:
        if not self.is_connected():
            if not self._reconnect():
                return None
        cmd = command.strip()
        if not cmd.endswith(";"):
            cmd += ";"
        payload = cmd.encode("ascii", errors="ignore")
        with self._lock:
            if not self.is_connected():
                if not self._reconnect():
                    return None
            try:
                # Prevent stale replies (eg. RX0;) from previous non-query commands.
                try:
                    self.ser.reset_input_buffer()
                except Exception:
                    _ignore_exception("ignored exception")
                if self.debug:
                    self.logger.info("CAT >> %s", cmd)
                self.ser.write(payload)
                self.ser.flush()
                if not expect_response:
                    # Consume optional command echo/ack to keep parser aligned.
                    self._drain_rx_buffer(timeout_s=0.06)
                    return None
                response = self._read_until_semicolon()
                if self.debug:
                    self.logger.info("CAT << %s", response)
                return response
            except Exception as exc:
                self.logger.error("Error enviando CAT '%s': %s", cmd, exc)
                self._log_runtime(f"CAT send error cmd={cmd!r} err={exc!r}")
                # Auto-recover from transient USB serial drops (Errno 5/2) frequently
                # observed when the SDR container restarts or reinitializes USB bus.
                if self._reconnect():
                    try:
                        self.ser.write(payload)
                        self.ser.flush()
                        if not expect_response:
                            self._drain_rx_buffer(timeout_s=0.06)
                            self._log_runtime(f"CAT resend ok cmd={cmd!r}")
                            return None
                        response = self._read_until_semicolon()
                        self._log_runtime(f"CAT resend ok cmd={cmd!r} resp={response!r}")
                        return response
                    except Exception as retry_exc:
                        self.logger.error("Reintento CAT falló para '%s': %s", cmd, retry_exc)
                        self._log_runtime(f"CAT resend error cmd={cmd!r} err={retry_exc!r}")
                return None

    def _read_until_semicolon(self) -> Optional[str]:
        if not self.is_connected():
            return None
        buffer = bytearray()
        start = time.time()
        while time.time() - start < self.timeout:
            try:
                chunk = self.ser.read(1)
            except Exception:
                break
            if not chunk:
                continue
            buffer.extend(chunk)
            if chunk == b";":
                break
        if not buffer:
            return None
        return buffer.decode("ascii", errors="ignore")

    def set_frequency_hz(self, hz: int) -> None:
        if hz is None:
            return
        freq = max(0, int(hz))
        self._send(f"FA{freq:011d}")

    def set_mode(self, mode: str) -> None:
        mode_key = (mode or "").upper()
        cat_mode = MODE_TO_CAT.get(mode_key, MODE_TO_CAT["USB"])
        self._send(f"MD{cat_mode}")

    def set_ptt(self, active: bool) -> None:
        command = "TX" if active else "RX"
        caller = "-"
        try:
            # Lower-overhead caller introspection than inspect.stack()
            caller = str(sys._getframe(2).f_code.co_name or "-")
        except Exception:
            caller = "-"
        start_ns = time.monotonic_ns()
        send_ok = False
        self._send(command)
        send_ok = True
        retried = False
        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000.0
        try:
            now = time.monotonic()
            self._last_ptt_runtime_log_ts = now
            self._log_runtime(
                "CAT PTT cmd=%s caller=%s connected=%s send_ok=%s retried=%s elapsed_ms=%.3f"
                % (
                    command,
                    caller,
                    int(bool(self.is_connected())),
                    int(bool(send_ok)),
                    int(bool(retried)),
                    float(elapsed_ms),
                )
            )
        except Exception:
            _ignore_exception("ignored exception")

    def probe(self) -> dict:
        results = {
            "id": self._send("ID", expect_response=True),
            "if": self._send("IF", expect_response=True),
            "fa": self._send("FA", expect_response=True),
        }
        return results

    def _parse_frequency(self, response: Optional[str], prefix: str) -> Optional[int]:
        if not response:
            return None
        text = response.strip()
        if not text.startswith(prefix):
            return None
        digits = "".join(ch for ch in text[len(prefix):] if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits[:11])
        except ValueError:
            return None

    def _parse_if(self, response: Optional[str]) -> tuple[Optional[int], Optional[str]]:
        if not response:
            return None, None
        text = response.strip()
        if not text.startswith("IF"):
            return None, None
        freq = None
        try:
            freq_digits = text[2:13]
            if freq_digits.isdigit():
                freq = int(freq_digits)
        except Exception:
            freq = None
        mode = None
        # Kenwood-style IF returns mode digit at position 28 (1-based) for TS-480.
        # uSDX partial emulation follows this layout.
        try:
            if len(text) >= 30:
                mode_digit = text[27]
                if mode_digit.isdigit():
                    mode = CAT_TO_MODE.get(int(mode_digit))
        except Exception:
            mode = None
        return freq, mode

    def _parse_if_ptt(self, response: Optional[str]) -> Optional[bool]:
        if not response:
            return None
        text = str(response).strip()
        if not text.startswith("IF"):
            return None
        # Kenwood-like IF: ... mem_chan(2) tx(1) mode(1) ...
        # Prefer strict decode, then fallback to tolerant index checks.
        try:
            match = re.match(
                r"^IF\d{11}.{5}[+-]\d{4}[01][01][01]\d{2}([01])\d[01][01][01][01]\d{2};$",
                text,
            )
            if match:
                return bool(int(match.group(1)))
        except Exception:
            _ignore_exception("ignored exception")
        try:
            if len(text) > 28 and text[28] in ("0", "1"):
                return bool(int(text[28]))
        except Exception:
            _ignore_exception("ignored exception")
        try:
            if len(text) > 26 and text[26] in ("0", "1"):
                return bool(int(text[26]))
        except Exception:
            _ignore_exception("ignored exception")
        return None

    def get_frequency_hz(self) -> Optional[int]:
        freq = self._parse_frequency(self._send("FA", expect_response=True), "FA")
        if freq is not None:
            return freq
        freq, _mode = self._parse_if(self._send("IF", expect_response=True))
        return freq

    def get_mode(self) -> Optional[str]:
        response = self._send("MD", expect_response=True)
        if response and response.startswith("MD"):
            try:
                digit = int(response[2:3])
                return CAT_TO_MODE.get(digit)
            except Exception:
                _ignore_exception("ignored exception")
        _freq, mode = self._parse_if(self._send("IF", expect_response=True))
        return mode

    def get_ptt_state(self) -> Optional[bool]:
        return self._parse_if_ptt(self._send("IF", expect_response=True))

    def get_state(self) -> dict:
        freq = self.get_frequency_hz()
        mode = self.get_mode()
        return {"frequency_hz": freq, "mode": mode}

    # Compatibilidad con el flujo anterior
    def activar_ptt(self) -> None:
        self.set_ptt(True)

    def desactivar_ptt(self) -> None:
        self.set_ptt(False)
