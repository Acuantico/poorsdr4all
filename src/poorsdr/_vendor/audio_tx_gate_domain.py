from __future__ import annotations

import time
from typing import Callable


def tx_source_is_easyeffects(source_name: object) -> bool:
    normalized = str(source_name or "").strip().lower()
    return "easyeffects" in normalized and "source" in normalized


def tx_use_external_dsp_passthrough(
    capture_mode: str,
    source_name: object,
    injected_present: bool,
    *,
    external_dsp_bypass: bool,
) -> bool:
    if not external_dsp_bypass:
        return False
    if str(capture_mode or "").strip().lower() != "mic":
        return False
    if injected_present:
        return False
    return tx_source_is_easyeffects(source_name)


def tx_output_signal_is_ready(
    output_rms: float,
    signal_ts: float,
    since_ts: float,
    now: float,
    *,
    window_s: float = 0.35,
    min_rms: float = 0.01,
) -> bool:
    return bool(
        float(output_rms or 0.0) >= float(min_rms)
        and float(signal_ts or 0.0) >= float(since_ts)
        and (float(now) - float(signal_ts or 0.0)) <= max(0.05, float(window_s))
    )


def reset_tx_gate_state(
    tx_gate_state: dict,
    tx_hpf_state: dict,
    tx_lpf_state: dict,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    tx_gate_state["env"] = 0.0
    tx_gate_state["hold_until"] = 0.0
    tx_gate_state["voice_until"] = 0.0
    tx_gate_state["noise_rms"] = 0.0
    tx_gate_state["noise_peak"] = 0.0
    tx_gate_state["start_ts"] = monotonic()
    tx_hpf_state["x_prev"] = None
    tx_hpf_state["y_prev"] = None
    tx_lpf_state["y_prev"] = None


def _tx_highpass(samples, cutoff_hz: float, sample_rate: int, tx_hpf_state: dict):
    import numpy as np

    if cutoff_hz <= 0.0 or sample_rate <= 0:
        return samples
    alpha = float(np.exp(-2.0 * np.pi * cutoff_hz / float(sample_rate)))
    out = np.empty_like(samples, dtype=np.float32)
    channels = int(samples.shape[1]) if samples.ndim > 1 else 1
    x_prev = tx_hpf_state.get("x_prev")
    y_prev = tx_hpf_state.get("y_prev")
    if x_prev is None or y_prev is None or np.size(x_prev) != channels or np.size(y_prev) != channels:
        x_prev = np.zeros(channels, dtype=np.float32)
        y_prev = np.zeros(channels, dtype=np.float32)
    else:
        x_prev = np.asarray(x_prev, dtype=np.float32).reshape((channels,))
        y_prev = np.asarray(y_prev, dtype=np.float32).reshape((channels,))
    for i in range(int(samples.shape[0])):
        x = samples[i]
        y = alpha * (y_prev + x - x_prev)
        out[i] = y
        x_prev = x
        y_prev = y
    tx_hpf_state["x_prev"] = x_prev.copy()
    tx_hpf_state["y_prev"] = y_prev.copy()
    return out


def _tx_lowpass(samples, cutoff_hz: float, sample_rate: int, tx_lpf_state: dict):
    import numpy as np

    if cutoff_hz <= 0.0 or sample_rate <= 0:
        return samples
    alpha = float(np.exp(-2.0 * np.pi * cutoff_hz / float(sample_rate)))
    out = np.empty_like(samples, dtype=np.float32)
    channels = int(samples.shape[1]) if samples.ndim > 1 else 1
    y_prev = tx_lpf_state.get("y_prev")
    if y_prev is None or np.size(y_prev) != channels:
        y_prev = np.zeros(channels, dtype=np.float32)
    else:
        y_prev = np.asarray(y_prev, dtype=np.float32).reshape((channels,))
    one_minus_alpha = float(1.0 - alpha)
    for i in range(int(samples.shape[0])):
        x = samples[i]
        y = one_minus_alpha * x + alpha * y_prev
        out[i] = y
        y_prev = y
    tx_lpf_state["y_prev"] = y_prev.copy()
    return out


def tx_cleanup(
    data: bytes,
    channels: int,
    sample_rate: int,
    *,
    bypass_gate: bool,
    bypass_all_processing: bool,
    tx_gate_state: dict,
    tx_hpf_state: dict,
    tx_lpf_state: dict,
    cfg: dict,
) -> bytes:
    import numpy as np

    if not data or channels <= 0 or sample_rate <= 0:
        return data
    if bypass_all_processing:
        return data
    if not bool(cfg.get("TX_GATE_ENABLED", True)):
        bypass_gate = True

    frames = np.frombuffer(data, dtype=np.int16).astype(np.float32).reshape((-1, channels))
    if frames.size == 0:
        return data
    norm = frames / 32768.0
    norm = _tx_highpass(norm, float(cfg.get("TX_HPF_CUTOFF", 120.0)), sample_rate, tx_hpf_state)
    norm = _tx_lowpass(norm, float(cfg.get("TX_LPF_CUTOFF", 3300.0)), sample_rate, tx_lpf_state)
    if bypass_gate:
        out = np.clip(norm * 32768.0, -32768, 32767).astype(np.int16)
        return out.tobytes()
    rms = float(np.sqrt(np.mean(norm * norm)))
    peak = float(np.max(np.abs(norm))) if norm.size else 0.0

    static_threshold = max(0.0, float(cfg.get("TX_GATE_THRESHOLD", 420.0)) / 32768.0)
    dynamic_threshold = static_threshold
    dynamic_peak_threshold = max(0.0, float(cfg.get("TX_GATE_OPEN_PEAK_OFFSET", 420.0)) / 32768.0)
    now = time.monotonic()
    cal_s = max(0.0, float(cfg.get("TX_GATE_CALIBRATE_MS", 320.0)) / 1000.0)
    start_ts = float(tx_gate_state.get("start_ts", 0.0) or 0.0)
    in_calibration = (start_ts <= 0.0) or ((now - start_ts) < cal_s)

    if in_calibration:
        track_s = max(0.03, float(cfg.get("TX_GATE_NOISE_TRACK_S", 0.8)) * 0.35)
        frame_dt = max(1e-4, float(norm.shape[0]) / float(sample_rate))
        alpha_n = 1.0 - float(np.exp(-frame_dt / track_s))
        nr = float(tx_gate_state.get("noise_rms", 0.0) or 0.0)
        npk = float(tx_gate_state.get("noise_peak", 0.0) or 0.0)
        tx_gate_state["noise_rms"] = nr + (rms - nr) * alpha_n
        tx_gate_state["noise_peak"] = npk + (peak - npk) * alpha_n
        return (np.zeros_like(frames, dtype=np.int16)).tobytes()

    if bool(cfg.get("TX_GATE_ADAPTIVE", True)):
        noise = float(tx_gate_state.get("noise_rms", 0.0) or 0.0)
        noise_peak = float(tx_gate_state.get("noise_peak", 0.0) or 0.0)
        if noise <= 0.0:
            noise = rms
        if noise_peak <= 0.0:
            noise_peak = peak
        if rms <= max(static_threshold * 1.5, noise * 1.35 + 1e-6):
            track_s = max(0.05, float(cfg.get("TX_GATE_NOISE_TRACK_S", 0.8)))
            frame_dt = max(1e-4, float(norm.shape[0]) / float(sample_rate))
            alpha_n = 1.0 - float(np.exp(-frame_dt / track_s))
            noise = noise + (rms - noise) * alpha_n
            noise_peak = noise_peak + (peak - noise_peak) * alpha_n
            tx_gate_state["noise_rms"] = max(0.0, float(noise))
            tx_gate_state["noise_peak"] = max(0.0, float(noise_peak))
        open_offset = max(0.0, float(cfg.get("TX_GATE_OPEN_OFFSET", 260.0)) / 32768.0)
        open_peak_offset = max(0.0, float(cfg.get("TX_GATE_OPEN_PEAK_OFFSET", 420.0)) / 32768.0)
        dynamic_threshold = max(
            static_threshold,
            float(tx_gate_state.get("noise_rms", 0.0) or 0.0)
            * max(1.05, float(cfg.get("TX_GATE_OPEN_RATIO", 2.2)))
            + open_offset,
        )
        dynamic_peak_threshold = max(
            open_peak_offset,
            float(tx_gate_state.get("noise_peak", 0.0) or 0.0)
            * max(1.0, float(cfg.get("TX_GATE_OPEN_PEAK_RATIO", 1.8)))
            + open_peak_offset,
        )

    hold_s = max(0.0, float(cfg.get("TX_GATE_HOLD_MS", 40.0)) / 1000.0)
    mono = norm.mean(axis=1) if channels > 1 else norm[:, 0]
    if mono.size > 2:
        zcr = float(np.mean((mono[:-1] * mono[1:]) < 0.0))
        spec = np.abs(np.fft.rfft(mono)) ** 2
        freqs = np.fft.rfftfreq(mono.size, d=(1.0 / float(sample_rate)))
        voice_mask = (freqs >= 250.0) & (freqs <= 3400.0)
        hum_mask = (freqs >= 20.0) & (freqs <= 180.0)
        voice_power = float(np.sum(spec[voice_mask])) if np.any(voice_mask) else 0.0
        hum_power = float(np.sum(spec[hum_mask])) if np.any(hum_mask) else 0.0
        band_ratio = voice_power / max(hum_power, 1e-12)
        total_power = float(np.sum(spec)) + 1e-12
        dom_ratio = float(np.max(spec) / total_power) if spec.size else 0.0
        spec_eps = spec + 1e-18
        flatness = float(np.exp(np.mean(np.log(spec_eps))) / np.mean(spec_eps))
        block = max(40, min(240, int(mono.size // 8) or 40))
        usable = int((mono.size // block) * block)
        if usable >= (block * 2):
            m = mono[:usable].reshape((-1, block))
            brms = np.sqrt(np.mean(m * m, axis=1))
            modulation = float(np.std(brms) / (np.mean(brms) + 1e-12))
        else:
            modulation = 0.0
    else:
        zcr = 0.0
        band_ratio = 0.0
        dom_ratio = 1.0
        flatness = 0.0
        modulation = 0.0
    crest = peak / max(rms, 1e-6)
    crest_ok = crest >= max(1.0, float(cfg.get("TX_GATE_MIN_CREST", 1.9)))
    zcr_ok = zcr >= max(0.0, float(cfg.get("TX_VOICE_MIN_ZCR", 0.006)))
    band_ok = band_ratio >= max(0.0, float(cfg.get("TX_VOICE_MIN_BAND_RATIO", 1.25)))
    flat_ok = flatness >= max(0.0, float(cfg.get("TX_VOICE_MIN_FLATNESS", 0.055)))
    tonal_like = dom_ratio >= max(0.25, min(0.98, float(cfg.get("TX_TONAL_MAX_DOMINANCE", 0.70))))
    hum_like = (
        bool(cfg.get("TX_HUM_REJECT_ENABLED", True))
        and (dom_ratio >= max(0.25, min(0.98, float(cfg.get("TX_HUM_DOMINANCE_MIN", 0.52)))))
        and (zcr <= max(0.0, float(cfg.get("TX_HUM_MAX_ZCR", 0.018))))
        and (flatness <= max(0.0, float(cfg.get("TX_HUM_MAX_FLATNESS", 0.0035))))
        and (modulation <= max(0.0, float(cfg.get("TX_HUM_MAX_MODULATION", 0.08))))
    )
    score = int(crest_ok) + int(zcr_ok) + int(band_ok) + int(flat_ok)
    mod_ok = modulation >= max(0.0, float(cfg.get("TX_VOICE_MIN_MODULATION", 0.11)))
    voice_like = (score >= 2) and (mod_ok or (not tonal_like and zcr_ok))
    if not voice_like and (rms >= (dynamic_threshold * 1.65)) and (
        peak >= (dynamic_peak_threshold * 1.25)
    ):
        voice_like = (not tonal_like) and (
            modulation >= (max(0.0, float(cfg.get("TX_VOICE_MIN_MODULATION", 0.11)) * 0.65))
        )
    if hum_like:
        voice_like = False
    open_now = (rms >= dynamic_threshold) and (peak >= dynamic_peak_threshold) and voice_like

    if open_now:
        tx_gate_state["hold_until"] = now + hold_s
        target = 1.0
    else:
        target = 1.0 if now < float(tx_gate_state.get("hold_until", 0.0) or 0.0) else 0.0

    if hum_like:
        tx_gate_state["hold_until"] = 0.0
        target = 0.0
        if bool(cfg.get("TX_HUM_HARD_RESET", True)):
            tx_gate_state["env"] = 0.0
            tx_gate_state["voice_until"] = 0.0
            return (np.zeros_like(frames, dtype=np.int16)).tobytes()

    if bool(cfg.get("TX_HARD_MUTE_WHEN_NO_VOICE", True)):
        hard_hold_s = max(0.0, float(cfg.get("TX_HARD_MUTE_HOLD_MS", 30.0)) / 1000.0)
        if open_now:
            tx_gate_state["voice_until"] = now + hard_hold_s
        if now >= float(tx_gate_state.get("voice_until", 0.0) or 0.0):
            tx_gate_state["env"] = 0.0
            tx_gate_state["hold_until"] = 0.0
            return (np.zeros_like(frames, dtype=np.int16)).tobytes()

    frame_dt = max(1e-4, float(norm.shape[0]) / float(sample_rate))
    attack_s = max(0.001, float(cfg.get("TX_GATE_ATTACK_MS", 8.0)) / 1000.0)
    release_s = max(0.001, float(cfg.get("TX_GATE_RELEASE_MS", 85.0)) / 1000.0)
    if target >= tx_gate_state["env"]:
        alpha = 1.0 - float(np.exp(-frame_dt / attack_s))
    else:
        alpha = 1.0 - float(np.exp(-frame_dt / release_s))

    env = float(tx_gate_state["env"]) + (target - float(tx_gate_state["env"])) * alpha
    env = float(np.clip(env, 0.0, 1.0))
    if env < 1e-4:
        env = 0.0
    tx_gate_state["env"] = env

    floor = float(np.clip(float(cfg.get("TX_GATE_FLOOR", 0.0)), 0.0, 1.0))
    gain = floor + (1.0 - floor) * env
    if gain <= 0.0:
        return (np.zeros_like(frames, dtype=np.int16)).tobytes()

    out = np.clip((norm * gain) * 32768.0, -32768, 32767).astype(np.int16)
    return out.tobytes()
