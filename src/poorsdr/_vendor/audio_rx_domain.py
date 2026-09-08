from __future__ import annotations

from typing import Callable


def highpass(samples, cutoff_hz: float, sample_rate: int, rx_hpf_state: dict):
    import numpy as np

    if cutoff_hz <= 0.0 or sample_rate <= 0:
        return samples
    alpha = float(np.exp(-2.0 * np.pi * cutoff_hz / sample_rate))
    prev_x = rx_hpf_state.get("prev_x")
    prev_y = rx_hpf_state.get("prev_y")
    if prev_x is None or prev_y is None or prev_x.shape != samples.shape or prev_y.shape != samples.shape:
        prev_x = np.zeros_like(samples)
        prev_y = np.zeros_like(samples)
    y = alpha * (prev_y + samples - prev_x)
    rx_hpf_state["prev_x"] = samples
    rx_hpf_state["prev_y"] = y
    return y


def rx_cleanup(
    data: bytes,
    channels: int,
    sample_rate: int,
    *,
    gate_enabled: bool,
    rx_hpf_cutoff: float,
    rx_gate_threshold: float,
    rx_hpf_state: dict,
) -> bytes:
    import numpy as np

    if not data:
        return data
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    frames = samples.reshape((-1, channels))
    frames = highpass(frames, rx_hpf_cutoff, sample_rate, rx_hpf_state)
    rms = float(np.sqrt(np.mean(frames * frames))) if frames.size else 0.0
    gate = float(rx_gate_threshold) / 32768.0 if gate_enabled else 0.0
    if gate > 0.0 and rms < gate:
        frames[:] = 0.0
    frames = np.clip(frames, -1.0, 1.0)
    return (frames * 32767.0).astype(np.int16).tobytes()


def apply_rx_frontend(
    data: bytes,
    *,
    rx_capture_gain: float,
    rx_hum_reduction: bool,
    attenuate_input_radio: Callable[[bytes], bytes],
) -> bytes:
    import numpy as np

    if not data:
        return data
    if rx_capture_gain != 1.0 or rx_hum_reduction:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if rx_hum_reduction:
            samples -= np.mean(samples)
        if rx_capture_gain != 1.0:
            samples *= rx_capture_gain
        np.clip(samples, -32768, 32767, out=samples)
        data = samples.astype(np.int16).tobytes()
    return attenuate_input_radio(data)
