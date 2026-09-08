"""core.waterfall: FFT del audio RX → fila de la cascada (puro)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

from poorsdr.core.waterfall import (  # noqa: E402
    WaterfallConfig,
    WaterfallProcessor,
    blank_image,
    scroll_in,
)


def _tone(freq_hz: float, *, n: int = 8192, rate: float = 48000.0, amp: float = 8000.0):
    t = np.arange(n) / rate
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


class WaterfallProcessorTests(unittest.TestCase):
    def test_returns_none_until_enough_samples(self):
        p = WaterfallProcessor(WaterfallConfig(bins=384))
        self.assertIsNone(p.push_samples(np.zeros(0, dtype=np.float32)))
        row = p.push_samples(_tone(1500, n=256))
        self.assertIsNotNone(row)  # se rellena con padding, siempre devuelve fila
        self.assertEqual(row.shape, (384,))

    def test_row_shape_and_range(self):
        cfg = WaterfallConfig(bins=256, vmin=-50.0, vmax=0.0)
        p = WaterfallProcessor(cfg)
        row = p.push_samples(_tone(2000), mode="AM")
        self.assertEqual(row.shape, (256,))
        self.assertTrue(np.all(row >= cfg.vmin - 1e-3))
        self.assertTrue(np.all(row <= cfg.vmax + 1e-3))

    def test_usb_zeroes_negative_frequencies(self):
        cfg = WaterfallConfig(bins=200)
        p = WaterfallProcessor(cfg)
        row = p.push_samples(_tone(2000), mode="USB")
        half = cfg.bins // 2
        # la mitad negativa queda al mínimo
        self.assertTrue(np.allclose(row[:half], cfg.vmin, atol=1e-3))
        self.assertFalse(np.allclose(row[half:], cfg.vmin))

    def test_lsb_zeroes_positive_frequencies(self):
        cfg = WaterfallConfig(bins=200)
        row = WaterfallProcessor(cfg).push_samples(_tone(2000), mode="LSB")
        half = cfg.bins // 2
        self.assertTrue(np.allclose(row[half:], cfg.vmin, atol=1e-3))

    def test_tone_shows_energy_near_its_bin(self):
        cfg = WaterfallConfig(bins=384, bandwidth_hz=12000.0)
        row = WaterfallProcessor(cfg).push_samples(_tone(3000), mode="AM")
        # el bin de mayor energía corresponde a ~±3 kHz dentro de ±6 kHz
        peak_bin = int(np.argmax(row))
        freqs = np.linspace(-6000, 6000, cfg.bins)
        self.assertAlmostEqual(abs(freqs[peak_bin]), 3000, delta=400)


class ImageHelpersTests(unittest.TestCase):
    def test_blank_and_scroll(self):
        cfg = WaterfallConfig(bins=8, rows=4, vmin=-50.0)
        img = blank_image(cfg)
        self.assertEqual(img.shape, (4, 8))
        self.assertTrue(np.all(img == -50.0))
        newrow = np.arange(8, dtype=np.float32)
        scroll_in(img, newrow)
        self.assertTrue(np.array_equal(img[-1], newrow))
        self.assertTrue(np.all(img[0] == -50.0))
        scroll_in(img, newrow + 100)
        self.assertTrue(np.array_equal(img[-1], newrow + 100))
        self.assertTrue(np.array_equal(img[-2], newrow))


if __name__ == "__main__":
    unittest.main()
