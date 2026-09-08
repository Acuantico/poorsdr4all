import ctypes
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


THIRD_PARTY_DIR = os.path.join(os.path.dirname(__file__), "third_party", "bin")

if os.name == "nt":
    SPEEX_LIBRARY_CANDIDATES = [
        "libspeexdsp.dll",
        "speexdsp.dll",
    ]
else:
    SPEEX_LIBRARY_CANDIDATES = [
        "libspeexdsp.so",
        "libspeexdsp.so.1",
    ]


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)


def _native_backend_allowed(config: Optional[Dict[str, object]] = None) -> bool:
    env_value = os.environ.get("POORSDR_ENABLE_NATIVE_DSP", "").strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    if env_value in {"0", "false", "no", "off"}:
        return False
    if config and "DSP_NATIVE_BACKEND" in config:
        return _as_bool(config.get("DSP_NATIVE_BACKEND"), default=True)
    return True


def _resolve_library(*filenames: str) -> Optional[str]:
    for filename in filenames:
        if not filename:
            continue
        candidate = os.path.join(THIRD_PARTY_DIR, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def _load_library(path: str) -> Optional[ctypes.CDLL]:
    if not path:
        return None
    try:
        if os.name == "nt":
            os.add_dll_directory(os.path.dirname(path))
        return ctypes.CDLL(path)
    except OSError as exc:
        print(f"No se pudo cargar la biblioteca {path}: {exc}")
        return None


def _load_system_library(*names: str) -> Optional[ctypes.CDLL]:
    last_error: Optional[OSError] = None
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError as exc:
            last_error = exc
            continue
    if last_error is not None:
        print(f"No se pudo cargar SpeexDSP del sistema: {last_error}")
    return None


class SpeexPreprocessor:
    SET_DENOISE = 0
    SET_AGC = 2
    SET_DEREVERB = 8
    SET_DEREVERB_DECAY = 10
    SET_DEREVERB_LEVEL = 12
    SET_PROB_CONTINUE = 16
    SET_NOISE_SUPPRESS = 18

    _INTENSITY_MIN = 1
    _INTENSITY_MAX = 10
    # Techo de atenuación de ruido (dB, cuanto más negativo más agresivo).
    _SUPPRESS_DB = {
        1: -12,
        2: -18,
        3: -24,
        4: -30,
        5: -36,
        6: -45,
        7: -55,
        8: -66,
        9: -78,
        10: -90,
    }
    # Umbral (% entero) para que el VAD interno de Speex siga considerando
    # "voz" el frame actual. Cuanto más baja la intensidad, antes suelta el
    # estado de voz y antes vuelve a estimar solo ruido — así el estimador
    # se readapta más rápido al terminar una transmisión, en vez de dejar
    # que el ruido suba de golpe y tarde en bajar.
    _PROB_CONTINUE = {
        1: 45,
        2: 42,
        3: 39,
        4: 36,
        5: 33,
        6: 30,
        7: 27,
        8: 24,
        9: 20,
        10: 15,
    }

    def __init__(self, lib: ctypes.CDLL, frame_size: int, sample_rate: int, channels: int):
        self._lib = lib
        self.frame_size = frame_size
        self.channels = channels

        self._lib.speex_preprocess_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.speex_preprocess_state_init.restype = ctypes.c_void_p
        self._lib.speex_preprocess_state_destroy.argtypes = [ctypes.c_void_p]
        self._lib.speex_preprocess_run.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_short),
        ]
        self._lib.speex_preprocess_run.restype = ctypes.c_int
        self._lib.speex_preprocess_ctl.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self._lib.speex_preprocess_ctl.restype = ctypes.c_int

        self._states: List[ctypes.c_void_p] = []
        for _ in range(channels):
            state = self._lib.speex_preprocess_state_init(frame_size, sample_rate)
            if not state:
                raise RuntimeError("No se pudo crear el estado SpeexDSP.")
            self._states.append(state)

        self._intensity = 3
        self._configure_states()

    def _ctl_int(self, state: ctypes.c_void_p, request: int, value: int) -> None:
        c_val = ctypes.c_int(value)
        self._lib.speex_preprocess_ctl(state, request, ctypes.byref(c_val))

    def _ctl_float(self, state: ctypes.c_void_p, request: int, value: float) -> None:
        c_val = ctypes.c_float(value)
        self._lib.speex_preprocess_ctl(state, request, ctypes.byref(c_val))

    def _configure_states(self) -> None:
        suppress_db = self._SUPPRESS_DB[self._intensity]
        prob_continue = self._PROB_CONTINUE[self._intensity]
        for state in self._states:
            self._ctl_int(state, self.SET_DENOISE, 1)
            # AGC deliberadamente apagado: no hay objetivo de volumen fiable
            # para RX de radio (varía con S-meter/squelch) y activarlo a
            # ciegas sin poder probarlo por oído es más riesgo que beneficio.
            self._ctl_int(state, self.SET_AGC, 0)
            self._ctl_int(state, self.SET_DEREVERB, 0)
            self._ctl_float(state, self.SET_DEREVERB_DECAY, 0.0)
            self._ctl_float(state, self.SET_DEREVERB_LEVEL, 0.0)
            self._ctl_int(state, self.SET_NOISE_SUPPRESS, suppress_db)
            self._ctl_int(state, self.SET_PROB_CONTINUE, prob_continue)

    def set_intensity(self, level: int) -> None:
        clamped = max(self._INTENSITY_MIN, min(self._INTENSITY_MAX, int(level)))
        if clamped != self._intensity:
            self._intensity = clamped
            self._configure_states()

    def process(self, frames: np.ndarray) -> np.ndarray:
        if frames.shape[0] != self.frame_size:
            raise ValueError(
                f"SpeexDSP requiere bloques de {self.frame_size} muestras, recibido {frames.shape[0]}"
            )
        data = np.clip(np.round(frames * 32767.0), -32768, 32767).astype(np.int16)
        for idx, state in enumerate(self._states):
            channel = np.ascontiguousarray(data[:, idx])
            ptr = channel.ctypes.data_as(ctypes.POINTER(ctypes.c_short))
            self._lib.speex_preprocess_run(state, ptr)
            data[:, idx] = channel
        return data.astype(np.float32) / 32768.0

    def shutdown(self) -> None:
        for state in self._states:
            if state:
                self._lib.speex_preprocess_state_destroy(state)
        self._states.clear()


