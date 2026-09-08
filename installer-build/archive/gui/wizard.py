#!/usr/bin/env python3
"""Asistente gráfico de instalación de PoorSDR4All.

Wrapper de Tkinter (sin dependencias fuera de la biblioteca estándar) que
guía al usuario por las pantallas típicas de un instalador —logo, licencia
con casilla de aceptación, opciones, progreso, fin— y por debajo ejecuta
literalmente ``scripts/install.sh`` del propio proyecto: este asistente NO
reimplementa la instalación, solo le pone una cara amigable y desatendida.

OpenWebRX+ y su pila (csdr, pycsdr, owrx_connector) son GPL/AGPL y el
proyecto nunca distribuye binarios de eso: install.sh los clona en
revisiones fijadas y los compila EN EL EQUIPO DEL USUARIO. Este asistente
respeta esa misma regla al pie de la letra — solo orquesta, nunca empaqueta
binarios de terceros.

install.sh se diseñó para ejecutarse como el usuario normal (no como root):
usa `${USER}`/`${HOME}` para saber dónde viven `pip install --user`, los
grupos del sistema y el servicio `systemd --user` de spiderd, y llama a
`sudo` solo en los puntos concretos que de verdad necesitan privilegios. Por
eso este asistente NUNCA se relanza entero con pkexec/sudo (eso rompería
esos entornos): en vez de eso, le antepone al PATH un `sudo` de mentira que
delega en el real con `-A`, y fija `SUDO_ASKPASS` a `sudo_askpass.py` — cada
`sudo algo` que haga install.sh termina pidiendo la contraseña en una
ventana gráfica en vez de fallar por falta de terminal.
"""

from __future__ import annotations

import argparse
import os
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk

GUI_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(GUI_DIR, "assets", "sdrlogo.png")
ASKPASS_PATH = os.path.join(GUI_DIR, "sudo_askpass.py")

WINDOW_TITLE = "Instalador de PoorSDR4All"
WINDOW_SIZE = "760x560"


# --------------------------------------------------------------------------- #
# Detección de sistema — el mismo criterio que scripts/install.sh:detect_os(),
# reimplementado aquí en Python porque el asistente necesita decidir ANTES de
# lanzar el script si merece la pena seguir (y explicarlo con una pantalla,
# no con un `die` de bash que el usuario nunca llega a ver).
# --------------------------------------------------------------------------- #
def detect_os() -> tuple[str | None, str]:
    """Devuelve (familia, nombre_bonito). familia es 'arch', 'debian' o None."""
    path = "/etc/os-release"
    info: dict[str, str] = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                info[key] = value.strip().strip('"')

    ident = info.get("ID", "")
    like = info.get("ID_LIKE", "")
    pretty = info.get("PRETTY_NAME", ident or "Desconocido")

    if ident == "arch" or "arch" in like:
        return "arch", pretty
    if ident in ("debian", "ubuntu") or "debian" in like:
        return "debian", pretty
    return None, pretty


# --------------------------------------------------------------------------- #
# Estado compartido entre pantallas
# --------------------------------------------------------------------------- #
class InstallerState:
    def __init__(self, payload_dir: str) -> None:
        self.payload_dir = payload_dir
        self.os_family: str | None = None
        self.os_pretty = ""

        # Casillas de la pantalla de componentes -> variables de entorno
        # que ya entiende scripts/install.sh (mismos nombres, mismo significado).
        # Los plugins van totalmente aparte de este instalador: no se
        # incluyen, no se instalan y no se mencionan aquí.
        self.install_owrx = True          # SKIP_OWRX_BUILD = no install_owrx
        self.install_spots = True         # SKIP_SPIDER = no install_spots
        self.install_web_extras = True    # INSTALL_WEB_EXTRAS

        self.launch_after = True

        self.log_lines: list[str] = []
        self.exit_code: int | None = None
        self.process: subprocess.Popen | None = None
        self.cancelled = False


