from __future__ import annotations

import numpy as np


def convert_channels(data: bytes, src_channels: int, dst_channels: int) -> bytes:
    if src_channels == dst_channels:
        return data

    samples = np.frombuffer(data, dtype=np.int16)

    if src_channels == 1:
        samples = np.repeat(samples[:, np.newaxis], dst_channels, axis=1).flatten()
    elif src_channels == 2 and dst_channels == 1:
        samples = samples.reshape((-1, 2)).mean(axis=1).astype(np.int16)
    elif src_channels == 2 and dst_channels > 2:
        samples = np.tile(samples.reshape((-1, 2)), dst_channels // 2).flatten()
    elif src_channels > 2 and dst_channels == 2:
        samples = samples.reshape((-1, src_channels))[:, :2].flatten()
    else:
        raise ValueError("Unsupported channel conversion")

    return samples.tobytes()


def apply_volume(data: bytes, volume: float) -> bytes:
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    try:
        gain = float(volume)
    except (TypeError, ValueError):
        gain = 0.0
    if not np.isfinite(gain):
        gain = 0.0
    scaled = samples * max(0.0, gain)
    np.clip(scaled, -32768.0, 32767.0, out=scaled)
    return scaled.astype(np.int16).tobytes()


def generate_sine_chunk(
    phase: float, step: float, frame_size: int, level: float
) -> tuple[np.ndarray, float]:
    """Un bloque de onda seno de ``frame_size`` muestras a ``level`` de
    amplitud (usado por el tono de prueba TX), y la fase resultante
    (envuelta a ``[0, 2π)``) para la siguiente llamada."""
    n = np.arange(frame_size, dtype=np.float32)
    chunk = np.sin(phase + (step * n)).astype(np.float32) * level
    new_phase = float((phase + (step * frame_size)) % (2.0 * np.pi))
    return chunk, new_phase


def prepare_tx_radio_audio(
    data: bytes,
    src_channels: int,
    dst_channels: int,
) -> tuple[bytes, int]:
    """TX voice should leave as mono-compatible audio before hitting the radio output."""
    if src_channels > 1:
        # Avoid averaging phase-shifted channels for TX voice.
        samples = np.frombuffer(data, dtype=np.int16)
        if samples.size >= src_channels:
            frames = samples[: (samples.size - (samples.size % src_channels))].reshape(
                (-1, src_channels)
            )
            data = frames[:, 0].astype(np.int16).tobytes()
        else:
            data = convert_channels(data, src_channels, 1)
        src_channels = 1
    if src_channels != dst_channels:
        data = convert_channels(data, src_channels, dst_channels)
        src_channels = dst_channels
    return data, src_channels