@dataclass
class FilterEntry:
    enabled: bool
    intensity: int
    available: bool


class DSPFilterManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._speex_lib: Optional[ctypes.CDLL] = None
        self._speex: Optional[SpeexPreprocessor] = None
        self._sample_rate = 48000
        self._channels = 1
        self._frame_size = 480
        self._filters: Dict[str, FilterEntry] = {
            "anr": FilterEntry(enabled=False, intensity=3, available=True)
        }
        self._ready = False

    def _configure_from_config(self, config: Optional[Dict[str, object]]) -> None:
        if not config or not isinstance(config, dict):
            return

        # Prefer the structured DSPFilters config if present (source of truth).
        enabled = None
        intensity = None
        filters_cfg = config.get("DSPFilters")
        if isinstance(filters_cfg, dict):
            entry = filters_cfg.get("anr")
            if isinstance(entry, dict):
                enabled = entry.get("enabled")
                intensity = entry.get("intensity")

        # Fallback to legacy keys.
        if enabled is None:
            enabled = config.get("ANR_Enabled")
        if intensity is None:
            intensity = config.get("ANR_Intensity")

        if enabled is not None:
            self._filters["anr"].enabled = _as_bool(enabled, default=False)
        if intensity is not None:
            try:
                parsed_intensity = int(float(intensity))
            except (TypeError, ValueError):
                parsed_intensity = self._filters["anr"].intensity
            self._filters["anr"].intensity = max(1, min(10, int(parsed_intensity)))

    def configure(
        self,
        sample_rate: int,
        channels: int,
        frame_size: int,
        config: Optional[Dict[str, object]] = None,
    ) -> None:
        with self._lock:
            self._sample_rate = int(sample_rate)
            self._channels = max(1, int(channels))
            self._frame_size = max(1, int(frame_size))
            self._shutdown_engines()
            self._configure_from_config(config)

            if not _native_backend_allowed(config):
                self._filters["anr"].available = False
                self._speex = None
                self._speex_lib = None
                self._ready = False
                return

            speex_path = _resolve_library(*SPEEX_LIBRARY_CANDIDATES)
            self._speex_lib = _load_library(speex_path) if speex_path else None
            if self._speex_lib is None:
                self._speex_lib = _load_system_library("libspeexdsp.so.1", "libspeexdsp.so", "speexdsp")
            self._filters["anr"].available = self._speex_lib is not None

            if self._speex_lib:
                self._speex = SpeexPreprocessor(
                    self._speex_lib, self._frame_size, self._sample_rate, self._channels
                )
                self._speex.set_intensity(self._filters["anr"].intensity)
            else:
                self._speex = None

            self._ready = self._speex is not None

    def process_rx(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        channels: int,
        frame_size: int,
    ) -> bytes:
        with self._lock:
            if not self._ready or not pcm_bytes:
                return pcm_bytes
            if frame_size != self._frame_size or channels != self._channels:
                self.configure(sample_rate, channels, frame_size)
            if not (self._filters["anr"].enabled and self._filters["anr"].available):
                return pcm_bytes
            if len(pcm_bytes) != frame_size * channels * 2:
                total_frames = len(pcm_bytes) // (channels * 2)
                if total_frames == 0:
                    return pcm_bytes
                frame_size = total_frames

            data = np.frombuffer(pcm_bytes, dtype=np.int16)
            frames = data.reshape((-1, channels)).astype(np.float32) / 32768.0

            if self._speex:
                self._speex.set_intensity(self._filters["anr"].intensity)
                processed = self._speex.process(frames)
            else:
                processed = frames

            ints = np.clip(np.round(processed * 32767.0), -32768, 32767).astype(np.int16)
            return ints.tobytes()

    def set_filter_state(self, name: str, enabled: bool) -> None:
        with self._lock:
            if name != "anr":
                raise KeyError(f"Filtro desconocido: {name}")
            entry = self._filters[name]
            if not entry.available and enabled:
                raise RuntimeError("El filtro ANR no esta disponible en este sistema.")
            entry.enabled = bool(enabled)

    def get_filter_state(self, name: str) -> bool:
        with self._lock:
            if name != "anr":
                raise KeyError(f"Filtro desconocido: {name}")
            return self._filters[name].enabled

    def set_filter_intensity(self, name: str, intensity: int) -> None:
        with self._lock:
            if name != "anr":
                raise KeyError(f"Filtro desconocido: {name}")
            entry = self._filters[name]
            entry.intensity = max(1, min(10, int(intensity)))
            if self._speex:
                self._speex.set_intensity(entry.intensity)

    def get_filter_intensity(self, name: str) -> int:
        with self._lock:
            if name != "anr":
                raise KeyError(f"Filtro desconocido: {name}")
            return self._filters[name].intensity

    def backend_loaded(self) -> bool:
        with self._lock:
            return self._ready

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown_engines()
            self._ready = False

    def _shutdown_engines(self) -> None:
        if self._speex:
            self._speex.shutdown()
        self._speex = None


