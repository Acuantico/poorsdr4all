"""Estado de vista de los controles de radio y sus reducers.

Puro y testeable: la vista Tk (``ui/panels/radio_panel.py``) solo pinta un
``RadioView`` y llama a los servicios; nunca calcula aquí.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from poorsdr.core.bands import BAND_MAP_HZ, infer_band
from poorsdr.core.cat.modes import DEFAULT_MODE
from poorsdr.core.tuning import FrequencyParts, format_frequency, split_frequency

if TYPE_CHECKING:
    from poorsdr.config.model import AppConfig

#: Modos que ofrece la UI (subconjunto operativo de ``MODE_TO_CAT``).
UI_MODES: tuple[str, ...] = ("LSB", "USB", "AM", "FM", "CW")


@dataclass(frozen=True, slots=True)
class RadioView:
    frequency_hz: int = 27_555_000
    mode: str = DEFAULT_MODE
    ptt: bool = False
    connected: bool = False
    step_hz: int = 1_000

    # -- derivados ------------------------------------------------------- #
    @property
    def parts(self) -> FrequencyParts:
        return split_frequency(self.frequency_hz)

    @property
    def freq_label(self) -> str:
        return format_frequency(self.frequency_hz)

    @property
    def band(self) -> str:
        return infer_band(self.frequency_hz, BAND_MAP_HZ)

    @property
    def cat_status_text(self) -> str:
        return "CAT" if self.connected else "sin CAT"


def with_frequency(view: RadioView, hz: int) -> RadioView:
    return replace(view, frequency_hz=max(0, int(hz)))


def with_mode(view: RadioView, mode: str) -> RadioView:
    m = (mode or DEFAULT_MODE).upper()
    return replace(view, mode=m if m in UI_MODES else view.mode)


def with_ptt(view: RadioView, active: bool) -> RadioView:
    return replace(view, ptt=bool(active))


def with_connected(view: RadioView, connected: bool) -> RadioView:
    return replace(view, connected=bool(connected))


def with_step(view: RadioView, step_hz: int) -> RadioView:
    return replace(view, step_hz=max(1, int(step_hz)))


def from_config(cfg: AppConfig) -> RadioView:
    """Vista inicial a partir de una ``AppConfig``."""
    return RadioView(
        frequency_hz=int(cfg.cat.start_freq_hz),
        mode=(cfg.ui.display_mode or DEFAULT_MODE).upper(),
        step_hz=max(1, int(cfg.cat.step_hz)),
    )


__all__ = [
    "UI_MODES",
    "RadioView",
    "from_config",
    "with_connected",
    "with_frequency",
    "with_mode",
    "with_ptt",
    "with_step",
]
