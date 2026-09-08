"""Catálogo de acciones asignables a teclas y resolución con los ajustes.

Sin tkinter: solo datos. La ventana de Ajustes (``settings/hotkeys_panel.py``)
pinta un editor a partir de :data:`HOTKEY_ACTIONS`; ``ui/app.py`` enlaza las
teclas y ``ui/main_window.py`` ejecuta cada acción vía ``MainWindow.invoke``.

Se excluyen a propósito EDIT, Ajustes y WEB ON/OFF (no deben tener atajo).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from poorsdr.config.defaults import DEFAULT_HOTKEYS

if TYPE_CHECKING:
    from collections.abc import Mapping


class HotkeyAction(NamedTuple):
    id: str
    label_key: str  # clave en poorsdr.i18n.settings_labels.LABELS


#: Orden y etiquetas (clave de traducción) de la pestaña "Atajos".
HOTKEY_ACTIONS: tuple[HotkeyAction, ...] = (
    HotkeyAction("ptt_toggle", "hk_ptt_toggle"),
    HotkeyAction("tune_tone", "hk_tune_tone"),
    HotkeyAction("vfo_up", "hk_vfo_up"),
    HotkeyAction("vfo_down", "hk_vfo_down"),
    HotkeyAction("ch_plus", "hk_ch_plus"),
    HotkeyAction("ch_minus", "hk_ch_minus"),
    HotkeyAction("mode_next", "hk_mode_next"),
    HotkeyAction("mode_prev", "hk_mode_prev"),
    HotkeyAction("band_next", "hk_band_next"),
    HotkeyAction("band_prev", "hk_band_prev"),
    HotkeyAction("step_next", "hk_step_next"),
    HotkeyAction("step_prev", "hk_step_prev"),
    HotkeyAction("anr_toggle", "hk_anr_toggle"),
    HotkeyAction("anr_up", "hk_anr_up"),
    HotkeyAction("anr_down", "hk_anr_down"),
    HotkeyAction("rx_vol_up", "hk_rx_vol_up"),
    HotkeyAction("rx_vol_down", "hk_rx_vol_down"),
    HotkeyAction("tx_gain_up", "hk_tx_gain_up"),
    HotkeyAction("tx_gain_down", "hk_tx_gain_down"),
    HotkeyAction("rx_source_radio", "hk_rx_source_radio"),
    HotkeyAction("rx_source_sdr", "hk_rx_source_sdr"),
    HotkeyAction("toggle_spots", "hk_toggle_spots"),
    HotkeyAction("open_digi", "hk_open_digi"),
    HotkeyAction("open_owrx", "hk_open_owrx"),
    HotkeyAction("open_libro", "hk_open_libro"),
    HotkeyAction("open_mem", "hk_open_mem"),
    HotkeyAction("auto_call_1", "hk_auto_call_1"),
    HotkeyAction("auto_call_2", "hk_auto_call_2"),
    HotkeyAction("auto_call_3", "hk_auto_call_3"),
    HotkeyAction("auto_call_4", "hk_auto_call_4"),
)

ACTION_IDS: frozenset[str] = frozenset(a.id for a in HOTKEY_ACTIONS)


def resolved(user: Mapping[str, str] | None) -> dict[str, str]:
    """``{id: keysym}`` para cada acción: por defecto + lo que ponga el usuario.

    Solo se conservan ids conocidos y keysyms no vacíos.
    """
    merged = dict(DEFAULT_HOTKEYS)
    for key, value in (user or {}).items():
        if key in ACTION_IDS:
            merged[key] = str(value or "").strip()
    return {a.id: merged.get(a.id, "").strip() for a in HOTKEY_ACTIONS}


def active_bindings(user: Mapping[str, str] | None) -> dict[str, str]:
    """Como :func:`resolved` pero sin las acciones sin tecla."""
    return {aid: key for aid, key in resolved(user).items() if key}


__all__ = ["ACTION_IDS", "HOTKEY_ACTIONS", "HotkeyAction", "active_bindings", "resolved"]
