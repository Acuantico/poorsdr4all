from __future__ import annotations

import re

import numpy as np


def parse_sample_spec(sample_spec: object) -> tuple[int, int]:
    channels = 0
    rate = 0
    if isinstance(sample_spec, dict):
        channels = int(sample_spec.get("channels") or 0)
        rate = int(sample_spec.get("rate") or 0)
    elif isinstance(sample_spec, str):
        match_channels = re.search(r"(\d+)ch", sample_spec)
        match_rate = re.search(r"(\d+)Hz", sample_spec)
        if match_channels:
            channels = int(match_channels.group(1))
        if match_rate:
            rate = int(match_rate.group(1))
    return channels, rate


def tx_frame_size_for_rate(sample_rate: int) -> int:
    """Return ~20 ms frame size for the given TX sample rate."""
    try:
        rate = int(sample_rate or 48000)
    except Exception:
        rate = 48000
    if rate <= 0:
        rate = 48000
    return max(120, int(round(float(rate) * 0.02)))


def fade_in_pcm16(data: bytes, channels: int, fade_ms: int, rate: int = 48000) -> bytes:
    if not data:
        return data
    try:
        ch = max(1, int(channels))
        ms = max(0, int(fade_ms))
        if ms <= 0:
            return data
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32, copy=True)
        if samples.size <= 0:
            return data
        total_frames = samples.size // ch
        fade_frames = min(total_frames, max(1, int(rate * ms / 1000.0)))
        if fade_frames <= 0:
            return data
        ramp = np.linspace(0.0, 1.0, fade_frames, dtype=np.float32)
        for i in range(fade_frames):
            start = i * ch
            end = start + ch
            samples[start:end] *= ramp[i]
        return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
    except Exception:
        return data


def soft_repeat_block_pcm16(data: bytes, decay: float = 0.96) -> bytes:
    """Return a softened copy of the last valid block to mask short underruns."""
    if not data:
        return data
    try:
        d = float(decay)
        if d <= 0.0 or d > 1.0:
            d = 0.96
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if arr.size == 0:
            return data
        arr *= d
        return np.clip(arr, -32768, 32767).astype(np.int16).tobytes()
    except Exception:
        return data


def verificar_datos(data: bytes, expected_channels: int) -> None:
    if len(data) // 2 % expected_channels != 0:
        raise ValueError(
            f"La longitud de los datos {len(data)} no es divisible por {expected_channels} canales"
        )


def pad_or_truncate_frame(data: bytes, expected_bytes: int) -> bytes:
    """Ajusta ``data`` a ``expected_bytes``: rellena con ceros o recorta.

    Compartido por las ramas Linux y Windows/fallback del motor RX/TX en
    vivo: el cálculo es plataforma-agnóstico.
    """
    if len(data) == expected_bytes:
        return data
    if len(data) < expected_bytes:
        return data + (b"\x00" * (expected_bytes - len(data)))
    return data[:expected_bytes]


def resample_linear(data: np.ndarray, src_rate: int, target_rate: int) -> np.ndarray:
    """Interpolación lineal simple (sin antialiasing).

    Devuelve ``data`` sin cambios si las tasas coinciden, ``src_rate <= 0``,
    o si la interpolación falla por cualquier motivo (mismo comportamiento
    "silencioso" que tenía el código original inline).
    """
    if src_rate == target_rate or src_rate <= 0:
        return data
    try:
        ratio = float(target_rate) / float(src_rate)
        out_len = int(len(data) * ratio)
        x_old = np.linspace(0, 1, len(data), endpoint=False)
        x_new = np.linspace(0, 1, out_len, endpoint=False)
        return np.interp(x_new, x_old, data).astype(np.float32)
    except Exception:
        return data


def frame_from_chunks(
    chunks: list[np.ndarray], frame_size: int
) -> tuple[np.ndarray, np.ndarray | None]:
    """Concatena ``chunks`` (ya resampleados) en un frame de ``frame_size``.

    Rellena con ceros si falta; si sobra, recorta y devuelve el remanente
    (``None`` si no sobra nada, o si ``chunks`` está vacío).
    """
    if not chunks:
        return np.zeros(frame_size, dtype=np.float32), None
    samples = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
    if len(samples) < frame_size:
        pad = np.zeros(frame_size - len(samples), dtype=np.float32)
        return np.concatenate([samples, pad]), None
    if len(samples) > frame_size:
        leftover = samples[frame_size:]
        return samples[:frame_size], (leftover if leftover.size else None)
    return samples, None
