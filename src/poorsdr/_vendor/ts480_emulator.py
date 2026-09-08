import socketserver
import threading
import time
from typing import Optional


MODE_TO_KENWOOD = {
    "LSB": "1",
    "USB": "2",
    "CW": "3",
    "FM": "4",
    "AM": "5",
}


class TS480State:
    def __init__(self):
        self._lock = threading.Lock()
        self._freq = 0
        self._mode = "USB"
        self._ptt = False
        self._ai = False

    def set_state(self, freq: int | None = None, mode: str | None = None, ptt: bool | None = None) -> None:
        with self._lock:
            if freq is not None:
                self._freq = max(0, int(freq))
            if mode is not None:
                mode_up = str(mode).upper()
                self._mode = mode_up if mode_up in MODE_TO_KENWOOD else "USB"
            if ptt is not None:
                self._ptt = bool(ptt)

    def get_state(self) -> tuple[int, str, bool]:
        with self._lock:
            return int(self._freq), str(self._mode), bool(self._ptt)

    def set_ai(self, enabled: bool) -> None:
        with self._lock:
            self._ai = bool(enabled)

    def get_ai(self) -> bool:
        with self._lock:
            return bool(self._ai)


class TS480Protocol:
    def __init__(self, state: TS480State):
        self.state = state
        self.if_mode = "kenwood"

    def set_if_mode(self, mode: str) -> None:
        self.if_mode = "hamlib" if mode == "hamlib" else "kenwood"

    def handle(self, cmd: str) -> list[str]:
        # Normalize common probes that include a trailing '?' or parameters.
        cmd = cmd.strip()
        # Handle VFO queries (Log4OM often sends "V ?" as a CAT probe).
        if cmd.startswith("V"):
            # Return VFOA and current frequency to satisfy clients expecting either.
            return ["VFOA;", self._format_fa()]
        if cmd.startswith("PS"):
            # Power status (1 = on)
            return ["PS1;"]
        if cmd.startswith("FA"):
            # Set frequency if provided, otherwise read.
            if len(cmd) > 2:
                try:
                    freq = int(cmd[2:])
                    self.state.set_state(freq=freq)
                except ValueError:
                    pass
            return [self._format_fa()]
        if cmd.startswith("FB"):
            # VFO-B frequency (mirror current for simplicity). Accept sets.
            if len(cmd) > 2:
                try:
                    freq = int(cmd[2:])
                    self.state.set_state(freq=freq)
                except ValueError:
                    pass
            return [self._format_fb()]
        if cmd.startswith("MD"):
            # Set mode if provided, otherwise read.
            if len(cmd) > 2:
                self.state.set_state(mode=cmd[2:])
            return [self._format_md()]
        if cmd.startswith("IF"):
            # Return a single, standard IF response (some clients break on duplicates).
            return [self._format_if()]
        if cmd.startswith("ID"):
            return ["ID020;"]
        if cmd.startswith("AI"):
            # Accept AI0/AI1 and reply with current AI state.
            if cmd == "AI0":
                self.state.set_ai(False)
            elif cmd == "AI1":
                self.state.set_ai(True)
            return [f"AI{1 if self.state.get_ai() else 0};"]
        if cmd.startswith("KS"):
            # Keying speed default
            return ["KS000;"]
        if cmd.startswith("AG"):
            # AF gain (3 digits)
            return ["AG000;"]
        if cmd.startswith("RG"):
            # RF gain
            return ["RG000;"]
        if cmd.startswith("MG"):
            # Mic gain
            return ["MG000;"]
        if cmd.startswith("NB"):
            # Noise blanker
            return ["NB0;"]
        if cmd.startswith("RA"):
            # Attenuator
            return ["RA01;"]
        if cmd.startswith("RM"):
            # Meter reading
            return ["RM5100000;"]
        if cmd.startswith("AN"):
            # Antenna
            return ["AN030;"]
        if cmd.startswith("IS"):
            # IF shift
            return ["IS+0000;"]
        if cmd.startswith("SA"):
            # Audio signal / AF meter
            if cmd == "SA":
                return ["SA000;"]
            return []
        if cmd.startswith("SM"):
            # S-meter
            return ["SM000;"]
        if cmd.startswith("SQ"):
            # Squelch setting/status
            return ["SQ000;"]
        if cmd.startswith("FV"):
            # Firmware/version
            return ["FV1.2;"]
        if cmd.startswith("FR"):
            # VFO selection acknowledge (echo requested VFO)
            if cmd in {"FR0", "FR1"}:
                return [f"{cmd};"]
            if cmd == "FR":
                return ["FR0;"]
            return []
        if cmd.startswith("FW"):
            # TX power default
            return ["FW000;"]
        if cmd.startswith("RX"):
            self.state.set_state(ptt=False)
            return ["RX;"]
        if cmd.startswith("TX"):
            self.state.set_state(ptt=True)
            return ["TX;"]
        if cmd.startswith("OM"):
            return ["OM000;"]
        if cmd.startswith("RT"):
            return ["RT0000;"]
        if cmd.startswith("MF"):
            return ["MF0;"]
        if cmd.startswith("PC"):
            # Power control (return nominal power)
            return ["PC010;"]
        return []

    def _format_fa(self) -> str:
        freq, _mode, _ptt = self.state.get_state()
        return f"FA{freq:011d};"

    def _format_md(self) -> str:
        _freq, mode, _ptt = self.state.get_state()
        code = MODE_TO_KENWOOD.get(mode, "2")
        return f"MD{code};"

    def _format_if(self) -> str:
        if self.if_mode == "hamlib":
            return self._format_if_hamlib()
        return self._format_if_kenwood()

    def _format_if_hamlib(self) -> str:
        # IF format compatible with Kenwood CAT (as used in Hamlib simulators):
        # IF + freq(11) + step/flags(7) + rit/xit/mode block(20)
        # Example: IF00028074000001000+0000000000{MODE}0000000;
        freq, mode, _ptt = self.state.get_state()
        code = MODE_TO_KENWOOD.get(mode, "2")
        step_flags = "0001000"
        # "+" + 11 zeros + mode + 7 zeros = 20 chars (matches Hamlib simkenwood)
        rit_mode_block = "+" + ("0" * 11) + code + ("0" * 7)
        return f"IF{freq:011d}{step_flags}{rit_mode_block};"

    def _format_if_kenwood(self) -> str:
        # TS-480 IF format per Kenwood TS-480 PC Control Command:
        # P1 freq(11), P2 5 spaces, P3 RIT/XIT (sign + 4 digits),
        # P4 RIT on/off, P5 XIT on/off, P6 mem bank(1), P7 mem chan(2),
        # P8 RX/TX, P9 mode, P10 FR/FT, P11 scan, P12 split,
        # P13 tone, P14 tone number(2).
        freq, mode, ptt = self.state.get_state()
        code = MODE_TO_KENWOOD.get(mode, "2")
        tx = "1" if ptt else "0"
        rit = "+0000"
        rit_on = "0"
        xit_on = "0"
        mem_bank = "0"
        mem_chan = "00"
        frft = "0"
        scan = "0"
        split = "0"
        tone = "0"
        tone_no = "00"
        spacer = " " * 5
        return (
            f"IF{freq:011d}"
            f"{spacer}"
            f"{rit}{rit_on}{xit_on}{mem_bank}{mem_chan}"
            f"{tx}{code}{frft}{scan}{split}{tone}{tone_no};"
        )

    def _format_fb(self) -> str:
        freq, _mode, _ptt = self.state.get_state()
        return f"FB{freq:011d};"



