"""Interfaz nueva de PoorSDR4All.

La ventana principal (``MainWindow``) reproduce la consola de operación; sus
controles hablan con los servicios mediante ``EventBus``. Memorias y Ajustes
se abren en ventanas propias, y la cascada y el visor digital se ejecutan como
visores externos coordinados con la consola.
"""

from __future__ import annotations

import contextlib
import re
import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import messagebox
from typing import TYPE_CHECKING, Any

import numpy as np

from poorsdr.core.bands import band_center_hz
from poorsdr.core.theme import accent_for_background
from poorsdr.core.tuning import apply_step, coerce_frequency, combine_frequency
from poorsdr.core.waterfall import WaterfallProcessor
from poorsdr.i18n import t
from poorsdr.infra import logging as plog
from poorsdr.infra import paths
from poorsdr.ui import state as ui_state
from poorsdr.ui.main_window import Callbacks, MainWindow
from poorsdr.ui.panels.memory_panel import MemoryPanel
from poorsdr.ui.state import RadioView
from poorsdr.ui.theme import THEME_COLORS

if TYPE_CHECKING:
    from poorsdr.core.memory import MemoryEntry
    from poorsdr.infra.events import Event
    from poorsdr.runtime import AppContext

_log = plog.get_logger("ui")

_GEOM_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")


def _parse_geometry(value: object) -> tuple[int, int, int, int] | None:
    m = _GEOM_RE.match(str(value or "").strip())
    if m is None:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


