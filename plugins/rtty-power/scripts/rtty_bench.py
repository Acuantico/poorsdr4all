"""Banco de pruebas del decodificador RTTY: tasa de error de caracteres (CER).

Uso:  .venv/bin/python3 scripts/rtty_bench.py [--quick]

Mide cada decodificador con exactamente las mismas señales, todas a 45.45
baudios / 170 Hz y 48 kHz, alimentadas en trozos de ~90 ms como en la app:

- ruido blanco a varias SNR (definición habitual: potencia de señal frente a
  potencia de ruido en 2500 Hz);
- canal HF de dos trayectos con desvanecimiento (tipo Watterson/CCIR): el
  retardo entre trayectos hunde una frecuencia y no la otra -- desvanecimiento
  selectivo, lo que más castiga a RTTY en la práctica;
- error de sintonía, deriva de velocidad, estación vecina, polaridad invertida;
- ruido solo: cuántos caracteres basura imprime sin señal;
- grabaciones reales de tests/fixtures (opcionales: si no están, se saltan).
"""

from __future__ import annotations

import argparse
import sys
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poorsdr_rtty_power.rtty import RttyDemodulator, generate_fsk_samples  # noqa: E402

SR = 48000
CHUNK = 4320
SHIFT = 170.0
CENTER = 1500.0
FIXTURES = ROOT / "tests" / "fixtures"

TEXTS = [
    "CQ TEST DE EA1ABC EA1ABC EA1ABC TEST\n",
    "EA1ABC 599 14 14 DE K1XYZ\n",
    "K1XYZ TU 599 05 05 EA1ABC\n",
    "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG 1234567890\n",
    "QRZ DE OH2BH OH2BH TEST\n",
    "DL1ZZZ 599 14 14 14 BK\n",
]

DecoderFactory = Callable[..., object]


# ---------------------------------------------------------------- métrica --
def cer(decoded: str, truth: str) -> float:
    """Distancia de edición con extremos libres en lo decodificado (la
    basura antes/después del mensaje no cuenta), dividida por len(truth)."""
    d = decoded.replace("\r", "")
    t = truth
    prev = np.zeros(len(d) + 1, dtype=np.int32)  # fila 0: prefijo libre
    for i in range(1, len(t) + 1):
        cur = np.empty_like(prev)
        cur[0] = i
        ti = t[i - 1]
        for j in range(1, len(d) + 1):
            cost = 0 if d[j - 1] == ti else 1
            cur[j] = min(prev[j - 1] + cost, prev[j] + 1, cur[j - 1] + 1)
        prev = cur
    return float(prev.min()) / max(1, len(t))


