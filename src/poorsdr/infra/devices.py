"""Enumeración de dispositivos del sistema para la ventana de Ajustes.

Todo es *best-effort*: si falta ``pyserial`` o ``pactl`` no está disponible,
se devuelve una lista vacía y la UI cae en entrada manual (el combo sigue
siendo editable). Nada de esto es crítico para arrancar la app.

Reemplaza los helpers ``_preferred_serial_ports`` / ``_list_pulse_devices`` de
``ajustes.py``.
"""

from __future__ import annotations

import glob
import json
import re
import shutil
import subprocess
import unicodedata
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable

    Runner = Callable[[list[str]], str]

_SERIAL_PREFIXES = (
    "/dev/ttyUSB",
    "/dev/ttyACM",
    "/dev/rfcomm",
    "/dev/ttyAMA",
    "/dev/ttyXRUSB",
    "/dev/ttyS",
)
_SERIAL_GLOBS = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/rfcomm*", "/dev/ttyAMA*", "/dev/ttyXRUSB*")


class AudioEndpoint(NamedTuple):
    """Un sink (salida) o source (entrada) de PulseAudio / PipeWire."""

    name: str  # identificador estable ("alsa_output.pci-…")
    description: str  # texto legible ("Altavoces – Realtek ALC…")
    channels: int = 0
    rate: int = 0
    pa_index: int = -1  # índice PortAudio/PyAudio equivalente (-1 si se desconoce)
    alsa_card: int = -1  # nº de tarjeta ALSA (respaldo para mostrar un número)

    @property
    def display_index(self) -> int:
        """Número a mostrar: el de PortAudio si se conoce, si no el de tarjeta ALSA."""
        return self.pa_index if self.pa_index >= 0 else self.alsa_card


def _default_runner(cmd: list[str]) -> str:
    if cmd and shutil.which(cmd[0]) is None:
        return ""
    try:
        proc = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=4, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


# --------------------------------------------------------------------------- #
# Puertos serie
# --------------------------------------------------------------------------- #
def _glob_serial() -> list[str]:
    out: list[str] = []
    for pattern in _SERIAL_GLOBS:
        out.extend(sorted(glob.glob(pattern)))
    return out


def serial_ports() -> list[str]:
    """Puertos serie del sistema, los USB/ACM primero. ``[]`` si no se puede."""
    try:
        from serial.tools import list_ports
    except Exception:  # noqa: BLE001 - sin pyserial
        return _glob_serial()
    try:
        devices = [str(getattr(p, "device", "") or "") for p in list_ports.comports()]
    except Exception:  # noqa: BLE001
        return _glob_serial()
    devices = [d for d in devices if d]
    devices.sort(key=lambda d: (not d.startswith(_SERIAL_PREFIXES), d))
    return devices or _glob_serial()


# --------------------------------------------------------------------------- #
# Dispositivos de audio (pactl)
# --------------------------------------------------------------------------- #
def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("(null)", "null", "none") else text


_DESC_KEYS = (
    "_top_description",  # "description" del JSON (en texto se usan las props punteadas)
    "device.description",
    "node.nick",
    "alsa.card_name",
    "node.description",
    "device.product.name",
)


def _describe(props: dict, name: str) -> str:
    for key in _DESC_KEYS:
        cleaned = _clean(props.get(key))
        if cleaned:
            return cleaned
    return name


# -- pactl -f json (fiable en PulseAudio clásico) ---------------------------- #
def _parse_pactl_json(raw: str) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    out: list[dict] = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        raw_props = entry.get("properties")
        props = dict(raw_props) if isinstance(raw_props, dict) else {}
        props["_top_description"] = entry.get("description")
        spec = entry.get("sample_specification") or entry.get("sample_spec") or {}
        channels = int(spec.get("channels") or 0) if isinstance(spec, dict) else 0
        rate = int(spec.get("rate") or 0) if isinstance(spec, dict) else 0
        out.append({"name": name, "props": props, "channels": channels, "rate": rate})
    return out


# -- pactl list <kind> (texto): PipeWire devuelve "(null)" en el JSON -------- #
_PROP_RE = re.compile(r'^\s+([A-Za-z0-9_.:-]+) = "?(.*?)"?\s*$')
_SPEC_RE = re.compile(r"(\d+)ch\s+(\d+)\s*Hz")
_HDR_RE = re.compile(r"#(\d+)\s*$")