_DEFAULT_CONTEXT = "default"
_MANAGERS: Dict[str, DSPFilterManager] = {_DEFAULT_CONTEXT: DSPFilterManager()}


def _get_manager(context: Optional[str] = None) -> DSPFilterManager:
    key = str(context or _DEFAULT_CONTEXT).strip() or _DEFAULT_CONTEXT
    manager = _MANAGERS.get(key)
    if manager is not None:
        return manager

    # New independent processing context (separate sample rate/channels/frame size state),
    # inheriting filter toggles from the default manager.
    manager = DSPFilterManager()
    default = _MANAGERS[_DEFAULT_CONTEXT]
    try:
        manager.set_filter_state("anr", default.get_filter_state("anr"))
        manager.set_filter_intensity("anr", default.get_filter_intensity("anr"))
    except Exception:
        pass
    _MANAGERS[key] = manager
    return manager


def configure(sample_rate: int, channels: int, frame_size: int, config: Optional[Dict[str, object]] = None) -> None:
    _get_manager().configure(sample_rate, channels, frame_size, config=config)


def configure_ctx(
    context: str,
    sample_rate: int,
    channels: int,
    frame_size: int,
    config: Optional[Dict[str, object]] = None,
) -> None:
    _get_manager(context).configure(sample_rate, channels, frame_size, config=config)


def process_rx(pcm_bytes: bytes, sample_rate: int, channels: int, frame_size: int) -> bytes:
    return _get_manager().process_rx(pcm_bytes, sample_rate, channels, frame_size)


def process_rx_ctx(context: str, pcm_bytes: bytes, sample_rate: int, channels: int, frame_size: int) -> bytes:
    return _get_manager(context).process_rx(pcm_bytes, sample_rate, channels, frame_size)


def set_filter_state(name: str, enabled: bool) -> None:
    _MANAGERS[_DEFAULT_CONTEXT].set_filter_state(name, enabled)
    for ctx, manager in list(_MANAGERS.items()):
        if ctx == _DEFAULT_CONTEXT:
            continue
        try:
            manager.set_filter_state(name, enabled)
        except Exception:
            pass


def get_filter_state(name: str) -> bool:
    return _MANAGERS[_DEFAULT_CONTEXT].get_filter_state(name)


def set_filter_intensity(name: str, intensity: int) -> None:
    _MANAGERS[_DEFAULT_CONTEXT].set_filter_intensity(name, intensity)
    for ctx, manager in list(_MANAGERS.items()):
        if ctx == _DEFAULT_CONTEXT:
            continue
        try:
            manager.set_filter_intensity(name, intensity)
        except Exception:
            pass


def get_filter_intensity(name: str) -> int:
    return _MANAGERS[_DEFAULT_CONTEXT].get_filter_intensity(name)


def backend_loaded() -> bool:
    return _MANAGERS[_DEFAULT_CONTEXT].backend_loaded()


def backend_loaded_ctx(context: str) -> bool:
    return _get_manager(context).backend_loaded()


def shutdown() -> None:
    for manager in list(_MANAGERS.values()):
        try:
            manager.shutdown()
        except Exception:
            pass
