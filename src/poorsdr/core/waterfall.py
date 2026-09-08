"""Procesado de la cascada (FFT del audio RX → fila de magnitudes en dB).

Portado verbatim de ``RadioCBApp._update_cascada`` (la parte de señal). Puro:
``push_samples`` acumula muestras y, cuando hay suficientes, devuelve una fila
lista para pintar; ``None`` mientras tanto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np

MODES_WITH_SIDEBAND = ("USB", "LSB", "AM", "FM")


@dataclass(frozen=True, slots=True)
class WaterfallConfig:
    bins: int = 384
    rows: int = 200
    vmin: float = -50.0
    vmax: float = 0.0
    sample_rate: float = 48000.0
    bandwidth_hz: float = 12000.0
    zoom: float = 1.0


class WaterfallProcessor:
    def __init__(self, cfg: WaterfallConfig | None = None) -> None:
        self.cfg = cfg or WaterfallConfig()
        self._buffer = np.empty(0, dtype=np.float32)
        self._window: np.ndarray | None = None
        self._nfft = max(self.cfg.bins * 2, 2048)

    @property
    def nfft(self) -> int:
        return self._nfft

    def reset(self) -> None:
        self._buffer = np.empty(0, dtype=np.float32)

    def push_samples(self, samples: np.ndarray, *, mode: str = "USB") -> np.ndarray | None:
        if samples is None or samples.size == 0:
            return None
        cfg = self.cfg
        self._nfft = max(cfg.bins * 2, 2048)
        if self._window is None or self._window.size != self._nfft:
            self._window = np.hanning(self._nfft).astype(np.float32)

        chunk = samples.astype(np.float32)
        self._buffer = chunk if self._buffer.size == 0 else np.concatenate([self._buffer, chunk])
        max_buffer = max(self._nfft * 4, 8192)
        if self._buffer.size > max_buffer:
            self._buffer = self._buffer[-max_buffer:]

        if self._buffer.size >= self._nfft:
            fft_samples = self._buffer[-self._nfft:]
        else:
            fft_samples = np.pad(self._buffer, (self._nfft - self._buffer.size, 0), mode="constant")
        fft_samples = fft_samples / 32768.0

        spec = np.fft.rfft(fft_samples * self._window)
        mag = 20.0 * np.log10(np.abs(spec) + 1e-9)
        peak = float(np.max(mag)) if mag.size else 0.0
        if np.isfinite(peak):
            mag = mag - peak
        noise_floor = float(np.percentile(mag, 94)) if mag.size else -45.0
        mag = (mag - (noise_floor + 16.0)) * 1.6
        mag = np.clip(mag, cfg.vmin, cfg.vmax)

        # Espectro centrado en 0 Hz, recortado al ancho de banda efectivo.
        neg = mag[1:-1][::-1]
        full_mag = np.concatenate([neg, mag])
        full_freq = np.linspace(-cfg.sample_rate / 2.0, cfg.sample_rate / 2.0, full_mag.size)
        effective_bw = max(100.0, cfg.bandwidth_hz * cfg.zoom)
        half_bw = effective_bw / 2.0
        target_freq = np.linspace(-half_bw, half_bw, cfg.bins)
        mask = np.abs(full_freq) <= half_bw
        if np.any(mask):
            row = np.interp(target_freq, full_freq[mask], full_mag[mask])
        else:
            row = full_mag[: cfg.bins]

        upper = (mode or "USB").upper()
        if upper == "USB":
            row[target_freq < 0.0] = cfg.vmin
        elif upper == "LSB":
            row[target_freq > 0.0] = cfg.vmin
        elif upper == "AM":
            row = np.maximum(row, row[::-1])
        elif upper == "FM":
            kernel = np.ones(9, dtype=np.float32) / 9.0
            row = np.maximum(row, np.convolve(row, kernel, mode="same"))

        return cast("np.ndarray", np.clip(row, cfg.vmin, cfg.vmax).astype(np.float32))


def blank_image(cfg: WaterfallConfig) -> np.ndarray:
    return np.full((cfg.rows, cfg.bins), cfg.vmin, dtype=np.float32)


def scroll_in(image: np.ndarray, row: np.ndarray) -> np.ndarray:
    """Empuja ``row`` por abajo (la fila más nueva) y descarta la más antigua."""
    image[:-1, :] = image[1:, :]
    image[-1, :] = row
    return image


__all__ = [
    "MODES_WITH_SIDEBAND",
    "WaterfallConfig",
    "WaterfallProcessor",
    "blank_image",
    "scroll_in",
]