# --------------------------------------------------------------------------- #
# Ejecución real: scripts/install.sh con sudo redirigido a una ventana gráfica
# --------------------------------------------------------------------------- #
def build_sudo_shim(shim_dir: str) -> None:
    """Escribe en shim_dir/sudo un envoltorio que fuerza `sudo -A` (pide la
    contraseña por SUDO_ASKPASS) sin importar si hay o no terminal de
    control. install.sh sigue llamando a `sudo` tal cual — no se toca ni una
    línea del script del proyecto."""
    real_sudo = shutil.which("sudo")
    if not real_sudo:
        raise RuntimeError("No se encontró 'sudo' en el sistema.")
    shim_path = os.path.join(shim_dir, "sudo")
    with open(shim_path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n")
        fh.write(f'exec {shlex.quote(real_sudo)} -A "$@"\n')
    os.chmod(shim_path, 0o755)


def run_install(state: InstallerState, log_queue: "queue.Queue[str]") -> int:
    """Lanza scripts/install.sh con las variables de entorno de las casillas
    elegidas y vuelca su salida línea a línea en log_queue. Devuelve el
    código de salida del proceso (0 = éxito)."""
    install_sh = os.path.join(state.payload_dir, "scripts", "install.sh")
    if not os.path.isfile(install_sh):
        log_queue.put(f"ERROR: no se encontró {install_sh}\n")
        return 1

    shim_dir = tempfile.mkdtemp(prefix="poorsdr-installer-sudo-")
    try:
        build_sudo_shim(shim_dir)
    except RuntimeError as exc:
        log_queue.put(f"ERROR: {exc}\n")
        shutil.rmtree(shim_dir, ignore_errors=True)
        return 1

    env = os.environ.copy()
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    env["SUDO_ASKPASS"] = ASKPASS_PATH
    env["SKIP_OWRX_BUILD"] = "0" if state.install_owrx else "1"
    env["SKIP_SPIDER"] = "0" if state.install_spots else "1"
    env["INSTALL_WEB_EXTRAS"] = "1" if state.install_web_extras else "0"

    log_queue.put(f"==> Ejecutando {install_sh}\n")
    try:
        proc = subprocess.Popen(
            ["bash", install_sh],
            cwd=state.payload_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,  # grupo de proceso propio: cancelar mata también a los hijos (pacman, cmake...)
        )
    except OSError as exc:
        log_queue.put(f"ERROR: no se pudo lanzar install.sh: {exc}\n")
        shutil.rmtree(shim_dir, ignore_errors=True)
        return 1

    state.process = proc
    assert proc.stdout is not None
    for line in proc.stdout:
        log_queue.put(line)
    proc.wait()
    shutil.rmtree(shim_dir, ignore_errors=True)
    return proc.returncode


def run_post_steps(state: InstallerState, log_queue: "queue.Queue[str]") -> bool:
    """Pasos que install.sh no hace por sí mismo: solo el lanzador de
    escritorio. Devuelve False si algo falla."""
    log_queue.put("==> Creando el lanzador de escritorio...\n")
    try:
        create_desktop_entry()
    except OSError as exc:
        log_queue.put(f"AVISO: no se pudo crear el lanzador de escritorio: {exc}\n")

    return True


def create_desktop_entry() -> None:
    """Icono + entrada .desktop apuntando al script instalado por pip
    (~/.local/bin/poorsdr), que es lo que deja `install_poorsdr_python_deps`
    en install.sh. No depende de que el payload extraído siga existiendo."""
    home = os.path.expanduser("~")
    exec_path = os.path.join(home, ".local", "bin", "poorsdr")

    icon_dir = os.path.join(home, ".local", "share", "poorsdr4all-installer")
    os.makedirs(icon_dir, exist_ok=True)
    icon_path = os.path.join(icon_dir, "poorsdr4all.png")
    if os.path.isfile(LOGO_PATH):
        shutil.copyfile(LOGO_PATH, icon_path)
    else:
        icon_path = "utilities-terminal"  # icono genérico de repuesto

    apps_dir = os.path.join(home, ".local", "share", "applications")
    os.makedirs(apps_dir, exist_ok=True)
    desktop_path = os.path.join(apps_dir, "poorsdr4all.desktop")
    with open(desktop_path, "w", encoding="utf-8") as fh:
        fh.write(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=PoorSDR4All\n"
            "Comment=Consola de operación de radio (Acuántico Power)\n"
            f"Exec={exec_path}\n"
            f"Icon={icon_path}\n"
            "Terminal=false\n"
            "Categories=HamRadio;Utility;\n"
            "StartupNotify=true\n"
        )
    os.chmod(desktop_path, 0o755)

    # Sin esto, confirmado en real: el menú de aplicaciones (KDE Plasma) no
    # siempre recoge el .desktop nuevo por sí solo hasta el próximo inicio
    # de sesión — el lanzador queda creado y ya es funcional (se puede
    # lanzar con `gtk-launch poorsdr4all`) pero no aparece al buscarlo hasta
    # que algo fuerza la reconstrucción de la caché. Se intentan las
    # variantes de KDE y la genérica; el fallo de cualquiera de ellas (p.
    # ej. un escritorio sin KDE) no es un error, solo no aplica aquí.
    for cmd in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(cmd):
            subprocess.run([cmd, "--noincremental"], capture_output=True, check=False)
    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", apps_dir], capture_output=True, check=False
        )


