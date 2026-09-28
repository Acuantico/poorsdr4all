"""Panel RTTY: señales detectadas en la pasabanda actual del uSDX + TX asistido.

Vive en el MISMO proceso que la consola (a diferencia de la cascada/Digi, que
son visores aparte que hablan por socket): necesita llamar directamente a
``_vendor.audio.pop_rx_raw_chunk_digi()``/``inject_tx_audio()``, que son
funciones de ese módulo Python, no algo alcanzable por red.

Diseño inspirado en el flujo clásico de MMTTY/fldigi (sintonía + banco de
señales + texto RX grande + macros + TX), adaptado al tema oscuro/rojo propio
de PoorSDR4All en vez de copiar la estética de Windows de esos programas.

Guardado de QSO: no habla el esquema propio de NMN1M ni de ningún otro libro
de guardia -- imita el protocolo UDP de WSJT-X ("Logged ADIF", puerto 2237),
que NMN1M (y cualquier otro programa que también lo escuche) ya sabe
importar solo. Ver ``rtty.build_wsjtx_logged_adif_packet``.
"""

from __future__ import annotations

import contextlib
import json
import socket
import time
import tkinter as tk
from collections.abc import Callable

import numpy as np

from poorsdr.infra import paths as _paths
from poorsdr.infra.logging import get_logger
from poorsdr_rtty_power.contest import (
    CALL_RE,
    CQ_LOOKAHEAD_CHARS,
    CQ_LOOKBACK_CHARS,
    WorkedLog,
    cq_answer,
    cq_caller,
    exchange_to_send,
    find_reply_exchange,
    is_calling_cq,
    is_contest_band,
    parse_exchange,
    reply_text,
    responder_step,
    split_exchange,
)
from poorsdr_rtty_power.engine import RttyEngine
from poorsdr_rtty_power.rtty import (
    band_from_freq_hz,
    build_qso_adif,
    build_wsjtx_logged_adif_packet,
    find_signal_candidates,
)

_log = get_logger("plugins.rtty_power.panel")

#: NMN1M escucha aquí por defecto ("Escuchar WSJT-X por UDP", 0.0.0.0:2237)
#: -- hay que tenerlo activado en NMN1M para que el autoguardado funcione.
#: Sin ventana de ajustes propia a propósito: coincide con el puerto por
#: defecto del propio NMN1M, así que no hace falta configurar nada más.
_LOG_UDP_HOST = "127.0.0.1"
_LOG_UDP_PORT = 2237



#: Tamaño/posición del panel entre sesiones -- mismo patrón que
#: ``viewers/waterfall.py::_save_geometry`` (un JSON aparte, no
#: ``AppConfig``: es estado de un plugin, no del núcleo).
_GEOMETRY_STATE_PATH = _paths.runtime_dir() / "rtty_panel_state.json"
#: QSOs guardados desde este panel (indicativo + banda + hora): lo que marca
#: un indicativo como "ya trabajado". Sobrevive a reinicios en mitad de un
#: concurso; solo cuentan las últimas 48 h (ver poorsdr_rtty_power.contest).
_WORKED_LOG_PATH = _paths.runtime_dir() / "rtty_worked.json"
#: Colores de los indicativos en el texto recibido (y su leyenda).
_CALL_STYLES = (
    ("call_new", "nuevo", dict(foreground="#3cff3c", underline=1)),
    ("call_dupe", "ya trabajado (esta banda)", dict(foreground="#6e6e6e", overstrike=1)),
    ("call_current", "trabajando ahora", dict(foreground="#000000", background="#e0c000")),
    ("call_mine", "te llaman", dict(foreground="#ffffff", background="#d5001c")),
)
_CALL_TAGS = tuple(tag for tag, _label, _style in _CALL_STYLES)
#: Tras cada trozo decodificado solo se recolorea la cola del texto: un
#: indicativo puede llegar partido entre dos trozos, pero nunca más atrás.
_RETAG_TAIL_CHARS = 400
#: Tras responder a un CQ, cuánto se espera (desde que acaba nuestra TX) a
#: que esa estación nos dé su intercambio antes de dejarlo.
_SP_REPLY_TIMEOUT_SEC = 20.0
#: Su reporte ya ha llegado, pero NO se contesta hasta que lleve esto sin
#: llegar texto nuevo (ha dejado de transmitir): si no, se le transmitía
#: encima nada más decodificar "599", antes de su zona (bug real, IB9R).
_SP_QUIET_SEC = 1.2
_GEOMETRY_SAVE_INTERVAL_SEC = 1.0

_TICK_MS = 80
_SCOPE_MS = 80
#: Filtros del uSDX, MEDIDOS en este equipo (2026-09-27, LSB, comparando el
#: ruido y una señal con cada filtro frente a Full): (desde, hasta) = la parte
#: del audio que deja pasar, y su centro. 1800 pasa lo mismo que 2400 y 3000
#: lo mismo que Full; el 100 no se ofrece (más estrecho que la propia señal
#: RTTY). El 200 tiene además una banda parásita hacia 2200 Hz. Solo adapta
#: el panel (cascada, auto-scan, centro de RX/TX): el filtro se pone a mano
#: en el uSDX.
_USDX_FILTERS: dict[str, tuple[float, float, float]] = {
    "Full / 3000": (200.0, 3000.0, 1500.0),
    "2400 / 1800": (200.0, 2400.0, 1300.0),
    "500": (500.0, 1000.0, 750.0),
    "200": (600.0, 950.0, 750.0),
}
_DEFAULT_FILTER = "Full / 3000"
#: Vista de sintonía fina: en cuanto hay una frecuencia manual o una señal
#: seleccionada, el FFT se centra ahí en vez de mostrar toda la pasabanda —
#: con 170 Hz de shift repartidos en solo 2.7 kHz de ancho, mark y space
#: quedan tan juntos que centrar a ojo era casi imposible.
_ZOOM_HALF_HZ = 220.0
#: Suavizado (media móvil exponencial) entre fotogramas del FFT: sin esto la
#: traza salta demasiado de un fotograma a otro para poder alinear nada.
_SMOOTH_ALPHA = 0.35
#: Si hay un pico de verdad a menos de esto del objetivo, la línea se pone
#: verde ("centrado"); si no, se queda amarilla.
_LOCK_TOLERANCE_HZ = 20.0
#: Un clic solo "engancha" al pico real más cercano (ver
#: ``_resolve_click_center``) si cae a menos de esto de donde se pinchó --
#: si no, usa el pixel pulsado tal cual. Sin este límite, en una pasabanda
#: con varias señales (justo el caso para el que existe este panel: un
#: pileup de concurso) un clic cerca de UNA estación podía "saltar" a otra
#: bastante más lejos con más energía, en vez de quedarse en la que se
#: señaló.
_CLICK_SNAP_TOLERANCE_HZ = 40.0
#: No mandar un SET_FREQ por cada pixel de arrastre — el CAT por serie tiene
#: su propia latencia y un radio real no necesita más resolución que esta.
_CAT_RETUNE_THROTTLE_SEC = 0.12
_WHEEL_STEP_HZ = 10
#: Con un ratón/trackpad real es fácil mover unos pocos px sin querer al
#: hacer clic -- con un margen de solo 3 px eso caía silenciosamente en la
#: rama de "arrastre" (que no alinea nada con la marca, solo desplaza lo que
#: se movió el ratón) en vez de la de "clic" (alinear con la marca
#: izquierda), así que el clic parecía no hacer lo que debía sin ningún
#: error visible. Subido a 8 px una vez, pero seguía sin bastar en la
#: práctica (mismo síntoma reportado otra vez) -- un trackpad o un ratón de
#: alto DPI mueve más de eso sin que el operador lo perciba como
#: "arrastre". Subido más, a 20 px: sigue siendo mucho más pequeño que
#: cualquier arrastre real con intención de retunear (la pasabanda visible
#: son cientos de Hz en unos ~600 px de ancho de canvas).
_CLICK_MAX_DRAG_PX = 20

# Tema oscuro/rojo propio, sin depender de main_window.py (evita acoplar un
# panel experimental a constantes privadas de otro módulo).
_BG = "#0b0b0b"
_PANEL = "#161616"
_FG = "#e6e6e6"
_DIM = "#8a8a8a"
_ACCENT = "#d5001c"
_BORDER = "#3a1414"
_RX_BG = "#050505"
_RX_FG = "#ff4d3d"


