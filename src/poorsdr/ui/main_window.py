"""Ventana principal de operación — reproducción fiel de ``RadioCBApp``.

Porta la construcción de widgets de ``configurar_ventana_principal`` /
``cargar_imagen_fondo`` / ``configurar_botones`` / ``crear_controles_cambio_canal``
/ ``crear_botones_autollamada`` / ``configurar_controles_volumen_ganancia`` con
las mismas posiciones (``poorsdr.ui.layout.LAYOUT_DEFAULTS``), fuentes y estilo.
Los ``command=`` van a un :class:`Callbacks`; ``PoorSDRApp`` los cablea a los
servicios y refresca la vista con los ``set_*`` de aquí.
"""

from __future__ import annotations

import contextlib
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

from poorsdr.core.bands import band_names
from poorsdr.core.smeter import (
    NoiseFloorTracker,
    SMeterAutoCalibration,
    SMeterBallistics,
    SMeterConfig,
)
from poorsdr.core.tuning import FrequencyParts
from poorsdr.i18n import t
from poorsdr.i18n.console_help import console_help
from poorsdr.infra.logging import get_logger
from poorsdr.ui import fonts as ui_fonts
from poorsdr.ui import layout as layout_mod
from poorsdr.ui.layout import DEV_LAYOUT_MODE, LAYOUT_DEFAULTS
from poorsdr.ui.settings.tooltip import Tooltip
from poorsdr.ui.theme import (
    CONTROL_DIAL_SIZE,
    CONTROL_FRAME_H,
    CONTROL_FRAME_W,
    THEME_COLORS,
)
from poorsdr.ui.widgets import DialControl

if TYPE_CHECKING:
    from PIL import ImageTk

_log = get_logger("ui.window")
_IMAGES = Path(__file__).resolve().parent / "assets" / "images"

_BG = THEME_COLORS["bg_main"]
_PANEL = THEME_COLORS["panel_bg"]
_FG = THEME_COLORS["text_primary"]
_MUTED = THEME_COLORS["text_muted"]
_ACCENT = THEME_COLORS["accent"]
_TX = THEME_COLORS["accent_tx"]
_BORDER = THEME_COLORS["border"]
_WARN = THEME_COLORS["warn"]
#: Excepción única del tema Classic: el frecuencímetro se ve en ocre, como un
#: LCD/LED antiguo, en vez de seguir el acento general (acero suave).
_CLASSIC_LED_COLOR = "#cc7722"
#: Excepción única del tema Classic: los indicadores de "activo" (Spots,
#: Digi, WEB, OWRX, fuente RX seleccionada) se ven en verde, no en el acero
#: suave del acento general — mismo verde que usa el S-metro.
_CLASSIC_ACTIVE_COLOR = "#33e26a"

MODES = ("AM", "FM", "USB", "LSB", "CW")
STEP_OPTIONS_KHZ = (0.01, 0.1, 0.5, 1, 5, 10, 100)

#: tamaño fijo de la consola (como el original)
WINDOW_W = 620
WINDOW_H = 760


def _noop(*_a: object, **_k: object) -> None:  # pragma: no cover
    return None


@dataclass
class Callbacks:
    tune: Callable[[int], None] = _noop            # freq_hz absoluta
    nudge: Callable[[int], None] = _noop           # +1 / -1 (paso)
    channel: Callable[[int], None] = _noop         # +1 / -1 (CH)
    set_step: Callable[[float], None] = _noop      # kHz
    set_mode: Callable[[str], None] = _noop
    set_band: Callable[[str], None] = _noop
    toggle_ptt: Callable[[], None] = _noop
    toggle_tune_tone: Callable[[bool], None] = _noop
    run_autocall: Callable[[int], None] = _noop
    # "Log" no tiene callback propio aquí: lo aporta el plugin del Libro de
    # Guardia como botón de consola (ver add_console_button).
    toggle_anr: Callable[[bool], None] = _noop
    set_anr_intensity: Callable[[int], None] = _noop
    set_rx_volume: Callable[[float], None] = _noop
    set_tx_volume: Callable[[float], None] = _noop
    set_rx_source: Callable[[str], None] = _noop
    open_settings: Callable[[], None] = _noop
    open_memories: Callable[[], None] = _noop
    open_owrx: Callable[[], None] = _noop
    toggle_digi: Callable[[], None] = _noop
    get_spots: Callable[[], dict] = dict
    set_spots: Callable[[dict], None] = _noop
    toggle_web: Callable[[], None] = _noop
    combine_frequency: Callable[[str, str, str], int | None] = field(
        default=lambda a, b, c: None
    )