def launch_poorsdr() -> None:
    exec_path = os.path.join(os.path.expanduser("~"), ".local", "bin", "poorsdr")
    if os.path.isfile(exec_path):
        subprocess.Popen([exec_path], start_new_session=True)
    else:
        python_bin = shutil.which("python3") or shutil.which("python")
        if python_bin:
            subprocess.Popen([python_bin, "-m", "poorsdr"], start_new_session=True)


# --------------------------------------------------------------------------- #
# Interfaz: una ventana, páginas intercambiables, barra de botones fija
# --------------------------------------------------------------------------- #
class WizardApp(tk.Tk):
    def __init__(self, state: InstallerState) -> None:
        super().__init__()
        self.state_ = state
        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(680, 480)
        self.logo_image = self._load_logo()

        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)

        bar = tk.Frame(self, padx=16, pady=12)
        bar.pack(fill="x", side="bottom")
        self.btn_cancel = ttk.Button(bar, text="Cancelar", command=self._on_cancel)
        self.btn_cancel.pack(side="left")
        self.btn_next = ttk.Button(bar, text="Siguiente", command=self._on_next)
        self.btn_next.pack(side="right")
        self.btn_back = ttk.Button(bar, text="Atrás", command=self._on_back)
        self.btn_back.pack(side="right", padx=(0, 8))

        self.pages = [
            WelcomePage(self),
            LicensePage(self),
            SystemCheckPage(self),
            ComponentsPage(self),
            SummaryPage(self),
            ProgressPage(self),
            FinishPage(self),
        ]
        self.index = 0
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._show(0)

    # -- logo, reescalado sin depender de Pillow ----------------------- #
    def _load_logo(self, target_width: int = 420) -> tk.PhotoImage | None:
        if not os.path.isfile(LOGO_PATH):
            return None
        try:
            img = tk.PhotoImage(file=LOGO_PATH)
        except tk.TclError:
            return None
        factor = max(1, img.width() // target_width)
        if factor > 1:
            img = img.subsample(factor, factor)
        return img

    # -- navegación ------------------------------------------------------ #
    def _show(self, index: int) -> None:
        for page in self.pages:
            page.pack_forget()
        page = self.pages[index]
        page.pack(fill="both", expand=True)
        page.on_show()
        self.index = index
        self.btn_back.configure(state="normal" if page.allow_back else "disabled")
        self.btn_next.configure(text=page.next_label, state="normal" if page.can_advance() else "disabled")
        self.btn_cancel.configure(state="normal" if page.allow_cancel else "disabled")

    def refresh_nav(self) -> None:
        page = self.pages[self.index]
        self.btn_next.configure(state="normal" if page.can_advance() else "disabled")

    def _on_next(self) -> None:
        page = self.pages[self.index]
        if not page.can_advance():
            return
        proceed = page.on_leave_forward()
        if proceed is False:
            return
        if self.index + 1 < len(self.pages):
            self._show(self.index + 1)

    def _on_back(self) -> None:
        if self.index > 0:
            self._show(self.index - 1)

    def _on_cancel(self) -> None:
        page = self.pages[self.index]
        if isinstance(page, ProgressPage) and page.running:
            if not messagebox.askyesno(
                "Cancelar instalación",
                "La instalación está en curso. Cancelarla ahora puede dejar "
                "componentes a medio instalar.\n\n¿Cancelar de todas formas?",
            ):
                return
            page.cancel_install()
        self.destroy()


class WizardPage(tk.Frame):
    """Página base: cada pantalla concreta hereda de aquí."""

    next_label = "Siguiente"
    allow_back = True
    allow_cancel = True

    def __init__(self, app: WizardApp) -> None:
        super().__init__(app.container, padx=24, pady=20)
        self.app = app
        self.state_ = app.state_

    def on_show(self) -> None:
        """Se llama cada vez que la página se hace visible."""

    def can_advance(self) -> bool:
        return True

    def on_leave_forward(self):
        """Se llama al pulsar Siguiente, antes de cambiar de página.
        Devolver False cancela el avance."""
        return True


# --------------------------------------------------------------------------- #
# 1. Bienvenida
# --------------------------------------------------------------------------- #
class WelcomePage(WizardPage):
    allow_back = False

    def __init__(self, app: WizardApp) -> None:
        super().__init__(app)
        if app.logo_image is not None:
            tk.Label(self, image=app.logo_image).pack(pady=(10, 20))
        tk.Label(
            self, text=WINDOW_TITLE, font=("TkDefaultFont", 16, "bold")
        ).pack()
        tk.Label(
            self,
            justify="left",
            wraplength=640,
            text=(
                "\nEste asistente instala PoorSDR4All: consola de operación de "
                "radio, control CAT, cascada SDR (OpenWebRX+), modos digitales, "
                "servidor web remoto y macros de llamada.\n\n"
                "OpenWebRX+ y su pila (csdr, pycsdr, owrx_connector) son software "
                "de terceros con licencia GPL/AGPL: este instalador NO trae "
                "binarios de eso, los descarga y compila en tu propio equipo "
                "durante la instalación, tal y como exige su licencia.\n\n"
                "Pulsa Siguiente para continuar."
            ),
        ).pack(pady=(4, 0))


# --------------------------------------------------------------------------- #
# 2. Licencia + casilla de aceptación
# --------------------------------------------------------------------------- #
class LicensePage(WizardPage):
    def __init__(self, app: WizardApp) -> None:
        super().__init__(app)
        tk.Label(
            self, text="Acuerdo de licencia", font=("TkDefaultFont", 13, "bold")
        ).pack(anchor="w")
        tk.Label(
            self,
            justify="left",
            text="Lee los términos antes de continuar. PoorSDR4All se ofrece bajo "
                 "la PolyForm Noncommercial License 1.0.0.",
            wraplength=680,
        ).pack(anchor="w", pady=(2, 10))

        text_frame = tk.Frame(self)
        text_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        self.text = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set, height=16)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.text.yview)
        self.text.insert("1.0", self._license_text())
        self.text.configure(state="disabled")

        self.accepted = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self,
            text="He leído y acepto los términos de la licencia.",
            variable=self.accepted,
            command=self.app.refresh_nav,
        ).pack(anchor="w", pady=(10, 0))

    def _license_text(self) -> str:
        path = os.path.join(self.state_.payload_dir, "LICENSE")
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return (
                "No se encontró el fichero LICENSE junto al instalador.\n"
                "Consulta la PolyForm Noncommercial License 1.0.0 en "
                "https://polyformproject.org/licenses/noncommercial/1.0.0"
            )

    def can_advance(self) -> bool:
        return self.accepted.get()