def _strip_control_chars(text: str) -> str:
    return text.replace("\x07", "").replace("\r", "\n")


class RttyPanel(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        engine: RttyEngine,
        *,
        my_call: str = "",
        on_close: Callable[[], None] | None = None,
        on_filter_change: Callable[[tuple[float, float] | None], None] | None = None,
    ) -> None:
        #: Avisa del filtro elegido (Hz de audio, o None = ancho normal) para
        #: que el selector de la cascada de OWRX tenga el mismo ancho.
        self._on_filter_change_cb = on_filter_change
        #: Tu propio indicativo (Ajustes -> Interfaz -> "Mi indicativo"), NO
        #: el de la estación con la que trabajas (eso es self.call_var). Se
        #: usa en el macro CQ y como OPERATOR al guardar el QSO.
        self.my_call = my_call.strip().upper()
        # Un Toplevel no hereda el className="PoorSDR4All" del root (eso solo
        # fija el WM_CLASS de la ventana principal): sin esto, la barra de
        # tareas no lo asocia con el .desktop y muestra un nombre genérico.
        # ``wm class`` como comando en caliente no existe en Tk 9 (produce
        # TclError: "bad option class" y rompía la apertura del panel) -- hay
        # que pasarlo al propio constructor con class_=.
        super().__init__(master, class_="PoorSDR4All")
        self.title("RTTY")
        self.geometry("640x560")
        self._restore_target_xy: tuple[int, int] | None = None
        self._geometry_correction_job: str | None = None
        self._restore_geometry()
        # No 0.0: eso haría que el primer _tick() (a los 80 ms) ya guardara
        # geometría -- antes de que _correct_restored_position() (que tarda
        # hasta ~1.2 s en reintentos) termine de corregir la posición,
        # volviendo a grabar la posición todavía desplazada.
        self._last_geometry_save = time.monotonic()
        self.configure(bg=_BG)
        self.engine = engine
        self._on_close = on_close
        self._tick_job: str | None = None
        self._scope_job: str | None = None
        self._rows: dict[int, int] = {}  # índice de fila listbox -> clave de señal
        self._selected_key: int | None = None
        self._displayed_len: dict[int, int] = {}
        self._drag_start_x: int | None = None
        self._drag_base_freq: int | None = None
        self._last_cat_update = 0.0
        self._smoothed_mags: np.ndarray | None = None
        if self._loaded_filter not in _USDX_FILTERS:
            self._loaded_filter = _DEFAULT_FILTER
        #: Filtro que el operador tiene puesto en el uSDX (selector del panel).
        self._filter_name = self._loaded_filter
        self._current_range: tuple[float, float] = self._filter_range()
        # El zoom solo se activa por una acción real del operador (clic en
        # una señal de la lista, o "Enganchar") -- nunca porque el campo
        # "Manual (Hz)" tenga su valor por defecto o porque el auto-scan
        # haya seguido de oficio la última señal detectada. Si no, la vista
        # ancha para buscar no llega a verse nunca.
        self._zoom_active = False
        #: Centro real (Hz de audio) que se dibuja/enfoca AHORA: por defecto
        #: el nominal, pero en cuanto se selecciona una señal de verdad
        #: (lista, "Enganchar" o clic en la cascada) pasa a ser su
        #: ``center_hz`` real -- ver ``_select_key``. Con esto las marcas y
        #: el zoom siguen a la señal elegida en vez de esperar siempre en
        #: 1500 Hz (que solo tenía sentido cuando el clic retuneaba por CAT
        #: para traer la señal hasta ahí).
        self._decode_center_hz: float = self._filter_center()
        #: QSOs guardados (por banda): "ya trabajado" = QSO guardado de
        #: verdad, no "le he contestado" (un QSO puede no completarse).
        self._worked = self._load_worked()
        self._retag_job: str | None = None
        #: Respuesta a un CQ en curso (S&P): a quién se llamó, lo recibido
        #: de él desde que acabó nuestra TX y hasta cuándo se le espera.
        self._sp_call: str | None = None
        self._sp_text = ""
        self._sp_deadline: float | None = None
        self._sp_last_rx = 0.0
        self._rx_log_buf = ""
        #: Indicativo cuyo intercambio ya se sacó de su respuesta: el
        #: "Recibido" automático no lo pisa con el de la siguiente estación.
        self._exchange_locked_call: str | None = None
        #: (indicativo, fase) del QSO en curso para el botón Responder (ver
        #: contest.responder_step). Cambiar de indicativo en CALL
        #: empieza de cero.
        self._qso_phase: tuple[str, str] = ("", "none")
        self.protocol("WM_DELETE_WINDOW", self._close)
        # Esc corta la transmisión en curso, como en N1MM/MMTTY.
        self.bind("<Escape>", lambda _e: self._abort_tx())

        self._build_ui()

        self.engine.on_signal_update = self._refresh_signals
        self._schedule_tick()
        self._schedule_scope()

    # ---- construcción -------------------------------------------------- #
    def _build_ui(self) -> None:
        tuning = tk.LabelFrame(
            self, text="Sintonía", bg=_PANEL, fg=_FG, bd=1, highlightbackground=_BORDER
        )
        tuning.pack(fill="x", padx=6, pady=(6, 3))

        left = tk.Frame(tuning, bg=_PANEL)
        left.pack(side="left", padx=6, pady=6)
        tk.Label(left, text="Manual (Hz):", bg=_PANEL, fg=_FG).grid(row=0, column=0, sticky="w")
        self.manual_freq_var = tk.StringVar(value=f"{self._filter_center():.0f}")
        tk.Entry(left, textvariable=self.manual_freq_var, width=8, bg=_BG, fg=_FG, insertbackground=_FG).grid(
            row=0, column=1, padx=4
        )
        tk.Button(left, text="Enganchar", command=self._lock_manual, bg=_PANEL, fg=_FG).grid(
            row=0, column=2, padx=4
        )
        tk.Button(left, text="Vista ancha", command=self._toggle_zoom_wide, bg=_PANEL, fg=_FG).grid(
            row=0, column=3, padx=4
        )
        # Filtro puesto en el uSDX: ajusta cascada, auto-scan y centro RX/TX.
        tk.Label(left, text="Filtro (Hz):", bg=_PANEL, fg=_FG).grid(row=0, column=4, padx=(12, 2), sticky="e")
        self.filter_var = tk.StringVar(value=self._filter_name)
        filter_menu = tk.OptionMenu(left, self.filter_var, *_USDX_FILTERS, command=self._on_filter_change)
        filter_menu.configure(bg=_PANEL, fg=_FG, activebackground=_PANEL, activeforeground=_FG,
                              highlightthickness=0, width=10)
        filter_menu["menu"].configure(bg=_PANEL, fg=_FG)
        filter_menu.grid(row=0, column=5, padx=2)
        self.engine.scan_range_hz = self._filter_range()
        self._notify_filter()
        self.auto_scan_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            left,
            text="Auto-scan",
            variable=self.auto_scan_var,
            command=self._toggle_auto_scan,
            bg=_PANEL,
            fg=_FG,
            selectcolor=_BG,
            activebackground=_PANEL,
            activeforeground=_FG,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.afc_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            left,
            text="AFC",
            variable=self.afc_var,
            command=self._toggle_afc,
            bg=_PANEL,
            fg=_FG,
            selectcolor=_BG,
            activebackground=_PANEL,
            activeforeground=_FG,
        ).grid(row=1, column=2, sticky="w", pady=(4, 0))
        # Rev: solo RX, para leer a una estación que transmite invertida. La
        # polaridad normal (USB/LSB) ya la pone el motor según el modo del
        # equipo, así que en uso normal esto se deja apagado.
        self.rev_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            left,
            text="Rev",
            variable=self.rev_var,
            command=self._toggle_rev,
            bg=_PANEL,
            fg=_FG,
            selectcolor=_BG,
            activebackground=_PANEL,
            activeforeground=_FG,
        ).grid(row=1, column=3, sticky="w", pady=(4, 0))

        self.scope = tk.Canvas(self, height=110, bg=_RX_BG, highlightthickness=1, highlightbackground=_BORDER)
        self.scope.pack(fill="x", padx=6, pady=(2, 4))
        self._bind_scope_drag()

        self.listbox = tk.Listbox(
            self, font=("Courier New", 10), height=4, bg=_PANEL, fg=_FG,
            selectbackground=_ACCENT, highlightthickness=0, bd=0,
        )
        self.listbox.pack(fill="x", padx=6, pady=(2, 4))
        self.listbox.bind("<<ListboxSelect>>", self._on_select_signal)
        self.listbox.bind("<Double-Button-1>", self._on_take_call)

        rx_toolbar = tk.Frame(self, bg=_BG)
        rx_toolbar.pack(fill="x", padx=6)
        tk.Button(rx_toolbar, text="Limpiar decodificación", command=self._clear_rx, bg=_PANEL, fg=_FG).pack(
            side="right"
        )
        # Leyenda de colores: se ve de un vistazo qué significa cada uno.
        for _tag, label, style in _CALL_STYLES:
            look = "bold" + (" underline" if style.get("underline") else "")
            look += " overstrike" if style.get("overstrike") else ""
            tk.Label(
                rx_toolbar, text=f" {label} ", font=("Courier New", 10, look),
                fg=style["foreground"], bg=style.get("background", _BG),
            ).pack(side="left", padx=(0, 6))

        self.rx_text = tk.Text(
            self, font=("Courier New", 11), bg=_RX_BG, fg=_RX_FG, insertbackground=_RX_FG,
            wrap="word", height=12, bd=0, highlightthickness=1, highlightbackground=_BORDER,
        )
        self.rx_text.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self.rx_text.configure(state="disabled")
        # Lo que TÚ transmites se inserta en esta misma ventana (ver _send())
        # en azul, para poder seguir la conversación completa (TX+RX) en un
        # solo sitio en vez de tener que fiarte de la barra de estado.
        self.rx_text.tag_configure("tx", foreground="#4da6ff")
        # Indicativos: aquí, en el texto decodificado, es donde de verdad hace
        # falta identificarlos rápido. Negrita para que resalten del texto.
        for tag, _label, style in _CALL_STYLES:
            self.rx_text.tag_configure(tag, font=("Courier New", 11, "bold"), **style)
            self.rx_text.tag_bind(tag, "<Enter>", lambda _e: self.rx_text.configure(cursor="hand2"))
            self.rx_text.tag_bind(tag, "<Leave>", lambda _e: self.rx_text.configure(cursor=""))
        self.rx_text.bind("<Double-Button-1>", self._on_rx_double_click)
        # Copiar: el widget está en "disabled" (para que no se escriba en
        # él) y así Tk no le da el foco al hacer clic -- Ctrl+C no llegaba y
        # no había forma de copiar nada. Clic -> foco; Ctrl+C y menú del
        # botón derecho copian la selección.
        self.rx_text.bind("<Button-1>", lambda _e: self.rx_text.focus_set(), add="+")
        self.rx_text.bind("<Control-c>", lambda _e: self._copy_rx_selection())
        self.rx_text.bind("<Control-C>", lambda _e: self._copy_rx_selection())
        self._rx_menu = tk.Menu(self, tearoff=0)
        self._rx_menu.add_command(label="Copiar", command=self._copy_rx_selection)
        self._rx_menu.add_command(label="Copiar todo", command=lambda: self._copy_rx_selection(everything=True))
        self.rx_text.bind("<Button-3>", lambda e: self._rx_menu.tk_popup(e.x_root, e.y_root))

        form = tk.Frame(self, bg=_BG)
        form.pack(fill="x", padx=6, pady=(0, 4))
        tk.Label(form, text="CALL:", bg=_BG, fg=_FG).grid(row=0, column=0, sticky="w")
        self.call_var = tk.StringVar()
        tk.Entry(form, textvariable=self.call_var, width=14, bg=_PANEL, fg=_FG, insertbackground=_FG).grid(
            row=0, column=1, padx=(2, 12)
        )
        # El indicativo en CALL se resalta como "trabajando ahora".
        self.call_var.trace_add("write", lambda *_a: self._schedule_retag())
        tk.Label(form, text="Exchange:", bg=_BG, fg=_FG).grid(row=0, column=2, sticky="w")
        self.exchange_var = tk.StringVar(value="599")
        tk.Entry(form, textvariable=self.exchange_var, width=10, bg=_PANEL, fg=_FG, insertbackground=_FG).grid(
            row=0, column=3, padx=2
        )

        # Concurso: mi zona CQ (para componer el exchange a enviar, "599
        # <zona>") y lo que el corresponsal me da a mí (heurística sobre el
        # texto decodificado -- el operador debe comprobarlo, no es fiable
        # al 100% con QRM). Sin esto no hay forma rápida de trabajar CQ WW
        # RTTY u otro concurso con exchange de zona.
        tk.Label(form, text="Mi zona CQ:", bg=_BG, fg=_FG).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.my_zone_var = tk.StringVar(value=self._loaded_my_zone)
        my_zone_entry = tk.Entry(
            form, textvariable=self.my_zone_var, width=14, bg=_PANEL, fg=_FG, insertbackground=_FG
        )
        my_zone_entry.grid(row=1, column=1, padx=(2, 12), pady=(4, 0))
        my_zone_entry.bind("<FocusOut>", lambda _e: self._apply_my_zone())
        my_zone_entry.bind("<Return>", lambda _e: self._apply_my_zone())
        tk.Label(form, text="Recibido:", bg=_BG, fg=_FG).grid(row=1, column=2, sticky="w", pady=(4, 0))
        self.received_exchange_var = tk.StringVar(value="")
        tk.Entry(
            form, textvariable=self.received_exchange_var, width=10, bg=_PANEL, fg=_FG, insertbackground=_FG
        ).grid(row=1, column=3, padx=2, pady=(4, 0))
        self._apply_my_zone(persist=False)

        macros = tk.LabelFrame(
            self, text="Macros", bg=_PANEL, fg=_FG, bd=1, highlightbackground=_BORDER
        )
        macros.pack(fill="x", padx=6, pady=(0, 4))
        specs = [
            ("CQ", self._send_cq),
            ("Responder", self._responder),
            ("599", self._send_report),
            ("TU", self._send_tu),
            ("AGN?", lambda: self._send("AGN?")),
            ("NR?", lambda: self._send("NR?")),
        ]
        for i, (label, fn) in enumerate(specs):
            tk.Button(macros, text=label, width=9, command=fn, bg=_PANEL, fg=_FG).grid(
                row=i // 3, column=i % 3, padx=3, pady=3
            )
        # Junto a 599: contestar a quien solo manda su indicativo, sin CQ.
        tk.Button(macros, text="Llamar", width=9, command=self._call_station, bg=_PANEL, fg=_FG).grid(
            row=0, column=3, padx=3, pady=3
        )
        # A la derecha, separado (sangrado) del resto de macros -- no es un
        # envío por radio como los demás botones, es guardar el QSO ya
        # cerrado en el log.
        tk.Button(
            macros, text="Guardar QSO...", command=self._open_qso_dialog, bg=_PANEL, fg=_FG
        ).grid(row=0, column=4, rowspan=2, padx=(18, 6), pady=3, sticky="ns")

        tx_row = tk.Frame(self, bg=_BG)
        tx_row.pack(fill="x", padx=6, pady=(0, 4))
        self.tx_var = tk.StringVar()
        tx_entry = tk.Entry(tx_row, textvariable=self.tx_var, bg=_PANEL, fg=_FG, insertbackground=_FG)
        tx_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        tx_entry.bind("<Return>", lambda _e: self._send_free_text())
        tk.Button(tx_row, text="Enviar", command=self._send_free_text, bg=_PANEL, fg=_FG).pack(side="left")

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, anchor="w", bg=_BG, fg=_DIM).pack(
            fill="x", padx=6, pady=(0, 6)
        )

    # ---- ciclo de refresco ------------------------------------------- #
    def _schedule_tick(self) -> None:
        self._tick_job = self.after(_TICK_MS, self._tick)

    def _tick(self) -> None:
        self.engine.tick()
        self._check_sp_timeout()
        now = time.monotonic()
        if now - self._last_geometry_save >= _GEOMETRY_SAVE_INTERVAL_SEC:
            self._last_geometry_save = now
            self._save_geometry()
        self._schedule_tick()

    def _restore_geometry(self) -> None:
        # También carga "mi zona CQ" del mismo JSON -- un solo archivo de
        # estado propio del panel, sin tocar AppConfig. self._loaded_my_zone
        # se aplica a my_zone_var más tarde, en _build_ui() (este método se
        # llama antes de construir los widgets).
        self._loaded_my_zone = ""
        self._loaded_filter = _DEFAULT_FILTER
        try:
            data = json.loads(_GEOMETRY_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        self._loaded_my_zone = str(data.get("my_zone", "") or "")
        self._loaded_filter = str(data.get("usdx_filter", "") or _DEFAULT_FILTER)
        try:
            w, h, x, y = int(data["width"]), int(data["height"]), int(data["x"]), int(data["y"])
        except Exception:
            return
        if w > 0 and h > 0:
            self.geometry(f"{w}x{h}+{x}+{y}")
            # El gestor de ventanas añade su propio marco (barra de título)
            # A PARTIR de la posición pedida, así que la ventana reaparece
            # unos pocos px más abajo/a la derecha de donde estaba realmente
            # (confirmado: pedir "+400+300" en este KWin acaba en
            # winfo_x/y=404,323). Guardar winfo_x/y ya captura la posición
            # real, pero pedir esa misma posición de nuevo suma el marco
            # OTRA VEZ -- se corrige en un segundo paso una vez el gestor de
            # ventanas ya ha colocado la ventana (ver _correct_restored_position).
            self._restore_target_xy = (x, y)
            self._geometry_correction_job = self.after(150, lambda: self._correct_restored_position(8))

    def _correct_restored_position(self, attempts_left: int) -> None:
        # Un único intento a los 150 ms asumía que el gestor de ventanas ya
        # había colocado la ventana del todo para entonces -- con la app
        # cargando 11 servicios de golpe puede tardar bastante más. Reintenta
        # (hasta 8 veces cada 150 ms, ~1.2 s en total) y para en cuanto la
        # posición ya coincide, en vez de asumir un único intento a ciegas.
        self._geometry_correction_job = None
        target = self._restore_target_xy
        if target is None:
            return
        self.update_idletasks()
        target_x, target_y = target
        dx = self.winfo_x() - target_x
        dy = self.winfo_y() - target_y
        if dx or dy:
            self.geometry(f"+{target_x - dx}+{target_y - dy}")
        if attempts_left <= 1:
            self._restore_target_xy = None
            return
        self._geometry_correction_job = self.after(150, lambda: self._correct_restored_position(attempts_left - 1))

    def _save_geometry(self) -> None:
        try:
            self.update_idletasks()
            if self._restore_target_xy is not None:
                # La corrección de posición todavía no ha terminado de
                # converger (p. ej. si se cierra el panel a los pocos
                # cientos de ms de abrirlo, antes de que acaben los
                # reintentos): usar el objetivo ya conocido en vez de
                # winfo_x/y "en construcción" evita grabar una posición a
                # medio corregir que luego se perpetuaría la próxima vez.
                x, y = self._restore_target_xy
            else:
                x, y = int(self.winfo_x()), int(self.winfo_y())
            data = {
                "width": int(self.winfo_width()),
                "height": int(self.winfo_height()),
                "x": x,
                "y": y,
                "my_zone": self.my_zone_var.get().strip(),
                "usdx_filter": self._filter_name,
            }
            _GEOMETRY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _GEOMETRY_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _schedule_scope(self) -> None:
        self._scope_job = self.after(_SCOPE_MS, self._draw_scope)

    def _draw_scope(self) -> None:
        self._render_scope()
        self._schedule_scope()

    def _view_range(self) -> tuple[float, float]:
        """Rango de frecuencia visible: "Vista ancha" elige entre ver toda
        la pasabanda para buscar o una franja estrecha centrada en
        ``self._decode_center_hz`` (la señal realmente seleccionada, o el
        nominal si todavía no hay ninguna) para afinar."""
        if self._zoom_active:
            center = self._decode_center_hz
            return (center - _ZOOM_HALF_HZ, center + _ZOOM_HALF_HZ)
        return self._filter_range()

    def _filter_range(self) -> tuple[float, float]:
        lo, hi, _center = _USDX_FILTERS[self._filter_name]
        return (lo, hi)

    def _filter_center(self) -> float:
        return _USDX_FILTERS[self._filter_name][2]

    def _on_filter_change(self, name: str) -> None:
        """El operador ha cambiado el filtro del uSDX: la cascada y el
        auto-scan pasan a mirar solo lo que deja pasar, y si no hay ninguna
        señal elegida, las marcas y el centro de RX/TX van al centro del
        filtro (con 500 o 200, ~750 Hz: mueve el dial hasta que las crestas
        caigan en las marcas)."""
        self._filter_name = name if name in _USDX_FILTERS else _DEFAULT_FILTER
        self.engine.scan_range_hz = self._filter_range()
        self._smoothed_mags = None
        if self._selected_key is None or self._selected_key not in self.engine.signals:
            self._decode_center_hz = self._filter_center()
            self.manual_freq_var.set(f"{self._filter_center():.0f}")
        lo, hi = self._filter_range()
        self.status_var.set(f"Filtro uSDX {self._filter_name}: pasa {lo:.0f}-{hi:.0f} Hz, centro {self._filter_center():.0f} Hz.")
        self._save_geometry()
        self._notify_filter()

    def _notify_filter(self) -> None:
        if self._on_filter_change_cb is None:
            return
        passband = None if self._filter_name == _DEFAULT_FILTER else self._filter_range()
        with contextlib.suppress(Exception):
            self._on_filter_change_cb(passband)

    def _render_scope(self) -> None:
        canvas = self.scope
        canvas.delete("all")
        w = max(1, canvas.winfo_width())
        h = max(1, canvas.winfo_height())

        # Recoge el centro EN VIVO de la señal seleccionada antes de dibujar:
        # el AFC del motor (RttyEngine._run_afc) la va recentrando sola en
        # segundo plano, así que hay que releerlo cada fotograma para que las
        # marcas se vean converger hacia el pico real en vez de quedarse
        # clavadas donde se hizo clic/Enganchar la primera vez.
        if self._selected_key is not None:
            sig = self.engine.signals.get(self._selected_key)
            if sig is not None:
                self._decode_center_hz = sig.center_hz

        lo, hi = self._view_range()
        if (lo, hi) != self._current_range:
            # Cambio de objetivo/rango: no tiene sentido mezclar el
            # suavizado con la traza de una franja de frecuencia distinta.
            self._smoothed_mags = None
        self._current_range = (lo, hi)

        # Vistas estrechas (filtro 500/200, zoom): más audio para que se vean
        # las dos crestas; la vista ancha sigue con el trozo corto de siempre.
        narrow = (hi - lo) <= 1000.0
        samples = self.engine.scope_samples if narrow else self.engine.last_samples
        mags = None
        if samples is not None and samples.size >= 256:
            # FFT de alta resolución sobre todo el audio disponible y luego
            # recorte a [lo, hi]: con la vista centrada estrecha (440 Hz) hace
            # falta bastante más resolución en frecuencia que para la vista
            # ancha, si no los dos picos de mark/space quedan indistinguibles.
            n = 8192
            tail = samples[-n:]
            windowed = tail.astype(np.float64) * np.hanning(tail.size)
            spectrum = np.abs(np.fft.rfft(windowed, n=n))
            freqs = np.fft.rfftfreq(n, d=1.0 / self.engine.sample_rate)
            mask = (freqs >= lo) & (freqs <= hi)
            bin_freqs = freqs[mask]
            mags = spectrum[mask]
            if mags.size and mags.max() > 0:
                mags = mags / mags.max()
                # Remuestrea a una columna por pixel, interpolando por
                # FRECUENCIA real de cada bin (no por índice): el primer/
                # último bin de la FFT no caen exactamente en lo/hi (la
                # resolución de la FFT es de varios Hz), así que interpolar
                # por índice desplazaba el pico visualmente unos pocos Hz
                # respecto a donde lo sitúa el clic/las marcas -- que sí usan
                # "lo + (x/w)*(hi-lo)" como frecuencia exacta de cada pixel.
                # Con esto ambos lados usan la misma correspondencia
                # pixel<->Hz y el clic cae justo donde se ve el pico.
                pixel_freqs = lo + (np.arange(w) / w) * (hi - lo)
                mags = np.interp(pixel_freqs, bin_freqs, mags)
                if self._smoothed_mags is not None and self._smoothed_mags.size == mags.size:
                    mags = _SMOOTH_ALPHA * mags + (1 - _SMOOTH_ALPHA) * self._smoothed_mags
                self._smoothed_mags = mags
            else:
                mags = None

        if mags is not None:
            points: list[float] = []
            for i, value in enumerate(mags):
                y = h - float(value) * (h - 6) - 3
                points.extend((float(i), y))
            if len(points) >= 4:
                # Línea limpia en vez del relleno rayado de antes (se veía
                # "bruto" — el patrón de puntos de un stipple no ayuda a ver
                # el pico, solo ensucia). Una segunda pasada más ancha y
                # tenue por debajo da un ligero resplandor sin ese aspecto
                # granulado.
                canvas.create_line(*points, fill=_RX_FG, width=3, joinstyle="round", smooth=True, stipple="gray50")
                canvas.create_line(*points, fill=_RX_FG, width=1, joinstyle="round", smooth=True)

        # Líneas verticales de mark/space: en ``self._decode_center_hz`` --
        # el nominal mientras no haya nada elegido, o el centro real de la
        # señal seleccionada/enganchada/pinchada en cuanto la hay. Verdes si
        # hay un pico de verdad justo ahí (ya alineado), amarillas si no.
        half = self.engine.shift_hz / 2.0
        center = self._decode_center_hz
        for target_hz in (center - half, center + half):
            if not (lo <= target_hz <= hi):
                continue
            x = (target_hz - lo) / (hi - lo) * w
            locked = False
            if mags is not None and mags.size:
                tol_px = max(1, int(round(_LOCK_TOLERANCE_HZ / (hi - lo) * w)))
                x_px = int(round(x))
                window = mags[max(0, x_px - tol_px) : min(mags.size, x_px + tol_px + 1)]
                locked = bool(window.size and window.max() > 0.55)
            canvas.create_line(x, 0, x, h, fill="#20c020" if locked else "#e0c000", width=2)

    # ---- FFT: arrastre = retunear por CAT, rueda = paso fino ----------- #
    def _bind_scope_drag(self) -> None:
        self.scope.bind("<ButtonPress-1>", self._on_scope_press)
        self.scope.bind("<B1-Motion>", self._on_scope_drag)
        self.scope.bind("<ButtonRelease-1>", self._on_scope_release)
        self.scope.bind("<MouseWheel>", self._on_scope_wheel)  # Windows/macOS
        self.scope.bind("<Button-4>", lambda e: self._on_scope_wheel_linux(1))  # Linux, arriba
        self.scope.bind("<Button-5>", lambda e: self._on_scope_wheel_linux(-1))  # Linux, abajo

    def _hz_per_pixel(self) -> float:
        lo, hi = self._current_range
        width = max(1, self.scope.winfo_width())
        return (hi - lo) / width

    def _current_radio_freq(self) -> int:
        return int(getattr(self.engine.radio, "frequency_hz", 0) or 0)

    def _retune(self, hz: int) -> None:
        set_freq = getattr(self.engine.radio, "set_frequency", None)
        _log.debug("retune hz=%s set_freq_disponible=%s", hz, set_freq is not None)
        if set_freq is None:
            return
        with contextlib.suppress(Exception):
            set_freq(hz, source="rtty")

    def _on_scope_press(self, event: tk.Event) -> None:
        self._drag_start_x = event.x
        self._drag_base_freq = self._current_radio_freq()
        _log.debug("scope press x=%s base_freq=%s", event.x, self._drag_base_freq)

    def _on_scope_drag(self, event: tk.Event) -> None:
        if self._drag_start_x is None or self._drag_base_freq is None:
            return
        now = time.monotonic()
        if now - self._last_cat_update < _CAT_RETUNE_THROTTLE_SEC:
            return
        self._last_cat_update = now
        dx = event.x - self._drag_start_x
        # Arrastrar a la derecha "empuja" el espectro -> sube la frecuencia.
        delta_hz = int(round(dx * self._hz_per_pixel()))
        _log.debug("scope drag x=%s dx=%s delta_hz=%s", event.x, dx, delta_hz)
        self._retune(self._drag_base_freq + delta_hz)

    def _on_scope_release(self, event: tk.Event) -> None:
        if self._drag_start_x is None or self._drag_base_freq is None:
            _log.debug("scope release IGNORADO: no hubo press previo registrado")
            return
        dx = event.x - self._drag_start_x
        _log.debug(
            "scope release x=%s start_x=%s dx=%s umbral=%s -> rama=%s",
            event.x, self._drag_start_x, dx, _CLICK_MAX_DRAG_PX,
            "clic" if abs(dx) <= _CLICK_MAX_DRAG_PX else "arrastre",
        )
        if abs(dx) <= _CLICK_MAX_DRAG_PX:
            # Clic sin arrastre real: NO toca el CAT -- solo elige qué señal
            # estrecha decodificar DENTRO de la pasabanda ya sintonizada,
            # igual que un clic en la cascada de WSJT-X deja el dial del
            # equipo donde estaba (p. ej. 7.074) y solo cambia qué se
            # decodifica dentro del ancho de banda. Antes esto mandaba un
            # SET_FREQ por CAT para "traer" la señal hasta las marcas fijas
            # -- eso movía el VFO real del uSDX sin que nadie lo hubiera
            # pedido para esta acción (el arrastre sí retunea, a propósito,
            # como barrido de búsqueda; el clic no).
            lo, hi = self._current_range
            width = max(1, self.scope.winfo_width())
            clicked_hz = lo + (event.x / width) * (hi - lo)
            center = self._resolve_click_center(clicked_hz)
            key = self.engine.lock_signal(center)
            self._refresh_signals()
            self._select_key(key)
            self.manual_freq_var.set(f"{center:.0f}")
            _log.debug(
                "scope click: clicked_hz=%.1f -> centro resuelto=%.1f Hz (key=%s, CAT sin tocar)",
                clicked_hz, center, key,
            )
        else:
            delta_hz = int(round(dx * self._hz_per_pixel()))
            self._retune(self._drag_base_freq + delta_hz)  # último valor, sin throttle
        self._drag_start_x = None
        self._drag_base_freq = None

    def _resolve_click_center(self, clicked_hz: float) -> float:
        """A partir de dónde se hizo clic, decide el CENTRO real
        ``(mark+space)/2`` de la señal a decodificar -- usando el propio
        detector de picos de la app (el mismo del auto-scan) para enganchar
        en el pico real aunque el clic no haya caído justo encima, en vez de
        fiarse a ciegas del pixel pulsado. Si todavía no hay ningún pico
        detectable ahí (señal débil / auto-scan no ha pasado por ahí),
        asume que se pinchó la cresta grave (space, la de la izquierda) --
        la convención que describió el operador."""
        half = self.engine.shift_hz / 2.0
        samples = self.engine.last_samples
        if samples is not None and samples.size >= 256:
            candidates = find_signal_candidates(
                samples, self.engine.sample_rate, shift_hz=self.engine.shift_hz
            )

            def distance(center: float) -> float:
                return min(abs(center - half - clicked_hz), abs(center + half - clicked_hz))

            if candidates:
                best = min(candidates, key=distance)
                if distance(best) <= _CLICK_SNAP_TOLERANCE_HZ:
                    return best
        return clicked_hz + half

    def _on_scope_wheel(self, event: tk.Event) -> None:
        step = _WHEEL_STEP_HZ if event.delta > 0 else -_WHEEL_STEP_HZ
        self._retune(self._current_radio_freq() + step)

    def _on_scope_wheel_linux(self, direction: int) -> None:
        self._retune(self._current_radio_freq() + direction * _WHEEL_STEP_HZ)

    def _toggle_auto_scan(self) -> None:
        self.engine.auto_scan = bool(self.auto_scan_var.get())

    def _toggle_afc(self) -> None:
        self.engine.afc = bool(self.afc_var.get())

    def _toggle_rev(self) -> None:
        self.engine.rx_reverse = bool(self.rev_var.get())

    def _apply_my_zone(self, *, persist: bool = True) -> None:
        """Recompone el exchange a enviar ("599 <zona> <zona>") a partir de
        "Mi zona CQ" -- pero solo si el campo Exchange todavía tiene el valor
        por defecto o el generado la vez anterior, para no pisar algo que
        el operador haya escrito a mano para un QSO concreto."""
        zone = self.my_zone_var.get().strip()
        auto_value = exchange_to_send(zone)
        current = self.exchange_var.get().strip()
        if current in ("", "599", getattr(self, "_auto_exchange_value", "599")):
            self.exchange_var.set(auto_value)
        self._auto_exchange_value = auto_value
        if persist:
            self._save_geometry()

    def _lock_manual(self) -> None:
        try:
            freq = float(self.manual_freq_var.get())
        except ValueError:
            self.status_var.set("Frecuencia manual inválida.")
            return
        key = self.engine.lock_signal(freq)
        self._refresh_signals()
        self._select_key(key)
        self._zoom_active = True

    def _toggle_zoom_wide(self) -> None:
        # Botón "Vista ancha": vuelve a ver toda la pasabanda para buscar,
        # sin perder la señal seleccionada/enganchada (solo deja de hacer
        # zoom en ella hasta que el operador vuelva a pedirlo).
        self._zoom_active = False

    # ---- señales detectadas -------------------------------------------- #
    def _refresh_signals(self) -> None:
        self.listbox.delete(0, "end")
        self._rows.clear()
        signals = sorted(self.engine.signals.items(), key=lambda kv: kv[1].center_hz)
        selected_row = None
        for i, (key, sig) in enumerate(signals):
            tag = "🔒" if sig.locked else " "
            tail = sig.text[-40:].replace("\n", " ").replace("\r", " ")
            self.listbox.insert("end", f"{tag} {sig.center_hz:6.0f} Hz | {tail}")
            self._rows[i] = key
            if key == self._selected_key:
                selected_row = i
        if selected_row is not None:
            self.listbox.selection_set(selected_row)
        elif self._selected_key is not None and self._selected_key not in self.engine.signals:
            self._selected_key = None

        if self._selected_key is not None:
            self._append_selected_text()
        elif signals:
            # nada seleccionado todavía: sigue automáticamente la más nueva
            self._select_key(signals[-1][0])

    def _on_select_signal(self, _event: object) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        key = self._rows.get(selection[0])
        if key is not None:
            self._select_key(key)
            self._zoom_active = True  # clic real del operador: aquí sí hace zoom

    def _on_take_call(self, _event: object) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        key = self._rows.get(selection[0])
        sig = self.engine.signals.get(key) if key is not None else None
        if sig is None:
            return
        caller = cq_caller(sig.text, self.my_call)
        if caller is not None:
            self._reply_to_call(caller, calling_cq=True)
            return
        calls = [m.group(0) for m in CALL_RE.finditer(sig.text.upper()) if m.group(0) != self.my_call]
        if calls:
            self._reply_to_call(calls[-1], calling_cq=False)

    def _select_key(self, key: int) -> None:
        self._selected_key = key
        sig = self.engine.signals.get(key)
        if sig is not None:
            # Marcas/zoom siguen a la señal de verdad seleccionada (lista,
            # "Enganchar" o clic en la cascada) -- ver _decode_center_hz.
            self._decode_center_hz = sig.center_hz
        self.rx_text.configure(state="normal")
        self.rx_text.delete("1.0", "end")
        self.rx_text.configure(state="disabled")
        self._displayed_len[key] = 0
        self.received_exchange_var.set("")
        if sig is not None:
            self._append_selected_text()

    def _append_selected_text(self) -> None:
        key = self._selected_key
        if key is None:
            return
        sig = self.engine.signals.get(key)
        if sig is None:
            return
        shown = self._displayed_len.get(key, 0)
        new_text = sig.text[shown:]
        if not new_text:
            return
        self._displayed_len[key] = len(sig.text)
        self.rx_text.configure(state="normal")
        self.rx_text.insert("end", _strip_control_chars(new_text))
        self._log_rx_text(sig.center_hz, new_text)
        self.rx_text.see("end")
        self.rx_text.configure(state="disabled")
        self._retag_calls(full=False)
        if self._sp_call is not None and not self.engine.transmitting:
            # Lo decodificado mientras transmitimos no cuenta (puede ser
            # nuestra propia señal): solo lo que llega después.
            self._sp_text += new_text
            self._sp_last_rx = time.monotonic()
            self._continue_sp()
        self._update_received_exchange(sig.text)

    def _continue_sp(self) -> None:
        """Tras responder a un CQ: si esa estación ya nos ha dado su
        intercambio ("EA1ABC 599 05 05") y ha terminado de transmitir, se
        apunta y se le envía el nuestro sin esperar a que el operador pulse
        nada. En concurso hace falta su zona, no basta el RST."""
        if self._sp_call is None:
            return
        contest = bool(split_exchange(self.exchange_var.get()).zone)
        exchange = find_reply_exchange(self._sp_text, self.my_call, require_zone=contest)
        if exchange is None:
            return
        if time.monotonic() - self._sp_last_rx < _SP_QUIET_SEC:
            self.status_var.set(f"{self._sp_call} te está dando su reporte ({exchange})... "
                                "se enviará el tuyo cuando termine.")
            return
        call = self._sp_call
        self._sp_call = None
        self.call_var.set(call)
        self.received_exchange_var.set(str(exchange))
        self._exchange_locked_call = call
        _log.info("S&P: %s nos da %s -> enviamos nuestro intercambio", call, exchange)
        if self._send_exchange():
            self._set_phase(call, "report_tx")
            self._status_with_next(call, f"{call} te da {exchange}: enviado tu reporte.")

    def _check_sp_timeout(self) -> None:
        if self._sp_call is None or self.engine.transmitting:
            return
        self._continue_sp()  # su reporte llegó y ya ha dejado de transmitir?
        if self._sp_call is None:
            return
        now = time.monotonic()
        if self._sp_deadline is None:
            self._sp_deadline = now + _SP_REPLY_TIMEOUT_SEC
        elif now > self._sp_deadline:
            self.status_var.set(f"{self._sp_call} no te ha contestado. Doble clic para volver a llamarle.")
            self._sp_call = None

    def _copy_rx_selection(self, *, everything: bool = False) -> str:
        try:
            text = self.rx_text.get("1.0", "end-1c") if everything else self.rx_text.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"  # nada seleccionado
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set(f"Copiado al portapapeles ({len(text)} caracteres).")
        return "break"

    def _log_rx_text(self, center_hz: float, text: str) -> None:
        """Lo decodificado queda también en el registro, por líneas y con la
        hora, para poder revisar un QSO después (qué te dijeron, no solo lo
        que transmitiste)."""
        self._rx_log_buf += _strip_control_chars(text)
        while "\n" in self._rx_log_buf:
            line, self._rx_log_buf = self._rx_log_buf.split("\n", 1)
            if line.strip():
                _log.info("RX %.0f Hz: %s", center_hz, line)
        if len(self._rx_log_buf) > 120:
            _log.info("RX %.0f Hz: %s", center_hz, self._rx_log_buf)
            self._rx_log_buf = ""

    def _update_received_exchange(self, text: str) -> None:
        """Heurística: coge el ÚLTIMO "RST + zona" que aparece en el texto
        decodificado de la señal actual (más probable que sea el exchange
        de verdad que uno anterior de otra estación). No sustituye
        comprobar contra el texto -- por eso se deja editable."""
        if self._exchange_locked_call and self.call_var.get().strip().upper() == self._exchange_locked_call:
            return  # ya se sacó de su respuesta directa: no pisarlo
        exchange = parse_exchange(text)
        if exchange is not None:
            self.received_exchange_var.set(str(exchange))

    def _schedule_retag(self) -> None:
        # Al teclear en CALL: un solo recoloreado cuando se deja de teclear.
        if self._retag_job is not None:
            self.after_cancel(self._retag_job)
        self._retag_job = self.after(150, self._retag_calls)

    def _call_tag(self, call: str, band: str, current: str) -> str:
        if call == self.my_call:
            return "call_mine"
        if call == current:
            return "call_current"
        if self._worked.is_worked(call, band):
            return "call_dupe"
        return "call_new"

    def _retag_calls(self, full: bool = True) -> None:
        """Colorea los indicativos del texto recibido (nunca los de lo que
        tú transmites, en azul). ``full=False`` solo repasa la cola: un
        indicativo puede llegar partido entre dos trozos decodificados."""
        self._retag_job = None
        start = self.rx_text.index("1.0" if full else f"end-{_RETAG_TAIL_CHARS}c")
        for tag in _CALL_TAGS:
            self.rx_text.tag_remove(tag, start, "end")
        content = self.rx_text.get(start, "end").upper()
        band = self._current_band()
        current = self.call_var.get().strip().upper()
        for match in CALL_RE.finditer(content):
            first = f"{start}+{match.start()}c"
            if "tx" in self.rx_text.tag_names(first):
                continue
            tag = self._call_tag(match.group(0), band, current)
            self.rx_text.tag_add(tag, first, f"{start}+{match.end()}c")

    def _on_rx_double_click(self, event: tk.Event) -> str:
        """Doble clic sobre un indicativo del texto recibido."""
        index = self.rx_text.index(f"@{event.x},{event.y}")
        if "tx" in self.rx_text.tag_names(index):
            return "break"
        line_start = self.rx_text.index(f"{index} linestart")
        column = int(index.split(".")[1])
        line = self.rx_text.get(line_start, f"{index} lineend").upper()
        match = next((m for m in CALL_RE.finditer(line) if m.start() <= column < m.end()), None)
        if match is None or match.group(0) == self.my_call:
            return "break"
        call_start = f"{line_start}+{match.start()}c"
        call_end = f"{line_start}+{match.end()}c"
        before = self._received_only(f"{call_start}-{CQ_LOOKBACK_CHARS}c", call_start)
        around = before + self._received_only(call_start, f"{call_end}+{CQ_LOOKAHEAD_CHARS}c")
        calling = is_calling_cq(around, len(before), len(before) + len(match.group(0)))
        _log.info("doble clic en %s: llamando=%s contexto=%r", match.group(0), calling, around)
        self._reply_to_call(match.group(0), calling_cq=calling)
        return "break"

    def _received_only(self, start: str, end: str) -> str:
        """Texto entre ``start`` y ``end`` con lo que TÚ has transmitido
        (líneas [TX] en azul) cambiado por espacios: si no, tras tu "TU
        EA0XXX TEST" la estación que te contesta parecía estar llamando CQ
        (el TEST era tuyo) y se le respondía con tu indicativo en vez de con
        el reporte."""
        first = self.rx_text.index(start)
        text = self.rx_text.get(first, end)
        return "".join(
            " " if "tx" in self.rx_text.tag_names(f"{first}+{i}c") else ch for i, ch in enumerate(text)
        )

    def _reply_to_call(self, call: str, *, calling_cq: bool) -> None:
        """Pone el indicativo en CALL y, si está llamando CQ, le responde
        con tu indicativo dos veces (lo normal en concurso). Si no llama CQ
        (o ya está trabajado en esta banda) NO transmite nada: un doble clic
        por error no debe salir al aire."""
        self.call_var.set(call)
        band = self._current_band()
        if not calling_cq:
            self.status_var.set(
                f"CALL = {call} (no está llamando CQ/TEST: no se transmite nada; pulsa Llamar para contestarle)."
            )
            return
        if self._worked.is_worked(call, band):
            self.status_var.set(f"{call} ya trabajado en {band or 'esta banda'}: duplicado, no se transmite.")
            return
        if not self.my_call:
            self.status_var.set('Falta "Mi indicativo" en Ajustes -> Interfaz.')
            return
        if not self._send(cq_answer(self.my_call)):
            return  # _send ya dejó en la barra de estado por qué no se transmitió
        # A la espera de que nos conteste con su intercambio (_continue_sp).
        self._sp_call = call
        self._sp_text = ""
        self._sp_deadline = None
        self._exchange_locked_call = None
        self._set_phase(call, "called")
        status = f"Respondiendo al CQ de {call}."
        if not is_contest_band(band):
            status += f" Ojo: {band or 'esta banda'} no cuenta en el CQ WW RTTY."
        self._status_with_next(call, status)

    def _current_band(self) -> str:
        return band_from_freq_hz(self._current_radio_freq())

    def _load_worked(self) -> WorkedLog:
        try:
            return WorkedLog.from_json(json.loads(_WORKED_LOG_PATH.read_text(encoding="utf-8")))
        except Exception:
            return WorkedLog()

    def _save_worked(self) -> None:
        try:
            _WORKED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _WORKED_LOG_PATH.write_text(json.dumps(self._worked.to_json()), encoding="utf-8")
        except Exception:
            _log.exception("no se pudo guardar la lista de trabajados RTTY")

    def _clear_rx(self) -> None:
        self.rx_text.configure(state="normal")
        self.rx_text.delete("1.0", "end")
        self.rx_text.configure(state="disabled")
        if self._selected_key is not None:
            sig = self.engine.signals.get(self._selected_key)
            if sig is not None:
                self._displayed_len[self._selected_key] = len(sig.text)

    # ---- TX -------------------------------------------------------------#
    def _current_tx_center(self) -> float:
        if self._selected_key is not None:
            sig = self.engine.signals.get(self._selected_key)
            if sig is not None:
                return sig.center_hz
        try:
            return float(self.manual_freq_var.get())
        except ValueError:
            return self._filter_center()

    def _abort_tx(self) -> None:
        if self.engine.transmitting:
            self.engine.abort_tx()
            self.status_var.set("TX cortada (Esc).")

    def _send(self, text: str) -> bool:
        ok = self.engine.send_text(text, center_hz=self._current_tx_center())
        self.status_var.set(f"TX: {text}" if ok else "No se pudo transmitir (revisa audio/PTT).")
        if ok:
            self._append_tx_text(text)
        return ok

    def _append_tx_text(self, text: str) -> None:
        # Se inserta en la MISMA ventana que el texto recibido, en azul, para
        # poder seguir la conversación (lo que envías + lo que te responden)
        # sin tener que mirar aparte -- antes solo quedaba un aviso fugaz en
        # la barra de estado inferior, que la siguiente transmisión pisaba.
        # No hace falta tocar self._displayed_len: solo lleva la cuenta de
        # cuánto de sig.text (lo recibido) ya se mostró, independiente de
        # cualquier otra cosa insertada en el widget.
        self.rx_text.configure(state="normal")
        self.rx_text.insert("end", f"\n[TX] {text}\n", ("tx",))
        self.rx_text.see("end")
        self.rx_text.configure(state="disabled")

    def _send_free_text(self) -> None:
        text = self.tx_var.get().strip()
        if not text:
            return
        self._send(text)
        self.tx_var.set("")

    def _send_cq(self) -> None:
        # OJO: antes esto leía self.call_var (el indicativo del CORRESPONSAL,
        # el que rellena "Responder"/doble clic sobre un CQ) como si fuera el
        # tuyo propio -- vacío antes de identificar a nadie, así que salía el
        # literal "MYCALL" sin que nadie lo pidiera. self.my_call es tu
        # propio indicativo de verdad (Ajustes -> Interfaz -> "Mi indicativo").
        if not self.my_call:
            self.status_var.set('Falta "Mi indicativo" en Ajustes -> Interfaz.')
            return
        self._send(f"CQ DE {self.my_call} {self.my_call}")

    def _send_exchange(self) -> bool:
        """Botón Responder y envío automático al recibir su reporte: formato
        de concurso si Exchange lleva zona, reporte completo si no."""
        call = self.call_var.get().strip().upper()
        if not call:
            self.status_var.set("Falta el indicativo.")
            return False
        if not self.my_call:
            self.status_var.set('Falta "Mi indicativo" en Ajustes -> Interfaz.')
            return False
        return self._send(reply_text(call, self.my_call, self.exchange_var.get()))

    # ---- Responder según la fase del QSO ---------------------------------#
    def _phase(self, call: str) -> str:
        return self._qso_phase[1] if self._qso_phase[0] == call else "none"

    def _set_phase(self, call: str, phase: str) -> None:
        self._qso_phase = (call, phase)

    def _is_calling_cq(self, call: str) -> bool:
        sig = self.engine.signals.get(self._selected_key) if self._selected_key is not None else None
        return sig is not None and cq_caller(sig.text, self.my_call) == call

    def _status_with_next(self, call: str, message: str) -> None:
        """Mensaje + qué enviará el PRÓXIMO Responder, para que no haya
        sorpresas al pulsarlo."""
        text, _next = responder_step(
            self._phase(call), call=call, my_call=self.my_call,
            exchange=self.exchange_var.get(), calling_cq=False,
        )
        self.status_var.set(f"{message}  Próximo Responder: {text}")

    def _responder(self) -> None:
        """Botón Responder: envía lo que toca según la fase del QSO con el
        indicativo de CALL (contestar a su CQ, dar tu reporte, despedirte)."""
        call = self.call_var.get().strip().upper()
        if not call:
            self.status_var.set("Falta el indicativo.")
            return
        if not self.my_call:
            self.status_var.set('Falta "Mi indicativo" en Ajustes -> Interfaz.')
            return
        phase = self._phase(call)
        calling = self._is_calling_cq(call)
        if phase == "none" and calling:
            self._reply_to_call(call, calling_cq=True)  # también controla duplicados
            return
        text, new_phase = responder_step(
            phase, call=call, my_call=self.my_call, exchange=self.exchange_var.get(), calling_cq=calling,
        )
        if self._send(text):
            self._sp_call = None  # el operador ya ha avanzado: no enviar nada automático
            self._set_phase(call, new_phase)
            self._status_with_next(call, f"Enviado: {text}.")

    def _call_station(self) -> None:
        """Botón Llamar: contesta a la estación de CALL aunque su macro no
        lleve CQ/TEST (solo su indicativo), como si fuera un CQ detectado."""
        call = self.call_var.get().strip().upper()
        if not call:
            self.status_var.set("Falta el indicativo.")
            return
        self._reply_to_call(call, calling_cq=True)

    def _send_report(self) -> None:
        """Botón 599: tu reporte. Como Responder, sigue lo que haya en
        Exchange: con zona, formato de concurso ("IB9R 599 14 14"); sin
        zona, QSO normal ("IB9R DE EA0XXX 599 599"). Antes mandaba siempre
        el normal, y en concurso salía sin zona."""
        call = self.call_var.get().strip().upper()
        if not call:
            self.status_var.set("Falta el indicativo.")
            return
        if not self.my_call:
            self.status_var.set('Falta "Mi indicativo" en Ajustes -> Interfaz.')
            return
        if self._send(reply_text(call, self.my_call, self.exchange_var.get())):
            self._set_phase(call, "report_tx")
            self._status_with_next(call, f"Enviado tu reporte a {call}.")

    def _send_tu(self) -> None:
        # En concurso el TU también vuelve a llamar: "TU EA1ABC TEST" da las
        # gracias y deja claro quién está en la frecuencia para el siguiente.
        if not self.my_call:
            self.status_var.set('Falta "Mi indicativo" en Ajustes -> Interfaz.')
            return
        if self._send(f"TU {self.my_call} TEST"):
            call = self.call_var.get().strip().upper()
            if call:
                self._set_phase(call, "done")

    # ---- guardado de QSO -------------------------------------------------#
    def _open_qso_dialog(self) -> None:
        call = self.call_var.get().strip().upper()
        if not call:
            self.status_var.set("Falta el indicativo para guardar el QSO.")
            return
        sent = split_exchange(self.exchange_var.get())
        recv = split_exchange(self.received_exchange_var.get())
        freq_hz = self._current_radio_freq()
        QsoConfirmDialog(
            self,
            call=call,
            freq_hz=freq_hz,
            rst_sent=sent.rst or "599",
            zone_sent=sent.zone or self.my_zone_var.get().strip(),
            rst_recv=recv.rst or "599",
            zone_recv=recv.zone,
            qth_recv=recv.qth,
            on_save=self._save_qso,
        )

    def _save_qso(self, data: dict[str, str]) -> None:
        try:
            freq_hz = float(data.get("freq_hz") or 0)
        except ValueError:
            freq_hz = 0.0
        adif = build_qso_adif(
            call=data["call"],
            band=data.get("band", ""),
            freq_hz=freq_hz,
            rst_sent=data.get("rst_sent") or "599",
            rst_recv=data.get("rst_recv") or "599",
            zone_sent=data.get("zone_sent", ""),
            zone_recv=data.get("zone_recv", ""),
            qth_recv=data.get("qth_recv", ""),
            my_call=self.my_call,
            notes=data.get("notes", ""),
        )
        packet = build_wsjtx_logged_adif_packet(adif)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.sendto(packet, (_LOG_UDP_HOST, _LOG_UDP_PORT))
            finally:
                sock.close()
        except OSError as exc:
            self.status_var.set(f"No se pudo mandar el QSO al log: {exc}")
            return
        call = data["call"]
        band = data.get("band") or self._current_band()
        self._worked.add(call, band)
        self._save_worked()
        self._retag_calls()
        status = f"QSO {call} enviado al libro de guardia (UDP {_LOG_UDP_HOST}:{_LOG_UDP_PORT})."
        if not is_contest_band(band):
            status += f" Ojo: {band or 'esta banda'} no cuenta en el CQ WW RTTY (solo 80/40/20/15/10 m)."
        self.status_var.set(status)

    # ---- cierre ---------------------------------------------------------#
    def _close(self) -> None:
        for job in (self._tick_job, self._scope_job, self._geometry_correction_job, self._retag_job):
            if job is not None:
                self.after_cancel(job)
        self._tick_job = None
        self._scope_job = None
        self._geometry_correction_job = None
        self._save_geometry()
        self.engine.on_signal_update = None
        if self._on_close is not None:
            self._on_close()
        self.destroy()


class QsoConfirmDialog(tk.Toplevel):
    """Ventana modal con los datos del QSO antes de guardarlo -- nada se
    manda al libro de guardia sin que el operador pulse "Guardar contacto"
    (o "Cancelar" para no guardar nada), y todos los campos son editables
    porque las heurísticas de arriba (exchange recibido, banda por
    frecuencia...) pueden equivocarse."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        call: str,
        freq_hz: int,
        rst_sent: str,
        zone_sent: str,
        rst_recv: str,
        zone_recv: str,
        qth_recv: str = "",
        on_save: Callable[[dict[str, str]], None],
    ) -> None:
        super().__init__(master, class_="PoorSDR4All")
        self.title("Guardar QSO")
        self.configure(bg=_BG)
        self.transient(master)
        self._on_save = on_save

        self.call_var = tk.StringVar(value=call)
        self.band_var = tk.StringVar(value=band_from_freq_hz(freq_hz))
        self.freq_var = tk.StringVar(value=str(freq_hz))
        self.rst_sent_var = tk.StringVar(value=rst_sent)
        self.zone_sent_var = tk.StringVar(value=zone_sent)
        self.rst_recv_var = tk.StringVar(value=rst_recv)
        self.zone_recv_var = tk.StringVar(value=zone_recv)
        # CQ WW RTTY: solo EE.UU. continental y Canadá mandan estado/provincia.
        self.qth_recv_var = tk.StringVar(value=qth_recv)
        self.notes_var = tk.StringVar(value="")

        rows: list[tuple[str, tk.StringVar]] = [
            ("Indicativo:", self.call_var),
            ("Banda:", self.band_var),
            ("Frecuencia (Hz):", self.freq_var),
            ("RST enviado:", self.rst_sent_var),
            ("Zona CQ enviada:", self.zone_sent_var),
            ("RST recibido:", self.rst_recv_var),
            ("Zona CQ recibida:", self.zone_recv_var),
            ("QTH EE.UU./Canadá:", self.qth_recv_var),
            ("Notas:", self.notes_var),
        ]
        body = tk.Frame(self, bg=_BG)
        body.pack(padx=10, pady=10)
        for i, (label, var) in enumerate(rows):
            tk.Label(body, text=label, bg=_BG, fg=_FG).grid(row=i, column=0, sticky="w", pady=2)
            tk.Entry(body, textvariable=var, width=24, bg=_PANEL, fg=_FG, insertbackground=_FG).grid(
                row=i, column=1, padx=(6, 0), pady=2
            )

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, bg=_BG, fg=_DIM, anchor="w").pack(
            fill="x", padx=10
        )

        btns = tk.Frame(self, bg=_BG)
        btns.pack(fill="x", padx=10, pady=(4, 10))
        tk.Button(btns, text="Cancelar", command=self.destroy, bg=_PANEL, fg=_FG).pack(
            side="right", padx=(6, 0)
        )
        tk.Button(btns, text="Guardar contacto", command=self._save, bg=_PANEL, fg=_FG).pack(side="right")

        self.grab_set()
        self.resizable(False, False)

    def _save(self) -> None:
        call = self.call_var.get().strip().upper()
        if not call:
            self.status_var.set("Falta el indicativo.")
            return
        data = {
            "call": call,
            "band": self.band_var.get().strip(),
            "freq_hz": self.freq_var.get().strip(),
            "rst_sent": self.rst_sent_var.get().strip(),
            "zone_sent": self.zone_sent_var.get().strip(),
            "rst_recv": self.rst_recv_var.get().strip(),
            "zone_recv": self.zone_recv_var.get().strip(),
            "qth_recv": self.qth_recv_var.get().strip().upper(),
            "notes": self.notes_var.get().strip(),
        }
        self._on_save(data)
        self.destroy()


__all__ = ["RttyPanel", "QsoConfirmDialog"]