def _parse_pactl_text(verbose: str, short: str) -> list[dict]:
    names: dict[str, str] = {}
    for line in (short or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            names[parts[0].strip()] = parts[1].strip()

    blocks: list[dict] = []
    cur: dict | None = None
    for line in (verbose or "").splitlines():
        if line and not line[0].isspace():
            if cur is not None:
                blocks.append(cur)
            match = _HDR_RE.search(line)
            cur = {"idx": match.group(1) if match else "", "props": {}, "channels": 0, "rate": 0}
            continue
        if cur is None:
            continue
        prop = _PROP_RE.match(line)
        if prop:
            cur["props"][prop.group(1)] = prop.group(2)
        spec = _SPEC_RE.search(line)
        if spec and not cur["channels"]:
            cur["channels"], cur["rate"] = int(spec.group(1)), int(spec.group(2))
    if cur is not None:
        blocks.append(cur)

    out: list[dict] = []
    for block in blocks:
        props = block["props"]
        # El nombre "corto" es el bueno: en PipeWire los monitores llevan el
        # ``node.name`` del sink padre (sin ``.monitor``) y se colarían.
        name = names.get(block["idx"], "") or props.get("node.name") or ""
        if not name:
            continue
        out.append(
            {"name": name, "props": props, "channels": block["channels"], "rate": block["rate"]}
        )
    return out


def normalize_label(value: object) -> str:
    """Normaliza un nombre de dispositivo para comparar (como en ``ajustes.py``)."""
    text = str(value or "").strip().lower()
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


_HW_RE = re.compile(r"\(hw:(\d+)")


def _portaudio_index_maps() -> tuple[dict[str, int], dict[str, int]]:
    """``(entradas, salidas)`` → mapa de PyAudio: por nombre normalizado y por
    ``"card:N"`` (tarjeta ALSA, extraída de ``(hw:N,M)`` del nombre).

    Vacío si no hay ``pyaudio`` (no es imprescindible: el índice cae en -1).
    """
    inputs: dict[str, int] = {}
    outputs: dict[str, int] = {}
    try:
        import pyaudio

        pa = pyaudio.PyAudio()
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                name = str(info.get("name", "") or "")
                keys = [k for k in (normalize_label(name),) if k]
                match = _HW_RE.search(name)
                if match:
                    keys.append(f"card:{match.group(1)}")
                if int(info.get("maxInputChannels", 0) or 0) > 0:
                    for k in keys:
                        inputs.setdefault(k, i)
                if int(info.get("maxOutputChannels", 0) or 0) > 0:
                    for k in keys:
                        outputs.setdefault(k, i)
        finally:
            pa.terminate()
    except Exception:  # noqa: BLE001 - sin pyaudio / portaudio
        return {}, {}
    return inputs, outputs


def _match_index(description: str, props: dict, index_map: dict[str, int]) -> int:
    if not index_map:
        return -1
    target = normalize_label(description)
    if target:
        if target in index_map:
            return index_map[target]
        for key, idx in index_map.items():
            if key.startswith("card:"):
                continue
            if key in target or target in key:
                return idx
    card = props.get("alsa.card")
    if card not in (None, ""):
        return index_map.get(f"card:{str(card).strip()}", -1)
    return -1


def _is_hidden(name: str, props: dict) -> bool:
    """Sinks/sources internos que no deben salir en la lista de Ajustes."""
    if str(props.get("node.hidden", "")).strip().lower() in ("true", "1", "yes"):
        return True
    blob = (name + " " + " ".join(str(v) for v in props.values())).lower()
    return "poorsdr" in blob or "owrx-anr" in blob


def _pactl_list(kind: str, runner: Runner, index_map: dict[str, int]) -> list[AudioEndpoint]:
    try:
        raw = runner(["pactl", "list", kind]) or ""
    except Exception:  # noqa: BLE001 - runner que lanza
        return []
    if raw.lstrip().startswith("["):  # el test / runner devolvió JSON
        entries = _parse_pactl_json(raw)
    else:
        try:
            short = runner(["pactl", "list", kind, "short"]) or ""
        except Exception:  # noqa: BLE001
            short = ""
        entries = _parse_pactl_text(raw, short)

    endpoints: list[AudioEndpoint] = []
    for entry in entries:
        name = entry["name"]
        props = entry["props"]
        if name.lower().endswith(".monitor") or _is_hidden(name, props):
            continue
        description = _describe(props, name)
        try:
            card = int(str(props.get("alsa.card", "")).strip())
        except (TypeError, ValueError):
            card = -1
        endpoints.append(
            AudioEndpoint(
                name, description, entry["channels"], entry["rate"],
                _match_index(description, props, index_map), card,
            )
        )
    return endpoints


def audio_outputs(*, runner: Runner = _default_runner) -> list[AudioEndpoint]:
    """Sinks de PulseAudio (altavoces / salidas), con índice PyAudio si se puede."""
    return _pactl_list("sinks", runner, _portaudio_index_maps()[1])


def audio_inputs(*, runner: Runner = _default_runner) -> list[AudioEndpoint]:
    """Sources de PulseAudio (micrófonos / entradas), sin los ``.monitor``."""
    return _pactl_list("sources", runner, _portaudio_index_maps()[0])


__all__ = [
    "AudioEndpoint",
    "audio_inputs",
    "audio_outputs",
    "normalize_label",
    "serial_ports",
]