# --------------------------------------------------------------------------- #
# 3. Comprobación del sistema
# --------------------------------------------------------------------------- #
class SystemCheckPage(WizardPage):
    def __init__(self, app: WizardApp) -> None:
        super().__init__(app)
        self.title_label = tk.Label(self, font=("TkDefaultFont", 13, "bold"))
        self.title_label.pack(anchor="w")
        self.body_label = tk.Label(self, justify="left", wraplength=680)
        self.body_label.pack(anchor="w", pady=(10, 0))
        self._checked = False

    def on_show(self) -> None:
        if self._checked:
            return
        self._checked = True
        family, pretty = detect_os()
        self.state_.os_family = family
        self.state_.os_pretty = pretty
        if family:
            self.title_label.configure(text="Sistema compatible")
            self.body_label.configure(
                text=(
                    f"Distribución detectada: {pretty}\n\n"
                    "PoorSDR4All se instalará usando scripts/install.sh, que "
                    "instala las dependencias del sistema, compila el acelerador "
                    "nativo opcional y (si lo eliges en el siguiente paso) "
                    "OpenWebRX+ desde sus fuentes oficiales.\n\n"
                    "Te pedirá la contraseña de administrador en una ventana "
                    "aparte cuando la necesite."
                )
            )
        else:
            self.title_label.configure(text="Distribución no reconocida automáticamente")
            self.body_label.configure(
                text=(
                    f"/etc/os-release indica: {pretty}\n\n"
                    "Este instalador automatiza scripts/install.sh, que hoy sabe "
                    "instalar dependencias en Arch Linux y en Debian/Ubuntu "
                    "(y derivados, incluida Raspberry Pi OS de 64 bits).\n\n"
                    "En otra distribución tendrás que instalar manualmente: "
                    "toolchain de C/C++ + cmake, libfftw3, libsamplerate, "
                    "librtlsdr, SoapySDR, Python 3 + tk, PyGObject/Gtk3 + cairo, "
                    "ffmpeg, hamlib y compilar csdr/pycsdr/owrx_connector/"
                    "openwebrx desde sus fuentes fijadas (docs/INSTALL.md).\n\n"
                    "No se puede continuar con este asistente en este sistema."
                )
            )
        self.app.refresh_nav()

    def can_advance(self) -> bool:
        return self.state_.os_family is not None


