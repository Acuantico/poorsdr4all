from __future__ import annotations

import time

import numpy as np


def tx_diag_metrics(data: bytes, channels: int, sample_rate: int) -> str:
    try:
        ch = max(1, int(channels or 1))
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if arr.size <= 0:
            return "empty=1"
        if arr.size % ch != 0:
            arr = arr[: arr.size - (arr.size % ch)]
        if arr.size <= 0:
            return "empty=1"
        frames = arr.reshape((-1, ch))
        mono = frames.mean(axis=1)
        norm = mono / 32768.0
        rms = float(np.sqrt(np.mean(norm * norm)))
        peak = float(np.max(np.abs(norm))) if norm.size else 0.0
        if mono.size > 2:
            zcr = float(np.mean((mono[:-1] * mono[1:]) < 0.0))
            spec = np.abs(np.fft.rfft(norm)) ** 2
            total = float(np.sum(spec)) + 1e-12
            dom = float(np.max(spec) / total) if spec.size else 0.0
            spec_eps = spec + 1e-18
            flat = float(np.exp(np.mean(np.log(spec_eps))) / np.mean(spec_eps))
            block = max(40, min(240, int(mono.size // 8) or 40))
            usable = int((mono.size // block) * block)
            if usable >= (block * 2):
                m = norm[:usable].reshape((-1, block))
                brms = np.sqrt(np.mean(m * m, axis=1))
                mod = float(np.std(brms) / (np.mean(brms) + 1e-12))
            else:
                mod = 0.0
        else:
            zcr = 0.0
            dom = 0.0
            flat = 0.0
            mod = 0.0
        return (
            f"rms={rms:.6f} peak={peak:.6f} zcr={zcr:.6f} "
            f"dom={dom:.6f} flat={flat:.6f} mod={mod:.6f} "
            f"n={int(norm.size)} sr={int(sample_rate)} ch={int(ch)}"
        )
    except Exception as exc:
        return f"diag_err={exc}"


def rx_meter_ballistics(data: bytes, channels: int, prev_dbfs: float) -> float | None:
    """RMS→dBFS del S-meter RX, con ataque rápido (0.30) y liberación lenta (0.10).

    ``None`` si no hay datos válidos que medir (buffer vacío, no silencio de
    audio) — el llamador debe conservar el dBFS anterior en ese caso, igual
    que hacía el código original al no tocar el global.
    """
    if not data:
        return None
    try:
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        ch = max(1, int(channels or 1))
        if ch > 1 and arr.size >= ch:
            arr = arr.reshape((-1, ch)).mean(axis=1)
        if arr.size <= 0:
            return None
        rms = float(np.sqrt(np.mean(arr * arr)))
        dbfs = float(20.0 * np.log10((rms / 32768.0) + 1e-12))
        prev = float(prev_dbfs or -120.0)
        # Stable ballistics: fast attack, slower release.
        alpha = 0.30 if dbfs > prev else 0.10
        return float((1.0 - alpha) * prev + (alpha * dbfs))
    except Exception:
        return None


def tx_diag_gate_snapshot(tx_gate_state: dict, *, now: float | None = None) -> str:
    try:
        now_value = time.monotonic() if now is None else float(now)
        env = float(tx_gate_state.get("env", 0.0) or 0.0)
        hold_left = max(0.0, float(tx_gate_state.get("hold_until", 0.0) or 0.0) - now_value)
        voice_left = max(
            0.0, float(tx_gate_state.get("voice_until", 0.0) or 0.0) - now_value
        )
        noise_rms = float(tx_gate_state.get("noise_rms", 0.0) or 0.0)
        noise_peak = float(tx_gate_state.get("noise_peak", 0.0) or 0.0)
        return (
            f"env={env:.4f} hold_left={hold_left:.3f} voice_left={voice_left:.3f} "
            f"noise_rms={noise_rms:.6f} noise_peak={noise_peak:.6f}"
        )
    except Exception as exc:
        return f"gate_err={exc}"