class _TcpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        protocol: TS480Protocol = self.server.protocol
        buffer = ""
        ai_event = threading.Event()
        ai_thread = None
        response_delay_ms = 20
        fast_cmds = {"ID", "FR0", "FR1", "IF", "FA", "FB", "AG0", "KS", "MD"}
        use_crlf = False
        try:
            self.server._log("CONNECT", f"{self.client_address[0]}:{self.client_address[1]}")
        except Exception:
            pass

        def _ai_loop():
            while not ai_event.is_set():
                try:
                    for resp in (protocol._format_fa(), protocol._format_md()):
                        payload = resp + ("\r\n" if use_crlf else "")
                        self.request.sendall(payload.encode("ascii", errors="ignore"))
                        try:
                            self.server._log("OUT", resp.strip())
                        except Exception:
                            pass
                except Exception:
                    break
                time.sleep(0.5)
        while True:
            try:
                data = self.request.recv(256)
            except Exception:
                try:
                    self.server._log("ERROR", "recv failed")
                except Exception:
                    pass
                break
            if not data:
                break
            try:
                buffer += data.decode("ascii", errors="ignore")
            except Exception:
                buffer = ""
                continue
            while ";" in buffer:
                cmd, buffer = buffer.split(";", 1)
                cmd = cmd.strip().upper()
                if not cmd:
                    continue
                if cmd == "AI1":
                    if not ai_event.is_set():
                        ai_event.clear()
                    if ai_thread is None or not ai_thread.is_alive():
                        ai_thread = threading.Thread(target=_ai_loop, daemon=True)
                        ai_thread.start()
                elif cmd == "AI0":
                    ai_event.set()
                try:
                    self.server._log("IN", cmd)
                except Exception:
                    pass
                responses = protocol.handle(cmd)
                for resp in responses:
                    try:
                        if response_delay_ms and cmd not in fast_cmds:
                            time.sleep(response_delay_ms / 1000.0)
                        payload = resp + ("\r\n" if use_crlf else "")
                        self.request.sendall(payload.encode("ascii", errors="ignore"))
                        try:
                            self.server._log("OUT", resp.strip())
                        except Exception:
                            pass
                    except Exception:
                        return
        ai_event.set()
        try:
            self.server._log("DISCONNECT", f"{self.client_address[0]}:{self.client_address[1]}")
        except Exception:
            pass


class TS480TcpServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = int(port)
        self.state = TS480State()
        self.protocol = TS480Protocol(self.state)
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.log_path: Optional[str] = None

    def set_state(self, freq: int | None = None, mode: str | None = None, ptt: bool | None = None) -> None:
        self.state.set_state(freq=freq, mode=mode, ptt=ptt)

    def start(self) -> bool:
        if self._server:
            return True
        try:
            class Server(socketserver.ThreadingTCPServer):
                allow_reuse_address = True
                daemon_threads = True

                def _log(self, direction: str, text: str) -> None:
                    path = getattr(self, "log_path", None)
                    if not path:
                        return
                    try:
                        with open(path, "a", encoding="utf-8") as handle:
                            handle.write(f"{direction} {text}\n")
                    except Exception:
                        return

            self._server = Server((self.host, self.port), _TcpHandler)
            self._server.protocol = self.protocol
            self._server.log_path = self.log_path
        except Exception:
            self._server = None
            return False
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._server:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass
        self._server = None
        self._thread = None

    def set_log_path(self, path: str) -> None:
        self.log_path = path
