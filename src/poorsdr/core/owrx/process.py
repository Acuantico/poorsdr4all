from __future__ import annotations

import os
import signal


def backend_launch_plan(*, skip_backend_check: bool, backend_fast_ready: bool) -> tuple[bool, str | None]:
    if bool(skip_backend_check):
        return False, None
    if bool(backend_fast_ready):
        return False, "fast_ready"
    return True, "ensure_internal"


def probe_backend_ready(
    *,
    host: str,
    port: int,
    wait_http_ready_fn,
    http_looks_valid_fn,
    wait_timeout_s: float,
    valid_timeout_s: float,
) -> bool:
    try:
        return bool(
            wait_http_ready_fn(host, port, timeout_s=float(wait_timeout_s))
            and http_looks_valid_fn(host, port, timeout_s=float(valid_timeout_s))
        )
    except Exception:
        return False


def should_force_embed_takeover(*, prioritize_embed: bool, has_active_sessions: bool) -> bool:
    return bool(prioritize_embed) and bool(has_active_sessions)


def startup_failure_detail(*, detail: str, code: int | str) -> str:
    text = str(detail or "").strip()
    if text:
        return text
    return f"El proceso terminó con código {code}."


def is_process_running(process) -> bool:
    if process is None:
        return False
    try:
        return process.poll() is None
    except Exception:
        return False


def is_running_with_port(process, port) -> bool:
    return is_process_running(process) and bool(port)


def should_sync_digi_receiver_without_owrx(owrx_active: bool) -> bool:
    return not bool(owrx_active)


def should_block_digi_backend_command(
    *,
    command_type: str,
    digi_backend_sync: bool,
    owrx_active: bool,
) -> bool:
    ctype = str(command_type or "").strip().lower()
    return ctype in ("profile", "step") and (not bool(digi_backend_sync)) and bool(owrx_active)


def should_use_digi_tune_only_sync(*, digi_backend_sync: bool, owrx_active: bool) -> bool:
    return (not bool(digi_backend_sync)) and bool(owrx_active)


def is_owrx_driven_sync_reason(reason: str) -> bool:
    return str(reason or "").strip().lower() in ("owrx_reverse_tune", "owrx_apply_pending", "owrx_tune")


def should_suppress_digi_tune_only_from_recent_owrx(
    *,
    now_ts: float,
    last_owrx_tune_ts: float,
    allow_owrx_driven_sync: bool,
    window_s: float = 0.9,
) -> bool:
    return (float(now_ts) - float(last_owrx_tune_ts or 0.0)) < float(window_s) and (not bool(allow_owrx_driven_sync))


def should_send_digi_tune_only(*, force: bool, freq_hz: int, last_freq_hz: int) -> bool:
    return bool(force) or int(freq_hz or 0) != int(last_freq_hz or 0)


def build_digi_tune_only_log_message(*, reason: str, force: bool, freq_hz: int) -> str:
    return (
        "digi_sync tune_only reason=%s force=%s freq=%s owrx_active=1"
        % (
            str(reason or ("force" if force else "state")),
            str(bool(force)),
            int(freq_hz or 0),
        )
    )


def parse_incoming_tune_frequency(raw_freq) -> int | None:
    try:
        if raw_freq is None:
            return None
        return int(float(raw_freq))
    except Exception:
        return None


def normalize_incoming_tune_mode(raw_mode) -> str:
    try:
        mode = str(raw_mode or "").strip().upper()
    except Exception:
        return ""
    if mode == "NFM":
        mode = "FM"
    if mode in ("AM", "FM", "USB", "LSB", "CW"):
        return mode
    return ""


def compute_tune_mismatch(
    *,
    incoming_freq: int | None,
    incoming_mode: str,
    app_freq: int,
    app_mode: str,
    tolerance_hz: int,
    min_freq_hz: int = 100_000,
) -> tuple[bool, bool]:
    freq_mismatch = bool(
        incoming_freq is not None
        and int(app_freq or 0) >= int(min_freq_hz or 0)
        and abs(int(incoming_freq) - int(app_freq or 0)) > int(tolerance_hz or 0)
    )
    mode_mismatch = bool(str(incoming_mode or "") and str(app_mode or "") and str(incoming_mode) != str(app_mode))
    return freq_mismatch, mode_mismatch


def compute_reverse_lock_frequency_match(
    *,
    raw_freq,
    app_freq: int,
    tolerance_hz: int,
    min_freq_hz: int = 100_000,
) -> tuple[bool, int | None]:
    try:
        if raw_freq is None:
            return False, None
        freq_val = int(raw_freq)
        if int(freq_val) < int(min_freq_hz or 0):
            return False, None
        freq_match = abs(int(freq_val) - int(app_freq or 0)) <= int(tolerance_hz or 0)
        return bool(freq_match), int(freq_val)
    except Exception:
        return False, None


def should_reassert_reverse_lock(*, now_ts: float, last_reassert_ts: float, min_interval_s: float = 0.45) -> bool:
    return (float(now_ts) - float(last_reassert_ts or 0.0)) >= float(min_interval_s)


