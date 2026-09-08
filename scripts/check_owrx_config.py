#!/usr/bin/env python3
"""Comprueba que la plantilla OpenWebRX+ coincide con las bandas de PoorSDR."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poorsdr.config.defaults import DEFAULT_OWRX_BAND_PROFILES  # noqa: E402
from poorsdr.core.bands import BAND_MAP_HZ  # noqa: E402

SETTINGS = ROOT / "assets" / "owrx" / "settings.json"
BOOKMARKS = ROOT / "assets" / "owrx" / "bookmarks.json"


def validate() -> list[str]:
    errors: list[str] = []
    try:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"settings.json no es legible: {error}"]

    if settings.get("version") != 8:
        errors.append("la plantilla debe usar el esquema OpenWebRX+ version=8")
    if settings.get("audio_compression") != "adpcm" or settings.get("fft_compression") != "adpcm":
        errors.append("audio_compression y fft_compression deben ser adpcm")
    if settings.get("allow_center_freq_changes") is not True:
        errors.append("allow_center_freq_changes debe estar activo para la integración")

    sdrs = settings.get("sdrs")
    if not isinstance(sdrs, dict) or not sdrs:
        return [*errors, "no hay ningún receptor SDR configurado"]

    labels: dict[str, dict] = {}
    for sdr in sdrs.values():
        if not isinstance(sdr, dict):
            continue
        sdr_name = str(sdr.get("name") or "").strip()
        profiles = sdr.get("profiles")
        if not isinstance(profiles, dict):
            continue
        for profile in profiles.values():
            if isinstance(profile, dict):
                labels[f"{sdr_name} {profile.get('name', '')}".strip()] = profile

    if set(DEFAULT_OWRX_BAND_PROFILES) != set(BAND_MAP_HZ):
        missing = sorted(set(BAND_MAP_HZ) - set(DEFAULT_OWRX_BAND_PROFILES))
        extra = sorted(set(DEFAULT_OWRX_BAND_PROFILES) - set(BAND_MAP_HZ))
        errors.append(f"mapa OWRX desincronizado; faltan={missing}, sobran={extra}")

    lsb_bands = {"160m", "80m", "60m", "40m"}
    for band, frequency in BAND_MAP_HZ.items():
        label = DEFAULT_OWRX_BAND_PROFILES.get(band, "")
        profile = labels.get(label)
        if profile is None:
            errors.append(f"falta el perfil visible {label!r} para {band}")
            continue
        try:
            center = int(profile["center_freq"])
            sample_rate = int(profile["samp_rate"])
            start = int(profile["start_freq"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"perfil {label!r}: frecuencias o sample rate inválidos")
            continue
        if not 250_000 <= sample_rate <= 3_200_000:
            errors.append(f"perfil {label!r}: samp_rate fuera del rango RTL-SDR")
        if not center - sample_rate / 2 <= start <= center + sample_rate / 2:
            errors.append(f"perfil {label!r}: start_freq queda fuera de la captura")
        if start != frequency:
            errors.append(f"perfil {label!r}: start_freq={start} pero PoorSDR usa {frequency}")
        expected_mode = "lsb" if band in lsb_bands else "usb"
        if profile.get("start_mod") != expected_mode:
            errors.append(f"perfil {label!r}: start_mod debe ser {expected_mode}")
        if frequency < 24_000_000 and profile.get("direct_sampling") != 2:
            errors.append(f"perfil {label!r}: falta direct_sampling=2 para RTL-SDR clásico")

    try:
        bookmarks = json.loads(BOOKMARKS.read_text(encoding="utf-8"))
        if bookmarks != []:
            errors.append("bookmarks.json debe estar vacío para no duplicar marcadores de banda")
    except (OSError, ValueError) as error:
        errors.append(f"bookmarks.json no es legible: {error}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Plantilla OpenWebRX+ NO válida:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Plantilla OpenWebRX+ válida: 10 bandas sincronizadas con PoorSDR4All.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