# --------------------------------------------------------------------------- #
# 4. Componentes opcionales
# --------------------------------------------------------------------------- #
class ComponentsPage(WizardPage):
    def __init__(self, app: WizardApp) -> None:
        super().__init__(app)
        tk.Label(
            self, text="Componentes a instalar", font=("TkDefaultFont", 13, "bold")
        ).pack(anchor="w")
        tk.Label(
            self,
            justify="left",
            wraplength=680,
            text="La instalación básica (consola, control CAT, audio) siempre se "
                 "hace. Elige aquí el resto:",
        ).pack(anchor="w", pady=(2, 14))

        self.var_owrx = tk.BooleanVar(value=self.state_.install_owrx)
        self.var_spots = tk.BooleanVar(value=self.state_.install_spots)
        self.var_web = tk.BooleanVar(value=self.state_.install_web_extras)

        self._check(
            self.var_owrx,
            "OpenWebRX+ y la cascada SDR (recomendado)",
            "Waterfall, espectro, S-metro y modos digitales. Se compila desde "
            "las fuentes oficiales fijadas por el proyecto — tarda varios "
            "minutos.",
        )
        self._check(
            self.var_spots,
            "Spots / DX Cluster (spiderd)",
            "Servicio en segundo plano que trae los spots por MQTT o Telnet.",
        )
        self._check(
            self.var_web,
            "Extras del servidor web remoto",
            "Solo si vas a operar desde el navegador. El servidor sigue "
            "apagado por defecto y exige contraseña antes de arrancar.",
        )

    def _check(self, var: tk.BooleanVar, title: str, desc: str) -> None:
        frame = tk.Frame(self)
        frame.pack(fill="x", pady=6, anchor="w")
        ttk.Checkbutton(frame, text=title, variable=var).pack(anchor="w")
        tk.Label(
            frame, text=desc, justify="left", wraplength=640,
            fg="#555555",
        ).pack(anchor="w", padx=(24, 0))

    def on_leave_forward(self):
        self.state_.install_owrx = self.var_owrx.get()
        self.state_.install_spots = self.var_spots.get()
        self.state_.install_web_extras = self.var_web.get()
        return True


