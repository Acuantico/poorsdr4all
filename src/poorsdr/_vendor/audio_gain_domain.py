from __future__ import annotations

import numpy as np


def aplicar_factor_lineal(data: bytes, factor: float) -> bytes:
    if factor == 1.0:
        return data
    array = np.frombuffer(data, dtype=np.int16).astype(np.int32)
    array = array * factor
    np.clip(array, -32768, 32767, out=array)
    return array.astype(np.int16).tobytes()


def atenuar_entrada_radio(data: bytes, radio_input_attenuation: float) -> bytes:
    return aplicar_factor_lineal(data, radio_input_attenuation)


def aplicar_gain_extra_rx(data: bytes, extra_rx_gain: float) -> bytes:
    return aplicar_factor_lineal(data, extra_rx_gain)


def reforzar_salida_pc(data: bytes, output_post_gain: float) -> bytes:
    return aplicar_factor_lineal(data, output_post_gain)


def aplicar_gain_manual(data: bytes, manual_gain: float) -> bytes:
    if abs(manual_gain - 1.0) < 1e-3:
        return data
    return aplicar_factor_lineal(data, manual_gain)


def aplicar_auto_gain(
    data: bytes,
    *,
    state: dict,
    target: float,
    min_gain: float,
    max_gain: float,
    attack: float,
    release: float,
) -> bytes:
    """AGC de ventana logarítmica (ataque/caída distintos) sobre PCM16.

    ``state`` guarda la ganancia entre llamadas (clave ``"gain"``, se crea a
    1.0 si no existe) — reemplaza al global ``_agc_gain`` de ``audio.py``,
    para que esto sea una función pura y testeable sin depender de estado de
    módulo. El llamador es responsable de resetear ``state["gain"] = 1.0``
    cuando corresponda (cambio de modo de ganancia, parada de RX/TX...).

    Un AGC que solo mira el RMS medio no sabe nada del factor de cresta de
    la señal: aplicar la ganancia que pide el objetivo de RMS sin más deja
    que un pico puntual bastante por encima de la media reciente (típico
    de voz en SSB) se recorte en seco contra el rango de int16, lo que se
    oye como distorsión. Por eso incluye un limitador de pico sin mirar
    hacia delante: calcula el pico real de este bloque ya escalado y, si se
    pasaría de rango, reduce solo la salida de este bloque lo justo para no
    recortar — ``state["gain"]`` guarda la ganancia que pide el propio AGC
    sin tocar, así el limitador no hace que el AGC persiga su propia
    corrección de un bloque para otro.
    """
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return data
    rms = float(np.sqrt(np.mean(samples * samples)))
    if not np.isfinite(rms) or rms < 1.0:
        target_gain = max_gain
    else:
        target_gain = target / rms
    target_gain = float(np.clip(target_gain, min_gain, max_gain))

    current = float(np.clip(state.get("gain", 1.0), min_gain, max_gain))
    desired = max(target_gain, min_gain)
    log_current = float(np.log(max(current, 1e-6)))
    log_desired = float(np.log(max(desired, 1e-6)))
    alpha = attack if desired > current else release
    log_new = log_current + (log_desired - log_current) * alpha
    new_gain = float(np.clip(np.exp(log_new), min_gain, max_gain))
    state["gain"] = new_gain

    scaled = samples * new_gain
    peak = float(np.max(np.abs(scaled))) if scaled.size else 0.0
    if peak > 32767.0:
        scaled = scaled * (32767.0 / peak)
    np.clip(scaled, -32768, 32767, out=scaled)
    return scaled.astype(np.int16).tobytes()
