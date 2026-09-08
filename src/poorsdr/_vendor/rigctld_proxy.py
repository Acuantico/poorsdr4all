import argparse
import socketserver
import threading
from typing import Optional, Tuple
import socket
import time
import logging

from cat import CatController, MODE_TO_CAT
import json
import os

_RIGCTLD_PROXY_LOGGER = logging.getLogger("rigctld_proxy")


def _ignore_exception(context: str) -> None:
    _RIGCTLD_PROXY_LOGGER.debug(context, exc_info=True)


HAMLIB_TO_CAT = {
    "LSB": "LSB",
    "USB": "USB",
    "CW": "CW",
    "CWR": "CW",
    "FM": "FM",
    "AM": "AM",
    "DIGU": "DIGU",
    "DIGL": "DIGU",
    "PKTLSB": "LSB",
    "PKTUSB": "USB",
}

CAT_TO_HAMLIB = {
    1: "LSB",
    2: "USB",
    3: "CW",
    4: "FM",
    5: "AM",
    6: "DIGU",
}

MODE_TO_KENWOOD = {
    "LSB": "1",
    "USB": "2",
    "CW": "3",
    "FM": "4",
    "AM": "5",
}


def _load_config(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except Exception:
        return {}


class RigState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.freq_hz = 0
        self.last_valid_freq_hz = 0
        self.mode = "AM"
        self.ptt = 0
        self.vfo = "VFOA"
        self.split = 0
        self.tx_vfo = "VFOA"
        self.cached_freq_hz = 0
        self.cached_mode = "AM"
        self.last_freq_query = 0.0
        self.last_mode_query = 0.0
        # Guard against "set then immediate get" races:
        # some clients (e.g. FreeDV via Hamlib) set F/M and immediately poll f/m.
        # If we query the real CAT too soon, we may read stale values and overwrite state.
        self.last_freq_set = 0.0
        self.last_mode_set = 0.0
        self.tx_locked_freq_hz = 0
        self.last_ptt_on_ts = 0.0
        self.pending_freq_hz = 0

    def update_freq(self, hz: int) -> None:
        with self.lock:
            value = int(hz)
            self.freq_hz = value
            if value > 0:
                self.last_valid_freq_hz = value
                self.cached_freq_hz = value
                if int(self.ptt):
                    self.tx_locked_freq_hz = value

    def update_mode(self, mode: str) -> None:
        with self.lock:
            self.mode = str(mode)
            self.cached_mode = str(mode)

    def note_freq_set(self, hz: int) -> None:
        with self.lock:
            self.last_freq_set = time.monotonic()
        self.update_freq(hz)

    def note_mode_set(self, mode: str) -> None:
        with self.lock:
            self.last_mode_set = time.monotonic()
        self.update_mode(mode)

    def recently_set_freq(self, grace: float = 0.75) -> bool:
        with self.lock:
            return (time.monotonic() - float(self.last_freq_set)) < float(grace)

    def recently_set_mode(self, grace: float = 0.75) -> bool:
        with self.lock:
            return (time.monotonic() - float(self.last_mode_set)) < float(grace)

    def update_ptt(self, ptt: int) -> None:
        with self.lock:
            new_ptt = 1 if ptt else 0
            prev_ptt = int(self.ptt)
            self.ptt = new_ptt
            if new_ptt:
                if prev_ptt == 0:
                    self.last_ptt_on_ts = time.monotonic()
                # Keep a stable frequency view for clients like WSJT-X while TX is active.
                lock = int(self.cached_freq_hz) or int(self.freq_hz) or int(self.last_valid_freq_hz)
                self.tx_locked_freq_hz = max(0, lock)
            else:
                self.tx_locked_freq_hz = 0

    def ptt_on_elapsed(self) -> float:
        with self.lock:
            if not int(self.ptt):
                return 0.0
            start = float(self.last_ptt_on_ts or 0.0)
            if start <= 0.0:
                return 0.0
            return max(0.0, time.monotonic() - start)

    def set_pending_freq(self, hz: int) -> None:
        with self.lock:
            self.pending_freq_hz = max(0, int(hz))

    def pop_pending_freq(self) -> int:
        with self.lock:
            value = int(self.pending_freq_hz or 0)
            self.pending_freq_hz = 0
            return value

    def update_vfo(self, vfo: str) -> None:
        with self.lock:
            self.vfo = str(vfo)

    def update_split(self, split: int, tx_vfo: Optional[str] = None) -> None:
        with self.lock:
            self.split = 1 if split else 0
            if tx_vfo:
                self.tx_vfo = str(tx_vfo)

    def get_frequency(self) -> int:
        with self.lock:
            if int(self.ptt) and int(self.tx_locked_freq_hz) > 0:
                return int(self.tx_locked_freq_hz)
            if int(self.freq_hz) > 0:
                return int(self.freq_hz)
            return int(self.last_valid_freq_hz)

    def get_cached_frequency(self) -> int:
        with self.lock:
            if int(self.ptt) and int(self.tx_locked_freq_hz) > 0:
                return int(self.tx_locked_freq_hz)
            if int(self.cached_freq_hz) > 0:
                return int(self.cached_freq_hz)
            if int(self.freq_hz) > 0:
                return int(self.freq_hz)
            return int(self.last_valid_freq_hz)

    def get_cached_mode(self) -> str:
        with self.lock:
            if self.cached_mode:
                return str(self.cached_mode)
            return str(self.mode)

    def can_query_freq(self, interval: float) -> bool:
        with self.lock:
            now = time.monotonic()
            if now - self.last_freq_query >= interval:
                self.last_freq_query = now
                return True
            return False

    def can_query_mode(self, interval: float) -> bool:
        with self.lock:
            now = time.monotonic()
            if now - self.last_mode_query >= interval:
                self.last_mode_query = now
                return True
            return False

    def snapshot(self) -> Tuple[int, str, int]:
        with self.lock:
            freq = int(self.freq_hz) if int(self.freq_hz) > 0 else int(self.last_valid_freq_hz)
            return freq, str(self.mode), int(self.ptt)

    def snapshot_vfo(self) -> Tuple[str, int, str]:
        with self.lock:
            return str(self.vfo), int(self.split), str(self.tx_vfo)


class RigCtlHandler(socketserver.StreamRequestHandler):
    state: RigState = None
    cat: Optional[CatController] = None
    set_frequency_cb = None
    set_mode_cb = None
    set_ptt_cb = None
    rig_name: str = "APower uSDX-v2.7.1"
    rig_model: int = 2028  # Kenwood TS-480
    chk_vfo_executed: bool = False
    log_path: str = ""
    log_lock = threading.Lock()
    ptt_min_on_s: float = 0.0
    ptt_off_delay_s: float = 0.0
    ptt_force_off_window_s: float = 0.0
    ptt_guard_lock = threading.Lock()
    ptt_guard_timer: Optional[threading.Timer] = None
    ptt_keepalive_lock = threading.Lock()
    ptt_keepalive_timer: Optional[threading.Timer] = None
    ptt_keepalive_interval_s: float = 0.35
    ptt_keepalive_last_log: float = 0.0
    ptt_keepalive_last_probe_ts: float = 0.0
    ptt_keepalive_probe_interval_s: float = 1.2
    ptt_owner_lock = threading.Lock()
    ptt_owner_peer: str = ""
    control_owner_lock = threading.Lock()
    control_owner_peer: str = ""
    reject_foreign_clients_while_tx: bool = True
    clients_lock = threading.Lock()
    active_clients: int = 0
    on_client_count_change_cb = None

    def _log(self, direction: str, text: str) -> None:
        if not self.log_path:
            return
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            ms = int((time.time() % 1.0) * 1000)
            peer = f"{self.client_address[0]}:{self.client_address[1]}"
            with self.log_lock:
                with open(self.log_path, "a", encoding="utf-8") as handle:
                    handle.write(f"{ts}.{ms:03d} [{peer}] {direction} {text}\n")
        except Exception:
            return

    def _peer_name(self) -> str:
        try:
            return f"{self.client_address[0]}:{self.client_address[1]}"
        except Exception:
            return ""

    def _acquire_control_owner(self, command: str) -> bool:
        peer = self._peer_name()
        if not peer:
            return True
        claimed = False
        owner = ""
        with self.control_owner_lock:
            owner = str(self.__class__.control_owner_peer or "")
            if not owner:
                self.__class__.control_owner_peer = str(peer)
                owner = str(peer)
                claimed = True
        if claimed:
            self._log("OWNER", f"control_set peer={peer} cmd={command}")
            return True
        if owner == peer:
            return True
        self._log("GUARD", f"control_ignored_foreign cmd={command} owner={owner} peer={peer}")
        return False

    @classmethod
    def _cancel_ptt_guard_timer(cls) -> None:
        with cls.ptt_guard_lock:
            timer = cls.ptt_guard_timer
            cls.ptt_guard_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                _ignore_exception("ignored exception")

    @classmethod
    def _schedule_ptt_guard_off(cls, delay_s: float) -> None:
        delay = max(0.0, float(delay_s))
        if delay <= 0.0:
            return
        cls._cancel_ptt_guard_timer()

        def _guard_release() -> None:
            applied = False
            try:
                if callable(cls.set_ptt_cb):
                    rv = cls.set_ptt_cb(False)
                    applied = (rv is not False)
                else:
                    applied = cls._apply_ptt_hard(False)
                if applied:
                    cls.state.update_ptt(0)
                    pending = int(cls.state.pop_pending_freq() or 0)
                    if pending > 0:
                        try:
                            if callable(cls.set_frequency_cb):
                                rvf = cls.set_frequency_cb(int(pending))
                                if rvf is not False:
                                    cls.state.note_freq_set(int(pending))
                            elif cls.cat and cls.cat.is_connected():
                                cls.cat.set_frequency_hz(int(pending))
                                cls.state.note_freq_set(int(pending))
                        except Exception:
                            _ignore_exception("ignored exception")
                try:
                    if cls.log_path:
                        with cls.log_lock:
                            with open(cls.log_path, "a", encoding="utf-8") as handle:
                                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                ms = int((time.time() % 1.0) * 1000)
                                handle.write(
                                    f"{ts}.{ms:03d} [guard] APPLY ptt=0 deferred_applied={int(bool(applied))}\n"
                                )
                except Exception:
                    _ignore_exception("ignored exception")
            except Exception:
                _ignore_exception("ignored exception")
            finally:
                with cls.ptt_guard_lock:
                    cls.ptt_guard_timer = None

        timer = threading.Timer(delay, _guard_release)
        timer.daemon = True
        with cls.ptt_guard_lock:
            cls.ptt_guard_timer = timer
        timer.start()

    @classmethod
    def _cancel_ptt_keepalive_timer(cls) -> None:
        with cls.ptt_keepalive_lock:
            timer = cls.ptt_keepalive_timer
            cls.ptt_keepalive_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                _ignore_exception("ignored exception")

    @classmethod
    def _schedule_ptt_keepalive(cls) -> None:
        cls._cancel_ptt_keepalive_timer()
        # In callback-driven mode (PoorSDR app owns CAT/PTT), keepalive must not
        # inject additional CAT writes because some radios report IF/PTT
        # inconsistently and can cause TX chopping.
        if callable(cls.set_ptt_cb):
            return
        interval = max(0.2, float(getattr(cls, "ptt_keepalive_interval_s", 0.35) or 0.35))

        def _ptt_keepalive_tick() -> None:
            try:
                _freq, _mode, ptt = cls.state.snapshot()
                if int(ptt) != 1:
                    return
                # Avoid hammering CAT/UI callbacks while TX is already latched.
                # Probe radio TX state periodically and only re-assert when needed.
                applied = True
                reasserted = False
                hard_reassert = False
                radio_ptt = None
                now = time.monotonic()
                try:
                    can_probe = bool(cls.cat and cls.cat.is_connected())
                    probe_interval = max(0.8, float(getattr(cls, "ptt_keepalive_probe_interval_s", 1.2) or 1.2))
                    last_probe = float(getattr(cls, "ptt_keepalive_last_probe_ts", 0.0) or 0.0)
                    if can_probe and (now - last_probe) >= probe_interval:
                        cls.ptt_keepalive_last_probe_ts = now
                        radio_ptt = cls.cat.get_ptt_state()
                        if radio_ptt is False:
                            # IMPORTANT: callback path can short-circuit when the
                            # app already thinks PTT is ON, so it may not issue a
                            # physical CAT TX command. Reassert CAT directly first.
                            applied = cls._apply_ptt_hard(True)
                            hard_reassert = bool(applied)
                            if (not applied) and callable(cls.set_ptt_cb):
                                rv = cls.set_ptt_cb(True)
                                applied = (rv is not False)
                            reasserted = bool(applied)
                except Exception:
                    applied = False
                if applied:
                    cls.state.update_ptt(1)
                try:
                    if now - float(getattr(cls, "ptt_keepalive_last_log", 0.0) or 0.0) >= 2.0:
                        cls.ptt_keepalive_last_log = now
                        if cls.log_path:
                            with cls.log_lock:
                                with open(cls.log_path, "a", encoding="utf-8") as handle:
                                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                    ms = int((time.time() % 1.0) * 1000)
                                    handle.write(
                                        f"{ts}.{ms:03d} [keepalive] APPLY ptt=1 applied={int(bool(applied))} "
                                        f"reasserted={int(bool(reasserted))} "
                                        f"hard_reassert={int(bool(hard_reassert))} "
                                        f"radio_ptt={'?' if radio_ptt is None else int(bool(radio_ptt))}\n"
                                    )
                except Exception:
                    _ignore_exception("ignored exception")
            finally:
                with cls.ptt_keepalive_lock:
                    cls.ptt_keepalive_timer = None
                try:
                    _freq, _mode, ptt = cls.state.snapshot()
                except Exception:
                    ptt = 0
                if int(ptt) == 1:
                    cls._schedule_ptt_keepalive()

        timer = threading.Timer(interval, _ptt_keepalive_tick)
        timer.daemon = True
        with cls.ptt_keepalive_lock:
            cls.ptt_keepalive_timer = timer
        timer.start()


    def _send(self, text: str) -> None:
        try:
            self.wfile.write(text.encode("ascii", errors="ignore"))
            try:
                self.wfile.flush()
            except Exception:
                _ignore_exception("ignored exception")
            self._log("OUT", text.strip())
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client disconnected
            return

    def _send_line(self, text: str = "") -> None:
        # Hamlib/rigctld is LF-terminated. Use '\n' to avoid parser issues in Log4OM.
        self._send(f"{text}\n")

    def _split_vfo_arg(self, args: list[str]) -> Tuple[Optional[str], list[str]]:
        if not args:
            return None, []
        vfo_token = args[0].upper()
        if vfo_token in {"VFOA", "VFOB", "VFOC", "VFO", "CURR", "MAIN", "SUB", "MEM", "A", "B"}:
            return vfo_token, args[1:]
        return None, args

    def setup(self) -> None:
        super().setup()
        self._reject_client = False
        new_count = None
        with self.clients_lock:
            try:
                self.__class__.active_clients = int(self.__class__.active_clients) + 1
            except Exception:
                self.__class__.active_clients = 1
            new_count = int(self.__class__.active_clients)
        try:
            cb = getattr(self.__class__, "on_client_count_change_cb", None)
            if callable(cb):
                cb(new_count)
        except Exception:
            _ignore_exception("ignored exception")
        try:
            # Keep connections stable for slow/idle clients like Log4OM.
            self.connection.settimeout(None)
        except Exception:
            _ignore_exception("ignored exception")
        try:
            peer = f"{self.client_address[0]}:{self.client_address[1]}"
            self._log("CONNECT", peer)
            try:
                _, _, ptt = self.state.snapshot()
            except Exception:
                ptt = 0
            try:
                with self.control_owner_lock:
                    owner = str(self.__class__.control_owner_peer or "")
            except Exception:
                owner = ""
            if (
                bool(getattr(self, "reject_foreign_clients_while_tx", True))
                and int(ptt) == 1
                and owner
                and str(peer) != str(owner)
            ):
                self._reject_client = True
                self._log("GUARD", f"connect_rejected_while_tx owner={owner} peer={peer}")
        except Exception:
            _ignore_exception("ignored exception")

    def finish(self) -> None:
        peer = ""
        try:
            peer = f"{self.client_address[0]}:{self.client_address[1]}"
            self._log("DISCONNECT", peer)
        except Exception:
            _ignore_exception("ignored exception")
        try:
            if peer:
                with self.ptt_owner_lock:
                    if str(self.__class__.ptt_owner_peer or "") == str(peer):
                        self.__class__.ptt_owner_peer = ""
                        self._log("OWNER", f"clear reason=disconnect peer={peer}")
                with self.control_owner_lock:
                    if str(self.__class__.control_owner_peer or "") == str(peer):
                        self.__class__.control_owner_peer = ""
                        self._log("OWNER", f"control_clear reason=disconnect peer={peer}")
        except Exception:
            _ignore_exception("ignored exception")
        new_count = None
        with self.clients_lock:
            try:
                self.__class__.active_clients = max(0, int(self.__class__.active_clients) - 1)
            except Exception:
                self.__class__.active_clients = 0
            new_count = int(self.__class__.active_clients)
        try:
            cb = getattr(self.__class__, "on_client_count_change_cb", None)
            if callable(cb):
                cb(new_count)
        except Exception:
            _ignore_exception("ignored exception")
        super().finish()

    def _rprt(self, code: int = 0) -> None:
        self._send_line(f"RPRT {code}")

    def _cat_query(self, cmd: str) -> Optional[str]:
        if not self.cat or not self.cat.is_connected():
            return None
        try:
            return self.cat._send(cmd, expect_response=True)
        except Exception:
            return None

    @classmethod
    def _apply_ptt_hard(cls, target: bool) -> bool:
        """Best-effort physical CAT apply to keep TX/RX state latched on radio."""
        try:
            if cls.cat and cls.cat.is_connected():
                cls.cat.set_ptt(bool(target))
                return True
        except Exception:
            return False
        return False

    def _get_freq(self) -> Optional[int]:
        # During TX keep frequency stable for rigctl clients; avoid CAT jitter that
        # can make WSJT-X think the rig drifted and stop TX early.
        _freq, _mode, ptt = self.state.snapshot()
        if int(ptt):
            return self.state.get_cached_frequency() or None
        if self.state.recently_set_freq(0.75):
            return self.state.get_cached_frequency() or None
        if self.cat and self.cat.is_connected() and self.state.can_query_freq(0.25):
            try:
                freq = self.cat.get_frequency_hz()
                if freq is not None:
                    self.state.update_freq(int(freq))
                    return int(freq)
            except Exception:
                _ignore_exception("ignored exception")
        return self.state.get_cached_frequency() or None

    def _get_mode(self) -> Optional[str]:
        # During TX keep mode stable for rigctl clients and avoid CAT mode polls
        # that can disturb some radios (uSDX) while transmitting.
        _freq, _mode, ptt = self.state.snapshot()
        if int(ptt):
            return self.state.get_cached_mode() or None
        if self.state.recently_set_mode(0.75):
            return self.state.get_cached_mode() or None
        if self.cat and self.cat.is_connected() and self.state.can_query_mode(0.25):
            try:
                mode = self.cat.get_mode()
                if mode:
                    cat_mode = str(mode).upper()
                    cached = str(self.state.get_cached_mode() or "").upper()
                    if cached == "PKTLSB" and cat_mode == "LSB":
                        return "PKTLSB"
                    if cached == "PKTUSB" and cat_mode == "USB":
                        return "PKTUSB"
                    if cached == "DIGL" and cat_mode == "LSB":
                        return "DIGL"
                    if cached == "DIGU" and cat_mode == "USB":
                        return "DIGU"
                    self.state.update_mode(cat_mode)
                    return cat_mode
            except Exception:
                _ignore_exception("ignored exception")
        return self.state.get_cached_mode() or None

    def _set_mode(self, mode: str) -> bool:
        target = HAMLIB_TO_CAT.get(mode)
        if not target:
            return False
        try:
            if callable(self.set_mode_cb):
                rv = self.set_mode_cb(target)
                if rv is False:
                    return False
            elif self.cat and self.cat.is_connected():
                self.cat.set_mode(target)
        except Exception:
            return False
        self.state.note_mode_set(mode)
        self._log("APPLY", f"mode={mode} target={target} via={'cb' if callable(self.set_mode_cb) else 'cat'}")
        return True

    def _set_freq(self, hz: int) -> bool:
        # Keep TX frequency stable while transmitting (or while delayed PTT off is pending).
        # Some digital clients send RX retune before they actually stop TX.
        _freq, _mode, ptt = self.state.snapshot()
        target_hz = int(hz)
        if int(ptt):
            self.state.set_pending_freq(target_hz)
            self._log("DEFER", f"freq_hz={target_hz} reason=ptt_active")
            return True
        return self._apply_freq_now(target_hz)

    def _apply_freq_now(self, hz: int) -> bool:
        try:
            if callable(self.set_frequency_cb):
                rv = self.set_frequency_cb(int(hz))
                if rv is False:
                    return False
            elif self.cat and self.cat.is_connected():
                self.cat.set_frequency_hz(hz)
        except Exception:
            return False
        self.state.note_freq_set(hz)
        self._log("APPLY", f"freq_hz={int(hz)} via={'cb' if callable(self.set_frequency_cb) else 'cat'}")
        return True

    def _apply_pending_freq_after_ptt(self) -> None:
        pending = int(self.state.pop_pending_freq() or 0)
        if pending <= 0:
            return
        try:
            ok = self._apply_freq_now(pending)
            self._log("DEFER", f"freq_hz={pending} apply_after_ptt ok={int(bool(ok))}")
        except Exception:
            _ignore_exception("ignored exception")

    def _set_ptt(self, value: int) -> bool:
        target = int(bool(value))
        _freq, _mode, current_ptt = self.state.snapshot()
        peer = ""
        try:
            peer = f"{self.client_address[0]}:{self.client_address[1]}"
        except Exception:
            peer = ""
        with self.ptt_owner_lock:
            owner = str(self.__class__.ptt_owner_peer or "")
        if target == 0 and int(current_ptt) == 1 and owner and peer and owner != peer:
            self._log("GUARD", f"ptt_off ignored_foreign owner={owner} peer={peer}")
            return True
        if target == 1:
            self._cancel_ptt_guard_timer()
            self._schedule_ptt_keepalive()
            if int(current_ptt) == 1 and owner and peer and owner != peer:
                self._log("OWNER", f"ptt_on ignored_foreign owner={owner} peer={peer}")
                return True
        else:
            self._cancel_ptt_keepalive_timer()
            min_on = max(0.0, float(getattr(self, "ptt_min_on_s", 0.0) or 0.0))
            off_delay = max(0.0, float(getattr(self, "ptt_off_delay_s", 0.0) or 0.0))
            elapsed = float(self.state.ptt_on_elapsed())
            force_off_window = max(0.0, float(getattr(self, "ptt_force_off_window_s", 0.0) or 0.0))
            remain_min_on = max(0.0, min_on - elapsed) if min_on > 0.0 else 0.0
            remaining = max(remain_min_on, off_delay)
            if int(current_ptt) == 0:
                self._cancel_ptt_guard_timer()
                return True
            if force_off_window > 0.0 and elapsed <= force_off_window:
                self._cancel_ptt_guard_timer()
                self._log(
                    "GUARD",
                    f"ptt_off forced_immediate elapsed_s={elapsed:.3f} force_window_s={force_off_window:.3f}",
                )
            else:
                with self.ptt_guard_lock:
                    guard_pending = self.ptt_guard_timer is not None
                if guard_pending:
                    # Keep existing deferred OFF guard. Repeated OFF frames are
                    # common in digital clients and must not bypass min-on timing.
                    self._log(
                        "GUARD",
                        f"ptt_off repeat_ignored elapsed_s={elapsed:.3f} remaining_s={remaining:.3f}",
                    )
                    return True
                elif remaining > 0.0:
                    self._schedule_ptt_guard_off(remaining)
                    self._log(
                        "GUARD",
                        f"ptt_off deferred remaining_s={remaining:.3f} elapsed_s={elapsed:.3f} "
                        f"min_on_s={min_on:.3f} off_delay_s={off_delay:.3f}",
                    )
                    return True
        try:
            if callable(self.set_ptt_cb):
                rv = self.set_ptt_cb(bool(target))
                if rv is False:
                    return False
            else:
                if not self._apply_ptt_hard(bool(target)):
                    return False
        except Exception:
            return False
        self.state.update_ptt(target)
        if target == 1 and peer:
            try:
                with self.ptt_owner_lock:
                    self.__class__.ptt_owner_peer = str(peer)
                self._log("OWNER", f"set peer={peer}")
            except Exception:
                _ignore_exception("ignored exception")
        if target == 0:
            try:
                with self.ptt_owner_lock:
                    self.__class__.ptt_owner_peer = ""
                self._log("OWNER", "clear reason=ptt_off")
            except Exception:
                _ignore_exception("ignored exception")
        self._log("APPLY", f"ptt={target} via={'cb' if callable(self.set_ptt_cb) else 'cat'}")
        if target == 0:
            self._cancel_ptt_keepalive_timer()
            self._apply_pending_freq_after_ptt()
        return True

    def _parse_freq_token(self, token: str) -> Optional[int]:
        text = str(token or "").strip()
        if not text:
            return None
        text = text.replace(",", ".")
        cleaned: list[str] = []
        dot_used = False
        for ch in text:
            if ch.isdigit() or ch in "+-":
                cleaned.append(ch)
            elif ch == "." and not dot_used:
                dot_used = True
                cleaned.append(".")
        if not cleaned:
            return None
        try:
            return int(round(float("".join(cleaned))))
        except Exception:
            return None

    def _format_fa(self) -> str:
        freq, _mode, _ptt = self.state.snapshot()
        return f"FA{int(freq):011d};"

    def _format_if_kenwood(self) -> str:
        freq, mode, ptt = self.state.snapshot()
        code = MODE_TO_KENWOOD.get(str(mode).upper(), "2")
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
            f"IF{int(freq):011d}"
            f"{spacer}"
            f"{rit}{rit_on}{xit_on}{mem_bank}{mem_chan}"
            f"{tx}{code}{frft}{scan}{split}{tone}{tone_no};"
        )

    def _cat_mode_code(self) -> str:
        _freq, mode, _ptt = self.state.snapshot()
        return MODE_TO_KENWOOD.get(str(mode).upper(), "2")

    def _handle_cat_command(self, cat_cmd: str) -> None:
        cmd = cat_cmd.upper()

        # Queries
        if cmd.startswith("ID"):
            self._send("ID020;")
            return
        if cmd.startswith("PS"):
            # Power status: 1 = on
            self._send("PS1;")
            return
        if cmd.startswith("FA") and len(cmd) <= 3:
            self._send(self._format_fa())
            return
        if cmd.startswith("FB") and len(cmd) <= 3:
            self._send(self._format_fa())
            return
        if cmd.startswith("IF"):
            self._send(self._format_if_kenwood())
            return
        if cmd.startswith("MD") and len(cmd) <= 3:
            self._send(f"MD{self._cat_mode_code()};")
            return
        if cmd.startswith("KS"):
            self._send("KS000;")
            return
        if cmd.startswith("AG"):
            self._send("AG000;")
            return
        if cmd.startswith("AI"):
            # Force AI off to avoid unsolicited traffic
            self._send("AI0;")
            return
        if cmd.startswith("FR"):
            # VFO select (FR0/FR1)
            if cmd.startswith("FR1"):
                self.state.update_vfo("VFOB")
                self._send("FR1;")
            else:
                self.state.update_vfo("VFOA")
                self._send("FR0;")
            return
        if cmd.startswith("V") and "?" in cmd:
            # VFO query
            self._send("VFOA;")
            return

        # Setters
        if cmd.startswith("FA") and len(cmd) > 3:
            digits = "".join(ch for ch in cmd[2:] if ch.isdigit())
            if digits:
                try:
                    self._set_freq(int(digits))
                except ValueError:
                    pass
            self._send(self._format_fa())
            return
        if cmd.startswith("MD") and len(cmd) > 3:
            try:
                code = int(cmd[2])
            except ValueError:
                code = 2
            mode = CAT_TO_HAMLIB.get(code, "USB")
            self._set_mode(mode)
            self._send(f"MD{self._cat_mode_code()};")
            return
        if cmd.startswith("TX"):
            self._set_ptt(1)
            self._send("TX;")
            return
        if cmd.startswith("RX"):
            self._set_ptt(0)
            self._send("RX;")
            return

        # Unknown CAT command: keep silent to avoid parser desyncs
        return

    def handle(self) -> None:
        if bool(getattr(self, "_reject_client", False)):
            try:
                self._rprt(-1)
            except Exception:
                _ignore_exception("ignored exception")
            return
        buffer = b""
        while True:
            try:
                chunk = self.connection.recv(1024)
            except socket.timeout:
                continue
            except (ConnectionResetError, OSError):
                break
            if not chunk:
                break
            buffer += chunk
            while True:
                # Prefer newline-delimited rigctl commands.
                if b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    text = raw.decode("ascii", errors="ignore").strip()
                elif b";" in buffer:
                    raw, buffer = buffer.split(b";", 1)
                    text = raw.decode("ascii", errors="ignore").strip() + ";"
                else:
                    break

                if not text:
                    continue

                self._log("IN", text)
                # Some clients (e.g., Log4OM) may send native CAT commands here.
                # If we detect a raw CAT query (starts/ends with ';'), forward to CAT.
                if text.startswith(";") or text.endswith(";"):
                    cat_cmd = text.strip().lstrip(";").strip()
                    cat_cmd = cat_cmd.replace(" ", "")

                    if not cat_cmd.endswith(";"):
                        cat_cmd = f"{cat_cmd};"

                    # Handle CAT locally to avoid out-of-order replies from the real CAT bus.
                    self._handle_cat_command(cat_cmd)
                    continue

                parts = text.split()
                cmd = parts[0]
                args = parts[1:]

                if cmd in ("q", "\\quit"):
                    self._rprt(0)
                    return

                if cmd in ("\\get_powerstat",):
                    self._send_line("1")
                    continue

                if cmd in ("\\get_lock_mode",):
                    self._send_line("0")
                    continue

                if cmd in ("\\chk_vfo",):
                    self.chk_vfo_executed = True
                    # Keep as a single-line response. '0' is widely accepted by Hamlib clients
                    # and avoids some VFO-mode paths (WSJT-X can be picky here).
                    self._send_line("CHKVFO 0")
                    continue

                if cmd in ("F", "\\set_freq"):
                    if not self._acquire_control_owner("F"):
                        self._rprt(0)
                        continue
                    if not args:
                        self._rprt(-1)
                        continue
                    vfo, rest = self._split_vfo_arg(args)
                    if vfo:
                        self.state.update_vfo(vfo)
                    if not rest:
                        self._rprt(-1)
                        continue
                    hz = self._parse_freq_token(rest[0])
                    if hz is None:
                        self._rprt(-1)
                        continue
                    self._set_freq(hz)
                    self._rprt(0)
                    continue

                if cmd in ("f", "\\get_freq"):
                    vfo, _rest = self._split_vfo_arg(args)
                    if vfo:
                        self.state.update_vfo(vfo)
                    freq = self._get_freq()
                    if freq is None:
                        freq, _, _ = self.state.snapshot()
                    self._send_line(f"{int(freq)}")
                    continue

                if cmd in ("M", "\\set_mode"):
                    if not self._acquire_control_owner("M"):
                        self._rprt(0)
                        continue
                    if len(args) < 1:
                        self._rprt(-1)
                        continue
                    vfo, rest = self._split_vfo_arg(args)
                    if vfo:
                        self.state.update_vfo(vfo)
                    if not rest:
                        self._rprt(-1)
                        continue
                    mode = rest[0].upper()
                    if not self._set_mode(mode):
                        self._rprt(-1)
                    else:
                        self._rprt(0)
                    continue

                if cmd in ("m", "\\get_mode"):
                    vfo, _rest = self._split_vfo_arg(args)
                    if vfo:
                        self.state.update_vfo(vfo)
                    mode = self._get_mode()
                    if mode is None:
                        _, mode, _ = self.state.snapshot()
                    self._send_line(f"{mode}")
                    self._send_line("0")
                    continue

                # Levels (S-meter, RF, AF, etc.). Many clients (e.g. WSJT-X) query these.
                # We don't expose real levels; return neutral values but report success
                # so the client can still control freq/mode/PTT.
                if cmd in ("l", "\\get_level"):
                    # Format: l <LEVEL>
                    self._send_line("0")
                    continue

                if cmd in ("L", "\\set_level"):
                    # Format: L <LEVEL> <VALUE>
                    self._rprt(0)
                    continue

                # Functions (RIT, XIT, etc.). Same approach as levels.
                if cmd in ("u", "\\get_func"):
                    # Format: u <FUNC>
                    self._send_line("0")
                    continue

                if cmd in ("U", "\\set_func"):
                    # Format: U <FUNC> <0|1>
                    self._rprt(0)
                    continue

                # Split VFO control.
                if cmd in ("S", "\\set_split_vfo"):
                    # Format: S <0|1> [TX_VFO]
                    split = 0
                    tx_vfo = None
                    if args:
                        _vfo, rest = self._split_vfo_arg(args)
                        if rest:
                            try:
                                split = int(rest[0])
                            except ValueError:
                                split = 0
                            if len(rest) > 1:
                                tx_vfo = rest[1].upper()
                    self.state.update_split(split, tx_vfo=tx_vfo)
                    self._rprt(0)
                    continue

                if cmd in ("s", "\\get_split_vfo"):
                    # Format: s  -> split \n tx_vfo
                    _vfo, split, tx_vfo = self.state.snapshot_vfo()
                    self._send_line(f"{int(split)}")
                    self._send_line(f"{tx_vfo}")
                    continue

                if cmd in ("V", "\\get_vfo"):
                    # Some clients use 'v' for get_vfo and 'V' for set_vfo, others do the opposite.
                    # Accept both: if no args -> query, if args -> set.
                    if args:
                        vfo = args[0].upper()
                        self.state.update_vfo(vfo)
                        self._rprt(0)
                    else:
                        vfo, _split, _tx_vfo = self.state.snapshot_vfo()
                        self._send_line(f"{vfo}")
                    continue

                if cmd in ("+\\get_vfo_info", "\\get_vfo_info"):
                    vfo, _rest = self._split_vfo_arg(args)
                    if vfo:
                        self.state.update_vfo(vfo)
                    freq = self._get_freq()
                    mode = self._get_mode()
                    if freq is None or mode is None:
                        f_cached, m_cached, _ptt = self.state.snapshot()
                        if freq is None:
                            freq = f_cached
                        if mode is None:
                            mode = m_cached
                    # Keep cached state aligned with live values.
                    if freq is not None:
                        self.state.update_freq(int(freq))
                    if mode is not None:
                        self.state.update_mode(str(mode).upper())
                    _vfo, split, _tx_vfo = self.state.snapshot_vfo()
                    mode_norm = str(mode).upper() if mode else "USB"
                    if mode_norm in ("USB", "LSB"):
                        width = 2400
                    elif mode_norm in ("CW", "CWR"):
                        width = 500
                    elif mode_norm in ("AM",):
                        width = 6000
                    elif mode_norm in ("FM",):
                        width = 12000
                    else:
                        width = 2400
                    satmode = 0
                    if cmd == "+\\get_vfo_info":
                        # Extended response header
                        self._send_line(f"get_vfo_info: {_vfo}")
                    self._send_line(f"Freq: {int(freq)}")
                    self._send_line(f"Mode: {mode_norm}")
                    self._send_line(f"Width: {int(width)}")
                    self._send_line(f"Split: {int(split)}")
                    self._send_line(f"SatMode: {int(satmode)}")
                    if cmd == "+\\get_vfo_info":
                        # Extended Response Protocol ends with an RPRT line.
                        self._rprt(0)
                    continue

                if cmd in ("v", "\\set_vfo", "\\get_vfo"):
                    # Accept both behaviors for compatibility:
                    # - 'v' without args -> get VFO
                    # - 'v' with args -> set VFO
                    if args:
                        vfo = args[0].upper()
                        self.state.update_vfo(vfo)
                        self._rprt(0)
                    else:
                        vfo, _split, _tx_vfo = self.state.snapshot_vfo()
                        self._send_line(f"{vfo}")
                    continue

                if cmd in ("T", "\\set_ptt"):
                    if not self._acquire_control_owner("T"):
                        self._rprt(0)
                        continue
                    if not args:
                        self._rprt(-1)
                        continue
                    _vfo, rest = self._split_vfo_arg(args)
                    if not rest:
                        self._rprt(-1)
                        continue
                    try:
                        value = int(rest[0])
                    except ValueError:
                        self._rprt(-1)
                        continue
                    ok = self._set_ptt(value)
                    self._rprt(0 if ok else -1)
                    continue

                if cmd in ("t", "\\get_ptt"):
                    _, _, ptt = self.state.snapshot()
                    self._send_line(f"{int(ptt)}")
                    continue

                if cmd in ("i", "\\get_info"):
                    self._send_line(f"{self.rig_name}")
                    continue

                if cmd in ("1", "\\dump_state"):
                    self._send_line("1")
                    self._send_line(str(self.rig_model))
                    self._send_line("0")
                    self._send_line("1000000 60000000 0xFFFFFFFF 0 100 0x3 0x0")
                    self._send_line("0 0 0 0 0 0 0")
                    self._send_line("1800000 60000000 0xFFFFFFFF 0 100 0x3 0x0")
                    self._send_line("0 0 0 0 0 0 0")
                    self._send_line("0 0")
                    self._send_line("0 0")
                    self._send_line("0")
                    self._send_line("0")
                    self._send_line("0")
                    self._send_line("0")
                    self._send_line("")
                    self._send_line("")
                    self._send_line("0x0")
                    self._send_line("0x0")
                    self._send_line("0x0")
                    self._send_line("0x0")
                    self._send_line("0x0")
                    self._send_line("0x0")

                    if self.chk_vfo_executed:
                        # Non-zero VFO ops helps clients like WSJT-X avoid "no VFO" paths.
                        self._send_line("vfo_ops=0x3")
                        # Tell clients PTT is supported; some (e.g. FreeDV) won't even try if this is 0.
                        self._send_line("ptt_type=0x1")
                        self._send_line("targetable_vfo=0x0")
                        self._send_line("has_set_vfo=1")
                        self._send_line("has_get_vfo=1")
                        self._send_line("has_set_freq=1")
                        self._send_line("has_get_freq=1")
                        self._send_line("has_set_mode=1")
                        self._send_line("has_get_mode=1")
                        self._send_line("has_set_ptt=1")
                        self._send_line("has_get_ptt=1")
                        self._send_line("has_set_conf=0")
                        self._send_line("has_get_conf=0")
                        self._send_line("has_power2mW=0")
                        self._send_line("has_mW2power=0")
                        self._send_line("has_get_ant=0")
                        self._send_line("has_set_ant=0")
                        self._send_line("timeout=500")
                        self._send_line(f"rig_model={self.rig_model}")
                        self._send_line("rigctld_version=4.6")
                        self._send_line("rig_model=2028")
                        self._send_line("hamlib_version=4.6")
                    # rigctld terminates dump_state with a sentinel line.
                    self._send_line("done")
                    continue

                # Unknown / unimplemented commands must not report success.
                self._rprt(-1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rigctld proxy for APower uSDX-v2.7.1")
    parser.add_argument("--listen", default="127.0.0.1", help="Listen address")
    parser.add_argument("--port", type=int, default=4532, help="Listen port")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    args = parser.parse_args()

    config = _load_config(args.config)
    cat = CatController.from_config(config)
    state = RigState()
    if "CAT_START_FREQ_HZ" in config:
        try:
            state.update_freq(int(config.get("CAT_START_FREQ_HZ")))
        except (TypeError, ValueError):
            pass
    if "Display_Mode" in config:
        state.update_mode(str(config.get("Display_Mode", "AM")).upper())

    server = RigCtldProxyServer(
        cat=cat,
        listen=args.listen,
        port=args.port,
        rig_name="APower uSDX-v2.7.1",
        state=state,
        ptt_min_on_s=max(0.0, float(config.get("RIGCTLD_PTT_MIN_ON_MS", 0) or 0) / 1000.0),
        ptt_off_delay_s=max(0.0, float(config.get("RIGCTLD_PTT_OFF_DELAY_MS", 0) or 0) / 1000.0),
        ptt_force_off_window_s=max(
            0.0,
            float(config.get("RIGCTLD_PTT_FORCE_OFF_WINDOW_MS", 0) or 0) / 1000.0,
        ),
    )
    try:
        server.start()
        server.join()
    finally:
        server.stop()


class RigCtldProxyServer:
    def __init__(
        self,
        cat: Optional[CatController],
        listen: str = "127.0.0.1",
        port: int = 4532,
        rig_name: str = "APower uSDX-v2.7.1",
        state: Optional[RigState] = None,
        set_frequency_cb=None,
        set_mode_cb=None,
        set_ptt_cb=None,
        on_client_count_change_cb=None,
        ptt_min_on_s: float = 0.0,
        ptt_off_delay_s: float = 0.0,
        ptt_force_off_window_s: float = 0.0,
    ) -> None:
        self.cat = cat
        self.listen = listen
        self.port = int(port)
        self.rig_name = rig_name
        self.state = state or RigState()
        self.set_frequency_cb = set_frequency_cb
        self.set_mode_cb = set_mode_cb
        self.set_ptt_cb = set_ptt_cb
        self.on_client_count_change_cb = on_client_count_change_cb
        self.ptt_min_on_s = max(0.0, float(ptt_min_on_s or 0.0))
        self.ptt_off_delay_s = max(0.0, float(ptt_off_delay_s or 0.0))
        self.ptt_force_off_window_s = max(0.0, float(ptt_force_off_window_s or 0.0))
        self._server = None
        self._thread = None
        self.log_path: Optional[str] = None

    def _build_server(self):
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        handler = RigCtlHandler
        handler.state = self.state
        handler.cat = self.cat
        handler.set_frequency_cb = self.set_frequency_cb
        handler.set_mode_cb = self.set_mode_cb
        handler.set_ptt_cb = self.set_ptt_cb
        handler.on_client_count_change_cb = self.on_client_count_change_cb
        handler.active_clients = 0
        handler.ptt_owner_lock = threading.Lock()
        handler.ptt_owner_peer = ""
        handler.control_owner_lock = threading.Lock()
        handler.control_owner_peer = ""
        handler.ptt_min_on_s = self.ptt_min_on_s
        handler.ptt_off_delay_s = self.ptt_off_delay_s
        handler.ptt_force_off_window_s = self.ptt_force_off_window_s
        handler.rig_name = self.rig_name
        handler.rig_model = 2028
        handler.chk_vfo_executed = False
        handler.log_path = self.log_path or ""
        return Server((self.listen, self.port), handler)

    def set_log_path(self, path: str) -> None:
        self.log_path = path

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = self._build_server()

        def _run():
            self._server.serve_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def join(self) -> None:
        if self._thread is None:
            return
        try:
            self._thread.join()
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        if not self._server:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            _ignore_exception("ignored exception")
        self._server = None


if __name__ == "__main__":
    main()