class MainWindow:
    def __init__(
        self,
        root: tk.Tk,
        callbacks: Callbacks,
        *,
        accent: str = _ACCENT,
        background: str = "back.png",
        lang: str = "es",
        smeter_calibrated: bool = False,
        smeter_s9_dbfs: int = -30,
        smeter_noise_floor_s: int = 5,
    ) -> None:
        self.root = root
        # Tk detecta su propio factor de escala de DPI ("tk scaling") a
        # partir de lo que reporte el servidor gráfico — confirmado en
        # real: 1.335 en un portátil con la pantalla a 1366x768/escala 1 de
        # KDE, no 1.0. Ese factor solo afecta el tamaño en píxeles de las
        # fuentes (en puntos), nunca a las coordenadas de _place() (ya en
        # píxeles) — con el reescalado de más abajo, el texto quedaba
        # escalado dos veces (el factor propio y encima el de Tk) mientras
        # que los marcos y botones solo una, descuadrando todo. Fijarlo a
        # 1.0 hace que "1 punto = 1 píxel" siempre, en cualquier pantalla,
        # y deja el reescalado entero en manos del único factor de más
        # abajo.
        root.tk.call("tk", "scaling", 1.0)
        self.cb = callbacks
        self._lang = lang
        self._smeter_calibrated = smeter_calibrated
        self._smeter_s9_dbfs = smeter_s9_dbfs
        self._smeter_noise_floor_s = smeter_noise_floor_s
        self._editing = False
        self._ptt = False
        self._accent = accent
        self._background_name = background
        self._spots_on = False
        self._digi_on = False
        self._owrx_on = False

        # Widgets cuyo color sigue al acento del tema (se re-aplican en
        # set_theme_accent). Bordes: highlightbackground/highlightcolor.
        # Texto: fg (+ insertbackground en Entry). Dials y el marco de la
        # cascada tienen su propia vía.
        self._accent_borders: list[tk.Widget] = []
        self._accent_texts: list[tk.Widget] = []
        self._freq_digits: list[tk.Widget] = []
        self._accent_selects: list[tk.Widget] = []  # toggles: selectcolor cuando ON
        self._state_toggle_refreshers: list[Callable[[], None]] = []  # ANR: color de texto
        self._dials: list[DialControl] = []
        self._center_outer: tk.Frame | None = None

        # Modo EDIT: arrastrar los controles y guardar sus posiciones.
        self._placed: dict[str, tk.Widget] = {}
        self._layout_ov = layout_mod.load_overrides()
        self._drag_target: tk.Widget | None = None
        self._drag_off = (0, 0)
        self._drag_moved = False

        detected = ui_fonts.install_led_font()
        self.led_family = ui_fonts.led_font_family(root, detected)
        self.ui_family = ui_fonts.ui_font_family(root)

        # Reescalado: el diseño (LAYOUT_DEFAULTS, WINDOW_W/H, tamaños de
        # fuente) está pensado en píxeles para una pantalla de referencia.
        # En una pantalla más pequeña (portátiles de baja resolución,
        # p. ej. 1366x768) la consola sin más no cabía — se cortaba por
        # abajo, confirmado en real. Un único factor de escala, aplicado
        # en _place() y _font(), encoge todo por igual sin tocar el diseño
        # relativo; nunca escala hacia arriba (cap en 1.0) para no
        # cambiarle nada a quien ya tenía sitio de sobra.
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        usable_w = max(1, screen_w - 40)
        # OJO: tiene que ser un margen fijo en píxeles, NO un porcentaje de
        # la pantalla — un porcentaje encoge la consola en cualquier
        # pantalla, incluidas las grandes donde el tamaño de diseño (760px)
        # ya cabe de sobra sin tocar nada (confirmado en real: con un
        # porcentaje, una pantalla grande de desarrollo que antes se
        # quedaba en escala 1.0 sin cambios empezó a encogerse también,
        # cosa que nunca debe pasar). Con un margen fijo, min(1.0, ...) ya
        # se encarga solo de eso: en cualquier pantalla con
        # screen_h - 250 >= 760 (grosso modo, más de ~1000px de alto) la
        # escala sigue siendo 1.0 exacta, sin excepción.
        usable_h = max(1, screen_h - 250)
        self._scale = min(1.0, usable_w / WINDOW_W, usable_h / WINDOW_H)
        self._win_w = max(1, round(WINDOW_W * self._scale))
        self._win_h = max(1, round(WINDOW_H * self._scale))

        root.title("PoorSDR4All")
        root.geometry(f"{self._win_w}x{self._win_h}")
        root.resizable(False, False)
        root.configure(bg=_BG)

        self._vars()
        self._background()
        self._icon()
        self._action_buttons()
        self._mode_band()
        self._ptt_area()
        self._frequency_controls()
        self._channel_step()
        self._anr()
        self._volume_gain()
        self._smeter_widget()
        self._center_panel()
        self._autocall(profiles_count=4)
        self._apply_accent()  # tiñe todo con el acento real del tema

    # -- fuentes / helpers -------------------------------------------- #
    def _font(self, size: int, weight: str = "normal") -> tuple:
        scaled = max(6, round(size * self._scale))
        return (self.ui_family, scaled) if weight == "normal" else (self.ui_family, scaled, weight)

    def _help(self, key: str, **kwargs: object) -> str:
        return console_help(key, self._lang, **kwargs)

    def _place(self, name: str, widget: tk.Widget, x: int, y: int, **over: object) -> None:
        d = {**LAYOUT_DEFAULTS.get(name, {}), **self._layout_ov.get(name, {})}
        kw: dict[str, object] = {
            "x": round(int(d.get("x", x)) * self._scale),
            "y": round(int(d.get("y", y)) * self._scale),
        }
        anchor = d.get("anchor", over.get("anchor"))
        if anchor:
            kw["anchor"] = anchor
        width = over.get("width", d.get("width"))
        height = over.get("height", d.get("height"))
        if width not in (None, ""):
            kw["width"] = round(int(width) * self._scale)  # type: ignore[arg-type]
        if height not in (None, ""):
            kw["height"] = round(int(height) * self._scale)  # type: ignore[arg-type]
        widget.place(**kw)  # type: ignore[arg-type]
        self._placed[name] = widget

    # -- registro de widgets teñidos por el acento ------------------ #
    def _border(self, w: tk.Widget) -> tk.Widget:
        self._accent_borders.append(w)
        return w

    def _text(self, w: tk.Widget) -> tk.Widget:
        self._accent_texts.append(w)
        return w

    def _active_accent(self) -> str:
        """Color de "activo" para indicadores de botón (Spots/Digi/WEB/OWRX/
        fuente RX): el acento normal, salvo en Classic, que usa siempre verde.
        """
        return _CLASSIC_ACTIVE_COLOR if self._background_name == "back.png" else self._accent

    def _apply_accent(self) -> None:
        a = self._accent
        for w in self._accent_borders:
            with contextlib.suppress(tk.TclError):
                w.configure(highlightbackground=a, highlightcolor=a)
        for w in self._accent_texts:
            with contextlib.suppress(tk.TclError):
                w.configure(fg=a)
            with contextlib.suppress(tk.TclError):
                w.configure(insertbackground=a)  # solo Entry
        for w in self._accent_selects:
            with contextlib.suppress(tk.TclError):
                w.configure(selectcolor=a)  # fondo del toggle cuando está activado
        for refresh in self._state_toggle_refreshers:
            refresh()
        freq_color = _CLASSIC_LED_COLOR if self._background_name == "back.png" else a
        for w in self._freq_digits:
            with contextlib.suppress(tk.TclError):
                w.configure(fg=freq_color)
            with contextlib.suppress(tk.TclError):
                w.configure(insertbackground=freq_color)  # solo Entry
        for d in self._dials:
            d.set_accent(a)
        if self._center_outer is not None:
            with contextlib.suppress(tk.TclError):
                self._center_outer.configure(bg=a)
        with contextlib.suppress(Exception):
            self.waterfall.set_accent(a, background=self._background_name)
        for item in getattr(self, "_auto_items", []):
            with contextlib.suppress(tk.TclError):
                item["canvas"].itemconfigure(item["circle"], outline=a)

    def _style_action(self, b: tk.Widget, *, compact: bool = False) -> None:
        b.configure(
            bg=_PANEL, fg=_FG, activebackground=_PANEL, activeforeground=_FG,
            relief="flat", bd=1, highlightthickness=1, highlightbackground=_BORDER,
            highlightcolor=_ACCENT, padx=10, pady=3 if compact else 5,
            font=self._font(10 if compact else 11, "bold"), cursor="hand2",
        )
        self._border(b)

    def _style_toggle(self, b: tk.Widget, *, compact: bool = True) -> None:
        b.configure(
            indicatoron=False, relief="flat", bd=1, highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT, selectcolor=self._accent,
            activebackground=_PANEL, activeforeground=_FG,
            font=self._font(9 if compact else 10, "bold"), padx=8, pady=2, cursor="hand2",
        )
        self._border(b)
        self._accent_selects.append(b)

    def _style_state_toggle(self, b: tk.Widget, var: tk.BooleanVar) -> None:
        """Como ``_style_toggle``, pero indica el estado con el color del
        texto (como OWRX/Spots/Digi/WEB) en vez de rellenar el fondo.
        """
        b.configure(
            indicatoron=False, relief="flat", bd=1, highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT, selectcolor=_PANEL,
            activebackground=_PANEL, activeforeground=_FG,
            font=self._font(9, "bold"), padx=8, pady=2, cursor="hand2",
        )
        self._border(b)

        def _refresh(*_args: object) -> None:
            with contextlib.suppress(tk.TclError):
                b.configure(fg=self._active_accent() if var.get() else _FG)

        var.trace_add("write", _refresh)
        self._state_toggle_refreshers.append(_refresh)
        _refresh()

    # -- modo EDIT: recolocar controles --------------------------- #
    # El arrastre es con el BOTÓN DERECHO: así el clic izquierdo sigue
    # operando los controles (y activando/desactivando el propio EDIT) sin
    # ambigüedad. El cursor "fleur" indica que el modo está activo.
    def _toggle_edit(self) -> None:
        on = bool(self.edit_var.get())
        for widget in list(self._placed.values()):
            self._prepare_drag(widget)
            self._set_cursor(widget, "fleur" if on else "")
        if not on:
            self._save_layout()

    def _prepare_drag(self, widget: tk.Widget) -> None:
        """Enlaza los manejadores de arrastre (botón derecho) una sola vez."""
        stack = [widget]
        while stack:
            w = stack.pop()
            with contextlib.suppress(tk.TclError):
                stack.extend(w.winfo_children())
            if getattr(w, "_psdr_drag_ready", False):
                continue
            w.bind("<ButtonPress-3>", self._drag_start, add="+")
            w.bind("<B3-Motion>", self._drag_motion, add="+")
            w.bind("<ButtonRelease-3>", self._drag_end, add="+")
            w._psdr_drag_ready = True  # type: ignore[attr-defined]

    def _set_cursor(self, widget: tk.Widget, cursor: str) -> None:
        stack = [widget]
        while stack:
            w = stack.pop()
            with contextlib.suppress(tk.TclError):
                stack.extend(w.winfo_children())
            with contextlib.suppress(tk.TclError):
                w.configure(cursor=cursor)

    def _resolve_drag_target(self, widget: tk.Misc | None) -> tk.Widget | None:
        placed = set(self._placed.values())
        w: tk.Misc | None = widget
        while w is not None and w is not self.root:
            if w in placed:
                return w  # type: ignore[return-value]
            w = getattr(w, "master", None)
        return None

    def _drag_start(self, event: tk.Event) -> None:
        if not self.edit_var.get():
            return
        target = self._resolve_drag_target(event.widget)
        if target is None:
            return
        self._drag_target = target
        self._drag_moved = False
        with contextlib.suppress(tk.TclError):
            target.place_configure(anchor="nw", x=target.winfo_x(), y=target.winfo_y())
        self._drag_off = (
            event.x_root - self.root.winfo_rootx() - target.winfo_x(),
            event.y_root - self.root.winfo_rooty() - target.winfo_y(),
        )

    def _drag_motion(self, event: tk.Event) -> None:
        target = self._drag_target
        if not self.edit_var.get() or target is None:
            return
        self._drag_moved = True
        nx = event.x_root - self.root.winfo_rootx() - self._drag_off[0]
        ny = event.y_root - self.root.winfo_rooty() - self._drag_off[1]
        with contextlib.suppress(tk.TclError):
            target.place_configure(x=max(0, nx), y=max(0, ny))

    def _drag_end(self, _event: tk.Event) -> None:
        if self._drag_target is None:
            return
        moved = self._drag_moved
        self._drag_target = None
        self._drag_moved = False
        if moved:
            self._save_layout()

    def _save_layout(self) -> None:
        positions: dict[str, dict[str, object]] = {}
        for name, widget in self._placed.items():
            try:
                info = widget.place_info()
                entry: dict[str, object] = {
                    "x": int(float(info.get("x", 0) or 0)),
                    "y": int(float(info.get("y", 0) or 0)),
                    "anchor": info.get("anchor") or "nw",
                }
                for key in ("width", "height"):
                    raw = info.get(key)
                    if raw not in (None, "", "0"):
                        entry[key] = int(float(raw))
                positions[name] = entry
            except (tk.TclError, TypeError, ValueError):
                continue
        layout_mod.save_overrides(positions)
        self._layout_ov = positions

    # -- variables Tk --------------------------------------------- #
    def _vars(self) -> None:
        self.mhz = tk.StringVar()
        self.khz = tk.StringVar()
        self.chz = tk.StringVar()
        self.mode_var = tk.StringVar(value="USB")
        self.band_var = tk.StringVar()
        self.step_var = tk.StringVar(value="1")
        self.anr_var = tk.BooleanVar(value=False)
        self.anr_intensity_var = tk.IntVar(value=1)
        self.tone_var = tk.BooleanVar(value=False)
        self.rx_source_var = tk.StringVar(value="sdr")
        self.edit_var = tk.BooleanVar(value=False)

    # -- fondo / icono ------------------------------------------ #
    def _background(self) -> None:
        name = self._background_name or "back.png"
        candidates = [name, "back.png", "back.jpg"]
        for cand in candidates:
            path = _IMAGES / cand
            if not path.exists():
                continue
            try:
                from PIL import Image, ImageTk

                img = Image.open(path).convert("RGB")
                if img.size != (self._win_w, self._win_h):
                    img = img.resize((self._win_w, self._win_h), Image.LANCZOS)
                self._bg_photo: ImageTk.PhotoImage = ImageTk.PhotoImage(img)
                self._bg_label = tk.Label(self.root, image=self._bg_photo, bg=_BG, bd=0)
                self._bg_label.place(x=0, y=0, width=self._win_w, height=self._win_h)
                self._bg_label.lower()  # detrás de todos los controles
                return
            except Exception:  # noqa: BLE001
                _log.debug("no se pudo cargar el fondo %s", path, exc_info=True)

    def set_background(self, name: str) -> None:
        """Cambia la imagen de fondo (al elegir otro tema en Ajustes)."""
        if name == self._background_name:
            return
        self._background_name = name or "back.png"
        old = getattr(self, "_bg_label", None)
        if old is not None:
            with contextlib.suppress(tk.TclError):
                old.destroy()
        self._background()

    def _icon(self) -> None:
        path = _IMAGES / "image.ico"
        if not path.exists():
            return
        try:
            from PIL import Image, ImageTk

            self._icon_photo = ImageTk.PhotoImage(Image.open(path))
            self.root.iconphoto(True, self._icon_photo)
        except Exception:  # noqa: BLE001
            pass

    # -- botones de acción ---------------------------------- #
    def _action_buttons(self) -> None:
        self.settings_button = tk.Button(
            self.root, text="Ajustes", width=8, font=self._font(12, "bold"),
            command=self.cb.open_settings,
        )
        self._style_action(self.settings_button)
        self._place("settings_button", self.settings_button, 556, 0)
        Tooltip(self.settings_button, self._help("help_settings_button"))

        self.web_button = tk.Button(self.root, text="WEB OFF", width=8, command=self.cb.toggle_web)
        self._style_action(self.web_button, compact=True)
        self._place("web_server_button", self.web_button, 470, 0)
        Tooltip(self.web_button, self._help("help_web_button"))

        self.mem_button = tk.Button(
            self.root, text="Mem", width=6, font=self._font(12, "bold"), command=self.cb.open_memories
        )
        self._style_action(self.mem_button)
        self._place("mem_button", self.mem_button, 505, 679)
        Tooltip(self.mem_button, self._help("help_mem_button"))

        # Botones que aporten los plugins (p. ej. "Log" del Libro de Guardia).
        # El primero ocupa la ranura "log_button" del layout original; los
        # siguientes se apilan a su izquierda. Sin plugins, no aparece nada.
        self._plugin_buttons: dict[str, tk.Button] = {}

        self.owrx_button = tk.Button(self.root, text="OWRX", width=8, command=self.cb.open_owrx)
        self._style_action(self.owrx_button, compact=True)
        self._place("owrx_button", self.owrx_button, 192, 363)
        Tooltip(self.owrx_button, self._help("help_owrx_button"))

        self.digi_button = tk.Button(self.root, text="Digi OFF", width=8, command=self.cb.toggle_digi)
        self._style_action(self.digi_button, compact=True)
        self._place("digi_button", self.digi_button, 184, 457)
        Tooltip(self.digi_button, self._help("help_digi_button"))

        self.spots_button = tk.Button(self.root, text="Spots", width=8, command=self._open_spots_menu)
        self._style_action(self.spots_button, compact=True)
        self._place("owrx_spots_button", self.spots_button, 184, 410)
        Tooltip(self.spots_button, self._help("help_spots_button"))
        self._spots_menu: tk.Toplevel | None = None

        if DEV_LAYOUT_MODE:
            self.edit_check = tk.Checkbutton(
                self.root, text="EDIT", variable=self.edit_var, bg=_PANEL, fg=_FG,
                selectcolor=_BG, font=self._font(10, "bold"), highlightthickness=0,
                command=self._toggle_edit,
            )
            self._style_toggle(self.edit_check)
            self._place("edit_check", self.edit_check, 110, 4)
            Tooltip(self.edit_check, self._help("help_edit_check"))

    # -- modo / banda ------------------------------------ #
    def _mode_band(self) -> None:
        self.mode_frame = tk.Frame(
            self.root, bg=_PANEL, bd=1, relief="flat", highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        tk.Label(self.mode_frame, text="MODE", bg=_PANEL, fg=_MUTED,
                 font=self._font(8, "bold")).pack(side="left", padx=(0, 4))
        combo = ttk.Combobox(self.mode_frame, values=list(MODES), textvariable=self.mode_var,
                             state="readonly", width=6, takefocus=False)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._combo_done(
            combo, lambda: self.cb.set_mode(self.mode_var.get())))
        combo.pack(side="left")
        self._border(self.mode_frame)
        self._place("mode_selector", self.mode_frame, 463, 596)
        Tooltip(combo, self._help("help_mode_selector"))

        self.band_frame = tk.Frame(
            self.root, bg=_PANEL, bd=1, relief="flat", highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        tk.Label(self.band_frame, text="BAND", bg=_PANEL, fg=_MUTED,
                 font=self._font(8, "bold")).pack(side="left", padx=(0, 4))
        bcombo = ttk.Combobox(self.band_frame, values=band_names(), textvariable=self.band_var,
                              state="readonly", width=6, takefocus=False)
        bcombo.bind("<<ComboboxSelected>>", lambda _e: self._combo_done(
            bcombo, lambda: self.cb.set_band(self.band_var.get())))
        bcombo.pack(side="left")
        self._border(self.band_frame)
        self._place("band_selector", self.band_frame, 100, 596, anchor="n")
        Tooltip(bcombo, self._help("help_band_selector"))

    # -- PTT / Tune ------------------------------------ #
    def _ptt_area(self) -> None:
        self.ptt_button = tk.Button(
            self.root, text="PTT", bg=_PANEL, fg=_FG, activebackground=_PANEL,
            activeforeground=_FG, disabledforeground=_FG, relief="flat", overrelief="flat", bd=1,
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_ACCENT,
            font=self._font(19, "bold"), command=self.cb.toggle_ptt,
        )
        self._border(self.ptt_button)
        self._place("ptt_button", self.ptt_button, 188, 565, width=240, height=80)
        Tooltip(self.ptt_button, self._help("help_ptt_button"))

        self.tone_button = tk.Checkbutton(
            self.root, text="Tune", variable=self.tone_var, bg=_PANEL, fg=_FG,
            selectcolor=_BG, highlightthickness=0, font=self._font(10, "bold"),
            command=lambda: self.cb.toggle_tune_tone(self.tone_var.get()),
        )
        self._style_toggle(self.tone_button)
        self._place("tone_ptt_button", self.tone_button, 145, 158)
        Tooltip(self.tone_button, self._help("help_tune_button"))

    # -- controles de frecuencia --------------------- #
    def _frequency_controls(self) -> None:
        frame = tk.Frame(
            self.root, bg=_BG, bd=1, relief="flat", highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        self._border(frame)
        self._place("frequency_controls", frame, 193, 282)
        style = {
            "bg": _BG, "fg": _ACCENT, "insertbackground": _ACCENT,
            "font": (self.led_family, max(6, round(34 * self._scale))),
            "justify": "center", "bd": 0,
            "highlightthickness": 1, "highlightbackground": _BG,
            "highlightcolor": _ACCENT, "relief": "flat", "width": 3,
        }
        self.e_mhz = tk.Entry(frame, textvariable=self.mhz, **style)
        self.e_mhz.pack(side="left", padx=(2, 0), pady=6)
        dot = tk.Label(frame, text=".", bg=_BG, fg=_ACCENT, font=self._font(32, "bold"))
        dot.pack(side="left", pady=6)
        self.e_khz = tk.Entry(frame, textvariable=self.khz, **style)
        self.e_khz.pack(side="left", pady=6)
        comma = tk.Label(frame, text=",", bg=_BG, fg=_ACCENT, font=self._font(32, "bold"))
        comma.pack(side="left", pady=6)
        self.e_chz = tk.Entry(frame, textvariable=self.chz, **style)
        self.e_chz.pack(side="left", pady=6)
        for w in (self.e_mhz, self.e_khz, self.e_chz, dot, comma):
            self._freq_digits.append(w)
        for e in (self.e_mhz, self.e_khz, self.e_chz):
            e.bind("<FocusIn>", self._on_focus_in)
            e.bind("<FocusOut>", self._on_focus_out)
            e.bind("<Return>", self._apply_entries)
            e.bind("<MouseWheel>", self._on_wheel)
            e.bind("<Button-4>", lambda _e: self.cb.nudge(+1))
            e.bind("<Button-5>", lambda _e: self.cb.nudge(-1))
        mhz_label = tk.Label(frame, text="MHz", bg=_BG, fg=_FG, font=self._font(17, "bold"))
        mhz_label.pack(side="left", padx=(8, 10), pady=6)
        freq_help = self._help("help_frequency_entry")
        for w in (self.e_mhz, dot, self.e_khz, comma, self.e_chz, mhz_label):
            Tooltip(w, freq_help)

    def _channel_step(self) -> None:
        bstyle = {
            "bg": _PANEL, "fg": _FG, "activebackground": _PANEL, "font": self._font(12, "bold"),
            "width": 5, "height": 1, "relief": "flat", "bd": 1, "highlightthickness": 1,
            "highlightbackground": _BORDER, "highlightcolor": _ACCENT, "cursor": "hand2",
        }
        ch = tk.Frame(self.root, bg=_PANEL, width=240)
        self._place("ch_controls", ch, 180, 465, width=240)
        # ch tiene ancho fijado (arriba) y escalado por _place(); el padx
        # entre botones también tiene que escalar, si no, a escalas
        # pequeñas los botones piden más ancho del que el marco ya
        # encogido tiene — y el segundo (CH +) se sale por el borde,
        # solapándose con el panel vecino (confirmado en real).
        gap_out = max(1, round(6 * self._scale))
        gap_in = max(1, round(34 * self._scale))
        ch_minus = tk.Button(ch, text="CH -", command=lambda: self.cb.channel(-1), **bstyle)
        ch_minus.pack(side="left", padx=(gap_out, gap_in), pady=3)
        ch_plus = tk.Button(ch, text="CH +", command=lambda: self.cb.channel(+1), **bstyle)
        ch_plus.pack(side="left", padx=(gap_in, gap_out), pady=3)
        self._border(ch_minus)
        self._border(ch_plus)
        ch_help = self._help("help_channel_buttons")
        Tooltip(ch_minus, ch_help)
        Tooltip(ch_plus, ch_help)

        step = tk.Frame(
            self.root, bg=_PANEL, bd=1, relief="flat", highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        self._border(step)
        self._place("step_controls", step, 270, 490)
        step_label = tk.Label(step, text="kHz", bg=_PANEL, fg=_MUTED, font=self._font(8, "bold"))
        step_label.pack(side="left")
        scombo = ttk.Combobox(
            step, values=[str(v) for v in STEP_OPTIONS_KHZ], textvariable=self.step_var,
            state="readonly", width=4, takefocus=False,
        )
        scombo.bind("<<ComboboxSelected>>", lambda _e: self._combo_done(
            scombo, lambda: self.cb.set_step(float(self.step_var.get()))))
        scombo.pack(side="left", padx=(4, 0), pady=2)
        step_help = self._help("help_step_selector")
        Tooltip(step_label, step_help)
        Tooltip(scombo, step_help)

    def _anr(self) -> None:
        frame = tk.Frame(self.root, bg=_PANEL)
        self._place("anr_frame", frame, 17, 156)
        anr = tk.Checkbutton(
            frame, text="ANR", variable=self.anr_var,
            command=lambda: self.cb.toggle_anr(self.anr_var.get()),
            bg=_PANEL, fg=_FG, selectcolor=_BG, font=self._font(10, "bold"), highlightthickness=0,
        )
        self._style_state_toggle(anr, self.anr_var)
        self._anr_check = anr
        anr.pack(side="left", padx=(0, 4))
        Tooltip(anr, self._help("help_anr_check"))
        spin = tk.Spinbox(
            frame, from_=1, to=10, width=3, textvariable=self.anr_intensity_var,
            command=lambda: self.cb.set_anr_intensity(int(self.anr_intensity_var.get())),
            font=self._font(10, "bold"), bg=_BG, fg=_FG, readonlybackground=_BG,
            buttonbackground=_PANEL, insertbackground=_FG, relief="flat", bd=1,
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_ACCENT,
            state="readonly",
        )
        self._border(spin)
        spin.pack(side="left", padx=(2, 0), pady=2)
        Tooltip(spin, self._help("help_anr_intensity"))

    # -- volumen / ganancia / audio RX ----------------- #
    def _control_frame(self, title: str, subtitle: str, help_text: str = "") -> tk.Frame:
        # pack_propagate(False) fija el marco a un tamaño exacto (para que
        # el título/subtítulo no lo empujen) — hay que escalar ese tamaño a
        # mano, si no, el marco se queda a tamaño de diseño completo aunque
        # todo lo de dentro (el dial, la letra) sí encoja: cuanto mayor la
        # reducción general, más se nota el hueco de más alrededor del dial.
        f = tk.Frame(
            self.root, bg=_PANEL, bd=1, relief="flat",
            width=max(1, round(CONTROL_FRAME_W * self._scale)),
            height=max(1, round(CONTROL_FRAME_H * self._scale)),
            highlightthickness=1, highlightbackground=_BORDER,
            highlightcolor=_ACCENT,
        )
        self._border(f)
        f.pack_propagate(False)
        # El marco tiene alto fijo (arriba); el pady de las etiquetas
        # también tiene que escalar — si no, a escalas pequeñas ese hueco
        # fijo deja de caber junto al dial dentro del alto ya encogido.
        label_pad = max(1, round(10 * self._scale))
        top = tk.Label(f, text=title, fg=_FG, bg=_PANEL, font=self._font(13, "bold"))
        top.pack(side="top", pady=(label_pad, 0))
        bottom = tk.Label(f, text=subtitle, fg=_FG, bg=_PANEL, font=self._font(13, "bold"))
        bottom.pack(side="bottom", pady=(0, label_pad))
        if help_text:
            Tooltip(top, help_text)
            Tooltip(bottom, help_text)
        return f

    def _volume_gain(self) -> None:
        vf = self._control_frame("Volumen", "Altavoz", self._help("help_volume_dial"))
        self._place("volumen", vf, 448, 360)
        dial_size = max(1, round(CONTROL_DIAL_SIZE * self._scale))
        dial_pad = max(1, round(10 * self._scale))
        rx_dial = DialControl(vf, from_=0, to_=100, command=self.cb.set_rx_volume, initial=25,
                              size=dial_size, step=2)
        rx_dial.pack(side="bottom", pady=(0, dial_pad))
        self._rx_dial = rx_dial

        gf = self._control_frame("Ganancia", "Micrófono", self._help("help_gain_dial"))
        self._place("ganancia", gf, 31, 361)
        tx_dial = DialControl(gf, from_=0, to_=100, command=self.cb.set_tx_volume, initial=100,
                              size=dial_size, step=2)
        tx_dial.pack(side="bottom", pady=(0, dial_pad))
        self._tx_dial = tx_dial
        self._dials.extend((rx_dial, tx_dial))

        rx = tk.Frame(
            self.root, bg=_PANEL, bd=1, relief="flat", highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        self._border(rx)
        rx_source_help = self._help("help_rx_source")
        rx_title = tk.Label(rx, text="Audio RX", fg=_FG, bg=_PANEL, font=self._font(10, "bold"))
        rx_title.pack(side="top", pady=(8, 2))
        Tooltip(rx_title, rx_source_help)
        sel = tk.Frame(rx, bg=_PANEL)
        sel.pack(side="top", pady=(0, 8))
        def _on_rx() -> None:
            self._refresh_rx_indicator()
            self.cb.set_rx_source(self.rx_source_var.get())

        common = {
            "variable": self.rx_source_var, "bg": _PANEL, "fg": _FG, "activebackground": _PANEL,
            "font": self._font(10, "bold"), "indicatoron": False, "bd": 0,
            "highlightthickness": 0, "relief": "flat", "selectcolor": _PANEL, "padx": 6,
            "command": _on_rx,
        }
        self._rx_buttons = {
            "radio": tk.Radiobutton(sel, text="Radio", value="radio", **common),
            "sdr": tk.Radiobutton(sel, text="SDR", value="sdr", **common),
        }
        self._rx_buttons["radio"].pack(side="left", padx=(0, 6))
        self._rx_buttons["sdr"].pack(side="left")
        Tooltip(self._rx_buttons["radio"], rx_source_help)
        Tooltip(self._rx_buttons["sdr"], rx_source_help)
        self._refresh_rx_indicator()
        self._place("rx_audio", rx, 313, 362)

    # -- S-metro de LEDs (estilo Superstar 3900) --------------------- #
    # El µSDX no informa el S-metro por CAT, pero OWRX sí calcula un nivel
    # de señal (lo mismo que dibuja el espectro): el visor lo manda por el
    # socket de control como {"type": "smeter", "dbfs": ...}. Por defecto no
    # hay forma de calibrar S9 a un dBFS absoluto (cada SDR/ganancia mide
    # distinto), así que la aguja se autocalibra: NoiseFloorTracker sigue el
    # "suelo" real de la banda (ruido + QRM ambiente) y la escala se
    # recalcula para que ese suelo caiga en S3-S5, como en una radio real —
    # no en S0. Con `smeter_calibrated` (Ajustes → OWRX, tras medir una
    # referencia real con ganancia de SDR fija) se usa en cambio una escala
    # FIJA con S9 en `smeter_s9_dbfs` y 6 dB/unidad (convención de
    # radioafición) hasta S9, para dar una lectura absoluta de verdad. Aquí
    # solo se dibuja: la conversión a unidades/etiqueta es lógica pura y está
    # testeada aparte (poorsdr.core.smeter).
    # Réplica de la barra de LEDs de la Superstar: pantalla negra, segmentos
    # verdes S1-S9 y rojos hasta +30 por encima (tope físico: 0 dBFS).
    _SMETER_W = 176
    _SMETER_H = 56
    _SMETER_SEGMENTS = 22
    _SMETER_TICKS: tuple[tuple[float, str], ...] = (
        (1.0, "1"), (3.0, "3"), (5.0, "5"), (7.0, "7"), (9.0, "9"), (12.0, "+30"),
    )

    #: dB por unidad S por debajo de S9 en la convención de radioafición
    #: (S9 a S1 son 6 dB/unidad; por encima de S9, 10 dB/unidad como ya usa
    #: SMeterConfig por defecto).
    _SMETER_CAL_DB_PER_UNIT = 6.0

    def _fixed_smeter_config(self) -> SMeterConfig:
        s9 = float(self._smeter_s9_dbfs)
        return SMeterConfig(
            noise_floor_dbfs=s9 - 9 * self._SMETER_CAL_DB_PER_UNIT,
            s9_dbfs=s9,
            db_per_s_unit=self._SMETER_CAL_DB_PER_UNIT,
        )

    def _smeter_auto_calibration(self) -> SMeterAutoCalibration:
        # El suelo de ruido/QRM ambiente no es el mismo en todas las
        # estaciones (antena, ubicación, banda...), así que la unidad S en
        # la que se calibra es ajustable en Ajustes → OWRX; se recorta a la
        # propia escala S0-S9 por si llega un valor fuera de rango desde
        # config.json.
        ambient = max(0.0, min(9.0, float(self._smeter_noise_floor_s)))
        return SMeterAutoCalibration(ambient_units=ambient)

    def _smeter_widget(self) -> None:
        self._smeter_floor = NoiseFloorTracker(self._smeter_auto_calibration())
        cfg = self._fixed_smeter_config() if self._smeter_calibrated else self._smeter_floor.meter_config
        self._smeter_ball = SMeterBallistics(cfg)
        self._smeter_last_ts: float | None = None
        boundary = 9.0  # a partir de S9 la barra pasa a rojo

        bezel = tk.Frame(
            self.root, bg=_PANEL, bd=1, relief="flat", highlightthickness=1,
            highlightbackground=_BORDER, highlightcolor=_ACCENT,
        )
        self._border(bezel)
        # El canvas dibuja todo a mano (segmentos, marcas, texto) a partir de
        # w/h — escalarlos aquí basta para que el resto de coordenadas
        # internas (derivadas de left/right/seg_w más abajo) salgan ya a
        # escala, sin tocar el resto del método.
        w, h = round(self._SMETER_W * self._scale), round(self._SMETER_H * self._scale)
        canvas = tk.Canvas(bezel, width=w, height=h, bg="#0a0a0a", highlightthickness=0, bd=0)
        canvas.pack(padx=2, pady=2)
        self._smeter_canvas = canvas

        # Margen derecho generoso: dentro de él debe caber entera la etiqueta
        # "+30" del último tramo, si no queda cortada por el borde del marco.
        left, right = round(24 * self._scale), w - round(22 * self._scale)
        top, bar_h = round(5 * self._scale), round(18 * self._scale)
        n = self._SMETER_SEGMENTS
        gap = 2.0 * self._scale
        seg_w = (right - left - (n - 1) * gap) / n

        def x_for_units(units: float) -> float:
            return left + (units / cfg.span_units) * (right - left)

        canvas.create_text(
            round(11 * self._scale), top + bar_h / 2,
            text="S", fill="#c9cdd3", font=self._font(10, "bold"),
        )

        segs: list[int] = []
        lit_colors: list[str] = []
        dim_colors: list[str] = []
        for i in range(n):
            x0 = left + i * (seg_w + gap)
            mid_units = ((i + 0.5) / n) * cfg.span_units
            over = mid_units > boundary
            dim = "#3a1414" if over else "#123018"
            segs.append(canvas.create_rectangle(x0, top, x0 + seg_w, top + bar_h, outline="", fill=dim))
            lit_colors.append("#ff4136" if over else "#33e26a")
            dim_colors.append(dim)
        self._smeter_segments = segs
        self._smeter_seg_lit = lit_colors
        self._smeter_seg_dim = dim_colors

        label_y = top + bar_h + round(11 * self._scale)
        tick_len = round(3 * self._scale)
        for units, label in self._SMETER_TICKS:
            color = "#ff8a80" if units > boundary else "#9aa0a6"
            x = x_for_units(units)
            canvas.create_line(x, top + bar_h, x, top + bar_h + tick_len, fill=color)
            canvas.create_text(x, label_y, text=label, fill=color, font=self._font(8, "bold"))

        self._smeter_readout = canvas.create_text(
            w / 2, label_y + round(11 * self._scale),
            text="S0", fill="#33e26a", font=self._font(11, "bold"),
        )
        self._place("smeter", bezel, 16, 86)
        Tooltip(canvas, self._help("help_smeter"))

    def set_smeter_calibration(self, calibrated: bool, s9_dbfs: int) -> None:
        """Aplica en caliente el cambio de calibración hecho en Ajustes."""
        self._smeter_calibrated = bool(calibrated)
        self._smeter_s9_dbfs = int(s9_dbfs)
        if self._smeter_calibrated:
            self._smeter_ball.cfg = self._fixed_smeter_config()
        else:
            # Vuelve a la autocalibración desde cero: un "suelo" heredado de
            # la escala fija no significa nada en la escala relativa.
            self._smeter_floor.reset()
            self._smeter_ball.cfg = self._smeter_floor.meter_config
        self._smeter_ball.reset()

    def set_smeter_noise_floor(self, noise_floor_s: int) -> None:
        """Aplica en caliente la unidad S del suelo de ruido (Ajustes → OWRX).

        Solo importa en modo autocalibrado — con la escala fija
        (``smeter_calibrated``) no hay "suelo detectado" que recolocar.
        """
        self._smeter_noise_floor_s = int(noise_floor_s)
        if not self._smeter_calibrated:
            self._smeter_floor = NoiseFloorTracker(self._smeter_auto_calibration())
            self._smeter_ball.cfg = self._smeter_floor.meter_config
            self._smeter_ball.reset()

    def set_smeter_dbfs(self, dbfs: float) -> None:
        """Enciende los segmentos del S-metro con una lectura de OWRX (dBFS).

        Sin calibrar (por defecto): la escala se autocalibra —
        :class:`NoiseFloorTracker` sigue el "suelo" real de la banda y
        recoloca S0/S9 para que ese suelo caiga en S3-S5 (ruido + QRM
        ambiente, como en una radio real) en vez de en S0. Calibrado
        (``smeter_calibrated``): se usa la escala fija medida por el usuario,
        sin reajustarla con cada lectura.
        """
        now = time.monotonic()
        dt = 0.0 if self._smeter_last_ts is None else max(0.0, now - self._smeter_last_ts)
        self._smeter_last_ts = now
        if not self._smeter_calibrated:
            self._smeter_floor.push(dbfs, dt)
            self._smeter_ball.cfg = self._smeter_floor.meter_config
        self._smeter_ball.push_dbfs(dbfs, dt)
        value = self._smeter_ball.value
        n = len(self._smeter_segments)
        lit = int(round((value / self._smeter_ball.cfg.span_units) * n))
        with contextlib.suppress(tk.TclError):
            for i, seg in enumerate(self._smeter_segments):
                on = i < lit
                self._smeter_canvas.itemconfigure(
                    seg, fill=self._smeter_seg_lit[i] if on else self._smeter_seg_dim[i]
                )
            self._smeter_canvas.itemconfigure(
                self._smeter_readout,
                text=self._smeter_ball.label,
                fill="#ff4136" if value > 9.0 else "#33e26a",
            )

    def _center_panel(self) -> None:
        from poorsdr.core.waterfall import WaterfallConfig
        from poorsdr.ui.panels.waterfall_view import WaterfallView

        outer = tk.Frame(self.root, bg=_ACCENT, width=190, height=260)
        self._center_outer = outer
        self._place("center_panel", outer, 211, 8, width=190, height=260)
        # host va a tamaño explícito en píxeles (no relwidth/relheight), así
        # que también hay que escalarlo a mano — si no, se queda al tamaño
        # de diseño completo aunque "outer" ya haya encogido.
        inset = max(1, round(2 * self._scale))
        host_w = round(190 * self._scale) - 2 * inset
        host_h = round(260 * self._scale) - 2 * inset
        host = tk.Frame(outer, bg=_PANEL)
        host.place(x=inset, y=inset, width=host_w, height=host_h)
        self._center_host = host
        self.waterfall = WaterfallView(
            host, WaterfallConfig(), accent=self._accent, background=self._background_name,
            lang=self._lang,
        )
        self.waterfall.place(x=0, y=0, relwidth=1, relheight=1)

        # Vúmetro de TX: 20 segmentos verticales, oculto salvo en transmisión.
        # Ocupa "host" entero vía relwidth/relheight (ver show_tx_meter), así
        # que su dibujo interno debe partir del tamaño real de host, no del
        # de diseño sin escalar.
        self._tx_meter = tk.Canvas(host, bg=_BG, highlightthickness=0, bd=0)
        self._tx_meter_dbfs = -60.0
        self._tx_segments: list[int] = []
        w, h = host_w, host_h
        n = 20
        gap, margin = 3 * self._scale, round(14 * self._scale)
        seg_h = (h - 2 * margin - (n - 1) * gap) / n
        for i in range(n):
            y1 = h - margin - i * (seg_h + gap)
            self._tx_segments.append(
                self._tx_meter.create_rectangle(
                    margin, y1 - seg_h, w - margin, y1, outline="", fill=_PANEL
                )
            )
        self._tx_meter_shown = False

    # -- autollamada ----------------------------------- #
    def _autocall(self, *, profiles_count: int) -> None:
        self.auto_frame = tk.Frame(self.root, bg=_PANEL)
        self._place("auto_call", self.auto_frame, 166, 670)
        self._auto_items: list[dict] = []
        self.set_autocall_profiles([""] * profiles_count)

    def set_autocall_profiles(self, labels: Sequence[str]) -> None:
        for item in self._auto_items:
            item["container"].destroy()
        self._auto_items.clear()
        for idx, raw in enumerate(labels):
            name = (raw or "").strip()
            cont = tk.Frame(self.auto_frame, bg=_PANEL)
            cont.grid(row=0, column=idx, padx=6, pady=2, sticky="n")
            csize = round(44 * self._scale)
            cpad = max(1, round(2 * self._scale))
            canvas = tk.Canvas(cont, width=csize, height=csize, bg=_PANEL, highlightthickness=0, bd=0)
            circle = canvas.create_oval(
                cpad, cpad, csize - cpad, csize - cpad, fill=_BG, outline=self._accent, width=2
            )
            canvas.create_text(
                csize / 2, csize / 2, text=str(idx + 1), fill=_FG, font=self._font(13, "bold")
            )
            canvas.pack()
            # El nombre de la macro va DEBAJO del círculo, envuelto: nunca desborda.
            caption = tk.Label(
                cont, text=name, bg=_PANEL, fg=_MUTED, font=self._font(7),
                wraplength=62, justify="center",
            )
            caption.pack(fill="x")
            slot_help = self._help("help_autocall_slot", n=idx + 1)
            for w in (cont, canvas, caption):
                w.bind("<Button-1>", partial(self._fire_autocall, idx))
                w.configure(cursor="hand2")
                Tooltip(w, slot_help)
            self._auto_items.append(
                {"container": cont, "canvas": canvas, "circle": circle, "caption": caption}
            )

    def _fire_autocall(self, idx: int, _event: object = None) -> None:
        self.cb.run_autocall(idx)

    def set_autocall_running(self, active_button: int | None) -> None:
        """Ilumina solo el círculo del botón en marcha (``None`` = ninguno)."""
        for idx, item in enumerate(self._auto_items):
            item["canvas"].itemconfigure(item["circle"], fill=_TX if idx == active_button else _BG)

    # -- selectores (combos) -------------------------- #
    def _combo_done(self, widget: ttk.Combobox, action: Callable[[], None]) -> None:
        """Ejecuta la acción y suelta el foco/resalte del combo readonly."""
        action()
        with contextlib.suppress(tk.TclError):
            widget.selection_clear()
            self.root.focus_set()

    # -- entradas de frecuencia ------------------------ #
    def _on_focus_in(self, _e: object) -> None:
        self._editing = True

    def _on_focus_out(self, _e: object) -> None:
        self._editing = False

    def _apply_entries(self, _e: object = None) -> None:
        hz = self.cb.combine_frequency(self.mhz.get(), self.khz.get(), self.chz.get())
        self._editing = False
        if hz is not None:
            self.cb.tune(hz)

    def _on_wheel(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self.cb.nudge(+1 if getattr(event, "delta", 0) > 0 else -1)

    # -- API de refresco (PoorSDRApp) ------------------ #
    def show_frequency(self, parts: FrequencyParts, label: str) -> None:
        if not self._editing:
            self.mhz.set(str(parts.mhz))
            self.khz.set(f"{parts.khz:03d}")
            self.chz.set(f"{parts.chz:02d}")

    def show_mode(self, mode: str) -> None:
        if mode in MODES:
            self.mode_var.set(mode)

    def show_band(self, band: str) -> None:
        if band and self.band_var.get() != band:
            self.band_var.set(band)

    def show_step_khz(self, khz: float) -> None:
        self.step_var.set(f"{khz:g}")

    def show_ptt(self, active: bool) -> None:
        self._ptt = active
        color = _TX if active else _PANEL
        # activebackground se fija igual que bg: si no, al pasar el ratón
        # por encima se ve el color del panel en vez del rojo de TX.
        self.ptt_button.configure(text="TX" if active else "PTT", bg=color, activebackground=color)

    def show_connected(self, connected: bool) -> None:
        self.settings_button.configure(fg=_FG if connected else _MUTED)

    def set_spots_enabled(self, enabled: bool) -> None:
        self._spots_on = enabled
        self.spots_button.configure(fg=self._active_accent() if enabled else _FG)

    # -- menú de tipos de spots ------------------------------- #
    def _open_spots_menu(self) -> None:
        if self._spots_menu is not None and self._spots_menu.winfo_exists():
            self._spots_menu.destroy()
            self._spots_menu = None
            return
        state = self.cb.get_spots() or {}
        menu = tk.Toplevel(self.root)
        self._spots_menu = menu
        menu.title("Spots")
        menu.resizable(False, False)
        menu.transient(self.root)
        menu.attributes("-topmost", True)
        menu.configure(bg=_PANEL)
        menu.protocol("WM_DELETE_WINDOW", lambda: self._close_spots_menu())
        menu.bind("<FocusOut>", lambda _e: self._close_spots_menu())

        vars_: dict[str, tk.BooleanVar] = {
            "enabled": tk.BooleanVar(value=bool(state.get("enabled", True))),
            "cw": tk.BooleanVar(value=bool(state.get("cw", True))),
            "digi": tk.BooleanVar(value=bool(state.get("digi", True))),
            "ssb": tk.BooleanVar(value=bool(state.get("ssb", True))),
            "off": tk.BooleanVar(value=bool(state.get("off", False))),
        }

        def _emit() -> None:
            self.cb.set_spots({k: v.get() for k, v in vars_.items()})
            self.set_spots_enabled(vars_["enabled"].get())

        rows = [
            (t("spots_show", self._lang), "enabled"),
            ("CW", "cw"),
            (t("spots_digi", self._lang), "digi"),
            (t("spots_ssb", self._lang), "ssb"),
            (t("spots_off_band", self._lang), "off"),
        ]
        for i, (label, key) in enumerate(rows):
            tk.Checkbutton(
                menu, text=label, variable=vars_[key], command=_emit,
                bg=_PANEL, fg=_FG, activebackground=_PANEL, activeforeground=_FG,
                selectcolor=_BG, highlightthickness=0, anchor="w", width=14,
            ).grid(row=i, column=0, padx=10, pady=(8 if i == 0 else 3, 3), sticky="w")
        tk.Button(
            menu, text=t("filters_close", self._lang), command=self._close_spots_menu,
            bg=_PANEL, fg=_FG, font=self._font(9, "bold"), width=12,
        ).grid(row=len(rows), column=0, padx=10, pady=(4, 10), sticky="ew")

        with contextlib.suppress(tk.TclError):
            bx = self.spots_button.winfo_rootx()
            by = self.spots_button.winfo_rooty() + self.spots_button.winfo_height()
            menu.geometry(f"+{bx}+{by}")

    def _close_spots_menu(self) -> None:
        if self._spots_menu is not None:
            with contextlib.suppress(tk.TclError):
                self._spots_menu.destroy()
            self._spots_menu = None

    def set_digi_enabled(self, enabled: bool) -> None:
        self._digi_on = enabled
        self.digi_button.configure(
            text="Digi ON" if enabled else "Digi OFF",
            fg=self._active_accent() if enabled else _FG,
        )

    def set_anr_state(self, enabled: bool, intensity: int) -> None:
        """Refleja el ANR persistido (no dispara los callbacks)."""
        self.anr_var.set(bool(enabled))
        self.anr_intensity_var.set(max(1, min(10, int(intensity))))

    def set_web_enabled(self, enabled: bool) -> None:
        self.web_button.configure(
            text="WEB ON" if enabled else "WEB OFF",
            fg=self._active_accent() if enabled else _FG,
        )

    def set_owrx_status(self, *, backend_ready: bool = False, client_ready: bool = False,
                        viewer_open: bool = False) -> None:
        # El botón OWRX refleja si la cascada está abierta.
        self._owrx_on = viewer_open
        self.owrx_button.configure(fg=self._active_accent() if viewer_open else _FG)

    def set_theme_accent(self, accent: str) -> None:
        self._accent = accent
        self._apply_accent()
        self.set_spots_enabled(self._spots_on)
        self.set_digi_enabled(self._digi_on)
        self.owrx_button.configure(fg=self._active_accent() if self._owrx_on else _FG)
        self._refresh_rx_indicator()

    def show_rx_source(self, src: str) -> None:
        self.rx_source_var.set(src)
        self._refresh_rx_indicator()

    def _refresh_rx_indicator(self) -> None:
        sel = (self.rx_source_var.get() or "radio").strip().lower()
        for value, btn in self._rx_buttons.items():
            if value == sel:
                btn.configure(relief="sunken", bd=2, bg=_PANEL, fg=self._active_accent())
            else:
                btn.configure(relief="flat", bd=0, bg=_PANEL, fg=_FG)

    # -- atajos de teclado (una acción por tecla) ------ #
    def _cycle(self, var: tk.StringVar, options: Sequence, step: int, apply: Callable) -> None:
        opts = [str(o) for o in options]
        if not opts:
            return
        try:
            idx = opts.index(str(var.get()))
        except ValueError:
            idx = 0
        value = opts[(idx + step) % len(opts)]
        var.set(value)
        apply(value)

    def _bump_dial(self, dial: DialControl | None, delta: float) -> None:
        if dial is not None:
            dial.set(float(getattr(dial, "value", 0.0)) + delta)

    def invoke(self, action_id: str) -> None:
        """Ejecuta lo mismo que pulsar el control asociado (para los atajos)."""
        cb = self.cb
        if action_id == "ptt_toggle":
            self.ptt_button.invoke()
        elif action_id == "tune_tone":
            self.tone_button.invoke()
        elif action_id == "vfo_up":
            cb.nudge(1)
        elif action_id == "vfo_down":
            cb.nudge(-1)
        elif action_id == "ch_plus":
            cb.channel(1)
        elif action_id == "ch_minus":
            cb.channel(-1)
        elif action_id in ("mode_next", "mode_prev"):
            self._cycle(self.mode_var, MODES, 1 if action_id == "mode_next" else -1, cb.set_mode)
        elif action_id in ("band_next", "band_prev"):
            self._cycle(self.band_var, band_names(), 1 if action_id == "band_next" else -1, cb.set_band)
        elif action_id in ("step_next", "step_prev"):
            self._cycle(
                self.step_var, [f"{v:g}" for v in STEP_OPTIONS_KHZ],
                1 if action_id == "step_next" else -1, lambda v: cb.set_step(float(v)),
            )
        elif action_id == "anr_toggle":
            self._anr_check.invoke()
        elif action_id in ("anr_up", "anr_down"):
            n = max(1, min(10, int(self.anr_intensity_var.get()) + (1 if action_id == "anr_up" else -1)))
            self.anr_intensity_var.set(n)
            cb.set_anr_intensity(n)
        elif action_id == "rx_vol_up":
            self._bump_dial(getattr(self, "_rx_dial", None), 5)
        elif action_id == "rx_vol_down":
            self._bump_dial(getattr(self, "_rx_dial", None), -5)
        elif action_id == "tx_gain_up":
            self._bump_dial(getattr(self, "_tx_dial", None), 5)
        elif action_id == "tx_gain_down":
            self._bump_dial(getattr(self, "_tx_dial", None), -5)
        elif action_id == "rx_source_radio":
            self._rx_buttons["radio"].invoke()
        elif action_id == "rx_source_sdr":
            self._rx_buttons["sdr"].invoke()
        elif action_id == "toggle_spots":
            self._open_spots_menu()
        elif action_id == "open_digi":
            self.digi_button.invoke()
        elif action_id == "open_owrx":
            self.owrx_button.invoke()
        elif action_id == "open_libro":
            btn = self._plugin_buttons.get("libro") or self._plugin_buttons.get("log")
            if btn is not None:
                btn.invoke()
        elif action_id == "open_mem":
            self.mem_button.invoke()
        elif action_id.startswith("auto_call_"):
            with contextlib.suppress(ValueError):
                self._fire_autocall(int(action_id.rsplit("_", 1)[1]) - 1)

    # -- botones aportados por plugins ---------------- #
    def add_plugin_button(self, button_id: str, label: str, on_click: Callable[[], None]) -> None:
        btn = tk.Button(self.root, text=label, width=6, command=on_click)
        self._style_action(btn)  # mismo estilo/fuente que Mem, OWRX, Digi…
        # add_plugin_button() se llama después de _apply_accent(); aplica el
        # acento a este botón para que su marco iguale al resto.
        with contextlib.suppress(tk.TclError):
            btn.configure(highlightbackground=self._accent, highlightcolor=self._accent)
        n = len(self._plugin_buttons)
        if n == 0:
            self._place("log_button", btn, 469, 666)
        else:
            self._place(f"plugin_button_{n}", btn, 469, 666 + 34 * n)
        self._plugin_buttons[button_id] = btn

    def clear_plugin_buttons(self) -> None:
        for btn in self._plugin_buttons.values():
            btn.destroy()
        self._plugin_buttons.clear()

    # -- volumen / vúmetro TX -------------------------- #
    def rx_volume(self) -> float:
        return float(getattr(getattr(self, "_rx_dial", None), "value", 25.0) or 25.0)

    def set_rx_volume(self, value: float) -> None:
        """Refleja el volumen RX (0-100) sin disparar el callback del dial."""
        if self._rx_dial is not None:
            self._rx_dial.set_silent(value)

    def set_tx_volume(self, value: float) -> None:
        """Refleja la ganancia TX (0-100) sin disparar el callback del dial."""
        if self._tx_dial is not None:
            self._tx_dial.set_silent(value)

    def show_tx_meter(self, on: bool) -> None:
        if on == self._tx_meter_shown:
            return
        self._tx_meter_shown = bool(on)
        if on:
            self.waterfall.place_forget()
            self._tx_meter.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            self._tx_meter.place_forget()
            self._tx_meter_dbfs = -60.0
            self.waterfall.place(x=0, y=0, relwidth=1, relheight=1)
            for rect in self._tx_segments:
                self._tx_meter.itemconfigure(rect, fill=_PANEL)

    def set_tx_level(self, dbfs: float) -> None:
        # Ataque inmediato, caída 1,5 dB por frame; los 20 segmentos cubren -54..0 dBFS.
        self._tx_meter_dbfs = max(float(dbfs), self._tx_meter_dbfs - 1.5)
        level = min(1.0, max(0.0, (self._tx_meter_dbfs + 54.0) / 54.0))
        lit = int(level * len(self._tx_segments) + 0.999) if level > 0 else 0
        for idx, rect in enumerate(self._tx_segments):
            if idx < lit:
                color = self._accent if idx >= 16 else _WARN if idx >= 12 else _FG
            else:
                color = _PANEL
            self._tx_meter.itemconfigure(rect, fill=color)

    def apply_view(self, view) -> None:  # type: ignore[no-untyped-def]
        self.show_frequency(view.parts, view.freq_label)
        self.show_mode(view.mode)
        self.show_band(view.band)
        self.show_step_khz(view.step_hz / 1000)
        self.show_ptt(view.ptt)
        self.show_connected(view.connected)


__all__ = ["Callbacks", "MainWindow"]