class PoorSDRApp:
    def __init__(self, context: AppContext) -> None:
        self.ctx = context
        self.view = ui_state.from_config(context.config)
        self._memory_window: tk.Toplevel | None = None
        self._wf = WaterfallProcessor()
        self._wf_after: str | None = None

        self.root = tk.Tk()

        self._accent = accent_for_background(context.config.ui.background_image)
        self.win = MainWindow(
            self.root,
            self._callbacks(),
            accent=self._accent,
            background=context.config.ui.background_image or "back.png",
            lang=context.config.ui.language,
            smeter_calibrated=context.config.owrx.smeter_calibrated,
            smeter_s9_dbfs=context.config.owrx.smeter_s9_dbfs,
            smeter_noise_floor_s=context.config.owrx.smeter_noise_floor_s,
        )
        self.win.apply_view(self.view)
        self.win.set_spots_enabled(context.config.owrx.spots.enabled)
        self.win.set_web_enabled(context.config.web.enabled)
        self.win.show_rx_source(context.config.audio.rx_source)
        self.win.set_anr_state(
            context.config.dsp.anr_enabled, context.config.dsp.anr_intensity
        )
        for spec in context.plugins.console_buttons:
            self.win.add_plugin_button(spec.id, spec.label, spec.on_click)
        self._backend_ready = False
        self._client_ready = False
        self._waterfall_open = False

        # Geometría: el tamaño ya lo fija MainWindow (reescalado a la pantalla
        # real, ver self.win._scale) al construirse — aquí solo se restaura la
        # posición, nunca el tamaño, para no deshacer ese reescalado. Antes
        # esto usaba un tamaño fijo ("620x760") propio, que en pantallas más
        # pequeñas volvía a agrandar la ventana justo después de que
        # MainWindow la hubiera encogido para que cupiera. La posición se
        # restaura con un lazo de compensación porque el gestor de ventanas
        # reubica la ventana tras mapearla (si no, cada arranque abre un poco
        # más abajo).
        self._win_size = f"{self.win._win_w}x{self.win._win_h}"
        self._restoring_geom = False
        self._current_geom = ""
        self._geom_save_after: str | None = None
        parsed = _parse_geometry(context.config.ui.window_geometry)
        self._target_xy: tuple[int, int] | None = (
            (parsed[2], parsed[3]) if parsed is not None else None
        )
        with contextlib.suppress(tk.TclError):
            self.root.geometry(
                f"{self._win_size}+{self._target_xy[0]}+{self._target_xy[1]}"
                if self._target_xy is not None
                else self._win_size
            )
        self.root.bind("<Configure>", self._on_configure, add="+")

        self._unsubs = [
            self.ctx.bus.subscribe("radio.frequency", self._on_radio_frequency),
            self.ctx.bus.subscribe("radio.mode", self._on_radio_mode),
            self.ctx.bus.subscribe("radio.ptt", self._on_radio_ptt),
            self.ctx.bus.subscribe("radio.status", self._on_radio_status),
            self.ctx.bus.subscribe("memory.changed", self._on_memory_changed),
            self.ctx.bus.subscribe("autocall.started", lambda ev: self._marshal(
                lambda: self.win.set_autocall_running(ev.get("button")))),
            self.ctx.bus.subscribe("autocall.finished", lambda _e: self._marshal(
                lambda: self.win.set_autocall_running(None))),
            self.ctx.bus.subscribe("owrx.status", self._on_owrx_status),
            self.ctx.bus.subscribe("owrx.tune", self._on_owrx_tune),
            self.ctx.bus.subscribe(
                "owrx.smeter",
                lambda ev: self._marshal(lambda: self.win.set_smeter_dbfs(float(ev["dbfs"]))),
            ),
            self.ctx.bus.subscribe(
                "web.status",
                lambda ev: self._marshal(
                    lambda: self.win.set_web_enabled(bool(ev.get("running")))
                ),
            ),
            self.ctx.bus.subscribe(
                "audio.anr",
                lambda ev: self._marshal(
                    lambda: self.win.set_anr_state(bool(ev["enabled"]), int(ev["intensity"]))
                ),
            ),
            self.ctx.bus.subscribe("audio.volume", self._on_audio_volume),
            self.ctx.bus.subscribe(
                "radio.step",
                lambda ev: self._marshal(lambda: self.win.show_step_khz(float(ev["hz"]) / 1000.0)),
            ),
        ]
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._hotkey_binds: list[str] = []
        self._bind_hotkeys()

    # ---- atajos de teclado --------------------------------------- #
    def _bind_hotkeys(self) -> None:
        from poorsdr.ui.hotkeys import active_bindings

        for keysym in self._hotkey_binds:
            with contextlib.suppress(tk.TclError):
                self.root.unbind_all(keysym)
        self._hotkey_binds = []
        for action_id, keysym in active_bindings(self.ctx.config.ui.hotkeys).items():
            seq = f"<KeyPress-{keysym}>"
            with contextlib.suppress(tk.TclError):
                self.root.bind_all(seq, lambda _e, a=action_id: self._run_hotkey(a))
                self._hotkey_binds.append(seq)

    def _run_hotkey(self, action_id: str) -> object:
        # No dispares atajos mientras se escribe en un campo de texto.
        widget = self.root.focus_get()
        if widget is not None and widget.winfo_class() in ("Entry", "TEntry", "Spinbox", "Text"):
            return None
        with contextlib.suppress(Exception):
            self.win.invoke(action_id)
        return "break"

    # ---- cableado de callbacks -------------------------------------- #
    def _callbacks(self) -> Callbacks:
        return Callbacks(
            tune=self._tune,
            nudge=self._nudge,
            channel=self._nudge,
            set_step=self._set_step,
            set_mode=self._set_mode,
            set_band=self._set_band,
            toggle_ptt=lambda: self._set_ptt(not self.view.ptt),
            toggle_tune_tone=self._toggle_tune_tone,
            run_autocall=self._run_autocall,
            toggle_anr=lambda on: self._reconfigure_dsp(anr_enabled=on),
            set_anr_intensity=lambda n: self._reconfigure_dsp(anr_intensity=n),
            set_rx_volume=self._set_rx_volume,
            set_tx_volume=self._set_tx_volume,
            set_rx_source=self._set_rx_source,
            open_settings=self._open_settings,
            open_memories=self._open_memories,
            open_owrx=self._toggle_waterfall,
            toggle_digi=self._toggle_digi,
            get_spots=self._get_spots,
            set_spots=self._set_spots,
            toggle_web=self._toggle_web,
            combine_frequency=lambda a, b, c: combine_frequency(a, b, c),
        )

    # ---- helpers de servicios -------------------------------------- #
    def _svc(self, name: str) -> Any:
        return self.ctx.services.get(name)

    def _set_rx_volume(self, value: float) -> None:
        svc = self._svc("audio")
        if svc is not None:
            svc.set_rx_volume(float(value))

    def _set_tx_volume(self, value: float) -> None:
        svc = self._svc("audio")
        if svc is not None:
            svc.set_tx_volume(float(value))

    # ---- acciones de radio --------------------------------------- #
    def _tune(self, hz: int) -> None:
        hz = coerce_frequency(hz)
        r = self._svc("radio")
        if r is not None:
            r.set_frequency(hz, source="ui")
        else:
            self._render(ui_state.with_frequency(self.view, hz))

    def _nudge(self, direction: int) -> None:
        self._tune(apply_step(self.view.frequency_hz, self.view.step_hz, direction))

    def _set_step(self, khz: float) -> None:
        """Paso de sintonía elegido en la consola (kHz) → vista + config + visores."""
        step_hz = max(1, int(round(khz * 1000)))
        self._render(ui_state.with_step(self.view, step_hz))
        svc = self._svc("owrx-control")
        if svc is not None:
            svc.set_step(step_hz)
        self._reconfigure(lambda cfg: replace(cfg, cat=replace(cfg.cat, step_hz=step_hz)))

    def _set_mode(self, mode: str) -> None:
        r = self._svc("radio")
        if r is not None:
            r.set_mode(mode, source="ui")
        else:
            self._render(ui_state.with_mode(self.view, mode))

    def _set_band(self, band: str) -> None:
        center = band_center_hz(band)
        if center is not None:
            self._tune(center)

    def _set_ptt(self, active: bool) -> None:
        audio = self._svc("audio")
        if audio is not None:
            (audio.start_tx if active else audio.stop_tx)()
        r = self._svc("radio")
        if r is not None:
            r.set_ptt(active, source="ui")
        else:
            self._render(ui_state.with_ptt(self.view, active))

    def _toggle_tune_tone(self, on: bool) -> None:
        audio = self._svc("audio")
        if audio is None:
            return
        if on:
            audio.start_tune_tone()
            r = self._svc("radio")
            if r is not None:
                r.set_ptt(True, source="tune")
        else:
            audio.stop_tune_tone()
            r = self._svc("radio")
            if r is not None:
                r.set_ptt(False, source="tune")

    def _run_autocall(self, index: int) -> None:
        svc = self._svc("autocall")
        if svc is None:
            return
        if svc.running or not svc.run_button(index):
            svc.cancel()

    def _refresh_autocall_buttons(self) -> None:
        svc = self._svc("autocall")
        labels = svc.button_labels if svc is not None else ["", "", "", ""]
        self.win.set_autocall_profiles([lbl or str(i + 1) for i, lbl in enumerate(labels)])

    def _set_rx_source(self, src: str) -> None:
        self._reconfigure(lambda cfg: replace(cfg, audio=replace(cfg.audio, rx_source=src)))

    # ---- reconfiguración ----------------------------------------- #
    def _reconfigure(self, mutate: Callable[[Any], Any]) -> None:
        self.ctx.reconfigure(mutate(self.ctx.config))

    def _reconfigure_ui(self, **fields: object) -> None:
        self._reconfigure(lambda cfg: replace(cfg, ui=replace(cfg.ui, **fields)))

    def _reconfigure_dsp(self, **fields: object) -> None:
        self._reconfigure(lambda cfg: replace(cfg, dsp=replace(cfg.dsp, **fields)))

    # ---- ajustes --------------------------------------------- #
    def _open_settings(self) -> None:
        existing = getattr(self, "_settings_win", None)
        if existing is not None and existing.top.winfo_exists():
            existing.top.deiconify()
            existing.top.lift()
            existing.top.focus_force()
            return
        from poorsdr.ui.settings import SettingsWindow

        self._settings_win = SettingsWindow(
            self.root, self.ctx.config, self._on_settings_saved,
            plugins=self.ctx.plugins.discovered,
            plugin_tabs=self.ctx.plugins.settings_tabs,
        )

    def _on_settings_saved(self, new_cfg: Any) -> None:
        self.ctx.reconfigure(new_cfg)
        self.view = ui_state.from_config(new_cfg)
        self.win.apply_view(self.view)
        self.win.set_spots_enabled(new_cfg.owrx.spots.enabled)
        self.win.show_rx_source(new_cfg.audio.rx_source)
        self.win.set_anr_state(new_cfg.dsp.anr_enabled, new_cfg.dsp.anr_intensity)
        self.win.set_smeter_calibration(new_cfg.owrx.smeter_calibrated, new_cfg.owrx.smeter_s9_dbfs)
        self.win.set_smeter_noise_floor(new_cfg.owrx.smeter_noise_floor_s)
        self._accent = accent_for_background(new_cfg.ui.background_image)
        # El fondo tiene que fijarse antes: la cascada usa el nombre de fondo
        # activo (no solo el acento) para saber si le toca su degradado fijo
        # estilo Classic en vez del derivado del acento.
        self.win.set_background(new_cfg.ui.background_image or "back.png")
        self.win.set_theme_accent(self._accent)
        self._refresh_autocall_buttons()
        self._bind_hotkeys()

    # ---- visores externos ------------------------------------- #
    def _control_port(self) -> int:
        svc = self._svc("owrx-control")
        return int(getattr(svc, "port", 0)) if svc is not None else 0

    def _waterfall_default_geometry(self) -> str:
        """Geometría de la cascada la primera vez (sin nada guardado aún en
        ``cfg.ui.owrx_window_geometry``): a lo ancho de la pantalla, justo
        debajo de la consola real — nunca el "1912x262+0+789" fijo de
        ``launcher.py``, pensado para una pantalla de referencia bastante
        más ancha que la de cualquiera y que en una más pequeña se sale
        literalmente fuera (confirmado en real: ni se veía)."""
        try:
            root = self.root
            root.update_idletasks()
            screen_h = root.winfo_screenheight()
            console_bottom = root.winfo_y() + root.winfo_height()
            margin_bottom = 40  # barra de tareas/panel del escritorio
            wf_w = max(320, root.winfo_screenwidth())
            wf_h = max(180, screen_h - console_bottom - margin_bottom)
            return f"{wf_w}x{wf_h}+0+{console_bottom}"
        except tk.TclError:
            return ""

    def _toggle_waterfall(self) -> None:
        from poorsdr.viewers import launcher

        handle = getattr(self, "_wf_handle", None)
        if handle is not None and handle.running():
            handle.terminate()
            self._wf_handle = None
            self._unregister_viewer("waterfall")
            self._waterfall_open = False
            self.win.set_owrx_status(
                backend_ready=self._backend_ready, client_ready=self._client_ready, viewer_open=False
            )
            return
        self._wf_handle = launcher.open_waterfall(
            self.ctx.config, control_port=self._control_port(),
            default_geometry=self._waterfall_default_geometry(),
            display_scale=self.win._scale,
        )
        self._register_viewer("waterfall", self._wf_handle)
        self._waterfall_open = self._wf_handle is not None
        self.win.set_owrx_status(
            backend_ready=self._backend_ready,
            client_ready=self._client_ready,
            viewer_open=self._waterfall_open,
        )

    def _toggle_digi(self) -> None:
        from poorsdr.viewers import launcher

        handle = getattr(self, "_digi_handle", None)
        if handle is not None and handle.running():
            handle.terminate()
            self._digi_handle = None
            self._unregister_viewer("digi")
            self.win.set_digi_enabled(False)
            return
        self._digi_handle = launcher.open_digi(self.ctx.config, control_port=self._control_port())
        self._register_viewer("digi", self._digi_handle)
        self.win.set_digi_enabled(self._digi_handle is not None)

    def _register_viewer(self, kind: str, handle: Any) -> None:
        svc = self._svc("owrx-control")
        if handle is not None and svc is not None and handle.command_port:
            svc.set_viewer_port(kind, handle.command_port)

    def _unregister_viewer(self, kind: str) -> None:
        svc = self._svc("owrx-control")
        if svc is not None:
            svc.clear_viewer_port(kind)

    def _toggle_web(self) -> None:
        new_enabled = not self.ctx.config.web.enabled
        self._reconfigure(lambda cfg: replace(cfg, web=replace(cfg.web, enabled=new_enabled)))
        self.win.set_web_enabled(new_enabled)  # el estado real llega por web.status

    def _get_spots(self) -> dict:
        s = self.ctx.config.owrx.spots
        return {
            "enabled": s.enabled,
            "cw": s.filter_cw,
            "digi": s.filter_digi,
            "ssb": s.filter_ssb,
            "off": s.filter_off,
        }

    def _set_spots(self, values: dict) -> None:
        self._reconfigure(
            lambda cfg: replace(
                cfg,
                owrx=replace(
                    cfg.owrx,
                    spots=replace(
                        cfg.owrx.spots,
                        enabled=bool(values.get("enabled", True)),
                        filter_cw=bool(values.get("cw", True)),
                        filter_digi=bool(values.get("digi", True)),
                        filter_ssb=bool(values.get("ssb", True)),
                        filter_off=bool(values.get("off", False)),
                    ),
                ),
            )
        )
        self.win.set_spots_enabled(bool(values.get("enabled", True)))

    # ---- memorias (diálogo aparte) ----------------------------- #
    def _open_memories(self) -> None:
        if self._memory_window is not None and self._memory_window.winfo_exists():
            self._memory_window.lift()
            return
        lang = self.ctx.config.ui.language
        top = tk.Toplevel(self.root)
        top.title(t("memories_title", lang))
        top.configure(bg=THEME_COLORS["bg_main"])
        panel = MemoryPanel(
            top,
            on_recall=self._recall_memory,
            on_save=self._save_memory,
            on_delete=self._delete_memory,
            current_hz=lambda: self.view.frequency_hz,
            lang=lang,
        )
        panel.pack(fill="both", expand=True)
        svc = self._svc("memory")
        if svc is not None:
            panel.set_entries(svc.entries)
        self._memory_panel = panel
        self._memory_window = top
        top.protocol("WM_DELETE_WINDOW", top.destroy)

    def _recall_memory(self, entry: MemoryEntry) -> None:
        self._tune(entry.hz)
        if entry.mode:
            self._set_mode(entry.mode)

    def _save_memory(self, entry: MemoryEntry) -> None:
        svc = self._svc("memory")
        if svc is not None:
            svc.add(entry)

    def _delete_memory(self, index: int) -> None:
        svc = self._svc("memory")
        if svc is not None:
            svc.remove(index)

    # ---- eventos del bus (→ hilo Tk) --------------------------- #
    def _marshal(self, fn: Callable[[], None]) -> None:
        with contextlib.suppress(RuntimeError, tk.TclError):
            self.root.after(0, fn)

    def _on_radio_frequency(self, ev: Event) -> None:
        self._marshal(lambda: self._render(ui_state.with_frequency(self.view, int(ev["hz"]))))

    def _on_radio_mode(self, ev: Event) -> None:
        self._marshal(lambda: self._render(ui_state.with_mode(self.view, str(ev["mode"]))))

    def _on_radio_ptt(self, ev: Event) -> None:
        active = bool(ev["active"])
        self._marshal(lambda: self._render(ui_state.with_ptt(self.view, active)))

    def _on_radio_status(self, ev: Event) -> None:
        self._marshal(
            lambda: self._render(ui_state.with_connected(self.view, bool(ev.get("connected"))))
        )

    def _on_audio_volume(self, ev: Event) -> None:
        rx, tx = float(ev["rx"]), float(ev["tx"])
        self._marshal(lambda: self._apply_volume(rx, tx))

    def _apply_volume(self, rx: float, tx: float) -> None:
        self.win.set_rx_volume(rx)
        self.win.set_tx_volume(tx)

    def _on_memory_changed(self, _ev: Event) -> None:
        svc = self._svc("memory")
        panel = getattr(self, "_memory_panel", None)
        if svc is not None and panel is not None:
            entries = svc.entries
            self._marshal(lambda: panel.set_entries(entries))

    def _on_owrx_tune(self, ev: Event) -> None:
        # Sintonía inversa desde la cascada OWRX.
        hz = int(ev["hz"])
        mode = str(ev.get("mode") or "")
        self._marshal(lambda: self._apply_reverse_tune(hz, mode))

    def _apply_reverse_tune(self, hz: int, mode: str) -> None:
        r = self._svc("radio")
        if r is not None:
            r.set_frequency(hz, source="owrx")
            if mode:
                r.set_mode(mode, source="owrx")
        else:
            self._render(ui_state.with_frequency(self.view, hz))

    def _on_owrx_status(self, ev: Event) -> None:
        component = ev.get("component")
        if component == "backend":
            self._backend_ready = bool(ev.get("ready"))
        elif component == "client":
            self._client_ready = bool(ev.get("ready"))
        self._marshal(
            lambda: self.win.set_owrx_status(
                backend_ready=self._backend_ready,
                client_ready=self._client_ready,
                viewer_open=self._waterfall_open,
            )
        )

    # ---- cascada ------------------------------------------- #
    def _tick_waterfall(self) -> None:
        # Si el visor externo se cerró por su cuenta, apaga el indicador OWRX.
        handle = getattr(self, "_wf_handle", None)
        if self._waterfall_open and (handle is None or not handle.running()):
            self._waterfall_open = False
            self._wf_handle = None
            self._unregister_viewer("waterfall")
            self.win.set_owrx_status(viewer_open=False)
            # Sin OWRX activo no se sigue calculando FFT ni redibujando la
            # cascada embebida (ver más abajo); se limpia una vez para no
            # dejar el último fotograma congelado en pantalla.
            with contextlib.suppress(Exception):
                self.win.waterfall.clear()

        # Igual para Digi: si se cerró por su cuenta (la X de la ventana),
        # el botón debe reflejar OFF, no quedarse "encendido" a la fuerza.
        digi_handle = getattr(self, "_digi_handle", None)
        if digi_handle is not None and not digi_handle.running():
            self._digi_handle = None
            self._unregister_viewer("digi")
            self.win.set_digi_enabled(False)

        audio = self._svc("audio")
        tx = self.view.ptt or bool(audio is not None and getattr(audio.module, "tx_activo", False))
        self.win.show_tx_meter(tx)
        if tx:
            # En TX el panel central muestra el vúmetro, no la cascada.
            samples = audio.call("pop_tx_raw") if audio is not None else None
            if samples is not None and getattr(samples, "size", 0):
                with contextlib.suppress(Exception):
                    norm = samples.astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(norm * norm)))
                    self.win.set_tx_level(20.0 * float(np.log10(max(rms, 1e-6))))
        elif self._waterfall_open:
            # FFT (>=2048 puntos) + redibujado con matplotlib a ~30 Hz: solo
            # merece la pena mientras el visor de OWRX está realmente
            # abierto. Si no, es CPU gastada en algo que nadie está mirando.
            samples = audio.call("pop_rx_raw") if audio is not None else None
            if samples is not None:
                with contextlib.suppress(Exception):
                    row = self._wf.push_samples(samples, mode=self.view.mode)
                    self.win.waterfall.push_row(row)
        with contextlib.suppress(RuntimeError, tk.TclError):
            self._wf_after = self.root.after(33, self._tick_waterfall)

    # ---- render ---------------------------------------------- #
    def _render(self, view: RadioView) -> None:
        self.view = view
        self.win.apply_view(view)

    # ---- geometría de la ventana ---------------------------- #
    def _restore_geometry(self) -> None:
        """Coloca la ventana en la posición guardada compensando el offset del WM."""
        if self._target_xy is None:
            return
        target_x, target_y = self._target_xy
        self._restoring_geom = True
        try:
            req_x, req_y = target_x, target_y
            for _ in range(3):
                self.root.geometry(f"{self._win_size}+{req_x}+{req_y}")
                self.root.update_idletasks()
                dx = int(self.root.winfo_x()) - target_x
                dy = int(self.root.winfo_y()) - target_y
                if dx == 0 and dy == 0:
                    break
                req_x -= dx
                req_y -= dy
        except tk.TclError:
            pass
        finally:
            self._restoring_geom = False

    def _on_configure(self, event: Any = None) -> None:
        if self._restoring_geom:
            return
        if event is not None and getattr(event, "widget", None) is not self.root:
            return
        try:
            if self.root.state() != "normal":
                return
            geom = str(self.root.winfo_geometry() or "").strip()
        except tk.TclError:
            return
        if _GEOM_RE.match(geom) and geom != self._current_geom:
            self._current_geom = geom
            self._schedule_geometry_save()

    def _schedule_geometry_save(self) -> None:
        if self._geom_save_after is not None:
            with contextlib.suppress(Exception):
                self.root.after_cancel(self._geom_save_after)
        self._geom_save_after = self.root.after(500, self._save_geometry_now)

    def _save_geometry_now(self) -> None:
        self._geom_save_after = None
        if not _GEOM_RE.match(self._current_geom):
            return
        from poorsdr.config import loader

        self.ctx.config = replace(
            self.ctx.config, ui=replace(self.ctx.config.ui, window_geometry=self._current_geom)
        )
        with contextlib.suppress(Exception):
            loader.save(self.ctx.config)

    # ---- ciclo de vida ------------------------------------- #
    def _close_children(self) -> None:
        """Cierra los procesos externos abiertos desde la consola."""
        for attr in ("_wf_handle", "_digi_handle"):
            handle = getattr(self, attr, None)
            if handle is not None:
                with contextlib.suppress(Exception):
                    handle.terminate()
                setattr(self, attr, None)

    def _on_close(self) -> None:
        if self._wf_after is not None:
            with contextlib.suppress(Exception):
                self.root.after_cancel(self._wf_after)
            self._wf_after = None
        if self._geom_save_after is not None:
            with contextlib.suppress(Exception):
                self.root.after_cancel(self._geom_save_after)
            self._geom_save_after = None
        for cancel in self._unsubs:
            cancel()
        with contextlib.suppress(Exception):
            geom = self._current_geom if _GEOM_RE.match(self._current_geom) else ""
            if not geom:
                raw = str(self.root.winfo_geometry() or "").strip()
                geom = raw if _GEOM_RE.match(raw) else self._win_size
            self.ctx.config = replace(
                self.ctx.config, ui=replace(self.ctx.config.ui, window_geometry=geom)
            )
            from poorsdr.config import loader

            loader.save(self.ctx.config)
        # 1) cerrar visores / complementos externos (cascada, Digi, Libro de Guardia)
        self._close_children()
        # 2) parar los servicios — incluye OwrxBackendService → systemctl stop openwebrx
        with contextlib.suppress(Exception):
            self.ctx.stop()
        with contextlib.suppress(tk.TclError):
            self.root.destroy()

    def run(self) -> int:
        try:
            self.ctx.start()
        except Exception:  # noqa: BLE001
            _log.exception("no se pudieron arrancar los servicios")
            with contextlib.suppress(Exception):
                lang = self.ctx.config.ui.language
                messagebox.showerror("PoorSDR4All", t("services_start_failed", lang))
        # Los 4 círculos muestran la macro asignada (o "1..4" si no hay).
        self._refresh_autocall_buttons()
        # Aplica el volumen RX que muestra el dial (los servicios ya arrancaron).
        with contextlib.suppress(Exception):
            self._set_rx_volume(self.win.rx_volume())
        # Reaplica la posición cuando la UI ya está realizada (el WM la reubica tarde).
        if self._target_xy is not None:
            self.root.after(0, self._restore_geometry)
            self.root.after(140, self._restore_geometry)
        self._wf_after = self.root.after(300, self._tick_waterfall)
        self.root.mainloop()
        return 0


def main() -> int:
    from poorsdr import runtime

    plog.configure()
    paths.ensure_runtime_dirs()
    runtime.install_vendor_path()
    ctx = runtime.build_context()
    runtime.set_active(ctx)
    try:
        return PoorSDRApp(ctx).run()
    finally:
        runtime.set_active(None)


if __name__ == "__main__":
    raise SystemExit(main())