def should_extend_reverse_lock_window(*, now_ts: float, lock_until_ts: float) -> bool:
    return float(now_ts) >= float(lock_until_ts or 0.0)


def next_reverse_lock_until(*, now_ts: float, extension_s: float = 8.0) -> float:
    return float(now_ts) + float(extension_s)


def should_ignore_tune_startup_window(*, now_ts: float, ignore_until_ts: float) -> bool:
    return float(now_ts) < float(ignore_until_ts or 0.0)


def should_ignore_tune_app_debounce(*, now_ts: float, last_app_tune_ts: float, debounce_s: float = 0.8) -> bool:
    return (float(now_ts) - float(last_app_tune_ts or 0.0)) < float(debounce_s)


def parse_pending_owrx_tune_frequency(
    raw_freq,
    *,
    min_hz: int = 100_000,
    max_hz: int = 2_000_000_000,
) -> int | None:
    try:
        value = int(raw_freq)
    except Exception:
        return None
    if int(min_hz or 0) <= int(value) <= int(max_hz or 0):
        return int(value)
    return None


def resolve_pending_owrx_mode(*, mode, modulation) -> str:
    mode_text = str(mode or "").strip().upper()
    if mode_text:
        return mode_text
    return normalize_incoming_tune_mode(modulation)


def compute_pending_owrx_apply_delay_ms(
    *,
    now_ts: float,
    last_apply_ts: float,
    normal_delay_ms: int = 120,
    fast_delay_ms: int = 40,
    idle_window_s: float = 0.5,
) -> int:
    if (float(now_ts) - float(last_apply_ts or 0.0)) > float(idle_window_s):
        return int(fast_delay_ms)
    return int(normal_delay_ms)


def build_reverse_lock_released_log(*, incoming_freq, app_freq: int, reason: str = "match") -> str:
    return "reverse_lock released reason=%s incoming_freq=%s app_freq=%s" % (
        str(reason or "match"),
        str(incoming_freq if incoming_freq is not None else "none"),
        int(app_freq or 0),
    )


def build_reverse_lock_ignored_log(*, incoming_freq, app_freq: int) -> str:
    return "tune ignored (reverse_lock_active) incoming_freq=%s app_freq=%s" % (
        str(incoming_freq if incoming_freq is not None else "none"),
        int(app_freq or 0),
    )


def build_digi_tune_ignored_log(
    *,
    source_view: str,
    incoming_freq,
    incoming_modulation,
    app_freq: int,
    app_mode: str,
    freq_mismatch: bool,
    mode_mismatch: bool,
) -> str:
    return (
        "tune ignored (digi_source_or_mode) src=%s freq=%s mod=%s app_freq=%s app_mode=%s mismatch_freq=%s mismatch_mode=%s"
        % (
            str(source_view or "unknown"),
            str(incoming_freq),
            str(incoming_modulation),
            int(app_freq or 0),
            str(app_mode or ""),
            str(bool(freq_mismatch)),
            str(bool(mode_mismatch)),
        )
    )


def should_send_owrx_pending_cat_update(*, now_ts: float, last_cat_ts: float, min_interval_s: float = 0.15) -> bool:
    return (float(now_ts) - float(last_cat_ts or 0.0)) >= float(min_interval_s)


def should_write_cat_from_owrx_pending(
    *,
    rx_audio_source: str,
    cat_connected: bool,
    cat_tx_active: bool,
) -> bool:
    src = str(rx_audio_source or "radio").strip().lower()
    return src != "sdr" and bool(cat_connected) and (not bool(cat_tx_active))


def is_supported_mode(mode: str) -> bool:
    return str(mode or "").strip().upper() in ("AM", "FM", "USB", "LSB", "CW")


def should_schedule_digi_mismatch_reassert(
    *,
    is_digi_source: bool,
    freq_mismatch: bool,
    mode_mismatch: bool,
    digi_backend_sync: bool,
) -> bool:
    return bool(is_digi_source) and bool(digi_backend_sync) and (bool(freq_mismatch) or bool(mode_mismatch))


def should_fire_reassert_now(*, now_ts: float, last_ts: float, min_interval_s: float = 2.0) -> bool:
    return (float(now_ts) - float(last_ts or 0.0)) > float(min_interval_s)


def is_valid_sync_frequency(freq_hz: int, min_hz: int = 100_000) -> bool:
    return int(freq_hz or 0) >= int(min_hz or 0)


def compute_digi_safe_sync_change_flags(
    *,
    profile: str,
    sdr_hint: str,
    step_hz: int,
    freq_hz: int,
    last_profile: str,
    last_sdr_hint: str,
    last_step_hz: int,
    last_freq_hz: int,
) -> tuple[bool, bool, bool]:
    profile_changed = bool(profile) and (
        str(profile or "") != str(last_profile or "")
        or str(sdr_hint or "") != str(last_sdr_hint or "")
    )
    step_changed = int(step_hz or 0) != int(last_step_hz or 0)
    tune_changed = int(freq_hz or 0) != int(last_freq_hz or 0)
    return profile_changed, step_changed, tune_changed


