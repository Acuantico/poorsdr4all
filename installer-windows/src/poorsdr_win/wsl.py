"""Control de la distribución WSL y del servicio OpenWebRX+ (solo tiene sentido en Windows).

Notas de diseño (comprobadas en una VM con WSL 3.0 / Windows 11):
  * WSL apaga la distribución ~25 s después de cerrarse la última sesión. Para que OpenWebRX+
    siga en marcha mientras PoorSDR4All está abierto se mantiene una sesión viva
    (``sleep infinity``) dentro de un *job object* de Windows con KILL_ON_JOB_CLOSE: si la
    aplicación muere por cualquier motivo, la sesión muere con ella y WSL se apaga sola.
  * Windows llega al servicio por ``127.0.0.1:8073`` (reenvío de localhost de WSL).
  * ``wsl.exe`` escribe sus propios mensajes en UTF-16; lo que se ejecuta dentro de la
    distribución sale en UTF-8. ``decodificar`` entiende ambos.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import DISTRO, OWRX_PORT, SERVICE, usb

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def decodificar(datos: bytes | None) -> str:
    if not datos:
        return ""
    if b"\x00" in datos:
        try:
            return datos.decode("utf-16-le").replace("\ufeff", "")
        except UnicodeDecodeError:
            return datos.replace(b"\x00", b"").decode("utf-8", "replace")
    return datos.decode("utf-8", "replace")


_AVISO_WSL = re.compile(r"^wsl: .*(anidada|[Nn]ested virtuali[sz]ation).*$", re.M)


def limpiar(salida: str) -> str:
    """Quita de la salida de wsl.exe el aviso inofensivo de «virtualización anidada» (sale a ratos, antes o después
    de lo que de verdad se imprime) para que no se confunda con datos: rutas, estados de systemd, etc."""
    return "\n".join(l for l in _AVISO_WSL.sub("", salida).splitlines() if l.strip())


def wsl_exe() -> str | None:
    ruta = shutil.which("wsl.exe") or shutil.which("wsl")
    if ruta:
        return ruta
    raiz = os.environ.get("SystemRoot", r"C:\Windows")
    candidato = Path(raiz) / "System32" / "wsl.exe"
    return str(candidato) if candidato.exists() else None


def ejecutar(args: list[str], timeout: float = 60.0) -> tuple[int, str]:
    """Ejecuta ``wsl.exe <args>`` sin ventana y devuelve (código, salida)."""
    exe = wsl_exe()
    if not exe:
        return 127, "wsl.exe no está disponible"
    try:
        # stdin=DEVNULL: un programa de ventanas lanzado por un instalador no tiene entrada estándar válida y
        # sin esto wsl.exe no arranca («el identificador no es válido»).
        p = subprocess.run([exe, *args], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW, check=False)
        return p.returncode, limpiar(decodificar(p.stdout) + decodificar(p.stderr))
    except subprocess.TimeoutExpired:
        return 124, "tiempo de espera agotado"
    except OSError as exc:
        return 1, str(exc)


def en_distro(comando: list[str], timeout: float = 60.0, usuario: str = "root") -> tuple[int, str]:
    """Ejecuta un comando (sin shell) dentro de la distribución de PoorSDR4All."""
    return ejecutar(["-d", DISTRO, "-u", usuario, "--exec", *comando], timeout)


def wsl_disponible() -> bool:
    rc, _ = ejecutar(["--status"], 20)
    return rc == 0


def distro_instalada() -> bool:
    rc, salida = ejecutar(["-l", "-q"], 20)
    return rc == 0 and any(l.strip() == DISTRO for l in salida.splitlines())


def servicio_listo(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - http local
            cuerpo = r.read(65536).decode("utf-8", "ignore").lower()
        return any(m in cuerpo for m in ("openwebrx", "webrx", "receiver"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# Sesión viva (mantiene WSL encendido) dentro de un job object
# --------------------------------------------------------------------------- #
class _Job:
    """Job object de Windows que mata a sus procesos cuando se cierra el último handle."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.CreateJobObjectW.restype = wintypes.HANDLE
        self._k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        self.handle = self._k32.CreateJobObjectW(None, None)

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXT()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self._k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))

    def añadir(self, proceso: subprocess.Popen) -> None:
        self._k32.AssignProcessToJobObject(self.handle, int(proceso._handle))  # noqa: SLF001


@dataclass
class Sesion:
    proceso: subprocess.Popen | None = None
    job: object | None = None


_sesion = Sesion()


