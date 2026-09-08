from __future__ import annotations

from typing import Callable


def rx_chain_gui(
    data: bytes,
    channels: int,
    sample_rate: int,
    frame_size: int,
    *,
    context: str,
    volume: float,
    apply_output_boost: bool,
    apply_user_gain: bool,
    gain_mode: str,
    web_rx_gain: float,
    rx_cleanup_fn: Callable[[bytes, int, int, bool], bytes],
    process_rx_ctx_fn: Callable[[str, bytes, int, int, int], bytes],
    apply_volume_fn: Callable[[bytes, float], bytes],
    apply_auto_gain_fn: Callable[[bytes], bytes],
    apply_manual_gain_fn: Callable[[bytes], bytes],
    apply_gain_extra_rx_fn: Callable[[bytes], bytes],
    reinforce_pc_output_fn: Callable[[bytes], bytes],
) -> bytes:
    data = rx_cleanup_fn(data, channels, sample_rate, True)
    data = process_rx_ctx_fn(context, data, sample_rate, channels, frame_size)
    data = apply_volume_fn(data, volume)
    if apply_user_gain and gain_mode == "auto":
        data = apply_auto_gain_fn(data)
    if apply_output_boost:
        data = apply_gain_extra_rx_fn(data)
    if apply_user_gain and gain_mode == "manual":
        data = apply_manual_gain_fn(data)
    if apply_output_boost:
        data = reinforce_pc_output_fn(data)
    return data


def rx_chain_web(
    data: bytes,
    channels: int,
    sample_rate: int,
    frame_size: int,
    *,
    context: str,
    volume: float,
    apply_user_gain: bool,
    gain_mode: str,
    web_rx_gain: float,
    rx_cleanup_fn: Callable[[bytes, int, int, bool], bytes],
    process_rx_ctx_fn: Callable[[str, bytes, int, int, int], bytes],
    apply_volume_fn: Callable[[bytes, float], bytes],
    apply_auto_gain_fn: Callable[[bytes], bytes],
    apply_manual_gain_fn: Callable[[bytes], bytes],
    apply_factor_lineal_fn: Callable[[bytes, float], bytes],
) -> bytes:
    data = rx_cleanup_fn(data, channels, sample_rate, False)
    data = process_rx_ctx_fn(context, data, sample_rate, channels, frame_size)
    data = apply_volume_fn(data, volume)
    if apply_user_gain and gain_mode == "auto":
        data = apply_auto_gain_fn(data)
    if apply_user_gain and gain_mode == "manual":
        data = apply_manual_gain_fn(data)
    if abs(web_rx_gain - 1.0) > 1e-3:
        data = apply_factor_lineal_fn(data, web_rx_gain)
    return data


def sdr_chain_light_gui(
    data: bytes,
    volume: float,
    *,
    output_post_gain: float,
    apply_volume_fn: Callable[[bytes, float], bytes],
    apply_factor_lineal_fn: Callable[[bytes, float], bytes],
) -> bytes:
    """Cadena RX ligera del SDR cuando el ANR está desactivado (baja latencia)."""
    out = apply_volume_fn(data, volume)
    if abs(output_post_gain - 1.0) > 1e-3:
        out = apply_factor_lineal_fn(out, output_post_gain)
    return out


def sdr_chain_light_web(
    data: bytes,
    volume: float,
    *,
    web_rx_gain: float,
    apply_volume_fn: Callable[[bytes, float], bytes],
    apply_factor_lineal_fn: Callable[[bytes, float], bytes],
) -> bytes:
    out = apply_volume_fn(data, volume)
    if abs(web_rx_gain - 1.0) > 1e-3:
        out = apply_factor_lineal_fn(out, web_rx_gain)
    return out
