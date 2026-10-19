"""Ventanas de PoorSDR4All para Windows (Tkinter, sin dependencias externas)."""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import setup, usb, wsl

FONDO = "#0e1117"
TARJETA = "#161b22"
TEXTO = "#e6edf3"
SUAVE = "#8b949e"
ACENTO = "#e5484d"
OK = "#3fb950"


def _logo(maximo: int = 72) -> tk.PhotoImage | None:
    """Logo de PoorSDR4All (el mismo de la aplicación), si está disponible."""
    candidatos = []
    try:
        import poorsdr

        candidatos.append(Path(poorsdr.__file__).resolve().parent / "ui" / "assets" / "images" / "image.png")
    except Exception:  # noqa: BLE001
        pass
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent
    candidatos.append(base / "poorsdr" / "ui" / "assets" / "images" / "image.png")
    for ruta in candidatos:
        if ruta.exists():
            try:
                img = tk.PhotoImage(file=str(ruta))
                factor = max(1, max(img.width(), img.height()) // maximo)
                return img.subsample(factor, factor) if factor > 1 else img
            except tk.TclError:
                continue
    return None


def _estilo(raiz: tk.Misc) -> None:
    s = ttk.Style(raiz)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure("PS.Horizontal.TProgressbar", troughcolor=TARJETA, background=ACENTO, bordercolor=FONDO,
                lightcolor=ACENTO, darkcolor=ACENTO)


def carpeta_registros() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    p = Path(base) / "poorsdr" / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------- #
# Ventana de arranque (al abrir PoorSDR4All)
# --------------------------------------------------------------------------- #
class Arranque:
    """Pequeña ventana «Arrancando OpenWebRX+…» mientras se prepara WSL."""

    def __init__(self) -> None:
        self.raiz = tk.Tk()
        self.raiz.title("PoorSDR4All")
        self.raiz.configure(bg=FONDO)
        self.raiz.resizable(False, False)
        self.raiz.overrideredirect(True)
        ancho, alto = 460, 150
        x = (self.raiz.winfo_screenwidth() - ancho) // 2
        y = (self.raiz.winfo_screenheight() - alto) // 2
        self.raiz.geometry(f"{ancho}x{alto}+{x}+{y}")
        _estilo(self.raiz)
        marco = tk.Frame(self.raiz, bg=TARJETA, highlightbackground=ACENTO, highlightthickness=1)
        marco.pack(fill="both", expand=True)
        self.logo = _logo(64)
        if self.logo:
            tk.Label(marco, image=self.logo, bg=TARJETA).pack(side="left", padx=16)
        derecha = tk.Frame(marco, bg=TARJETA)
        derecha.pack(side="left", fill="both", expand=True, padx=(0, 16))
        tk.Label(derecha, text="PoorSDR4All", bg=TARJETA, fg=TEXTO, font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(26, 0))
        self.texto = tk.Label(derecha, text="Iniciando…", bg=TARJETA, fg=SUAVE, font=("Segoe UI", 10), anchor="w")
        self.texto.pack(fill="x", pady=(4, 8))
        self.barra = ttk.Progressbar(derecha, mode="indeterminate", style="PS.Horizontal.TProgressbar")
        self.barra.pack(fill="x")
        self.barra.start(14)
        self.raiz.update()

    def mensaje(self, texto: str) -> None:
        self.texto.config(text=texto)
        self.raiz.update()

    def cerrar(self) -> None:
        try:
            self.barra.stop()
            self.raiz.destroy()
        except tk.TclError:
            pass

    def preguntar(self, titulo: str, texto: str) -> bool:
        self.raiz.overrideredirect(False)
        self.raiz.withdraw()
        r = messagebox.askyesno(titulo, texto, parent=self.raiz)
        self.raiz.deiconify()
        self.raiz.overrideredirect(True)
        return r


def arrancar_con_owrx(abrir_asistente) -> wsl.Resultado:
    """Prepara OpenWebRX+ antes de abrir la aplicación. Devuelve el resultado (para parar al salir)."""
    a = wsl.leer_ajustes()
    if not a.habilitado or not a.local or wsl.servicio_listo(a.url):
        return wsl.Resultado(True, gestionado=False)
    ventana = Arranque()
    aviso_pendiente = None
    try:
        if wsl.wsl_disponible() and not wsl.distro_instalada():
            if ventana.preguntar("OpenWebRX+ sin instalar",
                                 "OpenWebRX+ todavía no está instalado en este equipo.\n\n"
                                 "¿Quieres instalarlo ahora? (tarda unos 30 minutos la primera vez)"):
                ventana.cerrar()
                abrir_asistente()
                return wsl.Resultado(True, gestionado=False)
            return wsl.Resultado(True, gestionado=False)
        # La espera (arrancar WSL y OpenWebRX+) va en un hilo: la ventana de arranque sigue viva y no se queda en
        # «No responde» mientras tanto.
        mensajes: list[str] = []
        caja: dict = {}

        def trabajo() -> None:
            try:
                caja["r"] = wsl.asegurar_owrx(mensajes.append)
            except Exception as exc:  # noqa: BLE001
                caja["r"] = wsl.Resultado(False, f"Error inesperado: {exc}")

        hilo = threading.Thread(target=trabajo, name="arranque-owrx", daemon=True)
        hilo.start()
        while hilo.is_alive():
            if mensajes:
                ventana.texto.config(text=mensajes[-1])
                mensajes.clear()
            ventana.raiz.update()
            time.sleep(0.05)
        resultado = caja["r"]
        if resultado.ok and resultado.aviso and not (resultado.aviso.tipo == "ninguno" and usb.aviso_silenciado()):
            aviso_pendiente = resultado.aviso
        if not resultado.ok:
            seguir = ventana.preguntar(
                "OpenWebRX+ no arrancó",
                f"{resultado.mensaje}\n\nPoorSDR4All puede abrirse igualmente, pero sin la cascada de OpenWebRX+.\n"
                "Para repararlo, usa «Reparar OpenWebRX+» en el menú Inicio.\n\n¿Abrir PoorSDR4All sin OpenWebRX+?")
            if not seguir:
                raise SystemExit(1)
        return resultado
    finally:
        ventana.cerrar()
        if aviso_pendiente is not None:
            lanzar_aviso_sdr(aviso_pendiente)  # no bloquea: la consola se abre sin esperar a que se lea el aviso


def comando_propio(argumentos: list[str]) -> list[str]:
    """Comando para volver a lanzar este mismo programa con otros argumentos (ejecutable o código fuente)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *argumentos]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "launch_poorsdr.py"), *argumentos]


def lanzar_aviso_sdr(aviso) -> None:  # type: ignore[no-untyped-def]
    """Muestra el aviso del SDR en una ventana independiente (otro proceso), sin bloquear la aplicación."""
    import json
    import subprocess
    import tempfile

    fd, ruta = tempfile.mkstemp(prefix="aviso-sdr-", suffix=".json")
    os.close(fd)
    Path(ruta).write_text(json.dumps({"tipo": aviso.tipo, "texto": aviso.texto}), encoding="utf-8")
    try:
        subprocess.Popen(comando_propio(["--aviso-sdr", ruta]), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        pass


def mostrar_aviso_sdr(ruta: str) -> int:
    """Modo ``--aviso-sdr``: ventana pequeña con el aviso. El de «ninguno» se puede silenciar."""
    import json

    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    finally:
        try:
            Path(ruta).unlink(missing_ok=True)
        except OSError:
            pass
    raiz = tk.Tk()
    raiz.title("PoorSDR4All — SDR por USB")
    raiz.configure(bg=FONDO)
    raiz.geometry("520x250")
    raiz.attributes("-topmost", True)
    _estilo(raiz)
    tk.Label(raiz, text=datos.get("texto", ""), bg=FONDO, fg=TEXTO, font=("Segoe UI", 10), justify="left",
             wraplength=470).pack(padx=24, pady=(22, 10), anchor="w")
    silenciar = tk.BooleanVar(value=False)
    if datos.get("tipo") == "ninguno":
        tk.Checkbutton(raiz, text="No volver a mostrar este aviso", variable=silenciar, bg=FONDO, fg=SUAVE,
                       selectcolor=FONDO, activebackground=FONDO, activeforeground=TEXTO, bd=0,
                       highlightthickness=0).pack(padx=22, anchor="w")
    ttk.Button(raiz, text="Entendido", command=raiz.destroy).pack(pady=18)
    raiz.mainloop()
    if silenciar.get():
        usb.silenciar_aviso()
    return 0


# --------------------------------------------------------------------------- #
# Asistente de instalación de OpenWebRX+
# --------------------------------------------------------------------------- #
class Asistente:
    def __init__(self, forzar: bool = False, al_terminar=None) -> None:
        self.forzar = forzar
        self.al_terminar = al_terminar
        self.cola: queue.Queue = queue.Queue()
        self.cancelar = threading.Event()
        self.hilo: threading.Thread | None = None
        self.registro_ruta = carpeta_registros() / "asistente-owrx.log"
        self.registro = open(self.registro_ruta, "a", encoding="utf-8")

        self.raiz = tk.Tk()
        self.raiz.title("PoorSDR4All — Instalación de OpenWebRX+")
        self.raiz.configure(bg=FONDO)
        self.raiz.geometry("760x600")
        self.raiz.minsize(640, 520)
        self.raiz.protocol("WM_DELETE_WINDOW", self._cerrar)
        _estilo(self.raiz)

        cab = tk.Frame(self.raiz, bg=FONDO)
        cab.pack(fill="x", padx=22, pady=(18, 6))
        self.logo = _logo(72)
        if self.logo:
            tk.Label(cab, image=self.logo, bg=FONDO).pack(side="left", padx=(0, 16))
        tit = tk.Frame(cab, bg=FONDO)
        tit.pack(side="left", fill="x")
        tk.Label(tit, text="Instalando OpenWebRX+", bg=FONDO, fg=TEXTO, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(tit, text="PoorSDR4All usa OpenWebRX+ para la cascada. En Windows funciona dentro de un\n"
                           "subsistema Linux (WSL2) propio, que se instala y se gestiona solo.",
                 bg=FONDO, fg=SUAVE, font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=(4, 0))

        lista = tk.Frame(self.raiz, bg=TARJETA)
        lista.pack(fill="x", padx=22, pady=10)
        self.marcas: list[tk.Label] = []
        self.textos: list[tk.Label] = []
        for _, etiqueta in setup.PASOS:
            fila = tk.Frame(lista, bg=TARJETA)
            fila.pack(fill="x", padx=14, pady=3)
            m = tk.Label(fila, text="○", width=2, bg=TARJETA, fg=SUAVE, font=("Segoe UI", 12))
            m.pack(side="left")
            t = tk.Label(fila, text=etiqueta, bg=TARJETA, fg=SUAVE, font=("Segoe UI", 10), anchor="w", justify="left")
            t.pack(side="left", fill="x")
            self.marcas.append(m)
            self.textos.append(t)

        self.estado = tk.Label(self.raiz, text="Preparando…", bg=FONDO, fg=TEXTO, font=("Segoe UI", 10), anchor="w")
        self.estado.pack(fill="x", padx=24)
        self.barra = ttk.Progressbar(self.raiz, mode="indeterminate", style="PS.Horizontal.TProgressbar")
        self.barra.pack(fill="x", padx=22, pady=(4, 8))

        self.detalle_visible = tk.BooleanVar(value=False)
        tk.Checkbutton(self.raiz, text="Mostrar detalles", variable=self.detalle_visible, command=self._conmutar_detalle,
                       bg=FONDO, fg=SUAVE, selectcolor=FONDO, activebackground=FONDO, activeforeground=TEXTO,
                       bd=0, highlightthickness=0).pack(anchor="w", padx=22)
        self.log = ScrolledText(self.raiz, height=10, bg="#010409", fg="#c9d1d9", insertbackground=TEXTO,
                                font=("Consolas", 9), bd=0, state="disabled")

        pie = tk.Frame(self.raiz, bg=FONDO)
        pie.pack(side="bottom", fill="x", padx=22, pady=14)
        self.btn_cancelar = ttk.Button(pie, text="Cancelar", command=self._cancelar)
        self.btn_cancelar.pack(side="right")
        self.btn_reintentar = ttk.Button(pie, text="Reintentar", command=self.empezar)
        self.btn_cerrar = ttk.Button(pie, text="Cerrar", command=self._cerrar)

        self.raiz.after(100, self._vaciar_cola)

    # -- interfaz ------------------------------------------------------------------
    def _conmutar_detalle(self) -> None:
        if self.detalle_visible.get():
            self.log.pack(fill="both", expand=True, padx=22, pady=(4, 0))
        else:
            self.log.pack_forget()

    def _escribir_lote(self, lineas: list[str]) -> None:
        """Una sola escritura al fichero y una sola inserción en el cuadro de texto por lote."""
        marca = time.strftime("%H:%M:%S ")
        self.registro.write("".join(marca + l + "\n" for l in lineas))
        self.registro.flush()
        self.log.config(state="normal")
        self.log.insert("end", "\n".join(lineas) + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 2500:  # el historial visible se limita; el fichero lo guarda todo
            self.log.delete("1.0", "800.0")
        if self.detalle_visible.get():
            self.log.see("end")
        self.log.config(state="disabled")

    def _vaciar_cola(self) -> None:
        """Procesa la cola en lotes de como mucho ~30 ms: con miles de líneas por segundo (compilación) la
        ventana debe seguir respondiendo y redibujándose."""
        lineas: list[str] = []
        otros: list[tuple] = []
        limite = time.monotonic() + 0.03
        try:
            while time.monotonic() < limite:
                evento = self.cola.get_nowait()
                if evento[0] == "log":
                    lineas.append(evento[1])
                else:
                    otros.append(evento)
        except queue.Empty:
            pass
        if lineas:
            self._escribir_lote(lineas)
        for tipo, *datos in otros:
            if tipo == "paso":
                self._paso(*datos)
            elif tipo == "fin":
                self._fin(*datos)
        self.raiz.after(60, self._vaciar_cola)

    def _paso(self, i: int, texto: str, fraccion: float | None) -> None:
        for k in range(len(setup.PASOS)):
            if k < i:
                self.marcas[k].config(text="✓", fg=OK)
                self.textos[k].config(fg=TEXTO)
            elif k == i:
                self.marcas[k].config(text="▶", fg=ACENTO)
                self.textos[k].config(fg=TEXTO)
            else:
                self.marcas[k].config(text="○", fg=SUAVE)
                self.textos[k].config(fg=SUAVE)
        self.estado.config(text=texto)
        if fraccion is None:
            if str(self.barra.cget("mode")) != "indeterminate":
                self.barra.config(mode="indeterminate")
                self.barra.start(14)
        else:
            self.barra.stop()
            self.barra.config(mode="determinate", value=max(0.0, min(1.0, fraccion)) * 100)

    def _fin(self, error: str | None) -> None:
        self.barra.stop()
        self.btn_cancelar.pack_forget()
        if error is None:
            for m, t in zip(self.marcas, self.textos):
                m.config(text="✓", fg=OK)
                t.config(fg=TEXTO)
            self.barra.config(mode="determinate", value=100)
            self.estado.config(text="¡Listo! OpenWebRX+ está instalado. Se iniciará solo al abrir PoorSDR4All.", fg=OK)
            self.btn_cerrar.config(text="Terminar")
            self.btn_cerrar.pack(side="right")
        else:
            self.estado.config(text=error, fg=ACENTO, wraplength=700, justify="left")
            self.detalle_visible.set(True)
            self._conmutar_detalle()
            self.btn_cerrar.pack(side="right", padx=(8, 0))
            self.btn_reintentar.pack(side="right")
        if self.al_terminar:
            self.al_terminar(error)

    # -- ejecución -------------------------------------------------------------------
    def empezar(self) -> None:
        self.btn_reintentar.pack_forget()
        self.btn_cerrar.pack_forget()
        self.btn_cancelar.pack(side="right")
        self.cancelar.clear()
        self.estado.config(fg=TEXTO)
        self.hilo = threading.Thread(target=self._trabajo, daemon=True)
        self.hilo.start()

    def _trabajo(self) -> None:
        try:
            setup.ejecutar(lambda l: self.cola.put(("log", l)),
                           lambda i, t, f: self.cola.put(("paso", i, t, f)),
                           self.cancelar.is_set, setup.Opciones(forzar_owrx=self.forzar))
            self.cola.put(("fin", None))
        except setup.ErrorPaso as e:
            self.cola.put(("log", f"ERROR: {e}"))
            self.cola.put(("fin", str(e)))
        except Exception as e:  # noqa: BLE001
            import traceback

            self.cola.put(("log", traceback.format_exc()))
            self.cola.put(("fin", f"Error inesperado: {e}"))

    def _cancelar(self) -> None:
        if messagebox.askyesno("Cancelar", "¿Cancelar la instalación de OpenWebRX+?\n\n"
                               "Podrás retomarla más tarde con «Reparar OpenWebRX+» en el menú Inicio."):
            self.cancelar.set()
            self.estado.config(text="Cancelando…")

    def _cerrar(self) -> None:
        if self.hilo and self.hilo.is_alive():
            self._cancelar()
            return
        self.registro.close()
        self.raiz.destroy()

    def ejecutar(self) -> None:
        self.raiz.after(200, self.empezar)
        self.raiz.mainloop()


def ejecutar_asistente(forzar: bool = False) -> int:
    resultado: dict = {}
    a = Asistente(forzar=forzar, al_terminar=lambda e: resultado.update(error=e))
    a.ejecutar()
    return 0 if resultado.get("error") is None else 1


def ejecutar_asistente_sin_ventana(forzar: bool = False) -> int:
    """Mismo trabajo, en consola/registro: para pruebas automáticas y soporte."""
    ruta = carpeta_registros() / "asistente-owrx.log"
    with open(ruta, "a", encoding="utf-8") as reg:
        def log(l: str) -> None:
            reg.write(time.strftime("%H:%M:%S ") + l + "\n")
            reg.flush()
            print(l, flush=True)

        try:
            setup.ejecutar(log, lambda i, t, f: log(f"[{i + 1}/{len(setup.PASOS)}] {t}" + ("" if f is None else f" {f:.0%}")),
                           lambda: False, setup.Opciones(forzar_owrx=forzar))
        except setup.ErrorPaso as e:
            log(f"ERROR: {e}")
            return 1
        log("OK")
    return 0
