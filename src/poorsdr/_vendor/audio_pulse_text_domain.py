from __future__ import annotations

import unicodedata
from typing import Optional

from audio_pcm_domain import parse_sample_spec

# Normalización, matching y parseo de texto/dict de PulseAudio — sin IO.
# Todo lo de aquí recibe los datos ya obtenidos (por ``pactl``/JSON) como
# parámetro; el ``subprocess.run`` real se queda en ``audio.py``. Mismo
# patrón que el resto de ``audio_*_domain.py``: cálculo puro, testeable sin
# PulseAudio ni hardware real.


def normalize_linux_audio_name(value: object) -> str:
    text = str(value or "").strip().lower()
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def clean_pulse_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "(null)":
        return ""
    return text


def best_pulse_description(entry: dict) -> str:
    properties = entry.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    candidates = [
        entry.get("description"),
        properties.get("device.description"),
        properties.get("node.nick"),
        properties.get("device.nick"),
        properties.get("api.alsa.card.name"),
        properties.get("alsa.card_name"),
        properties.get("device.product.name"),
        properties.get("device.name"),
        entry.get("name"),
    ]
    for candidate in candidates:
        cleaned = clean_pulse_text(candidate)
        if cleaned:
            return cleaned
    return ""


def parse_pulse_device_entries(payload: object) -> list[dict]:
    """Convierte el JSON ya parseado de ``pactl -f json list <kind>`` en la
    forma reducida que usa ``audio.py`` (name/description/channels/rate).
    Reutiliza :func:`parse_sample_spec` de ``audio_pcm_domain`` en vez de
    duplicar el parseo de ``sample_spec`` inline.
    """
    entries: list[dict] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        description = best_pulse_description(item)
        sample_spec = item.get("sample_spec") or item.get("sample_specification") or {}
        channels, rate = parse_sample_spec(sample_spec)
        if name:
            entries.append(
                {"name": name, "description": description, "channels": channels, "rate": rate}
            )
    return entries


def filter_dict_entries(payload: object) -> list[dict]:
    return [entry for entry in payload if isinstance(entry, dict)] if isinstance(payload, list) else []


def resolve_pulse_device_from_list(target_label: object, devices: list[dict]) -> Optional[str]:
    """Empareja ``target_label`` (config del usuario) contra ``devices``
    (salida de :func:`parse_pulse_device_entries`): igualdad exacta →
    substring → puntuación por tokens compartidos.
    """
    target = normalize_linux_audio_name(target_label)
    if not target:
        return None
    for entry in devices:
        name = normalize_linux_audio_name(entry.get("name", ""))
        desc = normalize_linux_audio_name(entry.get("description", ""))
        if target == desc or target == name:
            return str(entry.get("name") or "")
    for entry in devices:
        name = normalize_linux_audio_name(entry.get("name", ""))
        desc = normalize_linux_audio_name(entry.get("description", ""))
        if target and (target in desc or target in name):
            return str(entry.get("name") or "")
    target_tokens = {token for token in target.split() if token}
    best_name = None
    best_score = 0
    for entry in devices:
        name = normalize_linux_audio_name(entry.get("name", ""))
        desc = normalize_linux_audio_name(entry.get("description", ""))
        for candidate in (desc, name):
            candidate_tokens = {token for token in candidate.split() if token}
            if not candidate_tokens:
                continue
            score = len(target_tokens & candidate_tokens)
            if score > best_score:
                best_score = score
                best_name = str(entry.get("name") or "")
    if best_name and best_score >= max(2, len(target_tokens) - 1):
        return best_name
    return None


def tx_entry_matches_hints(entry: dict, hints: tuple[str, ...]) -> bool:
    props = entry.get("properties") or {}
    if not isinstance(props, dict):
        props = {}
    haystack = " ".join(
        [
            str(props.get("media.name") or ""),
            str(props.get("application.name") or ""),
            str(props.get("node.name") or ""),
            str(props.get("application.process.binary") or ""),
            str(props.get("application.process.id") or ""),
        ]
    ).lower()
    return any(hint in haystack for hint in hints if hint)


def describe_tx_app_entry(entry: Optional[dict]) -> str:
    if not entry:
        return "App digital"
    props = entry.get("properties") or {}
    if not isinstance(props, dict):
        props = {}
    app_name = str(props.get("application.name") or props.get("application.process.binary") or "").strip()
    media_name = str(props.get("media.name") or "").strip()
    if app_name and media_name and media_name.lower() != app_name.lower():
        return f"{app_name} ({media_name})"
    return app_name or media_name or "App digital"