def should_skip_sync_by_interval(*, force: bool, now_ts: float, last_ts: float, min_interval_s: float) -> bool:
    return (not bool(force)) and (float(now_ts) - float(last_ts or 0.0)) < float(min_interval_s or 0.0)


def normalize_display_mode(mode: str, default: str = "USB") -> str:
    value = str(mode or default or "USB").upper().strip()
    if value not in ("AM", "FM", "USB", "LSB", "CW"):
        return str(default or "USB").upper()
    return value


def build_digi_profile_payload(*, profile: str, sdr_hint: str, key: str) -> dict:
    payload = {"type": "profile", "profile": str(profile or "")}
    sdr = str(sdr_hint or "").strip()
    if sdr:
        payload["sdr"] = sdr
    k = str(key or "").strip()
    if k:
        payload["key"] = k
    return payload


def build_digi_sync_log_message(
    *,
    sent: int,
    reason: str,
    force: bool,
    profile: str,
    step_hz: int,
    freq_hz: int,
    mode: str,
) -> str:
    return (
        "digi_sync sent=%s reason=%s force=%s profile=%s step=%s freq=%s mode=%s"
        % (
            int(sent),
            str(reason or ("force" if force else "state")),
            str(bool(force)),
            str(profile or ""),
            int(step_hz or 0),
            int(freq_hz or 0),
            str(mode or ""),
        )
    )


def digi_command_signature(payload: dict) -> tuple[str, str, float]:
    ptype = str((payload or {}).get("type") or "")
    if ptype == "profile":
        sig = "%s|%s|%s" % (
            str((payload or {}).get("profile") or ""),
            str((payload or {}).get("sdr") or ""),
            str((payload or {}).get("key") or ""),
        )
        return ptype, sig, 2.0
    if ptype == "step":
        return ptype, str(int((payload or {}).get("step_hz") or 0)), 0.9
    if ptype == "tune":
        return ptype, str(int((payload or {}).get("frequency") or 0)), 0.6
    return ptype, "", 0.0


def should_drop_digi_duplicate_command(
    *,
    signature: str,
    min_interval_s: float,
    now_ts: float,
    last_signature: str,
    last_ts: float,
) -> bool:
    sig = str(signature or "")
    if not sig:
        return False
    return sig == str(last_signature or "") and (float(now_ts) - float(last_ts or 0.0)) < float(min_interval_s or 0.0)


def should_hard_mute_owrx_sink(rx_audio_source: str) -> bool:
    return str(rx_audio_source or "radio").strip().lower() != "sdr"


def should_enable_owrx_sdr_anr(
    *,
    has_audio: bool,
    rx_audio_source: str,
    anr_enabled: bool,
    sdr_anr_supported: bool,
) -> bool:
    return (
        bool(has_audio)
        and str(rx_audio_source or "radio").strip().lower() == "sdr"
        and bool(anr_enabled)
        and bool(sdr_anr_supported)
    )


def compute_owrx_startup_locks(monotonic_now: float) -> tuple[float, bool, float]:
    now = float(monotonic_now or 0.0)
    return now + 10.0, True, now + 35.0


def compute_owrx_startup_band(*, inferred_band: str, current_band: str) -> str:
    return str(inferred_band or current_band or "").strip()


def should_send_startup_profile(startup_band: str) -> bool:
    return bool(str(startup_band or "").strip())


def owrx_startup_reassert_delays_ms() -> tuple[int, int]:
    return 900, 1100


def should_send_owrx_spots(spots_initialized: bool) -> bool:
    return bool(spots_initialized)


def build_owrx_startup_log_message(
    *,
    host: str,
    port: int,
    spider_port: int,
    band: str,
    frequency_hz: int,
    mode: str,
) -> str:
    return (
        "owrx_open startup host=%s port=%s spider_port=%s band=%s freq=%s mode=%s"
        % (
            str(host),
            int(port),
            int(spider_port),
            str(band or ""),
            int(frequency_hz or 0),
            str(mode or ""),
        )
    )


def terminate_process_tree(
    *,
    process,
    force: bool = False,
    os_module=os,
    signal_module=signal,
    posix_final_wait_s: float = 0.4,
) -> None:
    if process is None:
        return
    try:
        if process.poll() is not None:
            return
    except Exception:
        pass
    try:
        process.wait(timeout=0.5 if force else 1.5)
        return
    except Exception:
        pass
    pid = int(getattr(process, "pid", 0) or 0)
    if pid > 1 and getattr(os_module, "name", "") == "posix":
        try:
            os_module.killpg(os_module.getpgid(pid), signal_module.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
        try:
            process.wait(timeout=0.8 if force else 1.5)
            return
        except Exception:
            pass
        try:
            os_module.killpg(os_module.getpgid(pid), signal_module.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        try:
            process.wait(timeout=float(posix_final_wait_s))
        except Exception:
            pass
        return
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=0.8 if force else 1.5)
        return
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass
