try:
    import pyaudiowpatch as pyaudio  # WASAPI loopback support if available
except Exception:
    import pyaudio
import threading
import json
import queue
import os
import signal
import time
import sys
import subprocess
import select
import traceback
import shutil
import configparser
import logging
from typing import Callable, Optional

import numpy as np
from paths import runtime_path
import dsp_pipeline as dsp_filters
from audio_backend import create_pyaudio, probe_portaudio
from audio_config_domain import (
    as_bool as _domain_as_bool,
    clamp as _domain_clamp,
    get_config_path,
    load_runtime_config,
    normalize_anr_config as _domain_normalize_anr_config,
    persist_runtime_config as _domain_persist_runtime_config,
)
from audio_signal_domain import (
    apply_volume as _domain_apply_volume,
    convert_channels as _domain_convert_channels,
    generate_sine_chunk as _domain_generate_sine_chunk,
    prepare_tx_radio_audio as _domain_prepare_tx_radio_audio,
)
from audio_diag_domain import (
    rx_meter_ballistics as _domain_rx_meter_ballistics,
    tx_diag_gate_snapshot as _domain_tx_diag_gate_snapshot,
    tx_diag_metrics as _domain_tx_diag_metrics,
)
from audio_tx_gate_domain import (
    reset_tx_gate_state as _domain_reset_tx_gate_state,
    tx_cleanup as _domain_tx_cleanup,
    tx_source_is_easyeffects as _domain_tx_source_is_easyeffects,
    tx_output_signal_is_ready as _domain_tx_output_signal_is_ready,
    tx_use_external_dsp_passthrough as _domain_tx_use_external_dsp_passthrough,
)
from audio_rx_domain import (
    apply_rx_frontend as _domain_apply_rx_frontend,
    highpass as _domain_highpass,
    rx_cleanup as _domain_rx_cleanup,
)
from audio_rx_chain_domain import (
    rx_chain_gui as _domain_rx_chain_gui,
    rx_chain_web as _domain_rx_chain_web,
    sdr_chain_light_gui as _domain_sdr_chain_light_gui,
    sdr_chain_light_web as _domain_sdr_chain_light_web,
)
from audio_gain_domain import (
    aplicar_auto_gain as _domain_aplicar_auto_gain,
    aplicar_factor_lineal as _domain_aplicar_factor_lineal,
    aplicar_gain_extra_rx as _domain_aplicar_gain_extra_rx,
    aplicar_gain_manual as _domain_aplicar_gain_manual,
    atenuar_entrada_radio as _domain_atenuar_entrada_radio,
    reforzar_salida_pc as _domain_reforzar_salida_pc,
)
from audio_pcm_domain import (
    fade_in_pcm16 as _domain_fade_in_pcm16,
    frame_from_chunks as _domain_frame_from_chunks,
    pad_or_truncate_frame as _domain_pad_or_truncate_frame,
    parse_sample_spec as _domain_parse_sample_spec,
    resample_linear as _domain_resample_linear,
    soft_repeat_block_pcm16 as _domain_soft_repeat_block_pcm16,
    tx_frame_size_for_rate as _domain_tx_frame_size_for_rate,
    verificar_datos as _domain_verificar_datos,
)
from audio_pulse_text_domain import (
    best_pulse_description as _domain_best_pulse_description,
    clean_pulse_text as _domain_clean_pulse_text,
    describe_tx_app_entry as _domain_describe_tx_app_entry,
    filter_dict_entries as _domain_filter_dict_entries,
    normalize_linux_audio_name as _domain_normalize_linux_audio_name,
    parse_pulse_device_entries as _domain_parse_pulse_device_entries,
    resolve_pulse_device_from_list as _domain_resolve_pulse_device_from_list,
    tx_entry_matches_hints as _domain_tx_entry_matches_hints,
)
from collections import deque

# Import audio_remote for WebRTC integration (optional, fallback if not available)
try:
    import audio_remote
except Exception:
    audio_remote = None

# Cargar configuracion de dispositivos de audio desde config.json
CONFIG_FILE, config = load_runtime_config()
_AUDIO_LOGGER = logging.getLogger("audio")


def _ignore_exception(context: str) -> None:
    _AUDIO_LOGGER.debug(context, exc_info=True)


def _persist_runtime_config() -> None:
    _domain_persist_runtime_config(
        CONFIG_FILE,
        config,
        on_error=lambda _exc: _ignore_exception("ignored exception"),
    )


def _as_bool(value: object, default: bool = False) -> bool:
    return _domain_as_bool(value, default=default)


def _normalize_anr_config() -> None:
    """Keep legacy ANR_* keys and DSPFilters in sync (avoid mismatched states)."""
    _domain_normalize_anr_config(
        config,
        persist_callback=_persist_runtime_config,
        on_error=lambda _exc: _ignore_exception("ignored exception"),
    )


_normalize_anr_config()

DEBUG_AUDIO = bool(config.get("AudioDebug", False))

def _debug(message: str) -> None:
    if DEBUG_AUDIO:
        print(message)


def _trace(message: str) -> None:
    print(f"[audio] {message}", flush=True)


def _mark_rx_thread_stopped() -> None:
    global rx_activo, rx_thread
    with _state_lock:
        rx_activo = False
        if rx_thread and not rx_thread.is_alive():
            rx_thread = None
    _rx_stopped_event.set()


def _mark_tx_thread_stopped() -> None:
    global tx_activo, tx_thread
    with _state_lock:
        tx_activo = False
        if tx_thread and not tx_thread.is_alive():
            tx_thread = None
    _tx_stopped_event.set()

# Inicializar variables de audio segÃƒÂºn la configuraciÃƒÂ³n o valores por defecto
altavoz_pc_index = config.get("Altavoz_PC_Index", 6)
microfono_pc_index = config.get("Microfono_PC_Index", 3)
altavoz_radio_index = config.get("Altavoz_Radio_Index", 8)
microfono_radio_index = config.get("Microfono_Radio_Index", 17)

# Variables de volumen
volumen_tx = 1.0  # Rango de 0.0 a 1.0
volumen_rx = 0.6  # Rango de 0.0 a 1.0, inicializado en 60%
DIGITAL_APP_TX_GAIN = 0.70
# Ganancia extra para compensar niveles bajos de captura.
# Keep the default conservative to avoid clipping strong stations.
rx_capture_gain = float(config.get("RX_Capture_Gain", 1.0))
rx_hum_reduction = bool(config.get("RX_Hum_Reduction", True))
RX_HPF_CUTOFF = float(config.get("RX_HPF_CUTOFF", 80.0))
RX_GATE_THRESHOLD = float(config.get("RX_GATE_THRESHOLD", 0.0))
TX_GATE_ENABLED = _as_bool(config.get("TX_GATE_ENABLED", True), default=True)
TX_GATE_THRESHOLD = float(config.get("TX_GATE_THRESHOLD", 420.0))
TX_GATE_ATTACK_MS = float(config.get("TX_GATE_ATTACK_MS", 8.0))
TX_GATE_RELEASE_MS = float(config.get("TX_GATE_RELEASE_MS", 85.0))
TX_GATE_HOLD_MS = float(config.get("TX_GATE_HOLD_MS", 40.0))
TX_GATE_FLOOR = float(config.get("TX_GATE_FLOOR", 0.0))
TX_HPF_CUTOFF = float(config.get("TX_HPF_CUTOFF", 120.0))
TX_GATE_ADAPTIVE = _as_bool(config.get("TX_GATE_ADAPTIVE", True), default=True)
TX_GATE_NOISE_TRACK_S = float(config.get("TX_GATE_NOISE_TRACK_S", 0.8))
TX_GATE_OPEN_RATIO = float(config.get("TX_GATE_OPEN_RATIO", 2.2))
TX_GATE_OPEN_OFFSET = float(config.get("TX_GATE_OPEN_OFFSET", 260.0))
TX_GATE_CALIBRATE_MS = float(config.get("TX_GATE_CALIBRATE_MS", 320.0))
TX_GATE_OPEN_PEAK_RATIO = float(config.get("TX_GATE_OPEN_PEAK_RATIO", 1.8))
TX_GATE_OPEN_PEAK_OFFSET = float(config.get("TX_GATE_OPEN_PEAK_OFFSET", 420.0))
TX_GATE_MIN_CREST = float(config.get("TX_GATE_MIN_CREST", 1.9))
TX_LPF_CUTOFF = float(config.get("TX_LPF_CUTOFF", 3300.0))
TX_VOICE_MIN_ZCR = float(config.get("TX_VOICE_MIN_ZCR", 0.006))
TX_VOICE_MIN_BAND_RATIO = float(config.get("TX_VOICE_MIN_BAND_RATIO", 1.25))
TX_VOICE_MIN_FLATNESS = float(config.get("TX_VOICE_MIN_FLATNESS", 0.055))
TX_VOICE_MIN_MODULATION = float(config.get("TX_VOICE_MIN_MODULATION", 0.11))
TX_TONAL_MAX_DOMINANCE = float(config.get("TX_TONAL_MAX_DOMINANCE", 0.70))
TX_HUM_REJECT_ENABLED = _as_bool(config.get("TX_HUM_REJECT_ENABLED", True), default=True)
TX_HUM_DOMINANCE_MIN = float(config.get("TX_HUM_DOMINANCE_MIN", 0.52))
TX_HUM_MAX_ZCR = float(config.get("TX_HUM_MAX_ZCR", 0.018))
TX_HUM_MAX_FLATNESS = float(config.get("TX_HUM_MAX_FLATNESS", 0.0035))
TX_HUM_MAX_MODULATION = float(config.get("TX_HUM_MAX_MODULATION", 0.08))
TX_HUM_HARD_RESET = _as_bool(config.get("TX_HUM_HARD_RESET", True), default=True)
TX_HARD_MUTE_WHEN_NO_VOICE = _as_bool(config.get("TX_HARD_MUTE_WHEN_NO_VOICE", True), default=True)
TX_HARD_MUTE_HOLD_MS = float(config.get("TX_HARD_MUTE_HOLD_MS", 30.0))
TX_EXTERNAL_DSP_BYPASS = _as_bool(config.get("TX_EXTERNAL_DSP_BYPASS", True), default=True)
TX_DIAG_ENABLED = _as_bool(
    os.environ.get("TX_DIAG_ENABLED", config.get("TX_DIAG_ENABLED", True)),
    default=True,
)
TX_DIAG_INTERVAL_S = float(os.environ.get("TX_DIAG_INTERVAL_S", config.get("TX_DIAG_INTERVAL_S", 0.35)))
TX_CLEANUP_ENABLED = _as_bool(config.get("TX_CLEANUP_ENABLED", True), default=True)

# Control de habilitaciÃƒÂ³n de audio (se activa al encender la radio)
audio_habilitado = bool(config.get("Start_Audio_On_Launch", False))

DSP_FRAME_SIZE = 1440
# WebRTC uses 20 ms Opus frames at 48 kHz -> 960 samples (lower latency for TX/RX).
WEB_RX_FRAME_SIZE = 960
TX_FRAME_SIZE = 960
PULSE_LATENCY_MSEC = 20
RX_PULSE_LATENCY_MSEC = max(40, int(config.get("RX_PULSE_LATENCY_MSEC", 70) or 70))
TX_PULSE_LATENCY_MSEC = max(20, int(config.get("TX_PULSE_LATENCY_MSEC", 50) or 50))
# Latencia de captura de "Altavoz Radio" específica del modo remoto: en modo
# remoto, `parec` alimenta solo a audio_remote/WebRTC (nunca a un `pacat` de
# monitor local, ver el `if not _remote_mode` más abajo), que ya absorbe
# jitter con su propia cola por oyente — así que puede pedirse un búfer más
# corto a PulseAudio sin arriesgar el playback local (que no existe en este
# modo), reduciendo el tiempo hasta que llega la primera muestra real tras
# reabrir el stream (p. ej. justo al soltar PTT).
WEB_RX_PULSE_LATENCY_MSEC = max(20, int(config.get("WEB_RX_PULSE_LATENCY_MSEC", 30) or 30))
# Internal SDR timing knobs (not user-configurable; keep out of config.json).
SDR_PULSE_LATENCY_MSEC = 110
SDR_BATCH_FRAMES = 4
SDR_PREBUFFER_MS = 220
SDR_REBUFFER_MS = max(80, int(config.get("SDR_REBUFFER_MS", 180) or 180))
SDR_MAX_BUFFER_MS = max(220, int(config.get("SDR_MAX_BUFFER_MS", 380) or 380))
SDR_MAX_PROCESS_MS = max(40, int(config.get("SDR_MAX_PROCESS_MS", 100) or 100))
SDR_QUEUE_SOFT_LIMIT = max(6, int(config.get("SDR_QUEUE_SOFT_LIMIT", 16) or 16))
SDR_FADE_IN_MS = max(0, int(config.get("SDR_FADE_IN_MS", 120) or 120))
WEB_RX_GAIN = float(config.get("WEB_RX_GAIN", 1.0))
WEB_TX_GAIN = float(config.get("WEB_TX_GAIN", 1.0))
EXTRA_RX_GAIN = 1.0
RADIO_INPUT_ATTENUATION = 1.0
OUTPUT_POST_GAIN = 1.0
SDR_LIGHT_OUTPUT_POST_GAIN = float(config.get("SDR_LIGHT_OUTPUT_POST_GAIN", 1.0) or 1.0)
LINUX_AUDIO_RATE = int(config.get("LINUX_AUDIO_RATE", 48000) or 48000)

AUTO_GAIN_TARGET = float(config.get("AutoGainTarget", 6500.0))
AUTO_GAIN_MAX_GAIN = float(config.get("AutoGainMax", 2.0))
AUTO_GAIN_MIN_GAIN = float(config.get("AutoGainMin", 0.6))
# Attack = how quickly gain rises on weak audio.
# Release = how quickly gain falls after a loud station; keep this faster so
# a strong signal does not "stick" and keep the next stations crushed.
# Attack was 0.08 (~1.1s to settle) — noticeably slower than release, so the
# gain lingered low for almost a second after a station faded before
# climbing back up. 0.20 (~0.4s to settle) keeps the same curve, just
# quicker; measured stable across the tested range (no oscillation).
AUTO_GAIN_ATTACK = float(config.get("AutoGainAttack", 0.20))
AUTO_GAIN_RELEASE = float(config.get("AutoGainRelease", 0.15))
MANUAL_GAIN_MIN = float(config.get("ManualGainMin", 0.5))
MANUAL_GAIN_MAX = float(config.get("ManualGainMax", 3.0))
def _clamp(value: float, minimo: float, maximo: float) -> float:
    return _domain_clamp(value, minimo, maximo)

_config_gain_mode = str(config.get("GainMode", "")).strip().lower()
if _config_gain_mode not in {"auto", "manual", "off"}:
    _config_gain_mode = "auto" if config.get("AutoGainEnabled", True) else "off"

gain_mode = _config_gain_mode
auto_gain_enabled = gain_mode == "auto"
manual_gain = _clamp(config.get("ManualGain", 1.0), MANUAL_GAIN_MIN, MANUAL_GAIN_MAX)
if gain_mode != "manual":
    manual_gain = 1.0

_agc_state = {"gain": 1.0}
_rx_hpf_state = {"prev_x": None, "prev_y": None}
_tx_hpf_state = {"x_prev": None, "y_prev": None}
_tx_lpf_state = {"y_prev": None}
_tx_gate_state = {"env": 0.0, "hold_until": 0.0, "voice_until": 0.0, "noise_rms": 0.0, "noise_peak": 0.0, "start_ts": 0.0}
_raw_lock = threading.Lock()
_rx_raw_buffer_gui = deque(maxlen=60)
_rx_raw_buffer_web = deque(maxlen=240)
_rx_raw_buffer_digi = deque(maxlen=240)
_tx_raw_buffer = deque(maxlen=60)
_tx_inject_lock = threading.Lock()
_tx_inject_buffer = deque(maxlen=200)  # items: (samples, rate) - increased for WebRTC bursts
_tx_inject_rate = 48000
_tx_inject_last_warn = 0.0
_tx_inject_last_chunk = None
_tx_inject_last_time = 0.0
_tx_inject_pending = None
_tx_inject_pending_rate = 48000
_tx_capture_source = "mic"
_TX_APP_HINTS = ("wsjtx", "jtdx", "freedv", "js8call")
_tx_tone_active = False
_tx_tone_thread: Optional[threading.Thread] = None
_tx_tone_stop_event = threading.Event()
_rx_sample_rate = 48000
_rx_channels = 1
_rx_meter_dbfs = -120.0
_rx_meter_ts = 0.0
_tx_output_rms = 0.0
_tx_output_signal_ts = 0.0
_remote_mode = False
_stream_open_lock = threading.Lock()
_state_lock = threading.RLock()
_rx_stopped_event = threading.Event()
_tx_stopped_event = threading.Event()
_rx_stopped_event.set()
_tx_stopped_event.set()
_linux_audio_runtime = not sys.platform.startswith("win")
_audio_worker_thread = None
_audio_worker_event = threading.Event()
_audio_worker_stop = False
_audio_requested_mode = "idle"
_tx_diag_last_ts_by_stage = {}

# OpenWebRX audio capture (Linux/Pulse) to allow applying ANR to "audio SDR".
_sdr_volume = 1.0
_sdr_enabled = False
_sdr_thread: Optional[threading.Thread] = None
_sdr_stop_event = threading.Event()
_sdr_stop_event.set()
_sdr_loop_generation = 0
_sdr_pulse_module_id: Optional[int] = None
_owrx_pid: Optional[int] = None
_sdr_paused = False
_sdr_resume_drop = 0
_sdr_monitor_stream_id: Optional[int] = None
_sdr_last_rms = 0.0
_sdr_signal_ts = 0.0
_sdr_parec_pid: Optional[int] = None
_sdr_pacat_pid: Optional[int] = None
_sdr_output_active = False
_sdr_output_ts = 0.0
_sdr_prebuffering = True
_sdr_route_thread: Optional[threading.Thread] = None
_sdr_route_stop = threading.Event()
# Keep queue bounded to avoid multi-second latency build-up when DSP/CPU stalls.
_sdr_input_queue: "queue.Queue[tuple[bytes, int, int]]" = queue.Queue(maxsize=48)
_sdr_input_buffer = bytearray()
_sdr_input_rate = 48000
_sdr_input_channels = 2
_sdr_capture_ts = 0.0
_sdr_chunk_drop_total = 0
_sdr_chunk_enqueue_fail_total = 0


def _sdr_log(msg: str) -> None:
    try:
        path = str(runtime_path("sdr_audio.log"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        _ignore_exception("ignored exception")


def _tx_diag_log(msg: str) -> None:
    if not TX_DIAG_ENABLED:
        return
    try:
        path = str(runtime_path("tx_diag.log"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        _ignore_exception("ignored exception")


def _tx_diag_metrics(data: bytes, channels: int, sample_rate: int) -> str:
    return _domain_tx_diag_metrics(data, channels, sample_rate)


def _tx_diag_capture(stage: str, data: bytes, channels: int, sample_rate: int, extra: str = "") -> None:
    global _tx_diag_last_ts_by_stage
    if not TX_DIAG_ENABLED:
        return
    now = time.monotonic()
    interval = max(0.05, float(TX_DIAG_INTERVAL_S or 0.35))
    last_ts = float((_tx_diag_last_ts_by_stage or {}).get(stage, 0.0) or 0.0)
    if (now - last_ts) < interval:
        return
    _tx_diag_last_ts_by_stage[stage] = now
    metrics = _tx_diag_metrics(data, channels, sample_rate)
    suffix = f" {extra}" if extra else ""
    _tx_diag_log(f"{stage} {metrics}{suffix}")


def _tx_diag_gate_snapshot() -> str:
    return _domain_tx_diag_gate_snapshot(_tx_gate_state)

# Crear hilos de audio
rx_activo = False
tx_activo = False
rx_thread = None
tx_thread = None

# Inicializar PyAudio
p = create_pyaudio(pyaudio)


def _device_info_or_none(index):
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    if idx < 0:
        return None
    try:
        return probe_portaudio(p.get_device_info_by_index, idx)
    except Exception:
        return None


def _default_device_index(is_input: bool) -> int:
    getter = p.get_default_input_device_info if is_input else p.get_default_output_device_info
    try:
        info = probe_portaudio(getter)
        return int(info.get("index", -1))
    except Exception:
        _ignore_exception("ignored exception")
    for idx in range(probe_portaudio(p.get_device_count)):
        info = _device_info_or_none(idx)
        if not info:
            continue
        channels = int(info.get("maxInputChannels" if is_input else "maxOutputChannels", 0) or 0)
        if channels > 0:
            return idx
    return -1


def _coerce_device_index(index, is_input: bool, config_key: str) -> int:
    info = _device_info_or_none(index)
    channel_key = "maxInputChannels" if is_input else "maxOutputChannels"
    if info and int(info.get(channel_key, 0) or 0) > 0:
        return int(info["index"])
    fallback = _default_device_index(is_input)
    if fallback != -1:
        print(f"{config_key} inválido en config.json. Usando dispositivo por defecto #{fallback}.")
        config[config_key] = fallback
    else:
        print(f"{config_key} inválido y no se encontró dispositivo alternativo.")
        config[config_key] = -1
    return int(config[config_key])


if sys.platform.startswith("win"):
    altavoz_pc_index = _coerce_device_index(altavoz_pc_index, False, "Altavoz_PC_Index")
    microfono_pc_index = _coerce_device_index(microfono_pc_index, True, "Microfono_PC_Index")
    altavoz_radio_index = _coerce_device_index(altavoz_radio_index, True, "Altavoz_Radio_Index")
    microfono_radio_index = _coerce_device_index(microfono_radio_index, False, "Microfono_Radio_Index")
    _persist_runtime_config()

def _resolve_rx_input_index(index: int) -> int:
    """Use loopback device when selected device is output-only (WASAPI)."""
    try:
        info = probe_portaudio(p.get_device_info_by_index, index)
    except Exception:
        return index
    if info.get("maxInputChannels", 0) > 0:
        return index
    if hasattr(p, "get_wasapi_loopback_analogue_by_index"):
        try:
            loopback = p.get_wasapi_loopback_analogue_by_index(index)
            if isinstance(loopback, dict) and "index" in loopback:
                return int(loopback["index"])
        except Exception:
            pass
    if hasattr(p, "get_loopback_device_info_generator"):
        try:
            name = str(info.get("name", ""))
            for dev in p.get_loopback_device_info_generator():
                dev_name = str(dev.get("name", ""))
                if dev_name.startswith(name) or name in dev_name:
                    return int(dev.get("index", index))
        except Exception:
            pass
    return index

def listar_dispositivos_audio():
    print("Dispositivos de audio disponibles:")
    if not sys.platform.startswith("win"):
        for i in range(probe_portaudio(p.get_device_count)):
            device_info = probe_portaudio(p.get_device_info_by_index, i)
            device_name = str(device_info.get("name", ""))
            print(f"Index: {i}, Nombre: {device_name}, MaxInputChannels: {device_info['maxInputChannels']}, MaxOutputChannels: {device_info['maxOutputChannels']}")
        return
    wasapi_hostapi_index = None

    # Find the index of the WASAPI host API
    for i in range(probe_portaudio(p.get_host_api_count)):
        host_api_info = probe_portaudio(p.get_host_api_info_by_index, i)
        if host_api_info['name'] == 'Windows WASAPI':
            wasapi_hostapi_index = i
            break

    if wasapi_hostapi_index is None:
        print("No se encontrÃƒÂ³ el hostapi Windows WASAPI.")
        return

    # Collect devices that use the WASAPI host API
    for i in range(probe_portaudio(p.get_device_count)):
        device_info = probe_portaudio(p.get_device_info_by_index, i)
        if device_info['hostApi'] == wasapi_hostapi_index:
            device_name = device_info['name'].encode('latin1').decode('utf-8', 'ignore')
            print(f"Index: {i}, Nombre: {device_name}, MaxInputChannels: {device_info['maxInputChannels']}, MaxOutputChannels: {device_info['maxOutputChannels']}")

def verificar_canales_dispositivo(index, is_input):
    device_info = _device_info_or_none(index)
    if not device_info:
        return 0, 0
    device_name = device_info['name'].encode('latin1').decode('utf-8', 'ignore')
    _debug(f"Dispositivo {index}: {device_name}")
    if not sys.platform.startswith("win"):
        channel_key = 'maxInputChannels' if is_input else 'maxOutputChannels'
        channels = int(device_info.get(channel_key, 0) or 0)
        # PortAudio/PipeWire may report unrealistic channel counts (e.g. 128) for virtual devices.
        if channels <= 0 or channels > 8:
            channels = 0
        return channels, LINUX_AUDIO_RATE
    if is_input:
        return device_info['maxInputChannels'], int(device_info['defaultSampleRate'])
    else:
        return device_info['maxOutputChannels'], int(device_info['defaultSampleRate'])

def convertir_canales(data, src_channels, dst_channels):
    _debug(f"Convirtiendo canales de {src_channels} a {dst_channels}")
    return _domain_convert_channels(data, src_channels, dst_channels)

def aplicar_volumen(data, volumen):
    return _domain_apply_volume(data, volumen)


def _prepare_tx_radio_audio(data: bytes, src_channels: int, dst_channels: int) -> tuple[bytes, int]:
    return _domain_prepare_tx_radio_audio(data, src_channels, dst_channels)


def _reset_tx_gate_state() -> None:
    _domain_reset_tx_gate_state(_tx_gate_state, _tx_hpf_state, _tx_lpf_state)


def _tx_source_is_easyeffects(source_name: object) -> bool:
    return _domain_tx_source_is_easyeffects(source_name)


def _tx_use_external_dsp_passthrough(capture_mode: str, source_name: object, injected_present: bool) -> bool:
    return _domain_tx_use_external_dsp_passthrough(
        capture_mode,
        source_name,
        injected_present,
        external_dsp_bypass=TX_EXTERNAL_DSP_BYPASS,
    )


def _tx_cleanup(
    data: bytes,
    channels: int,
    sample_rate: int,
    bypass_gate: bool = False,
    bypass_all_processing: bool = False,
) -> bytes:
    return _domain_tx_cleanup(
        data,
        channels,
        sample_rate,
        bypass_gate=bypass_gate,
        bypass_all_processing=bypass_all_processing,
        tx_gate_state=_tx_gate_state,
        tx_hpf_state=_tx_hpf_state,
        tx_lpf_state=_tx_lpf_state,
        cfg={
            "TX_GATE_ENABLED": TX_GATE_ENABLED,
            "TX_HPF_CUTOFF": TX_HPF_CUTOFF,
            "TX_LPF_CUTOFF": TX_LPF_CUTOFF,
            "TX_GATE_THRESHOLD": TX_GATE_THRESHOLD,
            "TX_GATE_OPEN_PEAK_OFFSET": TX_GATE_OPEN_PEAK_OFFSET,
            "TX_GATE_CALIBRATE_MS": TX_GATE_CALIBRATE_MS,
            "TX_GATE_NOISE_TRACK_S": TX_GATE_NOISE_TRACK_S,
            "TX_GATE_ADAPTIVE": TX_GATE_ADAPTIVE,
            "TX_GATE_OPEN_OFFSET": TX_GATE_OPEN_OFFSET,
            "TX_GATE_OPEN_RATIO": TX_GATE_OPEN_RATIO,
            "TX_GATE_OPEN_PEAK_RATIO": TX_GATE_OPEN_PEAK_RATIO,
            "TX_GATE_HOLD_MS": TX_GATE_HOLD_MS,
            "TX_GATE_MIN_CREST": TX_GATE_MIN_CREST,
            "TX_VOICE_MIN_ZCR": TX_VOICE_MIN_ZCR,
            "TX_VOICE_MIN_BAND_RATIO": TX_VOICE_MIN_BAND_RATIO,
            "TX_VOICE_MIN_FLATNESS": TX_VOICE_MIN_FLATNESS,
            "TX_TONAL_MAX_DOMINANCE": TX_TONAL_MAX_DOMINANCE,
            "TX_HUM_REJECT_ENABLED": TX_HUM_REJECT_ENABLED,
            "TX_HUM_DOMINANCE_MIN": TX_HUM_DOMINANCE_MIN,
            "TX_HUM_MAX_ZCR": TX_HUM_MAX_ZCR,
            "TX_HUM_MAX_FLATNESS": TX_HUM_MAX_FLATNESS,
            "TX_HUM_MAX_MODULATION": TX_HUM_MAX_MODULATION,
            "TX_VOICE_MIN_MODULATION": TX_VOICE_MIN_MODULATION,
            "TX_HUM_HARD_RESET": TX_HUM_HARD_RESET,
            "TX_HARD_MUTE_WHEN_NO_VOICE": TX_HARD_MUTE_WHEN_NO_VOICE,
            "TX_HARD_MUTE_HOLD_MS": TX_HARD_MUTE_HOLD_MS,
            "TX_GATE_ATTACK_MS": TX_GATE_ATTACK_MS,
            "TX_GATE_RELEASE_MS": TX_GATE_RELEASE_MS,
            "TX_GATE_FLOOR": TX_GATE_FLOOR,
        },
    )

def _aplicar_factor_lineal(data: bytes, factor: float) -> bytes:
    return _domain_aplicar_factor_lineal(data, factor)


def _atenuar_entrada_radio(data: bytes) -> bytes:
    return _domain_atenuar_entrada_radio(data, RADIO_INPUT_ATTENUATION)


def _aplicar_gain_extra_rx(data: bytes) -> bytes:
    return _domain_aplicar_gain_extra_rx(data, EXTRA_RX_GAIN)


def _reforzar_salida_pc(data: bytes) -> bytes:
    return _domain_reforzar_salida_pc(data, OUTPUT_POST_GAIN)


def _aplicar_gain_manual(data: bytes) -> bytes:
    return _domain_aplicar_gain_manual(data, manual_gain)


def _aplicar_auto_gain(data: bytes) -> bytes:
    return _domain_aplicar_auto_gain(
        data,
        state=_agc_state,
        target=AUTO_GAIN_TARGET,
        min_gain=AUTO_GAIN_MIN_GAIN,
        max_gain=AUTO_GAIN_MAX_GAIN,
        attack=AUTO_GAIN_ATTACK,
        release=AUTO_GAIN_RELEASE,
    )

def _highpass(samples: np.ndarray, cutoff_hz: float, sample_rate: int) -> np.ndarray:
    return _domain_highpass(samples, cutoff_hz, sample_rate, _rx_hpf_state)


def _rx_cleanup(data: bytes, channels: int, sample_rate: int, gate_enabled: bool = True) -> bytes:
    return _domain_rx_cleanup(
        data,
        channels,
        sample_rate,
        gate_enabled=gate_enabled,
        rx_hpf_cutoff=RX_HPF_CUTOFF,
        rx_gate_threshold=RX_GATE_THRESHOLD,
        rx_hpf_state=_rx_hpf_state,
    )


def _apply_rx_frontend(data: bytes, channels: int) -> bytes:
    """Match the radio RX front-end steps (hum reduction + capture gain + attenuation)."""
    return _domain_apply_rx_frontend(
        data,
        rx_capture_gain=rx_capture_gain,
        rx_hum_reduction=rx_hum_reduction,
        attenuate_input_radio=_atenuar_entrada_radio,
    )


def _rx_chain_gui(
    data: bytes,
    channels: int,
    sample_rate: int,
    frame_size: int,
    *,
    context: str,
    volume: float,
    apply_output_boost: bool = True,
    apply_user_gain: bool = True,
) -> bytes:
    """Apply the same RX GUI processing chain used for radio audio."""
    return _domain_rx_chain_gui(
        data,
        channels,
        sample_rate,
        frame_size,
        context=context,
        volume=volume,
        apply_output_boost=apply_output_boost,
        apply_user_gain=apply_user_gain,
        gain_mode=gain_mode,
        web_rx_gain=WEB_RX_GAIN,
        rx_cleanup_fn=lambda d, ch, sr, ge: _rx_cleanup(d, ch, sr, gate_enabled=ge),
        process_rx_ctx_fn=dsp_filters.process_rx_ctx,
        apply_volume_fn=aplicar_volumen,
        apply_auto_gain_fn=_aplicar_auto_gain,
        apply_manual_gain_fn=_aplicar_gain_manual,
        apply_gain_extra_rx_fn=_aplicar_gain_extra_rx,
        reinforce_pc_output_fn=_reforzar_salida_pc,
    )


def _rx_chain_web(
    data: bytes,
    channels: int,
    sample_rate: int,
    frame_size: int,
    *,
    context: str,
    volume: float,
    apply_user_gain: bool = True,
) -> bytes:
    """Apply the same RX web processing chain used for radio audio."""
    return _domain_rx_chain_web(
        data,
        channels,
        sample_rate,
        frame_size,
        context=context,
        volume=volume,
        apply_user_gain=apply_user_gain,
        gain_mode=gain_mode,
        web_rx_gain=WEB_RX_GAIN,
        rx_cleanup_fn=lambda d, ch, sr, ge: _rx_cleanup(d, ch, sr, gate_enabled=ge),
        process_rx_ctx_fn=dsp_filters.process_rx_ctx,
        apply_volume_fn=aplicar_volumen,
        apply_auto_gain_fn=_aplicar_auto_gain,
        apply_manual_gain_fn=_aplicar_gain_manual,
        apply_factor_lineal_fn=_aplicar_factor_lineal,
    )


def _sdr_chain_light_gui(data: bytes, volume: float) -> bytes:
    """Low-latency SDR chain when ANR is disabled."""
    return _domain_sdr_chain_light_gui(
        data, volume,
        output_post_gain=SDR_LIGHT_OUTPUT_POST_GAIN,
        apply_volume_fn=aplicar_volumen,
        apply_factor_lineal_fn=_aplicar_factor_lineal,
    )


def _sdr_chain_light_web(data: bytes, volume: float) -> bytes:
    return _domain_sdr_chain_light_web(
        data, volume,
        web_rx_gain=WEB_RX_GAIN,
        apply_volume_fn=aplicar_volumen,
        apply_factor_lineal_fn=_aplicar_factor_lineal,
    )


def _push_raw(buffer: deque, data: bytes, channels: int) -> None:
    if not data:
        return
    try:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)
        with _raw_lock:
            buffer.append(samples.copy())
    except Exception:
        pass


def _push_rx_raw_web(data: bytes, channels: int) -> None:
    if not data:
        return
    try:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)
        # Normalize to [-1, 1] for WebRTC consumers.
        samples = np.clip(samples / 32768.0, -1.0, 1.0)
        with _raw_lock:
            _rx_raw_buffer_web.append(samples.copy())

        # Feed audio_remote if active (for low-latency WebRTC)
        if audio_remote and audio_remote.is_active():
            # audio_remote consumes mono float32 for deterministic low-latency path.
            audio_remote.push_rx_audio(samples)
    except Exception:
        pass


def _push_rx_raw_digi(data: bytes, channels: int) -> None:
    """Push a clean pre-volume RX stream for Digi decoders."""
    if not data:
        return
    try:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)
        samples = np.clip(samples / 32768.0, -1.0, 1.0)
        with _raw_lock:
            _rx_raw_buffer_digi.append(samples.copy())
    except Exception:
        pass


def _push_rx_raw_gui(data: bytes, channels: int) -> None:
    if not data:
        return
    try:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)
        with _raw_lock:
            _rx_raw_buffer_gui.append(samples.copy())
    except Exception:
        pass


def _clear_rx_buffers() -> None:
    with _raw_lock:
        _rx_raw_buffer_web.clear()
        _rx_raw_buffer_digi.clear()
        _rx_raw_buffer_gui.clear()


def pop_rx_raw() -> Optional[np.ndarray]:
    with _raw_lock:
        if not _rx_raw_buffer_gui:
            return None
        samples = _rx_raw_buffer_gui.pop()
        _rx_raw_buffer_gui.clear()
        return samples


def pop_rx_raw_chunk() -> Optional[np.ndarray]:
    """Consume a recent RX chunk and drop backlog to bound WebRTC latency."""
    with _raw_lock:
        if _rx_raw_buffer_web:
            # Always return the most recent chunk and clear backlog.
            # Returning older chunks after newer ones (reverse order) breaks digi decoders.
            latest = _rx_raw_buffer_web.pop()
            _rx_raw_buffer_web.clear()
            return latest
        return None


def pop_rx_raw_chunk_digi() -> Optional[np.ndarray]:
    """Independent RX chunk consumer for Digi to avoid contention with webserver."""
    with _raw_lock:
        if _rx_raw_buffer_digi:
            latest = _rx_raw_buffer_digi.pop()
            _rx_raw_buffer_digi.clear()
            return latest
        return None


def get_rx_sample_rate() -> int:
    return int(_rx_sample_rate or 48000)


def _set_mode_flags(mode: str) -> None:
    global rx_activo, tx_activo
    rx_activo = mode == "rx"
    tx_activo = mode == "tx"


def _normalize_linux_audio_name(value: object) -> str:
    return _domain_normalize_linux_audio_name(value)


def _clean_pulse_text(value: object) -> str:
    return _domain_clean_pulse_text(value)


def _best_pulse_description(entry: dict) -> str:
    return _domain_best_pulse_description(entry)


def _list_pulse_devices(kind: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", kind],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
        entries = _domain_parse_pulse_device_entries(payload)
        if entries:
            return entries
    except Exception:
        _ignore_exception("ignored exception")


def _update_rx_meter_from_pcm(data: bytes, channels: int) -> None:
    global _rx_meter_dbfs, _rx_meter_ts
    new_dbfs = _domain_rx_meter_ballistics(data, channels, _rx_meter_dbfs)
    if new_dbfs is not None:
        _rx_meter_dbfs = new_dbfs
        _rx_meter_ts = float(time.monotonic())


def get_rx_meter_dbfs(window_s: float = 1.2) -> Optional[float]:
    try:
        if (time.monotonic() - float(_rx_meter_ts or 0.0)) > float(window_s):
            return None
        return float(_rx_meter_dbfs)
    except Exception:
        return None


def _resolve_pulse_device(kind: str, configured_label: object) -> Optional[str]:
    if not _domain_normalize_linux_audio_name(configured_label):
        return None
    devices = _list_pulse_devices(kind)
    return _domain_resolve_pulse_device_from_list(configured_label, devices)


def _get_configured_pulse_device(kind: str, pulse_key: str, label_key: str) -> Optional[str]:
    pulse_name = str(config.get(pulse_key, "") or "").strip()
    if pulse_name:
        devices = _list_pulse_devices(kind)
        for entry in devices:
            if pulse_name == str(entry.get("name") or "").strip():
                return pulse_name
    return _resolve_pulse_device(kind, config.get(label_key, ""))


def _get_pulse_device_details(kind: str, pulse_key: str, label_key: str) -> tuple[Optional[str], int, int]:
    pulse_name = _get_configured_pulse_device(kind, pulse_key, label_key)
    channels = 0
    rate = 0
    if pulse_name:
        for entry in _list_pulse_devices(kind):
            if pulse_name == str(entry.get("name") or "").strip():
                channels = int(entry.get("channels") or 0)
                rate = int(entry.get("rate") or 0)
                break
    return pulse_name, channels, rate


def _list_sink_inputs() -> list[dict]:
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
    except Exception:
        return []
    return _domain_filter_dict_entries(payload)


def _parse_sample_spec(sample_spec: object) -> tuple[int, int]:
    return _domain_parse_sample_spec(sample_spec)


def _tx_entry_matches_hints(entry: dict, hints: tuple[str, ...]) -> bool:
    return _domain_tx_entry_matches_hints(entry, hints)


def _find_tx_app_sink_input() -> Optional[dict]:
    hints = tuple(h.lower() for h in _TX_APP_HINTS if h)
    if not hints:
        return None
    matches = []
    for entry in _list_sink_inputs():
        if not _tx_entry_matches_hints(entry, hints):
            continue
        props = entry.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        app_name = str(props.get("application.name") or props.get("application.process.binary") or "").strip()
        media_name = str(props.get("media.name") or "").strip()
        idx = entry.get("index")
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        matches.append((idx_int, app_name, media_name, entry))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][3]


def _describe_tx_app_entry(entry: Optional[dict]) -> str:
    return _domain_describe_tx_app_entry(entry)


def _get_tx_pulse_input_details() -> tuple[Optional[str], int, int, Optional[int], str]:
    capture_mode = str(_tx_capture_source or "mic").strip().lower()
    if capture_mode == "app":
        entry = _find_tx_app_sink_input()
        if entry:
            channels, rate = _parse_sample_spec(entry.get("sample_spec") or entry.get("sample_specification") or "")
            try:
                index = int(entry.get("index"))
            except (TypeError, ValueError):
                index = None
            return None, int(channels or 2), int(rate or LINUX_AUDIO_RATE), index, _describe_tx_app_entry(entry)
        # Fallback: if we cannot bind a per-app stream yet, capture from PC monitor
        # instead of emitting silence. This keeps WSJT-X/JTDX TX audio flowing.
        pulse_sink, sink_channels, sink_rate = _get_pulse_device_details("sinks", "Altavoz_PC_Pulse", "Altavoz_PC")
        pulse_source = f"{pulse_sink}.monitor" if pulse_sink else None
        return pulse_source, int(sink_channels or 2), int(sink_rate or LINUX_AUDIO_RATE), None, "Monitor Altavoz PC (fallback)"
    if capture_mode == "monitor":
        pulse_sink, sink_channels, sink_rate = _get_pulse_device_details("sinks", "Altavoz_PC_Pulse", "Altavoz_PC")
        pulse_source = f"{pulse_sink}.monitor" if pulse_sink else None
        if pulse_source:
            for entry in _list_pulse_devices("sources"):
                if pulse_source == str(entry.get("name") or "").strip():
                    return pulse_source, int(entry.get("channels") or sink_channels or 2), int(entry.get("rate") or sink_rate or LINUX_AUDIO_RATE), None, "Monitor Altavoz PC"
        return pulse_source, int(sink_channels or 2), int(sink_rate or LINUX_AUDIO_RATE), None, "Monitor Altavoz PC"
    pulse_source, channels, rate = _get_pulse_device_details("sources", "Microfono_PC_Pulse", "Microfono_PC")
    return pulse_source, channels, rate, None, "Micrófono PC"


def _read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def _close_subprocess_io(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    try:
        if process.stdout:
            process.stdout.close()
    except Exception:
        _ignore_exception("ignored exception")
    try:
        if process.stdin:
            process.stdin.close()
    except Exception:
        _ignore_exception("ignored exception")
    try:
        if process.stderr:
            process.stderr.close()
    except Exception:
        _ignore_exception("ignored exception")
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=0.5)
    except Exception:
        try:
            process.kill()
        except Exception:
            _ignore_exception("ignored exception")