# --------------------------------------------------------------------------- #
# 5. Resumen — último paso antes de tocar el sistema de verdad
# --------------------------------------------------------------------------- #
class SummaryPage(WizardPage):
    next_label = "Instalar"

    def __init__(self, app: WizardApp) -> None:
        super().__init__(app)
        tk.Label(
            self, text="Listo para instalar", font=("TkDefaultFont", 13, "bold")
        ).pack(anchor="w")
        self.body = tk.Label(self, justify="left", wraplength=680)
        self.body.pack(anchor="w", pady=(10, 0))

    def on_show(self) -> None:
        s = self.state_
        yes, no = "sí", "no"
        lines = [
            f"Distribución: {s.os_pretty}",
            "",
            f"· OpenWebRX+ y cascada SDR: {yes if s.install_owrx else no}",
            f"· Spots / DX Cluster: {yes if s.install_spots else no}",
            f"· Extras del servidor web remoto: {yes if s.install_web_extras else no}",
            "",
            "Se te pedirá la contraseña de administrador en una ventana aparte "
            "cuando haga falta (una o varias veces, según la operación).",
            "",
            "A partir de aquí el instalador modifica el sistema de verdad: "
            "instala paquetes, crea un usuario de sistema si eliges OpenWebRX+, "
            "y registra servicios. Pulsa Instalar para empezar.",
        ]
        self.body.configure(text="\n".join(lines))


# --------------------------------------------------------------------------- #
# 6. Progreso — ejecuta install.sh en un hilo aparte y vuelca el log
# --------------------------------------------------------------------------- #
class ProgressPage(WizardPage):
    next_label = "Siguiente"
    allow_back = False
    allow_cancel = True

    def __init__(self, app: WizardApp) -> None:
        super().__init__(app)
        self.step_label = tk.Label(self, text="Preparando…", font=("TkDefaultFont", 11, "bold"))
        self.step_label.pack(anchor="w")
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 10))

        log_frame = tk.Frame(self)
        log_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        self.log_text = tk.Text(
            log_frame, wrap="word", yscrollcommand=scrollbar.set,
            state="disabled", bg="#111111", fg="#dddddd", insertbackground="#dddddd",
            font=("monospace", 9),
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.log_text.yview)

        self.running = False
        self.started = False
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._finished_ok: bool | None = None

    def on_show(self) -> None:
        if self.started:
            return
        self.started = True
        self.running = True
        self.progress.start(12)
        self.app.btn_next.configure(state="disabled")
        threading.Thread(target=self._worker, daemon=True).start()
        self.after(150, self._poll_queue)

    def can_advance(self) -> bool:
        return not self.running and self._finished_ok is True

    def cancel_install(self) -> None:
        proc = self.state_.process
        if proc and proc.poll() is None:
            self.state_.cancelled = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass

    # -- hilo de trabajo --------------------------------------------------- #
    def _worker(self) -> None:
        code = run_install(self.state_, self._queue)
        self.state_.exit_code = code
        if code == 0 and not self.state_.cancelled:
            run_post_steps(self.state_, self._queue)
            self._queue.put("__DONE_OK__")
        else:
            self._queue.put("__DONE_FAIL__")

    def _poll_queue(self) -> None:
        try:
            while True:
                line = self._queue.get_nowait()
                if line == "__DONE_OK__":
                    self._on_finished(True)
                    return
                if line == "__DONE_FAIL__":
                    self._on_finished(False)
                    return
                self._append_log(line)
        except queue.Empty:
            pass
        if self.running:
            self.after(150, self._poll_queue)

    def _append_log(self, line: str) -> None:
        stripped = line.rstrip("\n")
        if stripped.startswith("==> "):
            self.step_label.configure(text=stripped[4:])
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line if line.endswith("\n") else line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_finished(self, ok: bool) -> None:
        self.running = False
        self._finished_ok = ok
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100 if ok else 0)
        if self.state_.cancelled:
            self.step_label.configure(text="Instalación cancelada por el usuario.")
        elif ok:
            self.step_label.configure(text="Instalación completada correctamente.")
        else:
            self.step_label.configure(text="La instalación terminó con errores — revisa el registro arriba.")
        self.app.refresh_nav()