def abrir_sesion_viva(ligada: bool = True) -> bool:
    """Deja una sesión ``sleep infinity`` abierta para que WSL no se apague sola.

    ``ligada=True`` la ata a la vida de este proceso (si muere, WSL se apaga sola). Con ``False``
    sobrevive a la aplicación (el usuario pidió no parar OpenWebRX+ al salir).
    """
    if _sesion.proceso and _sesion.proceso.poll() is None:
        return True
    exe = wsl_exe()
    if not exe:
        return False
    try:
        p = subprocess.Popen([exe, "-d", DISTRO, "-u", "root", "--exec", "/bin/sleep", "infinity"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=CREATE_NO_WINDOW)
    except OSError:
        return False
    if ligada and sys.platform == "win32":
        try:
            job = _Job()
            job.añadir(p)
            _sesion.job = job
        except Exception:  # noqa: BLE001 - sin job sigue funcionando; solo se pierde la red de seguridad
            pass
    _sesion.proceso = p
    return True


def cerrar_sesion_viva() -> None:
    p = _sesion.proceso
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    _sesion.proceso = None


# --------------------------------------------------------------------------- #
# Servicio OpenWebRX+
# --------------------------------------------------------------------------- #
def esperar_systemd(timeout: float = 40.0, pausa: Callable[[float], None] = time.sleep) -> bool:
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        rc, salida = en_distro(["systemctl", "is-system-running"], 10)
        if salida.strip() in ("running", "degraded"):
            return True
        pausa(1.5)
    return False


def arrancar_servicio() -> tuple[bool, str]:
    if not esperar_systemd():
        return False, "El sistema Linux de WSL no terminó de arrancar (systemd)."
    rc, salida = en_distro(["systemctl", "start", SERVICE], 60)
    return rc == 0, salida.strip()


def parar_servicio() -> None:
    en_distro(["systemctl", "stop", SERVICE], 30)


def apagar_distro() -> None:
    ejecutar(["--terminate", DISTRO], 30)


# --------------------------------------------------------------------------- #
# Configuración de PoorSDR4All que interesa al lanzador
# --------------------------------------------------------------------------- #
@dataclass
class AjustesOwrx:
    habilitado: bool = True
    host: str = "127.0.0.1"
    puerto: int = OWRX_PORT
    parar_al_salir: bool = True
    spots: bool = True

    @property
    def local(self) -> bool:
        return self.host.strip().lower() in ("", "127.0.0.1", "localhost", "::1")

    @property
    def url(self) -> str:
        return f"http://{self.host.strip() or '127.0.0.1'}:{self.puerto}/"


def ruta_config() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "poorsdr" / "config.json"


def leer_ajustes(ruta: Path | None = None) -> AjustesOwrx:
    """Lee los ajustes de OpenWebRX+ del config.json de PoorSDR4All (formato anidado o plano)."""
    a = AjustesOwrx()
    try:
        datos = json.loads((ruta or ruta_config()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return a
    owrx = datos.get("owrx") if isinstance(datos.get("owrx"), dict) else {}
    spots_cfg = owrx.get("spots") if isinstance(owrx.get("spots"), dict) else {}

    def tomar(clave_anidada: str, clave_plana: str, defecto):
        if clave_anidada in owrx:
            return owrx[clave_anidada]
        return datos.get(clave_plana, defecto)

    try:
        a.habilitado = bool(tomar("enabled", "OWRX_ENABLED", a.habilitado))
        a.host = str(tomar("host", "OWRX_HOST", a.host))
        a.puerto = int(tomar("port", "OWRX_PORT", a.puerto))
        a.parar_al_salir = bool(tomar("stop_on_exit", "OWRX_STOP_ON_EXIT", a.parar_al_salir))
        a.spots = bool(spots_cfg["enabled"]) if "enabled" in spots_cfg else bool(datos.get("OWRX_SPOTS_ENABLED", a.spots))
        runtime = str(tomar("runtime", "OWRX_RUNTIME", "native")).strip().lower()
        if runtime != "native":
            a.habilitado = False
    except (TypeError, ValueError):
        pass
    return a


# --------------------------------------------------------------------------- #
# spiderd (spots DX): corre en WSL como servicio de usuario; su configuración la escribe la app en Windows
# --------------------------------------------------------------------------- #
SPIDER_UNIT = "spiderd.service"
SPIDER_CONF_WSL = "/home/poorsdr/.config/poorsdr/spiderd.conf"
_spider = {"huella": None, "parar": threading.Event(), "hilo": None}


def ruta_spiderd_conf() -> Path:
    return ruta_config().with_name("spiderd.conf")


def sincronizar_spiderd(forzar: bool = False) -> bool:
    """Copia el spiderd.conf que escribe la app (Windows) a la distribución y reinicia spiderd.

    La app, en Linux, escribe ese fichero y reinicia la unidad con ``systemctl --user``; en Windows ni el fichero
    está donde lo lee WSL ni existe systemctl, así que aquí se hace el mismo trabajo.
    """
    conf = ruta_spiderd_conf()
    try:
        st = conf.stat()
    except OSError:
        return False
    huella = (st.st_mtime_ns, st.st_size)
    if not forzar and huella == _spider["huella"]:
        return True
    rc, salida = en_distro(["wslpath", "-a", str(conf)], 20)
    rutas = [l.strip() for l in salida.splitlines() if l.strip().startswith("/")]
    if rc != 0 or not rutas:
        return False
    origen = shlex.quote(rutas[-1])
    orden = (f"install -D -o poorsdr -g poorsdr -m 644 {origen} {SPIDER_CONF_WSL} && "
             f"/usr/sbin/runuser -u poorsdr -- bash -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart {SPIDER_UNIT}'")
    rc, _ = en_distro(["bash", "-c", orden], 60)
    if rc == 0:
        _spider["huella"] = huella
    return rc == 0


def _vigilar_spiderd() -> None:
    fallos = 0
    while not _spider["parar"].wait(3.0 if fallos < 3 else 30.0):
        fallos = 0 if sincronizar_spiderd() else fallos + 1


def iniciar_spiderd() -> None:
    """Hilo que mantiene spiderd con la configuración actual mientras la app está abierta."""
    if _spider["hilo"] is not None and _spider["hilo"].is_alive():
        return
    _spider["parar"].clear()
    _spider["huella"] = None
    _spider["hilo"] = threading.Thread(target=_vigilar_spiderd, name="spiderd-sync", daemon=True)
    _spider["hilo"].start()


def detener_spiderd() -> None:
    _spider["parar"].set()
    en_distro(["/usr/sbin/runuser", "-u", "poorsdr", "--", "bash", "-c",
               f"XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user stop {SPIDER_UNIT}"], 20)


# --------------------------------------------------------------------------- #
# Orquestación: lo que hace el lanzador al abrir y al cerrar PoorSDR4All
# --------------------------------------------------------------------------- #
@dataclass
class Resultado:
    ok: bool
    mensaje: str = ""
    gestionado: bool = False  # True si este proceso arrancó/gobierna OpenWebRX+
    aviso: usb.Aviso | None = None  # SDR por USB no disponible (ver usb.py)


def asegurar_owrx(progreso: Callable[[str], None] = lambda _m: None, espera_http: float = 90.0) -> Resultado:
    a = leer_ajustes()
    if not a.habilitado or not a.local:
        return Resultado(True, "OpenWebRX+ remoto o desactivado: no se toca.")
    if servicio_listo(a.url):
        return Resultado(True, "OpenWebRX+ ya estaba en marcha.")
    if not wsl_disponible():
        return Resultado(False, "WSL no está disponible en este equipo.")
    if not distro_instalada():
        return Resultado(False, "OpenWebRX+ todavía no está instalado (falta la distribución de WSL).")
    progreso("Arrancando el subsistema Linux (WSL)…")
    if not abrir_sesion_viva(ligada=a.parar_al_salir):
        return Resultado(False, "No se pudo abrir una sesión de WSL.")
    progreso("Conectando el SDR por USB…")
    aviso = usb.gestor.conectar_iniciales()  # antes de arrancar OpenWebRX+: solo descubre dispositivos al arrancar
    progreso("Arrancando OpenWebRX+…")
    ok, detalle = arrancar_servicio()
    if not ok:
        usb.gestor.detener()
        cerrar_sesion_viva()
        return Resultado(False, f"OpenWebRX+ no arrancó. {detalle}")
    progreso("Esperando a que OpenWebRX+ responda…")
    fin = time.monotonic() + espera_http
    while time.monotonic() < fin:
        if servicio_listo(a.url):
            if a.spots:
                iniciar_spiderd()
            # SDR que se enchufen con la app abierta: se conectan y OpenWebRX+ se reinicia para verlos.
            usb.gestor.vigilar(lambda: en_distro(["systemctl", "restart", SERVICE], 60))
            return Resultado(True, "OpenWebRX+ en marcha.", gestionado=True, aviso=aviso)
        time.sleep(1.0)
    parar_owrx(True)
    return Resultado(False, "OpenWebRX+ no respondió a tiempo.")


def parar_owrx(gestionado: bool) -> None:
    """Al cerrar la app: parar OpenWebRX+ y liberar WSL, salvo que el usuario lo haya pedido de otro modo."""
    if not gestionado:
        return
    if not leer_ajustes().parar_al_salir:
        return  # el usuario quiere dejarlo en marcha; la sesión viva se cierra sola con el proceso
    detener_spiderd()
    usb.gestor.detener()  # los SDR vuelven a Windows
    parar_servicio()
    cerrar_sesion_viva()
    apagar_distro()