def _run_pactl(*args: str) -> bool:
    try:
        result = subprocess.run(
            ["pactl", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _prepare_tx_pulse_sink(pulse_sink: Optional[str]) -> None:
    if not pulse_sink:
        return
    _run_pactl("set-sink-mute", pulse_sink, "0")
    # Do not force global sink volume by default, because on Linux this can
    # impact unrelated desktop applications using the same sink.
    if bool(config.get("TX_FORCE_RADIO_SINK_100", False)):
        _run_pactl("set-sink-volume", pulse_sink, "100%")


def _prepare_tx_pulse_sink_input(process: Optional[subprocess.Popen], pulse_sink: Optional[str]) -> None:
    """Force TX pacat sink-input to unmuted state (and optionally full volume)."""
    pid = int(getattr(process, "pid", 0) or 0)
    if pid <= 1:
        return
    deadline = time.monotonic() + 1.2
    entries: list[dict] = []
    while time.monotonic() < deadline:
        entries = _sink_inputs_for_pid(pid)
        if entries:
            break
        time.sleep(0.05)
    for entry in entries:
        idx = entry.get("index")
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        _run_pactl("set-sink-input-mute", str(idx_int), "0")
        if bool(config.get("TX_FORCE_RADIO_INPUT_100", True)):
            _run_pactl("set-sink-input-volume", str(idx_int), "100%")
        if pulse_sink:
            _run_pactl("move-sink-input", str(idx_int), str(pulse_sink))


def _reopen_tx_pulse_output(state: dict) -> Optional[subprocess.Popen]:
    pulse_sink = str(state.get("pulse_sink") or "").strip()
    if not pulse_sink:
        return None
    radio_rate = int(state.get("radio_rate") or LINUX_AUDIO_RATE)
    radio_channels = int(state.get("radio_channels") or 2)
    old = state.get("stream_out")
    if old is not None:
        _close_subprocess_io(old)
    _trace(
        f"Reabriendo TX output pulse: {pulse_sink} rate={radio_rate} channels={radio_channels}"
    )
    _prepare_tx_pulse_sink(pulse_sink)
    stream_out = subprocess.Popen(
        [
            "pacat",
            "--device",
            pulse_sink,
            "--playback",
            "--format=s16le",
            "--rate",
            str(radio_rate),
            "--channels",
            str(radio_channels),
            "--latency-msec",
            str(TX_PULSE_LATENCY_MSEC),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    _prepare_tx_pulse_sink_input(stream_out, pulse_sink)
    state["stream_out"] = stream_out
    return stream_out


def _reopen_tx_pulse_input(state: dict, *, reason: str = "") -> Optional[subprocess.Popen]:
    if _remote_mode:
        state["stream_in"] = None
        return None
    now = time.monotonic()
    retry_after = float(state.get("capture_retry_after", 0.0) or 0.0)
    if now < retry_after:
        return state.get("stream_in")
    # Avoid hot-loop respawns when Pulse stream is unstable.
    state["capture_retry_after"] = now + 0.2
    capture_mode = str(state.get("capture_mode") or _tx_capture_source or "mic").strip().lower()
    old = state.get("stream_in")
    if old is not None:
        _close_subprocess_io(old)
    pulse_source, src_channels, src_rate, monitor_stream_index, capture_label = _get_tx_pulse_input_details()
    if capture_mode == "app":
        state["capture_stream_index"] = None
    _trace(
        f"Reabriendo TX input pulse mode={capture_mode} reason={reason or 'unknown'} "
        f"source={pulse_source or '-'} stream={monitor_stream_index if monitor_stream_index is not None else '-'} "
        f"rate={int(src_rate or state.get('pc_rate') or LINUX_AUDIO_RATE)} "
        f"channels={int(src_channels or state.get('pc_channels') or 1)}"
    )
    process = _open_tx_pulse_input_process(
        pulse_source=pulse_source if monitor_stream_index is None else None,
        monitor_stream_index=monitor_stream_index,
        sample_rate=int(src_rate or state.get("pc_rate") or LINUX_AUDIO_RATE),
        channels=int(src_channels or state.get("pc_channels") or 1),
        label=capture_label or str(state.get("capture_label") or "Micrófono PC"),
    )
    state["stream_in"] = process
    state["pulse_source"] = pulse_source
    state["pc_channels"] = int(src_channels or state.get("pc_channels") or 1)
    state["pc_rate"] = int(src_rate or state.get("pc_rate") or LINUX_AUDIO_RATE)
    state["capture_stream_index"] = monitor_stream_index
    state["capture_label"] = capture_label or state.get("capture_label")
    return process


def _tx_frame_size_for_rate(sample_rate: int) -> int:
    """Return ~20 ms frame size for the given TX sample rate."""
    return _domain_tx_frame_size_for_rate(sample_rate)


def _open_tx_pulse_input_process(
    *,
    pulse_source: Optional[str],
    monitor_stream_index: Optional[int],
    sample_rate: int,
    channels: int,
    label: str,
) -> Optional[subprocess.Popen]:
    args = [
        "parec",
        "--format=s16le",
        "--rate",
        str(sample_rate),
        "--channels",
        str(channels),
        "--latency-msec",
        str(PULSE_LATENCY_MSEC),
        "--raw",
    ]
    if monitor_stream_index is not None:
        args.extend(["--monitor-stream", str(int(monitor_stream_index))])
        _trace(
            f"Abriendo TX input pulse: monitor-stream={int(monitor_stream_index)} "
            f"rate={sample_rate} channels={channels} label={label}"
        )
    elif pulse_source:
        args.extend(["--device", pulse_source])
        _trace(f"Abriendo TX input pulse: {pulse_source} rate={sample_rate} channels={channels}")
    else:
        return None
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    _trace("TX input abierto")
    return process


def _refresh_tx_app_capture_state(state: dict) -> None:
    now = time.monotonic()
    if now < float(state.get("capture_retry_after", 0.0) or 0.0):
        return
    state["capture_retry_after"] = now + 0.25
    entry = _find_tx_app_sink_input()
    if not entry:
        return
    try:
        monitor_stream_index = int(entry.get("index"))
    except (TypeError, ValueError):
        return
    channels, rate = _parse_sample_spec(entry.get("sample_spec") or entry.get("sample_specification") or "")
    channels = int(channels or state.get("pc_channels") or 2)
    rate = int(rate or state.get("pc_rate") or LINUX_AUDIO_RATE)
    if state.get("stream_in") is not None and state.get("capture_stream_index") == monitor_stream_index:
        return
    _close_subprocess_io(state.get("stream_in"))
    label = _describe_tx_app_entry(entry)
    process = _open_tx_pulse_input_process(
        pulse_source=None,
        monitor_stream_index=monitor_stream_index,
        sample_rate=rate,
        channels=channels,
        label=label,
    )
    if process is None:
        return
    state["stream_in"] = process
    state["capture_stream_index"] = monitor_stream_index
    state["pc_channels"] = channels
    state["pc_rate"] = rate
    state["capture_label"] = label
    _trace(f"TX app capture enlazado: stream={monitor_stream_index} label={label}")


def _linux_close_stream(stream) -> None:
    if stream is None:
        return
    try:
        if stream.is_active():
            stream.stop_stream()
    except Exception:
        _ignore_exception("ignored exception")
    try:
        stream.close()
    except Exception:
        _ignore_exception("ignored exception")


def _linux_open_rx_streams(pa):
    global _rx_sample_rate, _rx_channels
    rx_input_index = _resolve_rx_input_index(altavoz_radio_index)
    actual_altavoz_radio_channels, altavoz_radio_framerate = verificar_canales_dispositivo(rx_input_index, True)
    actual_altavoz_pc_channels, altavoz_pc_framerate = verificar_canales_dispositivo(altavoz_pc_index, False)

    if _linux_audio_runtime:
        pulse_source, pulse_source_channels, pulse_source_rate = _get_pulse_device_details("sources", "Altavoz_Radio_Pulse", "Altavoz_Radio")
        pulse_sink, pulse_sink_channels, pulse_sink_rate = _get_pulse_device_details("sinks", "Altavoz_PC_Pulse", "Altavoz_PC")
        actual_altavoz_radio_channels = int(pulse_source_channels or config.get("Altavoz_Radio_Channels", 1) or actual_altavoz_radio_channels or 1)
        altavoz_radio_framerate = int(pulse_source_rate or config.get("Altavoz_Radio_Framerate", LINUX_AUDIO_RATE) or altavoz_radio_framerate or LINUX_AUDIO_RATE)
        actual_altavoz_pc_channels = int(pulse_sink_channels or config.get("Altavoz_PC_Channels", 2) or actual_altavoz_pc_channels or 2)
        altavoz_pc_framerate = int(pulse_sink_rate or config.get("Altavoz_PC_Framerate", LINUX_AUDIO_RATE) or altavoz_pc_framerate or LINUX_AUDIO_RATE)
    else:
        pulse_source = None
        pulse_sink = None

    if not _linux_audio_runtime and (rx_input_index == -1 or altavoz_pc_index == -1):
        print("RX deshabilitado: faltan dispositivos de captura o reproducción válidos.")
        return None
    if actual_altavoz_pc_channels < actual_altavoz_radio_channels and not _remote_mode:
        print(f"Advertencia: El dispositivo de salida no soporta {actual_altavoz_radio_channels} canales. Soporta {actual_altavoz_pc_channels} canales.")
        return None
    if actual_altavoz_radio_channels == 0 or actual_altavoz_pc_channels == 0:
        print("Configuración de canales de audio inválida para RX.")
        return None

    print(f"RX Stream: Capturando de Altavoz Radio (channels: {actual_altavoz_radio_channels}) a Altavoz PC (channels: {actual_altavoz_pc_channels})")
    frame_size = WEB_RX_FRAME_SIZE if _remote_mode else DSP_FRAME_SIZE
    _rx_sample_rate = int(altavoz_radio_framerate or _rx_sample_rate)
    _rx_channels = int(actual_altavoz_radio_channels or 1)

    if _linux_audio_runtime:
        if not pulse_source or (not _remote_mode and not pulse_sink):
            print("No se pudieron resolver los dispositivos Pulse para RX.")
            return None
        bytes_per_chunk = frame_size * actual_altavoz_radio_channels * 2
        # En modo remoto este parec no alimenta ningún pacat de monitor local
        # (no existe en este modo), solo a audio_remote/WebRTC — que ya
        # absorbe jitter con su propia cola por oyente — así que puede
        # pedirse un búfer bastante más corto sin arriesgar nada; en modo
        # local se mantiene el valor de siempre para no arriesgar el
        # monitor por altavoces del PC (ver WEB_RX_PULSE_LATENCY_MSEC).
        rx_pulse_latency = WEB_RX_PULSE_LATENCY_MSEC if _remote_mode else RX_PULSE_LATENCY_MSEC
        _trace(f"Abriendo RX input pulse: {pulse_source} rate={altavoz_radio_framerate} channels={actual_altavoz_radio_channels} latency_ms={rx_pulse_latency}")
        stream_in = subprocess.Popen(
            [
                "parec",
                "--device", pulse_source,
                "--format=s16le",
                "--rate", str(altavoz_radio_framerate),
                "--channels", str(actual_altavoz_radio_channels),
                "--latency-msec", str(rx_pulse_latency),
                "--raw",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        _trace("RX input abierto")
        stream_out = None
        if not _remote_mode:
            _trace(f"Abriendo RX output pulse: {pulse_sink} rate={altavoz_pc_framerate} channels={actual_altavoz_pc_channels}")
            stream_out = subprocess.Popen(
                [
                    "pacat",
                    "--device", pulse_sink,
                    "--playback",
                    "--format=s16le",
                    "--rate", str(altavoz_pc_framerate),
                    "--channels", str(actual_altavoz_pc_channels),
                    "--latency-msec", str(RX_PULSE_LATENCY_MSEC),
                ],
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            _trace("RX output abierto")
    else:
        _trace(f"Abriendo RX input: device={rx_input_index} rate={altavoz_radio_framerate} channels={actual_altavoz_radio_channels} frames={frame_size}")
        stream_in = pa.open(
            format=pyaudio.paInt16,
            channels=actual_altavoz_radio_channels,
            rate=altavoz_radio_framerate,
            input=True,
            input_device_index=rx_input_index,
            frames_per_buffer=frame_size,
        )
        _trace("RX input abierto")
        stream_out = None
        if not _remote_mode:
            _trace(f"Abriendo RX output: device={altavoz_pc_index} rate={altavoz_pc_framerate} channels={actual_altavoz_pc_channels} frames={frame_size}")
            stream_out = pa.open(
                format=pyaudio.paInt16,
                channels=actual_altavoz_pc_channels,
                rate=altavoz_pc_framerate,
                output=True,
                output_device_index=altavoz_pc_index,
                frames_per_buffer=frame_size,
            )
            _trace("RX output abierto")

    # Separate DSP contexts for local playback ("gui") and WebRTC/web stream ("web").
    dsp_filters.configure_ctx(
        "web",
        altavoz_radio_framerate,
        actual_altavoz_radio_channels,
        frame_size,
        config=config,
    )
    if not _remote_mode:
        dsp_filters.configure_ctx(
            "gui",
            altavoz_pc_framerate,
            actual_altavoz_pc_channels,
            frame_size,
            config=config,
        )
    try:
        _trace(
            "RX radio ANR: gui_backend=%s web_backend=%s enabled=%s intensity=%s"
            % (
                bool(dsp_filters.backend_loaded_ctx("gui")) if not _remote_mode else False,
                bool(dsp_filters.backend_loaded_ctx("web")),
                bool(dsp_filters.get_filter_state("anr")),
                int(dsp_filters.get_filter_intensity("anr")),
            )
        )
    except Exception:
        _ignore_exception("ignored exception")
    return {
        "stream_in": stream_in,
        "stream_out": stream_out,
        "pulse_mode": _linux_audio_runtime,
        "radio_channels": actual_altavoz_radio_channels,
        "radio_rate": altavoz_radio_framerate,
        "pc_channels": actual_altavoz_pc_channels,
        "pc_rate": altavoz_pc_framerate,
        "frame_size": frame_size,
        "bytes_per_chunk": frame_size * actual_altavoz_radio_channels * 2,
    }


def _linux_process_rx_frame(state: dict) -> None:
    radio_channels = state["radio_channels"]
    radio_rate = state["radio_rate"]
    pc_channels = state["pc_channels"]
    pc_rate = state["pc_rate"]
    frame_size = state["frame_size"]
    stream_in = state["stream_in"]
    stream_out = state["stream_out"]

    if state.get("pulse_mode"):
        stdout = getattr(stream_in, "stdout", None)
        if stdout is None:
            raise RuntimeError("RX pulse capture sin stdout")
        data = _read_exact(stdout, state["bytes_per_chunk"])
    else:
        data = stream_in.read(frame_size, exception_on_overflow=False)
    expected_bytes = frame_size * radio_channels * 2
    data = _domain_pad_or_truncate_frame(data, expected_bytes)
    if rx_capture_gain != 1.0 or rx_hum_reduction:
        muestras = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if rx_hum_reduction:
            muestras -= np.mean(muestras)
        if rx_capture_gain != 1.0:
            muestras *= rx_capture_gain
        np.clip(muestras, -32768, 32767, out=muestras)
        data = muestras.astype(np.int16).tobytes()
    input_data = _atenuar_entrada_radio(data)
    _update_rx_meter_from_pcm(input_data, radio_channels)

    web_data = _rx_cleanup(input_data, radio_channels, radio_rate, gate_enabled=False)
    # Apply RX DSP (ANR) to the WebRTC/web stream too (SDR audio).
    web_data = dsp_filters.process_rx_ctx("web", web_data, radio_rate, radio_channels, frame_size)
    # Digi decoders use a clean branch before user volume/gain controls.
    _push_rx_raw_digi(web_data, radio_channels)
    # El volumen del oyente remoto es WEB_RX_GAIN (más abajo), no
    # volumen_rx: ese es el dial de la consola, la ruta de audio local del
    # PC — independiente de lo que escuche el navegador.
    if gain_mode == "auto":
        web_data = _aplicar_auto_gain(web_data)
    if gain_mode == "manual":
        web_data = _aplicar_gain_manual(web_data)
    if abs(WEB_RX_GAIN - 1.0) > 1e-3:
        web_data = _aplicar_factor_lineal(web_data, WEB_RX_GAIN)
    verificar_datos(web_data, radio_channels)
    _push_rx_raw_web(web_data, radio_channels)

    if stream_out is None:
        return

    if str(config.get("RX_AUDIO_SOURCE", "radio") or "radio").strip().lower() != "sdr":
        data = convertir_canales(input_data, radio_channels, pc_channels)
        data = _rx_cleanup(data, pc_channels, pc_rate, gate_enabled=True)
        data = dsp_filters.process_rx_ctx("gui", data, pc_rate, pc_channels, frame_size)
        data = aplicar_volumen(data, volumen_rx)
        if gain_mode == "auto":
            data = _aplicar_auto_gain(data)
        data = _aplicar_gain_extra_rx(data)
        if gain_mode == "manual":
            data = _aplicar_gain_manual(data)
        data = _reforzar_salida_pc(data)
        verificar_datos(data, pc_channels)
        _push_rx_raw_gui(data, pc_channels)
        if state.get("pulse_mode"):
            stdin = getattr(stream_out, "stdin", None)
            if stdin is None:
                raise RuntimeError("RX pulse playback sin stdin")
            stdin.write(data)
            stdin.flush()
        else:
            stream_out.write(data, exception_on_underflow=False)


def _linux_open_tx_streams(pa):
    actual_microfono_pc_channels, microfono_pc_framerate = verificar_canales_dispositivo(microfono_pc_index, True)
    actual_microfono_radio_channels, microfono_radio_framerate = verificar_canales_dispositivo(microfono_radio_index, False)
    capture_mode = str(_tx_capture_source or "mic").strip().lower()
    if _linux_audio_runtime:
        pulse_source, pulse_source_channels, pulse_source_rate, monitor_stream_index, capture_label = _get_tx_pulse_input_details()
        pulse_sink, pulse_sink_channels, pulse_sink_rate = _get_pulse_device_details("sinks", "Microfono_Radio_Pulse", "Microfono_Radio")
        actual_microfono_pc_channels = int(pulse_source_channels or config.get("Microfono_PC_Channels", 1) or actual_microfono_pc_channels or 1)
        microfono_pc_framerate = int(pulse_source_rate or config.get("Microfono_PC_Framerate", LINUX_AUDIO_RATE) or microfono_pc_framerate or LINUX_AUDIO_RATE)
        actual_microfono_radio_channels = int(pulse_sink_channels or config.get("Microfono_Radio_Channels", 2) or actual_microfono_radio_channels or 2)
        microfono_radio_framerate = int(pulse_sink_rate or config.get("Microfono_Radio_Framerate", LINUX_AUDIO_RATE) or microfono_radio_framerate or LINUX_AUDIO_RATE)
    else:
        pulse_source = None
        monitor_stream_index = None
        pulse_sink = None
        capture_label = "Micrófono PC"

    if not _linux_audio_runtime and (microfono_pc_index == -1 or microfono_radio_index == -1):
        print("TX deshabilitado: faltan dispositivos de captura o reproducción válidos.")
        return None
    if actual_microfono_radio_channels < actual_microfono_pc_channels:
        print(f"Advertencia: El dispositivo de salida no soporta {actual_microfono_pc_channels} canales. Soporta {actual_microfono_radio_channels} canales.")
        return None
    if actual_microfono_pc_channels == 0 or actual_microfono_radio_channels == 0:
        print("Configuración de canales de audio inválida para TX.")
        return None
    _reset_tx_gate_state()
    tx_frame_size = _tx_frame_size_for_rate(microfono_radio_framerate)

    input_label = capture_label if _linux_audio_runtime else ("Monitor Altavoz PC" if capture_mode == "monitor" else "Micrófono PC")
    print(f"TX Stream: Capturando de {input_label} (channels: {actual_microfono_pc_channels}) a Micrófono Radio (channels: {actual_microfono_radio_channels})")
    if _linux_audio_runtime:
        if (not _remote_mode and capture_mode != "app" and not pulse_source) or not pulse_sink:
            print("No se pudieron resolver los dispositivos Pulse para TX.")
            return None
        stream_in = None
        if not _remote_mode:
            if capture_mode == "app":
                stream_in = _open_tx_pulse_input_process(
                    pulse_source=pulse_source if monitor_stream_index is None else None,
                    monitor_stream_index=monitor_stream_index,
                    sample_rate=microfono_pc_framerate,
                    channels=actual_microfono_pc_channels,
                    label=input_label,
                )
            else:
                stream_in = _open_tx_pulse_input_process(
                    pulse_source=pulse_source,
                    monitor_stream_index=None,
                    sample_rate=microfono_pc_framerate,
                    channels=actual_microfono_pc_channels,
                    label=input_label,
                )
        _trace(f"Abriendo TX output pulse: {pulse_sink} rate={microfono_radio_framerate} channels={actual_microfono_radio_channels}")
        _prepare_tx_pulse_sink(pulse_sink)
        stream_out = subprocess.Popen(
            [
                "pacat",
                "--device", pulse_sink,
                "--playback",
                "--format=s16le",
                "--rate", str(microfono_radio_framerate),
                "--channels", str(actual_microfono_radio_channels),
                # TX-only latency budget: smoother uplink without affecting RX path.
                "--latency-msec", str(TX_PULSE_LATENCY_MSEC),
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        _prepare_tx_pulse_sink_input(stream_out, pulse_sink)
        _trace("TX output abierto")
    else:
        stream_in = None
        if not _remote_mode:
            _trace(f"Abriendo TX input: device={microfono_pc_index} rate={microfono_pc_framerate} channels={actual_microfono_pc_channels} frames={tx_frame_size}")
            stream_in = pa.open(
                format=pyaudio.paInt16,
                channels=actual_microfono_pc_channels,
                rate=microfono_pc_framerate,
                input=True,
                input_device_index=microfono_pc_index,
                frames_per_buffer=tx_frame_size,
            )
            _trace("TX input abierto")
        _trace(f"Abriendo TX output: device={microfono_radio_index} rate={microfono_radio_framerate} channels={actual_microfono_radio_channels} frames={tx_frame_size}")
        stream_out = pa.open(
            format=pyaudio.paInt16,
            channels=actual_microfono_radio_channels,
            rate=microfono_radio_framerate,
            output=True,
            output_device_index=microfono_radio_index,
            frames_per_buffer=tx_frame_size,
        )
        _trace("TX output abierto")
    return {
        "stream_in": stream_in,
        "stream_out": stream_out,
        "pulse_mode": _linux_audio_runtime,
        "pulse_sink": pulse_sink,
        "pulse_source": pulse_source,
        "pc_channels": actual_microfono_pc_channels,
        "pc_rate": microfono_pc_framerate,
        "radio_channels": actual_microfono_radio_channels,
        "radio_rate": microfono_radio_framerate,
        "tx_frame_size": tx_frame_size,
        "capture_mode": capture_mode,
        "capture_stream_index": monitor_stream_index,
        "capture_label": input_label,
        "capture_retry_after": 0.0,
    }


def _linux_process_tx_frame(state: dict) -> None:
    global _tx_output_rms, _tx_output_signal_ts
    stream_in = state["stream_in"]
    stream_out = state["stream_out"]
    pc_channels = state["pc_channels"]
    radio_channels = state["radio_channels"]
    radio_rate = state["radio_rate"]
    frame_size = int(state.get("tx_frame_size") or _tx_frame_size_for_rate(radio_rate))
    capture_mode = str(state.get("capture_mode") or "mic").strip().lower()
    pulse_source = state.get("pulse_source")

    # Hard guard: in remote mode never consume local TX capture.
    # If a stale capture process survived a mode flip, close it immediately.
    if _remote_mode and stream_in is not None:
        _close_subprocess_io(stream_in)
        state["stream_in"] = None
        stream_in = None

    if capture_mode == "app":
        _refresh_tx_app_capture_state(state)
        stream_in = state.get("stream_in")
        pc_channels = int(state.get("pc_channels") or pc_channels or 2)

    injected = _pop_tx_inject(radio_rate, frame_size)
    inject_allowed = (_remote_mode or capture_mode == "app" or bool(_tx_tone_active))
    if injected is not None and not inject_allowed:
        # Local mic TX must not be contaminated by stale WebRTC/digi chunks.
        injected = None

    if injected is not None:
        src_channels = 1
        if abs(WEB_TX_GAIN - 1.0) > 1e-3:
            injected = np.clip(injected * WEB_TX_GAIN, -1.0, 1.0)
        data = (np.clip(injected, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    else:
        if stream_in is None:
            src_channels = radio_channels
            data = (np.zeros(frame_size * src_channels, dtype=np.int16)).tobytes()
        else:
            src_channels = pc_channels
            if state.get("pulse_mode"):
                try:
                    if stream_in is None or stream_in.poll() is not None:
                        stream_in = _reopen_tx_pulse_input(state, reason="process_dead")
                        state["stream_in"] = stream_in
                except Exception as exc:
                    _trace(f"TX pulse input caido; reabrir falló: {exc}")
                    stream_in = None
                    state["stream_in"] = None
                if stream_in is None:
                    src_channels = radio_channels
                    data = (np.zeros(frame_size * src_channels, dtype=np.int16)).tobytes()
                else:
                    src_channels = int(state.get("pc_channels") or src_channels or 1)
                    pc_channels = src_channels
                    stdout = getattr(stream_in, "stdout", None)
                    if stdout is None:
                        stream_in = _reopen_tx_pulse_input(state, reason="stdout_none")
                        stdout = getattr(stream_in, "stdout", None) if stream_in is not None else None
                        if stdout is None:
                            raise RuntimeError("TX pulse capture sin stdout")
                    expected_bytes = frame_size * pc_channels * 2
                    data = _read_exact(stdout, expected_bytes)
                    if len(data) < expected_bytes:
                        stream_in = _reopen_tx_pulse_input(state, reason="short_read")
                        stdout = getattr(stream_in, "stdout", None) if stream_in is not None else None
                        if stdout is not None:
                            data = _read_exact(stdout, expected_bytes)
                    if capture_mode == "app" and not data:
                        _trace("TX app capture EOF; reintentando enlazar stream digital")
                        _close_subprocess_io(stream_in)
                        stream_in = None
                        state["stream_in"] = None
                        state["capture_stream_index"] = None
                        state["capture_retry_after"] = 0.0
                        src_channels = radio_channels
                        data = (np.zeros(frame_size * src_channels, dtype=np.int16)).tobytes()
            else:
                data = stream_in.read(frame_size, exception_on_overflow=False)

    if injected is None and stream_in is not None:
        expected_bytes = frame_size * pc_channels * 2
        data = _domain_pad_or_truncate_frame(data, expected_bytes)

    data, _ = _prepare_tx_radio_audio(data, src_channels, radio_channels)
    _tx_diag_capture(
        "pre_cleanup",
        data,
        radio_channels,
        radio_rate,
        extra=f"mode={capture_mode} injected={1 if injected is not None else 0}",
    )
    # TX must be transparent for every capture source (mic/monitor/app):
    # no internal gate/HPF/LPF cleanup, only routing and gain staging.
    external_passthrough = True
    bypass_gate = True
    data = _tx_cleanup(
        data,
        radio_channels,
        radio_rate,
        bypass_gate=bypass_gate,
        bypass_all_processing=external_passthrough,
    )
    _tx_diag_capture(
        "post_cleanup",
        data,
        radio_channels,
        radio_rate,
        extra=(
            f"mode={capture_mode} bypass={1 if bypass_gate else 0} "
            f"external={1 if external_passthrough else 0} "
            f"{_tx_diag_gate_snapshot()}"
        ),
    )
    data = aplicar_volumen(data, volumen_tx)
    if capture_mode == "app":
        data = aplicar_volumen(data, DIGITAL_APP_TX_GAIN)
    try:
        tx_samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        _tx_output_rms = float(np.sqrt(np.mean(tx_samples * tx_samples))) if tx_samples.size else 0.0
        if _tx_output_rms >= 0.01:
            _tx_output_signal_ts = time.monotonic()
    except Exception:
        _tx_output_rms = 0.0
    # The visual meter must represent the exact PCM sent to the radio, including
    # channel conversion and the TX gain selected by the operator.
    _push_raw(_tx_raw_buffer, data, radio_channels)
    verificar_datos(data, radio_channels)
    if state.get("pulse_mode"):
        try:
            if stream_out is None or stream_out.poll() is not None:
                stream_out = _reopen_tx_pulse_output(state)
        except Exception as exc:
            _trace(f"TX pulse output caido; reabrir falló: {exc}")
            return
        if stream_out is None:
            return
        stdin = getattr(stream_out, "stdin", None)
        if stdin is None:
            stream_out = _reopen_tx_pulse_output(state)
            stdin = getattr(stream_out, "stdin", None) if stream_out is not None else None
            if stdin is None:
                raise RuntimeError("TX pulse playback sin stdin")
        try:
            stdin.write(data)
            stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            _trace(f"TX pulse write error; reintentando abrir salida: {exc}")
            stream_out = _reopen_tx_pulse_output(state)
            stdin = getattr(stream_out, "stdin", None) if stream_out is not None else None
            if stdin is None:
                raise RuntimeError("TX pulse playback sin stdin tras reintento")
            stdin.write(data)
            stdin.flush()
    else:
        stream_out.write(data, exception_on_underflow=False)


def _linux_close_runtime_state(state: dict | None) -> None:
    if not state:
        return
    if state.get("pulse_mode"):
        _close_subprocess_io(state.get("stream_in"))
        _close_subprocess_io(state.get("stream_out"))
    else:
        _linux_close_stream(state.get("stream_in"))
        _linux_close_stream(state.get("stream_out"))


def _linux_audio_worker() -> None:
    global _audio_worker_thread
    pa = create_pyaudio(pyaudio)
    current_mode = "idle"
    state = None
    _trace("Linux audio worker iniciado")
    try:
        while True:
            with _state_lock:
                stop = _audio_worker_stop
                target_mode = "idle" if not audio_habilitado else _audio_requested_mode
            if stop:
                break

            if target_mode != current_mode:
                # Este cambio de modo (rx<->tx, el que dispara cada PTT)
                # cierra el subproceso parec/pacat en marcha y abre uno
                # nuevo para el modo destino: un cierre con
                # SIGTERM+wait(timeout=0.5) seguido de un `Popen` nuevo que
                # tiene que renegociar con PulseAudio desde cero, no un
                # simple cambio de una bandera en memoria.
                _linux_close_runtime_state(state)
                state = None
                current_mode = "idle"
                _set_mode_flags("idle")
                if target_mode == "rx":
                    try:
                        state = _linux_open_rx_streams(pa)
                        current_mode = "rx" if state else "idle"
                    except Exception as exc:
                        print(f"Exception abriendo RX: {exc}")
                        state = None
                        current_mode = "idle"
                elif target_mode == "tx":
                    try:
                        state = _linux_open_tx_streams(pa)
                        current_mode = "tx" if state else "idle"
                    except Exception as exc:
                        print(f"Exception abriendo TX: {exc}")
                        state = None
                        current_mode = "idle"
                _set_mode_flags(current_mode)

            if current_mode == "idle" or state is None:
                _audio_worker_event.wait(timeout=0.1)
                _audio_worker_event.clear()
                continue

            try:
                if current_mode == "rx":
                    _linux_process_rx_frame(state)
                elif current_mode == "tx":
                    _linux_process_tx_frame(state)
            except Exception as exc:
                print(f"Exception in {current_mode.upper()} Stream: {exc}")
                _linux_close_runtime_state(state)
                state = None
                current_mode = "idle"
                _set_mode_flags("idle")
                time.sleep(0.1)
            if _audio_worker_event.is_set():
                _audio_worker_event.clear()
    finally:
        _linux_close_runtime_state(state)
        try:
            pa.terminate()
        except Exception:
            _ignore_exception("ignored exception")
        _set_mode_flags("idle")
        with _state_lock:
            _audio_worker_thread = None
        _trace("Linux audio worker detenido")


def _ensure_linux_audio_worker() -> None:
    global _audio_worker_thread, _audio_worker_stop
    if not _linux_audio_runtime:
        return
    with _state_lock:
        if _audio_worker_thread and _audio_worker_thread.is_alive():
            return
        _audio_worker_stop = False
        _audio_worker_thread = threading.Thread(target=_linux_audio_worker, daemon=True, name="linux_audio_worker")
        _audio_worker_thread.start()


def _request_linux_audio_mode(mode: str) -> None:
    global _audio_requested_mode
    with _state_lock:
        if _audio_requested_mode == mode and (
            (mode == "rx" and rx_activo)
            or (mode == "tx" and tx_activo)
            or mode == "idle"
        ):
            return
        _audio_requested_mode = mode
    _ensure_linux_audio_worker()
    _audio_worker_event.set()


def set_remote_mode(enabled: bool) -> None:
    """Disable local monitor/mic while keeping radio I/O for WebRTC."""
    global _remote_mode
    enabled = bool(enabled)
    if _remote_mode == enabled:
        return
    _remote_mode = enabled
    was_tx = tx_activo
    was_rx = rx_activo
    if not enabled and (was_tx and was_rx):
        detener_rx_tx()
        if audio_habilitado:
            if was_tx:
                activar_tx()
            else:
                activar_rx()
        return

    # When switching modes, restart RX to apply frame size changes.
    if was_rx and not was_tx:
        _detener_rx_only()
        if audio_habilitado:
            activar_rx()
    elif was_tx and audio_habilitado:
        # Re-arm TX path so input source follows the new remote/local mode.
        # Linux worker only reopens streams on mode transitions, so force idle->tx.
        if _linux_audio_runtime:
            _request_linux_audio_mode("idle")
            _request_linux_audio_mode("tx")
        else:
            _detener_tx_only()
            activar_tx()
    elif enabled and audio_habilitado:
        # Ensure RX is running in remote full-duplex mode.
        if not rx_activo:
            activar_rx()


def set_tx_capture_source(source: str) -> None:
    global _tx_capture_source
    value = str(source or "mic").strip().lower()
    if value not in {"mic", "monitor", "app"}:
        value = "mic"
    _tx_capture_source = value


def _read_digital_app_ini(path: str) -> dict[str, str]:
    if not path or not os.path.isfile(path):
        return {}
    parser = configparser.ConfigParser()
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except Exception:
        return {}
    if not parser.has_section("Configuration"):
        return {}
    try:
        return dict(parser.items("Configuration"))
    except Exception:
        return {}


def _digital_app_direct_radio_output() -> tuple[bool, str]:
    radio_sink = str(config.get("Microfono_Radio_Pulse", "") or "").strip()
    if not radio_sink:
        return False, ""

    candidates = [
        ("WSJT-X", os.path.expanduser("~/.config/WSJT-X.ini")),
        ("JTDX", os.path.expanduser("~/.config/JTDX.ini")),
    ]
    for app_name, path in candidates:
        values = _read_digital_app_ini(path)
        sound_out = str(values.get("SoundOutName", "") or "").strip()
        if sound_out and sound_out == radio_sink:
            return True, app_name

    try:
        entry = _find_tx_app_sink_input()
    except Exception:
        entry = None
    if entry:
        props = entry.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        target = str(props.get("target.object") or "").strip()
        app_name = str(props.get("application.name") or props.get("application.process.binary") or "App digital").strip()
        sink_index = entry.get("sink")
        if target and target == radio_sink:
            return True, app_name
        if sink_index is not None:
            try:
                sink_index = int(sink_index)
            except (TypeError, ValueError):
                sink_index = None
            if sink_index is not None:
                for sink_entry in _list_pulse_devices("sinks"):
                    try:
                        if int(sink_entry.get("index")) != sink_index:
                            continue
                    except Exception:
                        continue
                    sink_name = str(sink_entry.get("name") or "").strip()
                    if sink_name and sink_name == radio_sink:
                        return True, app_name
                    break
    return False, ""


def tx_capture_needs_local_audio() -> bool:
    capture_mode = str(_tx_capture_source or "mic").strip().lower()
    if capture_mode != "app":
        return True
    direct_output, app_name = _digital_app_direct_radio_output()
    if direct_output:
        label = app_name or "App digital"
        _trace(f"TX CAT: {label} ya entrega audio directo al sink de radio; se omite TX local")
        return False
    return True


def tx_app_capture_available() -> bool:
    """Return True when a known digital app sink-input is currently available."""
    try:
        return _find_tx_app_sink_input() is not None
    except Exception:
        return False


def tx_output_signal_since(since_ts: float, window_s: float = 0.35, min_rms: float = 0.01) -> bool:
    """Return whether real TX audio was emitted after the requested timestamp."""
    return _domain_tx_output_signal_is_ready(
        _tx_output_rms,
        _tx_output_signal_ts,
        since_ts,
        time.monotonic(),
        window_s=window_s,
        min_rms=min_rms,
    )


def pop_tx_raw() -> Optional[np.ndarray]:
    with _raw_lock:
        if not _tx_raw_buffer:
            return None
        samples = _tx_raw_buffer.pop()
        _tx_raw_buffer.clear()
        return samples


def inject_tx_audio(samples: np.ndarray, sample_rate: int) -> None:
    """Inyecta audio TX (float32 mono) desde WebRTC/externo."""
    global _tx_inject_rate
    if samples is None:
        return
    try:
        data = np.asarray(samples, dtype=np.float32).flatten()
    except Exception:
        return
    if data.size == 0:
        return
    rate = int(sample_rate or _tx_inject_rate)
    with _tx_inject_lock:
        _tx_inject_rate = rate
        _tx_inject_buffer.append((data.copy(), rate))


def clear_tx_inject_buffer() -> None:
    """Limpia la cola de audio TX inyectado (WebRTC) para evitar audio viejo."""
    global _tx_inject_last_chunk, _tx_inject_last_time
    global _tx_inject_pending, _tx_inject_pending_rate
    with _tx_inject_lock:
        _tx_inject_buffer.clear()
        _tx_inject_pending = None
        _tx_inject_pending_rate = _tx_inject_rate
    _tx_inject_last_chunk = None
    _tx_inject_last_time = 0.0


def _pop_tx_inject(target_rate: int, frame_size: int) -> Optional[np.ndarray]:
    global _tx_inject_last_warn
    global _tx_inject_last_chunk, _tx_inject_last_time
    global _tx_inject_pending, _tx_inject_pending_rate

    now = time.time()
    with _tx_inject_lock:
        pending = _tx_inject_pending
        pending_rate = _tx_inject_pending_rate
        _tx_inject_pending = None
        _tx_inject_pending_rate = _tx_inject_rate

        chunks = []
        if pending is not None:
            chunks.append((pending, pending_rate))

        while _tx_inject_buffer and sum(c[0].shape[0] for c in chunks) < frame_size:
            chunks.append(_tx_inject_buffer.popleft())

    if not chunks:
        # Short packet-loss concealment to reduce robotic/choppy TX on mobile Wi-Fi jitter.
        if _tx_inject_last_chunk is not None:
            if (now - float(_tx_inject_last_time or 0.0)) <= 0.03:
                return _tx_inject_last_chunk.copy()
        if _remote_mode and tx_activo:
            if now - _tx_inject_last_warn > 3.0:
                _tx_inject_last_warn = now
                _debug("TX WebRTC buffer vacío (no llega audio del navegador)")
        return None

    # Resample cada trozo a target_rate (interpolación lineal, sin aliasing) y
    # arma el frame final: cálculo puro delegado a audio_pcm_domain, ver ahí
    # el porqué (mismo bucle en vivo, mismo lock, solo cambia dónde vive la
    # matemática).
    out_chunks = [_domain_resample_linear(data, src_rate, target_rate) for data, src_rate in chunks]
    samples, leftover = _domain_frame_from_chunks(out_chunks, frame_size)
    if leftover is not None:
        with _tx_inject_lock:
            _tx_inject_pending = leftover
            _tx_inject_pending_rate = target_rate

    _tx_inject_last_chunk = samples.copy()
    _tx_inject_last_time = time.time()
    return samples


def _tx_test_tone_loop(freq_hz: float, level: float, rate: int, frame_size: int) -> None:
    global _tx_tone_active, _tx_tone_thread
    phase = 0.0
    try:
        step = (2.0 * np.pi * float(freq_hz)) / float(rate)
    except Exception:
        step = (2.0 * np.pi * 1000.0) / 48000.0
    frame = max(120, int(frame_size or TX_FRAME_SIZE))
    sr = max(8000, int(rate or 48000))
    lvl = float(max(0.01, min(0.95, float(level or 0.2))))
    sleep_s = float(frame) / float(sr)
    try:
        while not _tx_tone_stop_event.is_set():
            if not bool(tx_activo):
                time.sleep(0.02)
                continue
            chunk, phase = _domain_generate_sine_chunk(phase, step, frame, lvl)
            inject_tx_audio(chunk, sr)
            time.sleep(max(0.004, sleep_s * 0.9))
    except Exception:
        _ignore_exception("ignored exception")
    finally:
        _tx_tone_active = False
        _tx_tone_thread = None


def start_tx_test_tone(freq_hz: float = 1000.0, level: float = 0.22, sample_rate: int = 48000) -> None:
    global _tx_tone_active, _tx_tone_thread
    if _tx_tone_active and _tx_tone_thread and _tx_tone_thread.is_alive():
        return
    _tx_tone_stop_event.clear()
    _tx_tone_active = True
    _tx_tone_thread = threading.Thread(
        target=_tx_test_tone_loop,
        args=(float(freq_hz), float(level), int(sample_rate), int(TX_FRAME_SIZE)),
        daemon=True,
        name="tx_test_tone",
    )
    _tx_tone_thread.start()


def stop_tx_test_tone() -> None:
    global _tx_tone_active, _tx_tone_thread
    _tx_tone_stop_event.set()
    thr = _tx_tone_thread
    if thr and thr.is_alive():
        try:
            thr.join(timeout=0.25)
        except Exception:
            _ignore_exception("ignored exception")
    _tx_tone_active = False
    _tx_tone_thread = None


def tx_test_tone_active() -> bool:
    return bool(_tx_tone_active)

def verificar_datos(data, expected_channels):
    _debug(f"Verificando datos con {expected_channels} canales")
    _domain_verificar_datos(data, expected_channels)

def rx_audio_stream():
    global rx_activo, rx_thread
    global _rx_sample_rate, _rx_channels

    _rx_stopped_event.clear()
    pa = create_pyaudio(pyaudio)
    rx_input_index = _resolve_rx_input_index(altavoz_radio_index)
    actual_altavoz_radio_channels, altavoz_radio_framerate = verificar_canales_dispositivo(rx_input_index, True)
    actual_altavoz_pc_channels, altavoz_pc_framerate = verificar_canales_dispositivo(altavoz_pc_index, False)

    if rx_input_index == -1 or altavoz_pc_index == -1:
        print("RX deshabilitado: faltan dispositivos de captura o reproducción válidos.")
        _mark_rx_thread_stopped()
        return

    if actual_altavoz_pc_channels < actual_altavoz_radio_channels and not _remote_mode:
        print(f"Advertencia: El dispositivo de salida no soporta {actual_altavoz_radio_channels} canales. Soporta {actual_altavoz_pc_channels} canales.")
        _mark_rx_thread_stopped()
        return

    print(f"RX Stream: Capturando de Altavoz Radio (channels: {actual_altavoz_radio_channels}) a Altavoz PC (channels: {actual_altavoz_pc_channels})")

    if actual_altavoz_radio_channels == 0 or actual_altavoz_pc_channels == 0:
        print("ConfiguraciÃƒÂ³n de canales de audio invÃƒÂ¡lida para RX.")
        _mark_rx_thread_stopped()
        return

    # WebRTC should follow the capture rate to avoid resampling artifacts.
    _rx_sample_rate = int(altavoz_radio_framerate or _rx_sample_rate)
    _rx_channels = int(actual_altavoz_radio_channels or 1)

    frame_size = WEB_RX_FRAME_SIZE if _remote_mode else DSP_FRAME_SIZE
    with _stream_open_lock:
        _trace(f"Abriendo RX input: device={rx_input_index} rate={altavoz_radio_framerate} channels={actual_altavoz_radio_channels} frames={frame_size}")
        stream_in = pa.open(
            format=pyaudio.paInt16,
            channels=actual_altavoz_radio_channels,
            rate=altavoz_radio_framerate,
            input=True,
            input_device_index=rx_input_index,
            frames_per_buffer=frame_size,
        )
        _trace("RX input abierto")
    stream_out = None
    if not _remote_mode:
        with _stream_open_lock:
            _trace(f"Abriendo RX output: device={altavoz_pc_index} rate={altavoz_pc_framerate} channels={actual_altavoz_pc_channels} frames={frame_size}")
            stream_out = pa.open(
                format=pyaudio.paInt16,
                channels=actual_altavoz_pc_channels,
                rate=altavoz_pc_framerate,
                output=True,
                output_device_index=altavoz_pc_index,
                frames_per_buffer=frame_size,
            )
            _trace("RX output abierto")
    if not rx_activo:
        _trace("RX cancelado antes del bucle principal")
        try:
            stream_in.close()
        except Exception:
            _ignore_exception("ignored exception")
        if stream_out is not None:
            try:
                stream_out.close()
            except Exception:
                _ignore_exception("ignored exception")
        try:
            pa.terminate()
        except Exception:
            _ignore_exception("ignored exception")
        _mark_rx_thread_stopped()
        return
    # Keep separate DSP contexts for local output ("gui") and WebRTC/web streaming ("web")
    # so sample-rate/channel mismatches don't cause constant reconfiguration.
    dsp_filters.configure_ctx(
        "web",
        altavoz_radio_framerate,
        actual_altavoz_radio_channels,
        frame_size,
        config=config,
    )
    if not _remote_mode:
        dsp_filters.configure_ctx(
            "gui",
            altavoz_pc_framerate,
            actual_altavoz_pc_channels,
            frame_size,
            config=config,
        )
    # Esta lectura es bloqueante: si `stream_in.read()` tarda mucho más de
    # lo que le corresponde a un chunk de `frame_size` muestras a
    # `altavoz_radio_framerate` Hz, deja de producir audio para todo lo que
    # depende de este bucle (incluido `_push_rx_raw_web`) sin lanzar
    # ninguna excepción por el camino — no queda ningún rastro salvo el
    # propio hueco de audio.
    try:
        while rx_activo:
            data = stream_in.read(frame_size, exception_on_overflow=False)
            # Quick exit check after blocking read for instant PTT response
            if not rx_activo:
                break
            _debug(f"Read data with shape {len(data)} and channels {actual_altavoz_radio_channels}")
            expected_bytes = frame_size * actual_altavoz_radio_channels * 2
            if len(data) != expected_bytes:
                _debug(f"RX frame incompleto: {len(data)} bytes (esperado {expected_bytes})")
            data = _domain_pad_or_truncate_frame(data, expected_bytes)
            if rx_capture_gain != 1.0 or rx_hum_reduction:
                muestras = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                if rx_hum_reduction:
                    muestras -= np.mean(muestras)
                if rx_capture_gain != 1.0:
                    muestras *= rx_capture_gain
                np.clip(muestras, -32768, 32767, out=muestras)
                data = muestras.astype(np.int16).tobytes()
            input_data = _atenuar_entrada_radio(data)
            _update_rx_meter_from_pcm(input_data, actual_altavoz_radio_channels)

            # WebRTC RX: prefer raw input rate/channels (avoid output resample drift).
            web_data = _rx_cleanup(
                input_data,
                actual_altavoz_radio_channels,
                altavoz_radio_framerate,
                gate_enabled=False,
            )
            # Apply RX DSP (ANR) to the WebRTC/web stream too (SDR audio).
            web_data = dsp_filters.process_rx_ctx(
                "web",
                web_data,
                altavoz_radio_framerate,
                actual_altavoz_radio_channels,
                frame_size,
            )
            # Digi decoders use a clean branch before user volume/gain controls.
            _push_rx_raw_digi(web_data, actual_altavoz_radio_channels)

            # Continue with the existing WebRTC processing chain. El volumen
            # del oyente remoto es WEB_RX_GAIN (más abajo), no volumen_rx (el
            # dial de la consola, ruta de audio local del PC).
            if gain_mode == "auto":
                web_data = _aplicar_auto_gain(web_data)
            if gain_mode == "manual":
                web_data = _aplicar_gain_manual(web_data)
            if abs(WEB_RX_GAIN - 1.0) > 1e-3:
                web_data = _aplicar_factor_lineal(web_data, WEB_RX_GAIN)
            verificar_datos(web_data, actual_altavoz_radio_channels)
            _push_rx_raw_web(web_data, actual_altavoz_radio_channels)

            if not _remote_mode and str(config.get("RX_AUDIO_SOURCE", "radio") or "radio").strip().lower() != "sdr":
                # Local RX keeps gate and uses output rate/channels.
                data = convertir_canales(input_data, actual_altavoz_radio_channels, actual_altavoz_pc_channels)
                _debug(f"Converted data to channels {actual_altavoz_pc_channels}")
                data = _rx_cleanup(data, actual_altavoz_pc_channels, altavoz_pc_framerate, gate_enabled=True)
                data = dsp_filters.process_rx_ctx(
                    "gui",
                    data,
                    altavoz_pc_framerate,
                    actual_altavoz_pc_channels,
                    frame_size,
                )
                data = aplicar_volumen(data, volumen_rx)
                if gain_mode == "auto":
                    data = _aplicar_auto_gain(data)
                data = _aplicar_gain_extra_rx(data)
                if gain_mode == "manual":
                    data = _aplicar_gain_manual(data)
                data = _reforzar_salida_pc(data)
                verificar_datos(data, actual_altavoz_pc_channels)
                _push_rx_raw_gui(data, actual_altavoz_pc_channels)
                if stream_out is not None:
                    _debug(f"Writing data with {actual_altavoz_pc_channels} channels to output stream")
                    stream_out.write(data, exception_on_underflow=False)
    except Exception as e:
        print(f"Exception in RX Stream: {e}")
    finally:
        for stream in (stream_in, stream_out):
            try:
                if stream.is_active():
                    stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                _ignore_exception("ignored exception")
        try:
            pa.terminate()
        except Exception:
            _ignore_exception("ignored exception")
        _mark_rx_thread_stopped()

def tx_audio_stream():
    global tx_activo, tx_thread

    _tx_stopped_event.clear()
    pa = create_pyaudio(pyaudio)
    actual_microfono_pc_channels, microfono_pc_framerate = verificar_canales_dispositivo(microfono_pc_index, True)
    actual_microfono_radio_channels, microfono_radio_framerate = verificar_canales_dispositivo(microfono_radio_index, False)

    if microfono_pc_index == -1 or microfono_radio_index == -1:
        print("TX deshabilitado: faltan dispositivos de captura o reproducción válidos.")
        _mark_tx_thread_stopped()
        return

    if actual_microfono_radio_channels < actual_microfono_pc_channels:
        print(f"Advertencia: El dispositivo de salida no soporta {actual_microfono_pc_channels} canales. Soporta {actual_microfono_radio_channels} canales.")
        _mark_tx_thread_stopped()
        return

    print(f"TX Stream: Capturando de MicrÃƒÂ³fono PC (channels: {actual_microfono_pc_channels}) a MicrÃƒÂ³fono Radio (channels: {actual_microfono_radio_channels})")

    if actual_microfono_pc_channels == 0 or actual_microfono_radio_channels == 0:
        print("ConfiguraciÃƒÂ³n de canales de audio invÃƒÂ¡lida para TX.")
        _mark_tx_thread_stopped()
        return
    _reset_tx_gate_state()
    tx_frame_size = _tx_frame_size_for_rate(microfono_radio_framerate)

    stream_in = None
    if not _remote_mode:
        with _stream_open_lock:
            _trace(f"Abriendo TX input: device={microfono_pc_index} rate={microfono_pc_framerate} channels={actual_microfono_pc_channels} frames={tx_frame_size}")
            stream_in = pa.open(format=pyaudio.paInt16, channels=actual_microfono_pc_channels,
                                rate=microfono_pc_framerate, input=True, input_device_index=microfono_pc_index,
                                frames_per_buffer=tx_frame_size)
            _trace("TX input abierto")
    with _stream_open_lock:
        _trace(f"Abriendo TX output: device={microfono_radio_index} rate={microfono_radio_framerate} channels={actual_microfono_radio_channels} frames={tx_frame_size}")
        stream_out = pa.open(format=pyaudio.paInt16, channels=actual_microfono_radio_channels,
                            rate=microfono_radio_framerate, output=True, output_device_index=microfono_radio_index,
                            frames_per_buffer=tx_frame_size)
        _trace("TX output abierto")
    if not tx_activo:
        _trace("TX cancelado antes del bucle principal")
        if stream_in is not None:
            try:
                stream_in.close()
            except Exception:
                _ignore_exception("ignored exception")
        try:
            stream_out.close()
        except Exception:
            _ignore_exception("ignored exception")
        try:
            pa.terminate()
        except Exception:
            _ignore_exception("ignored exception")
        _mark_tx_thread_stopped()
        return
    try:
        configured_source = str(config.get("Microfono_PC_Pulse", "") or config.get("Microfono_PC", "") or "")
        while tx_activo:
            injected = _pop_tx_inject(microfono_radio_framerate, tx_frame_size)
            inject_allowed = (_remote_mode or bool(_tx_tone_active))
            if injected is not None and not inject_allowed:
                # Fallback TX loop: ignore injected chunks unless remote/tone TX is active.
                injected = None

            if injected is not None:
                # WebRTC mic arrives as mono float32.
                src_channels = 1
                if abs(WEB_TX_GAIN - 1.0) > 1e-3:
                    injected = np.clip(injected * WEB_TX_GAIN, -1.0, 1.0)
                data = (np.clip(injected, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
            else:
                if stream_in is None:
                    # No local mic and no injected audio: send silence.
                    src_channels = actual_microfono_radio_channels
                    data = (np.zeros(tx_frame_size * src_channels, dtype=np.int16)).tobytes()
                else:
                    src_channels = actual_microfono_pc_channels
                    data = stream_in.read(tx_frame_size, exception_on_overflow=False)
            # Quick exit check after blocking operations for instant PTT response
            if not tx_activo:
                break
            _debug(f"Read data with shape {len(data)} and channels {src_channels}")
            if injected is None and stream_in is not None:
                expected_bytes = tx_frame_size * actual_microfono_pc_channels * 2
                if len(data) != expected_bytes:
                    _debug(f"TX frame incompleto: {len(data)} bytes (esperado {expected_bytes})")
                data = _domain_pad_or_truncate_frame(data, expected_bytes)
            data, _ = _prepare_tx_radio_audio(data, src_channels, actual_microfono_radio_channels)
            _tx_diag_capture(
                "pre_cleanup_fallback",
                data,
                actual_microfono_radio_channels,
                microfono_radio_framerate,
                extra=f"injected={1 if injected is not None else 0}",
            )
            # Keep fallback TX path fully transparent too.
            external_passthrough = True
            bypass_gate = True
            data = _tx_cleanup(
                data,
                actual_microfono_radio_channels,
                microfono_radio_framerate,
                bypass_gate=bypass_gate,
                bypass_all_processing=external_passthrough,
            )
            _tx_diag_capture(
                "post_cleanup_fallback",
                data,
                actual_microfono_radio_channels,
                microfono_radio_framerate,
                extra=(
                    f"bypass={1 if bypass_gate else 0} "
                    f"external={1 if external_passthrough else 0} "
                    f"{_tx_diag_gate_snapshot()}"
                ),
            )
            _debug(f"Converted data to channels {actual_microfono_radio_channels}")
            data = aplicar_volumen(data, volumen_tx)
            _push_raw(_tx_raw_buffer, data, actual_microfono_radio_channels)
            verificar_datos(data, actual_microfono_radio_channels)
            _debug(f"Writing data with {actual_microfono_radio_channels} channels to output stream")
            stream_out.write(data, exception_on_underflow=False)
    except Exception as e:
        print(f"Exception in TX Stream: {e}")
    finally:
        if stream_in is not None:
            stream_in.close()
        stream_out.close()
        try:
            pa.terminate()
        except Exception:
            _ignore_exception("ignored exception")
        _mark_tx_thread_stopped()

def activar_rx():
    global rx_activo, rx_thread
    _trace(f"activar_rx solicitado: audio_habilitado={audio_habilitado} rx_activo={rx_activo} tx_activo={tx_activo}")
    if _linux_audio_runtime:
        if not audio_habilitado:
            return
        _request_linux_audio_mode("rx")
        return
    with _state_lock:
        if not audio_habilitado:
            return
        if not _remote_mode and tx_activo:
            _detener_tx_only(wait=True)
        if rx_activo and rx_thread and rx_thread.is_alive():
            return
        _rx_stopped_event.clear()
        rx_activo = True
        rx_thread = threading.Thread(target=rx_audio_stream, daemon=True, name="rx_audio")
        rx_thread.start()


def _detener_rx_only(wait: bool = False) -> None:
    global rx_activo, rx_thread
    thread = rx_thread
    rx_activo = False
    if wait and thread and thread.is_alive() and threading.current_thread() is not thread:
        _rx_stopped_event.wait(timeout=1.5)
        thread.join(timeout=0.2)
    if thread and not thread.is_alive():
        rx_thread = None


def _detener_tx_only(wait: bool = False) -> None:
    global tx_activo, tx_thread
    thread = tx_thread
    tx_activo = False
    if wait and thread and thread.is_alive() and threading.current_thread() is not thread:
        _tx_stopped_event.wait(timeout=1.5)
        thread.join(timeout=0.2)
    if thread and not thread.is_alive():
        tx_thread = None


def activar_tx():
    global tx_activo, tx_thread
    _trace(f"activar_tx solicitado: audio_habilitado={audio_habilitado} rx_activo={rx_activo} tx_activo={tx_activo}")
    for line in traceback.format_stack(limit=5):
        _trace(line.rstrip())
    if _linux_audio_runtime:
        if not audio_habilitado:
            return
        _request_linux_audio_mode("tx")
        return
    with _state_lock:
        if not audio_habilitado:
            return
        if not _remote_mode and rx_activo:
            _detener_rx_only(wait=True)
        if tx_activo and tx_thread and tx_thread.is_alive():
            return
        _tx_stopped_event.clear()
        tx_activo = True
        tx_thread = threading.Thread(target=tx_audio_stream, daemon=True, name="tx_audio")
        tx_thread.start()


def detener_rx_tx():
    global rx_activo, tx_activo, rx_thread, tx_thread
    if _linux_audio_runtime:
        with _state_lock:
            rx_activo = False
            tx_activo = False
        _request_linux_audio_mode("idle")
        _agc_state["gain"] = 1.0
        return
    with _state_lock:
        _detener_rx_only(wait=True)
        _detener_tx_only(wait=True)
        _agc_state["gain"] = 1.0


def habilitar_audio_para_radio(estado: bool):
    """Control externo para iniciar/detener los flujos de audio con el estado de la radio."""
    global audio_habilitado
    estado = bool(estado)
    if audio_habilitado == estado and ((estado and rx_activo) or (not estado and not rx_activo)):
        return
    audio_habilitado = estado
    if audio_habilitado:
        activar_rx()
    else:
        detener_rx_tx()


def habilitar_audio_en_modo(modo: str):
    """Habilita el audio local arrancando directamente en RX o TX."""
    global audio_habilitado
    modo = "tx" if str(modo).lower() == "tx" else "rx"
    audio_habilitado = True
    if _linux_audio_runtime:
        _request_linux_audio_mode(modo)
        return
    if modo == "tx":
        activar_tx()
    else:
        activar_rx()


def habilitar_audio(estado: bool):
    """API compatible para activar/desactivar audio desde otros mÃ³dulos."""
    habilitar_audio_para_radio(estado)


roger_beep_lock = threading.Lock()

def _obtener_config_radio():
    channels = int(config.get("Microfono_Radio_Channels", 1) or 1)
    framerate = int(config.get("Microfono_Radio_Framerate", 48000) or 48000)
    return channels, framerate

def _get_ffmpeg_binary() -> str:
    return config.get("FFMPEG_BINARY") or config.get("FFMPEG_PATH") or "ffmpeg"

def _abrir_stream_radio(channels: int, framerate: int):
    if microfono_radio_index is None or microfono_radio_index == -1:
        print("Microfono_Radio_Index no estÃƒÂ¡ configurado.")
        return None
    try:
        return p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=framerate,
            output=True,
            output_device_index=microfono_radio_index,
            frames_per_buffer=1024
        )
    except Exception as exc:
        print(f"Error al abrir el dispositivo de salida para Roger Beep: {exc}")
        return None

def _crear_decodificador_ffmpeg(path: str, framerate: int, channels: int):
    ffmpeg_bin = _get_ffmpeg_binary()
    if not os.path.isfile(path):
        print(f"Archivo de audio no encontrado: {path}")
        return None

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(framerate),
        "-ac",
        str(channels),
        "-",
    ]

    startupinfo = None
    creationflags = 0
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except FileNotFoundError:
        print("ffmpeg no encontrado. Configura 'FFMPEG_BINARY' en config.json o aÃƒÂ±ade ffmpeg al PATH.")
        return None
    except Exception as exc:
        print(f"Error al invocar ffmpeg: {exc}")
        return None

    if not process.stdout:
        print("No se pudo obtener la salida de ffmpeg.")
        process.kill()
        return None
    return process


def _reproducir_stream_ffmpeg(path: str, framerate: int, channels: int, stop_checker: Optional[Callable[[], bool]], lock: Optional[threading.Lock]) -> bool:
    process = _crear_decodificador_ffmpeg(path, framerate, channels)
    if not process or not process.stdout:
        return False

    stream = None
    pulse_out = None
    if _linux_audio_runtime:
        pulse_sink, _sink_channels, _sink_rate = _get_pulse_device_details(
            "sinks",
            "Microfono_Radio_Pulse",
            "Microfono_Radio",
        )
        if not pulse_sink:
            print("No se pudo resolver el sink Pulse para Microfono_Radio.")
            if process.poll() is None:
                process.terminate()
            return False
        _prepare_tx_pulse_sink(pulse_sink)
        try:
            pulse_out = subprocess.Popen(
                [
                    "pacat",
                    "--device",
                    pulse_sink,
                    "--playback",
                    "--format=s16le",
                    "--rate",
                    str(framerate),
                    "--channels",
                    str(channels),
                    "--latency-msec",
                    str(PULSE_LATENCY_MSEC),
                ],
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            print(f"Error al abrir pacat para autollamada: {exc}")
            if process.poll() is None:
                process.terminate()
            return False
    else:
        stream = _abrir_stream_radio(channels, framerate)
        if stream is None:
            if process.poll() is None:
                process.terminate()
            return False

    lock_obj = lock
    acquired = False
    try:
        if lock_obj is not None:
            lock_obj.acquire()
            acquired = True

        while True:
            if stop_checker and stop_checker():
                process.terminate()
                break
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            if pulse_out is not None:
                stdin = getattr(pulse_out, "stdin", None)
                if stdin is None:
                    raise RuntimeError("pacat sin stdin para autollamada")
                stdin.write(chunk)
                stdin.flush()
            elif stream is not None:
                stream.write(chunk)
        return_code = process.wait()
        if return_code not in (0, -15, None):
            stderr = process.stderr.read().decode(errors="ignore") if process.stderr else ""
            if stderr:
                print(f"ffmpeg finalizÃƒÂ³ con errores: {stderr.strip()}")
        return True
    except Exception as exc:
        print(f"Error durante la reproducciÃƒÂ³n de audio con ffmpeg: {exc}")
        return False
    finally:
        if acquired and lock_obj is not None:
            try:
                lock_obj.release()
            except RuntimeError:
                pass
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                _ignore_exception("ignored exception")
        if pulse_out is not None:
            _close_subprocess_io(pulse_out)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass


def reproducir_audio_en_radio(path: str, wait: bool = True, stop_checker: Optional[Callable[[], bool]] = None, lock: Optional[threading.Lock] = None) -> bool:
    desired_channels, desired_rate = _obtener_config_radio()

    def _worker():
        return _reproducir_stream_ffmpeg(path, desired_rate, desired_channels, stop_checker, lock)

    if wait:
        return _worker()

    threading.Thread(target=_worker, daemon=True).start()
    return True

def reproducir_roger_beep(path, wait=False):
    if not path or not os.path.isfile(path):
        print(f"Archivo de Roger Beep no vÃƒÂ¡lido: {path}")
        return False

    return reproducir_audio_en_radio(path, wait=wait, lock=roger_beep_lock)

# FunciÃƒÂ³n para activar/desactivar el PTT
def activar_ptt():
    if _remote_mode:
        if not tx_activo:
            activar_tx()
        return
    activar_tx()

def desactivar_ptt():
    if _remote_mode:
        if _linux_audio_runtime:
            if audio_habilitado:
                _request_linux_audio_mode("rx")
            else:
                _request_linux_audio_mode("idle")
        else:
            _detener_tx_only()
            if audio_habilitado:
                activar_rx()
        return
    activar_rx()

def is_tx_active() -> bool:
    return bool(tx_activo)

def is_rx_active() -> bool:
    return bool(rx_activo)

# FunciÃƒÂ³n para iniciar/detener el audio
def activar_audio():
    habilitar_audio_para_radio(True)

def desactivar_audio():
    detener_rx_tx()

# Funciones para ajustar el volumen
def set_volumen_tx(value):
    global volumen_tx
    volumen_tx = value / 100.0

def set_volumen_rx(value):
    global volumen_rx
    volumen_rx = value / 100.0

def set_web_rx_gain(value):
    """Ganancia del audio RX que se manda al navegador por WebRTC (0.0-1.0
    lineal, no 0-100 como ``set_volumen_rx``: así llega ya el slider web).
    Independiente de ``volumen_rx`` (el de la ruta de audio local de la
    consola), que no afecta en nada a lo que oye el navegador."""
    global WEB_RX_GAIN
    WEB_RX_GAIN = max(0.0, float(value))

def set_web_tx_gain(value):
    """Igual que :func:`set_web_rx_gain`, para el audio TX inyectado desde
    el micrófono del navegador."""
    global WEB_TX_GAIN
    WEB_TX_GAIN = max(0.0, float(value))


def set_rx_source(source: str) -> None:
    """Update RX source in audio runtime to avoid stale config while switching."""
    try:
        src = str(source or "").strip().lower()
    except Exception:
        src = ""
    if src not in ("radio", "sdr"):
        src = "radio"
    config["RX_AUDIO_SOURCE"] = src


def set_owrx_pid(pid: Optional[int]) -> None:
    """PID del proceso del visor nativo de OWRX para rutear su audio en Pulse."""
    global _owrx_pid
    try:
        _owrx_pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        _owrx_pid = None


def set_owrx_sink_muted(muted: bool, attempts: int = 1, delay_s: float = 0.12) -> None:
    """Mute/unmute OWRX sink-input(s) with optional retries while stream appears."""
    def _worker():
        n = max(1, int(attempts))
        wait_s = max(0.02, float(delay_s))
        for _ in range(n):
            try:
                _set_owrx_sink_input_muted(bool(muted))
            except Exception:
                _ignore_exception("ignored exception")
            time.sleep(wait_s)

    try:
        if int(attempts) <= 1:
            _set_owrx_sink_input_muted(bool(muted))
            return
    except Exception:
        _ignore_exception("ignored exception")
    threading.Thread(target=_worker, daemon=True, name="owrx_sink_mute").start()


def push_owrx_audio_chunk(data: bytes, sample_rate: int, channels: int) -> None:
    global _sdr_capture_ts, _sdr_input_rate, _sdr_input_channels
    global _sdr_chunk_drop_total, _sdr_chunk_enqueue_fail_total
    if not data:
        return
    try:
        sample_rate = int(sample_rate)
        channels = int(channels)
    except (TypeError, ValueError):
        return
    if sample_rate <= 0 or channels <= 0:
        return
    _sdr_capture_ts = time.monotonic()
    _sdr_input_rate = sample_rate
    _sdr_input_channels = channels
    count = 0
    now = time.monotonic()
    try:
        count = int(getattr(push_owrx_audio_chunk, "_count", 0) or 0) + 1
        setattr(push_owrx_audio_chunk, "_count", count)
    except Exception:
        _ignore_exception("ignored exception")
    q_before = 0
    q_after = 0
    soft_drop = 0
    enqueue_ok = False
    try:
        q_before = int(_sdr_input_queue.qsize())
    except Exception:
        q_before = 0
    try:
        try:
            # Keep queue close to real-time to avoid long-delay playback bursts.
            while _sdr_input_queue.qsize() >= SDR_QUEUE_SOFT_LIMIT:
                _sdr_input_queue.get_nowait()
                soft_drop += 1
        except Exception:
            _ignore_exception("ignored exception")
        _sdr_input_queue.put_nowait((bytes(data), sample_rate, channels))
        enqueue_ok = True
    except queue.Full:
        try:
            _sdr_input_queue.get_nowait()
            soft_drop += 1
        except Exception:
            _ignore_exception("ignored exception")
        _sdr_chunk_enqueue_fail_total = int(_sdr_chunk_enqueue_fail_total or 0) + 1
    try:
        if soft_drop > 0:
            _sdr_chunk_drop_total = int(_sdr_chunk_drop_total or 0) + int(soft_drop)
    except Exception:
        _ignore_exception("ignored exception")
    try:
        q_after = int(_sdr_input_queue.qsize())
    except Exception:
        q_after = 0
    try:
        last = float(getattr(push_owrx_audio_chunk, "_last_log", 0.0) or 0.0)
        if now - last > 1.0:
            setattr(push_owrx_audio_chunk, "_last_log", now)
            prev_ts = float(getattr(push_owrx_audio_chunk, "_last_chunk_ts", 0.0) or 0.0)
            dt_ms = (now - prev_ts) * 1000.0 if prev_ts > 0.0 else 0.0
            setattr(push_owrx_audio_chunk, "_last_chunk_ts", now)
            _trace(
                "OWRX chunk enqueue count=%s rate=%s ch=%s bytes=%s q_before=%s q_after=%s "
                "soft_drop=%s drop_total=%s enq_fail_total=%s dt_ms=%.1f enq_ok=%s"
                % (
                    int(count),
                    int(sample_rate),
                    int(channels),
                    int(len(data)),
                    int(q_before),
                    int(q_after),
                    int(soft_drop),
                    int(_sdr_chunk_drop_total or 0),
                    int(_sdr_chunk_enqueue_fail_total or 0),
                    float(dt_ms),
                    bool(enqueue_ok),
                )
            )
    except Exception:
        _ignore_exception("ignored exception")


def _fade_in_pcm16(data: bytes, channels: int, fade_ms: int, rate: int = 48000) -> bytes:
    return _domain_fade_in_pcm16(data, channels, fade_ms, rate)


def _soft_repeat_block_pcm16(data: bytes, decay: float = 0.96) -> bytes:
    """Return a softened copy of the last valid block to mask short underruns."""
    return _domain_soft_repeat_block_pcm16(data, decay)


def set_volumen_sdr(value: float) -> None:
    """Volumen (0-100) para el audio SDR capturado desde OpenWebRX."""
    global _sdr_volume
    try:
        vol = float(value)
    except (TypeError, ValueError):
        vol = 0.0
    vol = max(0.0, min(100.0, vol))
    _sdr_volume = vol / 100.0


def set_sdr_paused(paused: bool) -> None:
    """Pausa la reproducción del audio SDR (útil durante PTT para evitar retorno)."""
    global _sdr_paused, _sdr_resume_drop, _sdr_prebuffering
    _sdr_paused = bool(paused)
    if _sdr_paused:
        # Drop pending buffered audio for immediate mute on TX/PTT.
        _sdr_input_buffer.clear()
        while True:
            try:
                _sdr_input_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
        _sdr_prebuffering = True
        return
    if not _sdr_paused:
        # Drop a few frames to avoid stale audio after PTT.
        _sdr_resume_drop = max(1, min(2, int(SDR_BATCH_FRAMES)))
        _sdr_prebuffering = True


def set_sdr_output_active(active: bool) -> None:
    """Controla si el audio SDR procesado debe reproducirse/mostrarse."""
    global _sdr_output_active, _sdr_prebuffering
    new_state = bool(active)
    if new_state and not _sdr_output_active:
        _sdr_prebuffering = True
    _sdr_output_active = new_state


def owrx_sdr_last_rms() -> float:
    return float(_sdr_last_rms)


def owrx_sdr_has_signal(window_s: float = 2.0) -> bool:
    """True si se detectó señal reciente del flujo SDR real."""
    try:
        return (time.monotonic() - float(_sdr_signal_ts or 0.0)) <= float(window_s)
    except Exception:
        return False


def owrx_sdr_capture_active(window_s: float = 2.0) -> bool:
    try:
        return (time.monotonic() - float(_sdr_capture_ts or 0.0)) <= float(window_s)
    except Exception:
        return False


def owrx_sdr_output_flowing(window_s: float = 2.0) -> bool:
    try:
        return (time.monotonic() - float(_sdr_output_ts or 0.0)) <= float(window_s)
    except Exception:
        return False


def _sink_inputs_for_pid(pid: int) -> list[dict]:
    if not pid:
        return []
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
    except Exception:
        return []
    out = []
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        props = entry.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        proc_id = props.get("application.process.id")
        try:
            proc_id_int = int(proc_id) if proc_id is not None else None
        except (TypeError, ValueError):
            proc_id_int = None
        if proc_id_int == int(pid):
            out.append(entry)
    return out


def owrx_sdr_playback_active() -> bool:
    """True si nuestro pacat de SDR está generando un sink-input."""
    pid = _sdr_pacat_pid
    try:
        pid_int = int(pid) if pid is not None else 0
    except (TypeError, ValueError):
        pid_int = 0
    if pid_int <= 1:
        return False
    return bool(_sink_inputs_for_pid(pid_int))


def owrx_sdr_anr_supported() -> bool:
    """Devuelve True si Linux puede rutear OWRX directo y reproducir su ruta procesada."""
    if not _linux_audio_runtime:
        return False
    return all(shutil.which(tool) for tool in ("pactl", "pacat"))


def owrx_sdr_processing_available() -> bool:
    """True si el contexto DSP real del SDR ha cargado el backend nativo."""
    try:
        return bool(dsp_filters.backend_loaded_ctx("sdr_gui"))
    except Exception:
        return False


def owrx_sdr_anr_enabled() -> bool:
    return bool(_sdr_enabled)


def owrx_sdr_sink_name() -> str:
    """Compat: ya no se usa un sink dedicado para el aislamiento SDR."""
    return ""


def _pactl_capture(*args: str) -> str:
    try:
        result = subprocess.run(
            ["pactl", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _get_default_sink() -> str:
    sink = _pactl_capture("get-default-sink")
    return str(sink or "").strip()


def _ensure_sdr_null_sink() -> bool:
    global _sdr_pulse_module_id
    if not owrx_sdr_anr_supported():
        return False
    if _sdr_pulse_module_id is not None:
        return True
    _cleanup_sdr_null_sink()
    try:
        result = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                f"sink_name={_SDR_NULL_SINK_NAME}",
                (
                    "sink_properties="
                    f"device.description={_SDR_NULL_SINK_DESC},"
                    "node.hidden=true,"
                    "node.virtual=true,"
                    "media.class=Audio/Sink"
                ),
                "rate=48000",
                "channels=2",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (result.stdout or "").strip()
        if out.isdigit():
            _sdr_pulse_module_id = int(out)
            sinks = _pactl_capture("list", "short", "sinks")
            if _SDR_NULL_SINK_NAME in sinks:
                return True
            return False
    except Exception:
        _ignore_exception("ignored exception")
    sinks = _pactl_capture("list", "short", "sinks")
    return _SDR_NULL_SINK_NAME in sinks


def _cleanup_sdr_null_sink() -> None:
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "modules"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (result.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            mod_id, mod_name, mod_args = parts[0], parts[1], parts[2]
            if mod_name != "module-null-sink":
                continue
            if f"sink_name={_SDR_NULL_SINK_NAME}" not in mod_args:
                continue
            try:
                _run_pactl("unload-module", str(mod_id))
            except Exception:
                _ignore_exception("ignored exception")
    except Exception:
        _ignore_exception("ignored exception")


def _unload_sdr_null_sink() -> None:
    global _sdr_pulse_module_id
    module_id = _sdr_pulse_module_id
    _sdr_pulse_module_id = None
    if module_id is not None:
        try:
            _run_pactl("unload-module", str(module_id))
        except Exception:
            _ignore_exception("ignored exception")
    # Also remove a matching module left by an interrupted or previous process.
    _cleanup_sdr_null_sink()


def _move_sink_inputs_for_pid(pid: int, target_sink: str) -> None:
    if not pid or not target_sink:
        return
    _move_sink_inputs_for_pids({int(pid)}, target_sink)


def _move_sink_inputs_for_pids(pids: set[int], target_sink: str) -> None:
    if not pids or not target_sink:
        return
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
    except Exception:
        payload = []
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        props = entry.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        proc_id = props.get("application.process.id")
        try:
            proc_id_int = int(proc_id) if proc_id is not None else None
        except (TypeError, ValueError):
            proc_id_int = None
        if proc_id_int is None or proc_id_int not in pids:
            continue
        idx = entry.get("index")
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        _run_pactl("move-sink-input", str(idx_int), str(target_sink))


def _move_sink_inputs_by_media_hint(hint: str, target_sink: str) -> None:
    if not hint or not target_sink:
        return
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
    except Exception:
        payload = []
    hint_l = str(hint).strip().lower()
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        props = entry.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        media = str(props.get("media.name") or "").lower()
        app = str(props.get("application.name") or "").lower()
        node = str(props.get("node.name") or "").lower()
        if hint_l not in media and hint_l not in app and hint_l not in node:
            continue
        idx = entry.get("index")
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        _run_pactl("move-sink-input", str(idx_int), str(target_sink))


def _set_sink_input_mute(index: int, muted: bool) -> None:
    try:
        _run_pactl("set-sink-input-mute", str(int(index)), "1" if muted else "0")
    except Exception:
        _ignore_exception("ignored exception")


def _allow_owrx_media_hint_fallback() -> bool:
    """Safety gate for media-hint fallback matching (can affect full browser sink-input)."""
    try:
        return bool(config.get("OWRX_ALLOW_MEDIA_HINT_FALLBACK", False))
    except Exception:
        return False


def _owrx_sink_input_entries() -> list[dict]:
    entries: list[dict] = []
    seen: set[int] = set()
    if _owrx_pid:
        try:
            pids = _list_descendant_pids(_owrx_pid)
            for entry in _find_sink_inputs_for_pids(pids):
                idx = entry.get("index")
                try:
                    idx_int = int(idx)
                except (TypeError, ValueError):
                    continue
                if idx_int in seen:
                    continue
                seen.add(idx_int)
                entries.append(entry)
        except Exception:
            _ignore_exception("ignored exception")
    # Important: media-name fallback can match a browser sink-input and mute
    # unrelated browser tabs/apps. Keep it opt-in.
    if _allow_owrx_media_hint_fallback() and not entries:
        try:
            entry = _find_owrx_sink_input()
            if entry:
                idx = entry.get("index")
                idx_int = int(idx)
                if idx_int not in seen:
                    entries.append(entry)
        except Exception:
            _ignore_exception("ignored exception")
    return entries


def _set_owrx_sink_input_muted(muted: bool) -> None:
    for entry in _owrx_sink_input_entries():
        idx = entry.get("index")
        try:
            _set_sink_input_mute(int(idx), muted)
        except Exception:
            _ignore_exception("ignored exception")


def _list_descendant_pids(root_pid: int) -> set[int]:
    """Return root_pid + all descendant PIDs by scanning /proc (Linux)."""
    try:
        root_pid = int(root_pid)
    except (TypeError, ValueError):
        return set()
    if root_pid <= 1:
        return {root_pid}
    if os.name != "posix" or not os.path.isdir("/proc"):
        return {root_pid}

    parent_of: dict[int, int] = {}
    children_of: dict[int, list[int]] = {}
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            stat_path = f"/proc/{pid}/stat"
            try:
                with open(stat_path, "r", encoding="utf-8", errors="ignore") as handle:
                    stat = handle.read()
            except Exception:
                continue
            # Format: pid (comm) state ppid ...
            end = stat.rfind(")")
            if end == -1:
                continue
            rest = stat[end + 1 :].strip()
            parts = rest.split()
            if len(parts) < 2:
                continue
            try:
                ppid = int(parts[1])
            except (TypeError, ValueError):
                continue
            parent_of[pid] = ppid
            children_of.setdefault(ppid, []).append(pid)
    except Exception:
        return {root_pid}

    out: set[int] = {root_pid}
    queue = [root_pid]
    while queue:
        current = queue.pop()
        for child in children_of.get(current, []):
            if child in out:
                continue
            out.add(child)
            queue.append(child)
        # Safety: avoid pathological scans.
        if len(out) > 4000:
            break
    return out


def _find_sink_inputs_for_pids(pids: set[int]) -> list[dict]:
    if not pids:
        return []
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
    except Exception:
        return []
    matches = []
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        props = entry.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        proc_id = props.get("application.process.id")
        try:
            proc_id_int = int(proc_id) if proc_id is not None else None
        except (TypeError, ValueError):
            proc_id_int = None
        if proc_id_int is not None and proc_id_int in pids:
            matches.append(entry)
    return matches


def _find_owrx_sink_input() -> Optional[dict]:
    """Locate the sink-input for OpenWebRX (external browser)."""
    hint = str(config.get("OWRX_MEDIA_HINT", "openwebrx") or "openwebrx").strip().lower()
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
    except Exception:
        payload = []
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        props = entry.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        media = str(props.get("media.name") or "").lower()
        app = str(props.get("application.name") or "").lower()
        node = str(props.get("node.name") or "").lower()
        if hint and (hint in media or hint in app or hint in node):
            return entry
    return None


def _get_sink_name_by_index(index: int) -> Optional[str]:
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sinks"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(result.stdout or "[]")
    except Exception:
        return None
    for sink in payload if isinstance(payload, list) else []:
        if not isinstance(sink, dict):
            continue
        try:
            idx = int(sink.get("index"))
        except (TypeError, ValueError):
            continue
        if idx == int(index):
            name = str(sink.get("name") or "").strip()
            return name or None
    return None


def _resolve_owrx_monitor_source() -> Optional[str]:
    # Prefer dedicated SDR null-sink monitor while ANR path is enabled,
    # avoiding recapture/feedback from the user playback sink.
    try:
        if _sdr_enabled:
            sinks = _pactl_capture("list", "short", "sinks")
            if _SDR_NULL_SINK_NAME in str(sinks or ""):
                return f"{_SDR_NULL_SINK_NAME}.monitor"
    except Exception:
        _ignore_exception("ignored exception")

    # Prefer the actual sink where OWRX is playing (avoid silence if moving failed).
    try:
        if _owrx_pid:
            pids = _list_descendant_pids(_owrx_pid)
            sinks = _find_sink_inputs_for_pids(pids)
            for entry in sinks:
                sink_idx = entry.get("sink")
                try:
                    sink_int = int(sink_idx)
                except (TypeError, ValueError):
                    continue
                sink_name = _get_sink_name_by_index(sink_int)
                if sink_name:
                    return f"{sink_name}.monitor"
    except Exception:
        _ignore_exception("ignored exception")

    # If OWRX runs in an external browser, look for the media name hint.
    try:
        entry = _find_owrx_sink_input()
        if entry:
            sink_idx = entry.get("sink")
            try:
                sink_int = int(sink_idx)
            except (TypeError, ValueError):
                sink_int = None
            if sink_int is not None:
                sink_name = _get_sink_name_by_index(sink_int)
                if sink_name:
                    return f"{sink_name}.monitor"
    except Exception:
        _ignore_exception("ignored exception")

    # Last resort: default sink monitor.
    default_sink = _get_default_sink()
    if default_sink:
        return f"{default_sink}.monitor"
    return None


def owrx_sdr_routed() -> bool:
    """True si detectamos el sink-input de OpenWebRX (por PID o media.name)."""
    if _owrx_pid:
        try:
            pids = _list_descendant_pids(_owrx_pid)
            if _find_sink_inputs_for_pids(pids):
                return True
        except Exception:
            _ignore_exception("ignored exception")
    return _find_owrx_sink_input() is not None


def _route_owrx_tree_to_sink_with_retries(root_pid: int, sink: str, attempts: int = 20, delay_s: float = 0.25) -> None:
    """Retry moving sink-inputs for the whole process tree (QtWebEngine uses child PIDs)."""
    try:
        root_pid = int(root_pid)
    except (TypeError, ValueError):
        return
    if not sink:
        return
    for _ in range(max(1, int(attempts))):
        try:
            pids = _list_descendant_pids(root_pid)
            _move_sink_inputs_for_pids(pids, sink)
        except Exception:
            _ignore_exception("ignored exception")
        time.sleep(max(0.05, float(delay_s)))


def _route_owrx_media_hint_with_retries(hint: str, sink: str, attempts: int = 60, delay_s: float = 0.25) -> None:
    for _ in range(max(1, int(attempts))):
        try:
            _move_sink_inputs_by_media_hint(hint, sink)
        except Exception:
            _ignore_exception("ignored exception")
        time.sleep(max(0.05, float(delay_s)))


def _route_owrx_to_sink_once(target_sink: str) -> None:
    if not target_sink:
        return
    try:
        if _owrx_pid:
            pids = _list_descendant_pids(_owrx_pid)
            _move_sink_inputs_for_pids(pids, target_sink)
    except Exception:
        _ignore_exception("ignored exception")


def route_owrx_to_configured_pc_sink() -> None:
    sink = _get_configured_pulse_device("sinks", "Altavoz_PC_Pulse", "Altavoz_PC")
    if not sink:
        return
    try:
        _route_owrx_to_sink_once(sink)
    except Exception:
        _ignore_exception("ignored exception")
    if _owrx_pid:
        try:
            threading.Thread(
                target=_route_owrx_tree_to_sink_with_retries,
                args=(int(_owrx_pid), sink, 40, 0.25),
                daemon=True,
                name="owrx_route_tree",
            ).start()
        except Exception:
            _ignore_exception("ignored exception")
    hint = str(config.get("OWRX_MEDIA_HINT", "openwebrx") or "openwebrx").strip()
    if hint and _allow_owrx_media_hint_fallback() and not _owrx_pid:
        try:
            threading.Thread(
                target=_route_owrx_media_hint_with_retries,
                args=(hint, sink, 40, 0.25),
                daemon=True,
                name="owrx_route_hint",
            ).start()
        except Exception:
            _ignore_exception("ignored exception")


def _sdr_route_loop() -> None:
    """Continuously move the OWRX sink-input to the hidden SDR sink while enabled."""
    _sdr_route_stop.clear()
    while not _sdr_route_stop.is_set():
        if not _sdr_enabled:
            break
        try:
            sinks = _pactl_capture("list", "short", "sinks")
            if _SDR_NULL_SINK_NAME not in sinks:
                time.sleep(0.2)
                continue
        except Exception:
            time.sleep(0.2)
            continue
        try:
            _route_owrx_to_sink_once(_SDR_NULL_SINK_NAME)
        except Exception:
            _ignore_exception("ignored exception")
        time.sleep(0.2)


def _start_sdr_route_loop() -> None:
    global _sdr_route_thread
    if _sdr_route_thread and _sdr_route_thread.is_alive():
        return
    _sdr_route_stop.clear()
    _sdr_route_thread = threading.Thread(target=_sdr_route_loop, daemon=True, name="owrx_sdr_route")
    _sdr_route_thread.start()


def _stop_sdr_route_loop() -> None:
    global _sdr_route_thread
    _sdr_route_stop.set()
    thread = _sdr_route_thread
    _sdr_route_thread = None
    if thread and thread.is_alive():
        try:
            thread.join(timeout=0.6)
        except Exception:
            _ignore_exception("ignored exception")


def _sdr_capture_loop(loop_generation: int) -> None:
    global _sdr_last_rms, _sdr_signal_ts, _sdr_parec_pid, _sdr_pacat_pid, _sdr_monitor_stream_id
    global _sdr_input_buffer, _sdr_output_ts, _sdr_resume_drop, _sdr_prebuffering
    frame_size = 480
    channels = 2
    rate = 48000
    bytes_per_chunk = frame_size * channels * 2
    write_block_bytes = bytes_per_chunk * max(1, int(SDR_BATCH_FRAMES))
    block_duration_s = float(write_block_bytes) / float(rate * channels * 2)
    prebuffer_target_bytes = int(rate * channels * 2 * (float(SDR_PREBUFFER_MS) / 1000.0))
    rebuffer_target_bytes = int(rate * channels * 2 * (float(SDR_REBUFFER_MS) / 1000.0))
    # Hard caps to keep SDR playback low-latency under bursty WebView/Docker delivery.
    max_live_buffer_bytes = int(rate * channels * 2 * (float(SDR_MAX_BUFFER_MS) / 1000.0))
    max_process_bytes = int(rate * channels * 2 * (float(SDR_MAX_PROCESS_MS) / 1000.0))
    prebuffer_data = bytearray()
    playout_buffer = bytearray()

    try:
        _normalize_anr_config()
    except Exception:
        _ignore_exception("ignored exception")
    dsp_filters.configure_ctx("sdr_gui", rate, channels, frame_size, config=config)
    dsp_filters.configure_ctx("sdr_web", rate, channels, frame_size, config=config)
    try:
        _trace(
            "SDR ANR: backend_loaded=%s enabled=%s intensity=%s"
            % (
                bool(dsp_filters.backend_loaded_ctx("sdr_gui")),
                bool(dsp_filters.get_filter_state("anr")),
                int(dsp_filters.get_filter_intensity("anr")),
            )
        )
    except Exception:
        _ignore_exception("ignored exception")
    target = str(config.get("SDR_OUTPUT_TARGET", "") or "").strip().lower()
    if not target:
        target = "pc"
    if target in ("radio", "mic_radio", "microfono_radio"):
        sink = _get_configured_pulse_device("sinks", "Microfono_Radio_Pulse", "Microfono_Radio")
    else:
        # Prefer system default sink (e.g. EasyEffects) to avoid fighting other apps
        # that are routed through the desktop processing chain.
        sink = str(_get_default_sink() or "").strip()
        if not sink:
            sink = _get_configured_pulse_device("sinks", "Altavoz_PC_Pulse", "Altavoz_PC")
    _sdr_log(
        f"loop start gen={int(loop_generation)} target={target} sink={sink} rate={rate} ch={channels}"
    )
    pacat = None
    parec = None
    prev_paused = _sdr_paused

    def _open_pacat():
        nonlocal pacat
        pacat_cmd = [
            "pacat",
            "--playback",
            "--format=s16le",
            "--rate",
            str(rate),
            "--channels",
            str(channels),
            "--latency-msec",
            str(SDR_PULSE_LATENCY_MSEC),
        ]
        if sink:
            pacat_cmd += ["--device", sink]
        pacat = subprocess.Popen(
            pacat_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        try:
            _sdr_log(f"pacat open pid={int(getattr(pacat, 'pid', 0) or 0)} cmd={' '.join(pacat_cmd)}")
        except Exception:
            _ignore_exception("ignored exception")
        return pacat

    def _close_parec():
        nonlocal parec
        global _sdr_parec_pid
        try:
            if parec and parec.stdout:
                parec.stdout.close()
        except Exception:
            _ignore_exception("ignored exception")
        _close_subprocess_io(parec)
        parec = None
        _sdr_parec_pid = None

    def _open_parec() -> bool:
        nonlocal parec
        global _sdr_parec_pid
        if parec is not None:
            return True
        source = _resolve_owrx_monitor_source()
        if not source:
            return False
        cmd = [
            "parec",
            "--raw",
            "--format=s16le",
            "--rate",
            str(rate),
            "--channels",
            str(channels),
            "--latency-msec",
            str(max(20, int(SDR_PULSE_LATENCY_MSEC))),
            "--device",
            source,
        ]
        try:
            parec = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            _sdr_parec_pid = int(getattr(parec, "pid", 0) or 0) or None
            _sdr_log(f"parec open pid={_sdr_parec_pid} src={source}")
            return True
        except Exception as exc:
            _sdr_log(f"parec open failed: {exc!r}")
            parec = None
            _sdr_parec_pid = None
            return False

    def _drain_input_queue() -> tuple[int, int]:
        nonlocal channels
        global _sdr_input_buffer
        drained = 0
        drained_bytes = 0
        while True:
            try:
                chunk, sample_rate, in_channels = _sdr_input_queue.get_nowait()
            except queue.Empty:
                break
            if int(sample_rate) != rate:
                continue
            if int(in_channels) not in (1, 2):
                continue
            if int(in_channels) != channels:
                try:
                    converted = convertir_canales(chunk, int(in_channels), channels)
                except Exception:
                    continue
                _sdr_input_buffer.extend(converted)
                drained_bytes += len(converted)
            else:
                _sdr_input_buffer.extend(chunk)
                drained_bytes += len(chunk)
            drained += 1
        return drained, drained_bytes

    try:
        last_write_log = 0.0
        last_drop_log = 0.0
        write_count = 0
        last_queue_chunk_ts = 0.0
        underrun_count = 0
        silence_fill_count = 0
        fade_in_pending = True
        loop_rx_chunks = 0
        loop_rx_bytes = 0
        last_flow_log = 0.0
        next_playout_ts: float | None = None
        last_playout_block: bytes | None = None
        while (not _sdr_stop_event.is_set()) and (int(loop_generation) == int(_sdr_loop_generation)):
            try:
                if pacat is None:
                    _open_pacat()
                    _sdr_pacat_pid = int(getattr(pacat, "pid", 0) or 0) or None
                else:
                    try:
                        rc = pacat.poll()
                    except Exception:
                        rc = None
                    if rc is not None:
                        _sdr_log(f"pacat exited rc={int(rc)} pid={int(getattr(pacat, 'pid', 0) or 0)}; reopening")
                        _close_subprocess_io(pacat)
                        pacat = None
                        _sdr_pacat_pid = None
                        _open_pacat()
                        _sdr_pacat_pid = int(getattr(pacat, "pid", 0) or 0) or None

                stdin = pacat.stdin if pacat else None

                if prev_paused and not _sdr_paused:
                    _sdr_log("resume from paused: reopening pacat")
                    try:
                        if pacat and pacat.stdin:
                            pacat.stdin.close()
                    except Exception:
                        _ignore_exception("ignored exception")
                    _close_subprocess_io(pacat)
                    pacat = None
                    _open_pacat()
                    _sdr_pacat_pid = int(getattr(pacat, "pid", 0) or 0) or None
                    fade_in_pending = True
                    next_playout_ts = None
                    prev_paused = False
                elif _sdr_paused:
                    prev_paused = True

                rx_source = str(config.get("RX_AUDIO_SOURCE", "radio") or "radio").strip().lower()
                if rx_source == "sdr":
                    try:
                        globals()["_rx_sample_rate"] = int(rate)
                        globals()["_rx_channels"] = int(channels)
                    except Exception:
                        _ignore_exception("ignored exception")

                try:
                    chunk, sample_rate, in_channels = _sdr_input_queue.get(timeout=0.25)
                    if int(sample_rate) == rate:
                        last_queue_chunk_ts = time.monotonic()
                        if int(in_channels) != channels:
                            try:
                                chunk = convertir_canales(chunk, int(in_channels), channels)
                            except Exception:
                                chunk = b""
                        if chunk:
                            _sdr_capture_ts = time.monotonic()
                            _sdr_input_buffer.extend(bytes(chunk))
                            loop_rx_chunks += 1
                            loop_rx_bytes += len(chunk)
                except queue.Empty:
                    # Sin chunks del servidor OWRX: no intentamos capturar desde dispositivos locales.
                    pass
                drained_chunks, drained_bytes = _drain_input_queue()
                loop_rx_chunks += int(drained_chunks or 0)
                loop_rx_bytes += int(drained_bytes or 0)
                now_flow = time.monotonic()
                if now_flow - last_flow_log > 1.0:
                    last_flow_log = now_flow
                    try:
                        qsize = int(_sdr_input_queue.qsize())
                    except Exception:
                        qsize = -1
                    _sdr_log(
                        "flow rx_chunks=%s rx_bytes=%s qsize=%s inbuf=%s prebuf=%s paused=%s active=%s"
                        % (
                            int(loop_rx_chunks),
                            int(loop_rx_bytes),
                            int(qsize),
                            int(len(_sdr_input_buffer)),
                            bool(_sdr_prebuffering),
                            bool(_sdr_paused),
                            bool(_sdr_output_active),
                        )
                    )
                    loop_rx_chunks = 0
                    loop_rx_bytes = 0
                if len(_sdr_input_buffer) > max_live_buffer_bytes:
                    overflow = len(_sdr_input_buffer) - max_live_buffer_bytes
                    # Drop oldest audio first (real-time > completeness).
                    drop_len = overflow - (overflow % bytes_per_chunk)
                    if drop_len > 0:
                        del _sdr_input_buffer[:drop_len]
                        now = time.monotonic()
                        if now - last_drop_log > 1.0:
                            last_drop_log = now
                            _sdr_log(
                                f"drop backlog bytes={drop_len} buffered={len(_sdr_input_buffer)}"
                            )
                if len(_sdr_input_buffer) < bytes_per_chunk:
                    # If flow dips after playback started, re-enter prebuffering to
                    # avoid underrun crackles and restart cleanly.
                    if not _sdr_prebuffering and _sdr_output_active:
                        underrun_count = int(underrun_count) + 1
                        idle = time.monotonic() - float(last_queue_chunk_ts or 0.0)
                        # For short drops, keep timing stable by filling with silence.
                        # This avoids audible start/stop bursts on transient jitter.
                        if idle <= 0.75 and stdin is not None:
                            try:
                                if last_playout_block:
                                    fill_block = _soft_repeat_block_pcm16(last_playout_block, decay=0.94)
                                else:
                                    fill_block = b"\x00" * write_block_bytes
                                stdin.write(fill_block)
                                _sdr_output_ts = time.monotonic()
                                silence_fill_count += 1
                                now = time.monotonic()
                                if now - last_write_log > 1.0:
                                    last_write_log = now
                                    _sdr_log(
                                        f"write silence count={silence_fill_count} bytes={write_block_bytes} "
                                        f"paused={_sdr_paused} active={_sdr_output_active} prebuf={_sdr_prebuffering}"
                                    )
                            except Exception:
                                _ignore_exception("ignored exception")
                            continue
                        if underrun_count >= 5 and idle > 0.40:
                            _sdr_prebuffering = True
                            fade_in_pending = True
                            prebuffer_data.clear()
                    continue
                underrun_count = 0

                out_gui = bytearray()
                out_web = bytearray()
                process_len = len(_sdr_input_buffer) - (len(_sdr_input_buffer) % bytes_per_chunk)
                if process_len > max_process_bytes:
                    process_len = max_process_bytes - (max_process_bytes % bytes_per_chunk)
                data = bytes(_sdr_input_buffer[:process_len])
                del _sdr_input_buffer[:process_len]
                for offset in range(0, process_len, bytes_per_chunk):
                    sub = data[offset : offset + bytes_per_chunk]
                    try:
                        arr = np.frombuffer(sub, dtype=np.int16).astype(np.float32)
                        rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
                        _sdr_last_rms = rms
                        if rms > 20.0:
                            _sdr_signal_ts = time.monotonic()
                    except Exception:
                        _ignore_exception("ignored exception")
                    if _sdr_paused:
                        continue
                    try:
                        sdr_anr_on = bool(dsp_filters.get_filter_state("anr"))
                    except Exception:
                        sdr_anr_on = False
                    if sdr_anr_on:
                        sub_gui = _rx_chain_gui(
                            sub,
                            channels,
                            rate,
                            frame_size,
                            context="sdr_gui",
                            volume=_sdr_volume,
                            apply_output_boost=False,
                            apply_user_gain=False,
                        )
                        sub_web = _rx_chain_web(
                            sub,
                            channels,
                            rate,
                            frame_size,
                            context="sdr_web",
                            # El volumen del oyente remoto es WEB_RX_GAIN, no
                            # _sdr_volume (el dial de la consola en modo SDR,
                            # ruta de audio local del PC) — independiente de
                            # lo que oiga el navegador, igual que en la ruta
                            # de radio/CAT con volumen_rx.
                            volume=1.0,
                            apply_user_gain=False,
                        )
                    else:
                        sub_gui = _sdr_chain_light_gui(sub, _sdr_volume)
                        sub_web = _sdr_chain_light_web(sub, 1.0)
                    out_gui.extend(sub_gui)
                    out_web.extend(sub_web)
                if _sdr_resume_drop > 0:
                    _sdr_resume_drop = max(0, _sdr_resume_drop - 1)
                    continue

                if out_gui:
                    if rx_source == "sdr":
                        try:
                            _push_rx_raw_gui(out_gui, channels)
                            _push_rx_raw_web(out_web or out_gui, channels)
                        except Exception:
                            _ignore_exception("ignored exception")
                    if _sdr_output_active:
                        try:
                            payload = bytes(out_gui)
                            if _sdr_prebuffering:
                                prebuffer_data.extend(payload)
                                target_bytes = max(prebuffer_target_bytes, rebuffer_target_bytes)
                                if len(prebuffer_data) < target_bytes:
                                    continue
                                payload = bytes(prebuffer_data)
                                prebuffer_data.clear()
                                _sdr_prebuffering = False
                                fade_in_pending = True
                            if fade_in_pending:
                                payload = _fade_in_pcm16(payload, channels, SDR_FADE_IN_MS, rate=rate)
                                fade_in_pending = False
                            # Stable playout cadence: write fixed-size blocks only.
                            playout_buffer.extend(payload)
                            if stdin is not None:
                                while len(playout_buffer) >= write_block_bytes:
                                    block = bytes(playout_buffer[:write_block_bytes])
                                    del playout_buffer[:write_block_bytes]
                                    now_w = time.monotonic()
                                    if next_playout_ts is None:
                                        next_playout_ts = now_w
                                    # Keep playout cadence stable instead of burst-writing.
                                    if now_w < next_playout_ts:
                                        time.sleep(max(0.0, next_playout_ts - now_w))
                                        now_w = time.monotonic()
                                    elif (now_w - next_playout_ts) > (block_duration_s * 3.0):
                                        # If timing drifted too far (scheduler hiccup),
                                        # re-anchor to "now" to avoid catch-up bursts.
                                        next_playout_ts = now_w
                                    stdin.write(block)
                                    write_count += 1
                                    _sdr_output_ts = time.monotonic()
                                    last_playout_block = block
                                    next_playout_ts = float(next_playout_ts) + block_duration_s
                            now = time.monotonic()
                            if now - last_write_log > 1.0:
                                last_write_log = now
                                _sdr_log(
                                    f"write count={write_count} block={write_block_bytes} queued={len(playout_buffer)} "
                                    f"rms={float(_sdr_last_rms):.2f} paused={_sdr_paused} active={_sdr_output_active} prebuf={_sdr_prebuffering}"
                                )
                        except Exception as exc:
                            rc = None
                            try:
                                if pacat is not None:
                                    rc = pacat.poll()
                            except Exception:
                                rc = None
                            _sdr_log(
                                f"write error exc={exc!r} rc={rc!r} pid={int(getattr(pacat, 'pid', 0) or 0)}"
                            )
                            try:
                                if pacat and pacat.stdin:
                                    pacat.stdin.close()
                            except Exception:
                                _ignore_exception("ignored exception")
                            _close_subprocess_io(pacat)
                            pacat = None
                            _sdr_pacat_pid = None
                            time.sleep(0.03)
            except Exception as exc:
                _sdr_log(f"iter exception: {exc!r}")
                try:
                    _sdr_log(traceback.format_exc())
                except Exception:
                    _ignore_exception("ignored exception")
                try:
                    if pacat and pacat.stdin:
                        pacat.stdin.close()
                except Exception:
                    _ignore_exception("ignored exception")
                _close_subprocess_io(pacat)
                pacat = None
                _sdr_pacat_pid = None
                time.sleep(0.1)
    except Exception:
        _sdr_log("loop exception")
    finally:
        _close_parec()
        _sdr_pacat_pid = None
        _sdr_monitor_stream_id = None
        try:
            if pacat and pacat.stdin:
                pacat.stdin.close()
        except Exception:
            _ignore_exception("ignored exception")
        _close_subprocess_io(pacat)
        _sdr_log(
            f"loop stop gen={int(loop_generation)} stop_event={bool(_sdr_stop_event.is_set())} "
            f"gen_active={int(_sdr_loop_generation)}"
        )


def owrx_sdr_queue_stats() -> dict:
    try:
        qsize = int(_sdr_input_queue.qsize())
    except Exception:
        qsize = -1
    return {
        "qsize": int(qsize),
        "drop_total": int(_sdr_chunk_drop_total or 0),
        "enq_fail_total": int(_sdr_chunk_enqueue_fail_total or 0),
        "input_rate": int(_sdr_input_rate or 0),
        "input_channels": int(_sdr_input_channels or 0),
        "capture_ts": float(_sdr_capture_ts or 0.0),
    }


def enable_owrx_sdr_anr() -> bool:
    """Activa la ruta SDR Linux interna para procesar OWRX antes de la salida."""
    global _sdr_enabled, _sdr_thread, _sdr_route_thread, _sdr_loop_generation
    if _sdr_enabled:
        return True
    if not owrx_sdr_anr_supported():
        return False
    while True:
        try:
            _sdr_input_queue.get_nowait()
        except queue.Empty:
            break
    _sdr_enabled = True
    _sdr_input_buffer.clear()
    try:
        if _ensure_sdr_null_sink():
            _start_sdr_route_loop()
    except Exception:
        _ignore_exception("ignored exception")
    # Invalidate any stale loop that may still be winding down from a previous cycle.
    _sdr_loop_generation = int(_sdr_loop_generation) + 1
    this_generation = int(_sdr_loop_generation)
    _sdr_stop_event.clear()
    _sdr_thread = threading.Thread(
        target=_sdr_capture_loop,
        args=(this_generation,),
        daemon=True,
        name="owrx_sdr_anr",
    )
    _sdr_thread.start()
    return True


def disable_owrx_sdr_anr() -> None:
    global _sdr_enabled, _sdr_thread, _sdr_route_thread, _sdr_monitor_stream_id, _sdr_loop_generation
    if not _sdr_enabled:
        _unload_sdr_null_sink()
        return
    _sdr_enabled = False
    # Invalidate current loop immediately so it exits even if stop_event is cleared quickly.
    _sdr_loop_generation = int(_sdr_loop_generation) + 1
    _sdr_stop_event.set()
    if _sdr_thread and _sdr_thread.is_alive():
        _sdr_thread.join(timeout=2.0)
    _sdr_thread = None
    _stop_sdr_route_loop()
    _sdr_route_thread = None
    _sdr_monitor_stream_id = None
    while True:
        try:
            _sdr_input_queue.get_nowait()
        except queue.Empty:
            break
    _sdr_input_buffer.clear()
    try:
        route_owrx_to_configured_pc_sink()
    except Exception:
        _ignore_exception("ignored exception")
    _unload_sdr_null_sink()


def restart_owrx_sdr_pipeline(reason: str = "") -> bool:
    """Hard reset of SDR capture/playback loop for stalled states."""
    if not owrx_sdr_anr_supported():
        return False
    detail = str(reason or "-")
    try:
        _sdr_log(f"pipeline restart requested reason={detail}")
    except Exception:
        _ignore_exception("ignored exception")
    try:
        disable_owrx_sdr_anr()
    except Exception as exc:
        try:
            _sdr_log(f"pipeline restart disable error={exc!r}")
        except Exception:
            _ignore_exception("ignored exception")
    time.sleep(0.08)
    try:
        ok = bool(enable_owrx_sdr_anr())
        try:
            _sdr_log(f"pipeline restart done ok={ok}")
        except Exception:
            _ignore_exception("ignored exception")
        return ok
    except Exception as exc:
        try:
            _sdr_log(f"pipeline restart enable error={exc!r}")
        except Exception:
            _ignore_exception("ignored exception")
        return False

def anr_disponible():
    try:
        # Lazy probe so ANR availability is known even before RX starts.
        if not dsp_filters.backend_loaded():
            try:
                dsp_filters.configure(
                    int(_rx_sample_rate or LINUX_AUDIO_RATE),
                    int(_rx_channels or 1),
                    int(DSP_FRAME_SIZE),
                    config=config,
                )
            except Exception:
                _ignore_exception("ignored exception")
        if dsp_filters.backend_loaded():
            return True
        return (
            dsp_filters.backend_loaded_ctx("gui")
            or dsp_filters.backend_loaded_ctx("web")
            or dsp_filters.backend_loaded_ctx("sdr_gui")
            or dsp_filters.backend_loaded_ctx("sdr_web")
        )
    except Exception:
        return False


def establecer_anr(habilitado: bool) -> None:
    habilitado = bool(habilitado)
    config["ANR_Enabled"] = habilitado
    filtros = config.get("DSPFilters")
    if not isinstance(filtros, dict):
        filtros = {}
    entrada = filtros.get("anr")
    if not isinstance(entrada, dict):
        entrada = {}
    entrada["enabled"] = habilitado
    filtros["anr"] = entrada
    config["DSPFilters"] = filtros
    _persist_runtime_config()
    dsp_filters.set_filter_state("anr", habilitado)


def anr_activo() -> bool:
    return dsp_filters.get_filter_state("anr")


def establecer_intensidad_anr(intensidad: int) -> None:
    intensidad = max(1, min(10, int(intensidad)))
    config["ANR_Intensity"] = intensidad
    filtros = config.get("DSPFilters")
    if not isinstance(filtros, dict):
        filtros = {}
    entrada = filtros.get("anr")
    if not isinstance(entrada, dict):
        entrada = {}
    entrada["intensity"] = intensidad
    filtros["anr"] = entrada
    config["DSPFilters"] = filtros
    _persist_runtime_config()
    dsp_filters.set_filter_intensity("anr", intensidad)


def obtener_intensidad_anr() -> int:
    return dsp_filters.get_filter_intensity("anr")

def establecer_modo_ganancia(modo: str) -> None:
    global gain_mode, auto_gain_enabled
    modo = str(modo).strip().lower()
    if modo not in {"auto", "manual", "off"}:
        return
    gain_mode = modo
    auto_gain_enabled = gain_mode == "auto"
    if gain_mode != "auto":
        _agc_state["gain"] = 1.0


def obtener_modo_ganancia() -> str:
    return gain_mode


def establecer_auto_gain(estado: bool) -> None:
    establecer_modo_ganancia("auto" if estado else "off")


def auto_gain_activo() -> bool:
    return gain_mode == "auto"


def establecer_ganancia_manual(valor: float) -> None:
    global manual_gain
    manual_gain = _clamp(valor, MANUAL_GAIN_MIN, MANUAL_GAIN_MAX)
    establecer_modo_ganancia("manual")


def obtener_ganancia_manual() -> float:
    return float(manual_gain)


def cleanup_on_exit():
    global _audio_worker_stop
    stop_tx_test_tone()
    desactivar_audio()
    disable_owrx_sdr_anr()
    dsp_filters.shutdown()
    if _linux_audio_runtime:
        with _state_lock:
            _audio_worker_stop = True
        _audio_worker_event.set()
        if _audio_worker_thread and _audio_worker_thread.is_alive():
            _audio_worker_thread.join(timeout=1.0)
    p.terminate()

# Iniciar automÃƒÂ¡ticamente solo si estÃƒÂ¡ configurado explÃƒÂ­citamente
# No iniciar automÃƒÂ¡ticamente; se harÃƒÂ¡ desde el controlador de la radio

# Exponer las funciones para que sean usadas por otros scripts
__all__ = [
    'activar_audio',
    'activar_ptt',
    'desactivar_ptt',
    'desactivar_audio',
    'set_volumen_tx',
    'set_volumen_rx',
    'habilitar_audio_para_radio',
    'listar_dispositivos_audio',
    'reproducir_audio_en_radio',
    'reproducir_roger_beep',
    'anr_disponible',
    'establecer_anr',
    'anr_activo',
    'establecer_intensidad_anr',
    'obtener_intensidad_anr',
    'establecer_modo_ganancia',
    'obtener_modo_ganancia',
    'establecer_auto_gain',
    'auto_gain_activo',
    'establecer_ganancia_manual',
    'obtener_ganancia_manual',
    'pop_rx_raw',
    'get_rx_meter_dbfs',
    'pop_tx_raw',
    'is_tx_active',
    'is_rx_active',
    'set_owrx_sink_muted',
    'push_owrx_audio_chunk',
    'owrx_sdr_queue_stats',
    'route_owrx_to_configured_pc_sink',
    'owrx_sdr_capture_active',
    'set_tx_capture_source',
    'tx_capture_needs_local_audio',
    'tx_app_capture_available',
    'tx_output_signal_since',
    'start_tx_test_tone',
    'stop_tx_test_tone',
    'tx_test_tone_active',
]

# Configurar el manejo de la seÃƒÂ±al SIGINT (Ctrl+C) para asegurar una salida limpia
def signal_handler(sig, frame):
    print('Saliendo...')
    cleanup_on_exit()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


_SDR_NULL_SINK_NAME = "poorsdr_owrx"
_SDR_NULL_SINK_DESC = "PoorSDR4All-OWRX-ANR"