# ------------------------------------------------------------------ canal --
def analytic(x: np.ndarray) -> np.ndarray:
    n = x.size
    spec = np.fft.fft(x)
    h = np.zeros(n)
    h[0] = 1
    if n % 2 == 0:
        h[n // 2] = 1
        h[1 : n // 2] = 2
    else:
        h[1 : (n + 1) // 2] = 2
    return np.fft.ifft(spec * h)


def slow_gain(n: int, doppler_hz: float, rng: np.random.Generator) -> np.ndarray:
    """Ganancia compleja gaussiana de ancho Doppler ~doppler_hz (Rayleigh)."""
    step = 100  # genera a SR/100 y interpola: barato y suave
    m = n // step + 4
    g = rng.normal(size=m) + 1j * rng.normal(size=m)
    k = max(1, int(SR / step / doppler_hz))
    win = np.hanning(2 * k + 1)
    g = np.convolve(g, win / np.sqrt(np.sum(win**2)), mode="same")
    t = np.arange(n) / step
    return np.interp(t, np.arange(m), g.real) + 1j * np.interp(t, np.arange(m), g.imag)


def watterson(x: np.ndarray, delay_ms: float, doppler_hz: float, rng) -> np.ndarray:
    a = analytic(x)
    d = int(SR * delay_ms / 1000)
    a2 = np.concatenate([np.zeros(d, complex), a[: a.size - d]])
    g1 = slow_gain(x.size, doppler_hz, rng)
    g2 = slow_gain(x.size, doppler_hz, rng)
    y = np.real(g1 * a + g2 * a2) / np.sqrt(2)
    return y


def add_noise(x: np.ndarray, snr_db: float, rng, signal_power: float) -> np.ndarray:
    sigma2 = signal_power * SR / (5000.0 * 10 ** (snr_db / 10))
    return x + rng.normal(0, np.sqrt(sigma2), x.size)


def make_signal(text, *, center=CENTER, baud=45.45, amp=0.25, reverse=False):
    shift = -SHIFT if reverse else SHIFT
    pad = np.zeros(int(SR * 1.0))
    body = generate_fsk_samples(
        text, sample_rate=SR, center_hz=center, shift_hz=shift, baud=baud,
        amplitude=amp, idle_marks=6,
    ).astype(np.float64)
    return np.concatenate([pad, body, pad])


# --------------------------------------------------------------- escenarios --
def scenarios(quick: bool):
    snrs = [10, 0, -4, -7, -10] if quick else [15, 5, 0, -3, -6, -8, -10, -12]
    for snr in snrs:
        yield f"AWGN {snr:+d} dB", dict(snr=snr)
    for snr in ([10, 0] if quick else [15, 5, 0, -3]):
        yield f"Fading CCIR moderado (1 ms, 0.5 Hz) {snr:+d} dB", dict(snr=snr, fade=(1.0, 0.5))
        yield f"Fading CCIR malo (2 ms, 1 Hz) {snr:+d} dB", dict(snr=snr, fade=(2.0, 1.0))
    yield "Sintonía +15 Hz, 0 dB", dict(snr=0, offset=15.0)
    yield "Velocidad +1.5 %, 0 dB", dict(snr=0, baud=45.45 * 1.015)
    yield "Estación a +250 Hz, 6 dB más fuerte, 0 dB", dict(snr=0, qrm=(250.0, 2.0))
    yield "Estación a +350 Hz, 12 dB más fuerte, 0 dB", dict(snr=0, qrm=(350.0, 4.0))
    yield "Polaridad invertida, 5 dB", dict(snr=5, reverse=True)


def run_decoder(factory, audio, *, center, reverse) -> str:
    dec = factory(sample_rate=SR, center_hz=center, shift_hz=SHIFT, reverse=reverse)
    out = []
    for i in range(0, audio.size, CHUNK):
        out.append(dec.feed(audio[i : i + CHUNK].astype(np.float32)))
    return "".join(out)


def bench(decoders: dict[str, DecoderFactory], quick: bool, seeds: int) -> None:
    names = list(decoders)
    print(f"{'escenario':52s}" + "".join(f"{n:>14s}" for n in names))
    for label, p in scenarios(quick):
        errs = {n: [] for n in names}
        for seed in range(seeds):
            rng = np.random.default_rng(1000 + seed)
            text = "".join(TEXTS[(seed + k) % len(TEXTS)] for k in range(3))
            reverse = p.get("reverse", False)
            x = make_signal(text, baud=p.get("baud", 45.45), reverse=reverse,
                            center=CENTER + p.get("offset", 0.0))
            power = float(np.mean(x[x != 0] ** 2))
            if "fade" in p:
                x = watterson(x, *p["fade"], rng)
            if "qrm" in p:
                df, rel = p["qrm"]
                other = make_signal("RYRYRY CQ CQ DE W1AW W1AW K " * 8, center=CENTER + df,
                                    amp=0.25 * rel)
                x = x + other[: x.size]
            x = add_noise(x, p["snr"], rng, power)
            x *= 0.3 / max(1e-9, np.max(np.abs(x)))
            for n in names:
                got = run_decoder(decoders[n], x, center=CENTER, reverse=reverse)
                errs[n].append(cer(got, text))
        print(f"{label:52s}" + "".join(f"{100*np.mean(errs[n]):13.1f}%" for n in names))

    # ruido solo: caracteres basura por minuto
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 0.05, SR * 60)
    print(f"{'Solo ruido: caracteres basura por minuto':52s}" + "".join(
        f"{len(run_decoder(decoders[n], noise, center=CENTER, reverse=False).strip()):14d}"
        for n in names))

    # grabaciones reales
    for fn, center, reverse, truth in (
        ("generated_bartg_wikipedia_45bd_170hz_reverse_6000sr.wav", 1000.9, True,
         "WELCOME TO WIKIPEDIA, THE FREE ENCYCLOPEDIA THAT"),
        ("offair_ru3amo_cq_14084k7_45bd_170hz_7119sr.wav", 518.3, False, None),
    ):
        if not (FIXTURES / fn).exists():
            continue  # grabaciones opcionales, no se distribuyen con el plugin
        with wave.open(str(FIXTURES / fn)) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        print(f"\n{fn}")
        for n in names:
            dec = decoders[n](sample_rate=sr, center_hz=center, shift_hz=SHIFT, reverse=reverse)
            got = "".join(dec.feed(x[i : i + sr // 10]) for i in range(0, x.size, sr // 10))
            extra = f"  CER {100*cer(got, truth):.1f}%" if truth else ""
            print(f"  {n:12s}{extra}  {got.strip()!r}")


def demodulator(*, sample_rate, center_hz, shift_hz, reverse):
    return RttyDemodulator(
        sample_rate=sample_rate, center_hz=center_hz, shift_hz=shift_hz, reverse=reverse
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    bench({"RttyDemodulator": demodulator}, args.quick, args.seeds)


if __name__ == "__main__":
    main()