# --------------------------------------------------------------------------- #
# 7. Fin
# --------------------------------------------------------------------------- #
class FinishPage(WizardPage):
    next_label = "Finalizar"
    allow_back = False
    allow_cancel = False

    def __init__(self, app: WizardApp) -> None:
        super().__init__(app)
        self.title_label = tk.Label(self, font=("TkDefaultFont", 14, "bold"))
        self.title_label.pack(anchor="w", pady=(0, 10))
        self.body = tk.Label(self, justify="left", wraplength=680)
        self.body.pack(anchor="w")
        self.launch_var = tk.BooleanVar(value=True)
        self.launch_check = ttk.Checkbutton(
            self, text="Iniciar PoorSDR4All ahora", variable=self.launch_var
        )

    def on_show(self) -> None:
        ok = self.state_.exit_code == 0 and not self.state_.cancelled
        if ok:
            self.title_label.configure(text="✓ PoorSDR4All está instalado")
            self.body.configure(
                text=(
                    "Se ha creado un acceso directo «PoorSDR4All» en el menú de "
                    "aplicaciones.\n\n"
                    "Si has instalado OpenWebRX+, es posible que necesites "
                    "cerrar sesión y volver a entrar una vez para que se "
                    "apliquen los grupos de sistema nuevos (incluido "
                    "'openwebrx', necesario para arrancar el servicio sin "
                    "pedir contraseña otra vez)."
                )
            )
            self.launch_check.pack(anchor="w", pady=(16, 0))
        else:
            self.title_label.configure(text="La instalación no terminó bien")
            reason = "cancelada por el usuario" if self.state_.cancelled else \
                f"código de salida {self.state_.exit_code}"
            self.body.configure(
                text=(
                    f"install.sh terminó con: {reason}.\n\n"
                    "Revisa el registro de la pantalla anterior para ver en qué "
                    "paso falló. Puedes volver a ejecutar este instalador: "
                    "vuelve a intentar los pasos ya completados sin problema.\n\n"
                    "Si el problema persiste, abre una incidencia en el "
                    "repositorio de GitHub del proyecto con el registro."
                )
            )
            self.launch_check.pack_forget()

    def on_leave_forward(self):
        if self.state_.exit_code == 0 and not self.state_.cancelled and self.launch_var.get():
            launch_poorsdr()
        self.app.destroy()
        return False


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--payload", required=True,
        help="Directorio con el código fuente de PoorSDR4All ya extraído.",
    )
    args = parser.parse_args()

    payload_dir = os.path.abspath(args.payload)
    if not os.path.isdir(payload_dir):
        print(f"ERROR: no existe el directorio de instalación: {payload_dir}", file=sys.stderr)
        return 1

    state = InstallerState(payload_dir)
    app = WizardApp(state)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
