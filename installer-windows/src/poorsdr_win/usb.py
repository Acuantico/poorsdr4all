"""SDR por USB para OpenWebRX+ en WSL2, con usbipd-win.

WSL2 no ve los dispositivos USB de Windows por defecto. usbipd-win los comparte, pero compartir exige
administrador. Por eso el instalador (que ya corre como administrador) autoriza de una vez los SDR habituales
con directivas ``AutoBind`` (``usbipd policy add``): después un usuario normal puede conectarlos sin permisos.

Aquí se hace el resto, al abrir y cerrar la aplicación:
  * al abrir: se conectan a WSL los SDR de la lista que estén enchufados (``usbipd attach --auto-attach``, que
    reconecta solo si se desenchufa), ANTES de arrancar OpenWebRX+ (que solo descubre dispositivos al arrancar);
  * mientras la app está abierta: si se enchufa un SDR nuevo se conecta y se reinicia OpenWebRX+ para que lo vea;
  * al cerrar: se sueltan y vuelven a Windows;
  * si algo no cuadra se devuelve un aviso claro (``Aviso``).
Mientras un SDR está conectado a WSL, Windows no puede usarlo.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import DISTRO

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_RE_VIDPID = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")


def usbipd_exe() -> Path | None:
    base = os.environ.get("ProgramFiles", r"C:\Program Files")
    ruta = Path(base) / "usbipd-win" / "usbipd.exe"
    return ruta if ruta.is_file() else None


def ruta_ids() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "tools" / "sdr-ids.txt"
    return Path(__file__).resolve().parents[2] / "inno" / "sdr-ids.txt"


def leer_ids(ruta: Path | None = None) -> dict[str, str]:
    """{'0bda:2838': 'RTL-SDR · ...'} desde sdr-ids.txt (una línea por dispositivo: ``vid:pid  # nombre``)."""
    ids: dict[str, str] = {}
    try:
        texto = (ruta or ruta_ids()).read_text(encoding="utf-8")
    except OSError:
        return ids
    for linea in texto.splitlines():
        cuerpo, _, nombre = linea.partition("#")
        clave = cuerpo.strip().lower()
        if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", clave):
            ids[clave] = nombre.strip() or clave
    return ids


@dataclass(frozen=True)
class Dispositivo:
    hardware_id: str  # 'vid:pid' en minúsculas
    busid: str
    nombre: str
    conectado: bool  # ya está conectado a algún cliente (WSL)


def _ejecutar(args: list[str], timeout: float = 20.0) -> tuple[int, str]:
    exe = usbipd_exe()
    if exe is None:
        return 127, "usbipd-win no está instalado"
    try:
        p = subprocess.run([str(exe), *args], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW, check=False)
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def parsear_estado(texto: str) -> list[tuple[str, str, str, bool]]:
    """(hardware_id, busid, descripción, conectado) de cada dispositivo del JSON de ``usbipd state``."""
    try:
        datos = json.loads(texto)
    except ValueError:
        return []
    salida = []
    for d in datos.get("Devices", []) if isinstance(datos, dict) else []:
        m = _RE_VIDPID.search(str(d.get("InstanceId") or ""))
        if m:
            salida.append((f"{m.group(1)}:{m.group(2)}".lower(), str(d.get("BusId") or ""),
                           str(d.get("Description") or ""), d.get("ClientIPAddress") is not None))
    return salida


def sdr_presentes(ids: dict[str, str] | None = None) -> list[Dispositivo]:
    """SDR de la lista que hay enchufados ahora mismo."""
    ids = ids if ids is not None else leer_ids()
    rc, texto = _ejecutar(["state"])
    if rc != 0:
        return []
    return [Dispositivo(h, b, ids[h], c) for h, b, _d, c in parsear_estado(texto) if h in ids]


def visibles_en_wsl() -> set[str]:
    """vid:pid de los dispositivos USB que ve la distribución."""
    from . import wsl

    orden = ('for d in /sys/bus/usb/devices/*; do [ -f "$d/idVendor" ] && '
             'echo "$(cat $d/idVendor):$(cat $d/idProduct)"; done')
    rc, salida = wsl.en_distro(["bash", "-c", orden], 20)
    return {l.strip().lower() for l in salida.splitlines() if re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", l.strip())}


# --------------------------------------------------------------------------- #
@dataclass
class Aviso:
    """Mensaje para el usuario cuando el SDR no está disponible para OpenWebRX+."""
    tipo: str  # ninguno | no_autorizado | fallo
    texto: str


def aviso_silenciado() -> bool:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return (Path(base) / "poorsdr" / "sin_aviso_sdr.flag").exists()


def silenciar_aviso() -> None:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    ruta = Path(base) / "poorsdr" / "sin_aviso_sdr.flag"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("no volver a avisar\n", encoding="utf-8")


@dataclass
class _Conexion:
    proceso: subprocess.Popen
    salida: Path
    inicio: float = field(default_factory=time.monotonic)


class Gestor:
    """Mantiene conectados a WSL los SDR de la lista mientras la aplicación está abierta."""

    def __init__(self, ids: dict[str, str] | None = None, lanzar: Callable | None = None) -> None:
        self.ids = ids if ids is not None else leer_ids()
        self._lanzar = lanzar or self._lanzar_attach
        self._conexiones: dict[str, _Conexion] = {}
        self.rechazados: dict[str, str] = {}  # hardware_id -> motivo (no se reintenta)
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._job = None

    # -- lanzar usbipd attach ------------------------------------------------------
    def _lanzar_attach(self, hardware_id: str) -> _Conexion:
        from . import wsl

        fd, nombre = tempfile.mkstemp(prefix="usbipd-", suffix=".log")
        salida = Path(nombre)
        f = os.fdopen(fd, "wb")
        p = subprocess.Popen([str(usbipd_exe()), "attach", "--wsl", DISTRO, "--hardware-id", hardware_id, "--auto-attach"],
                             stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
        f.close()
        if sys.platform == "win32":  # si la app muere, los attach mueren con ella (y los SDR vuelven a Windows)
            try:
                if self._job is None:
                    self._job = wsl._Job()  # noqa: SLF001
                self._job.añadir(p)
            except Exception:  # noqa: BLE001
                pass
        return _Conexion(p, salida)

    def sincronizar(self) -> list[str]:
        """Conecta los SDR presentes que aún no lo estén. Devuelve los hardware_id que se acaban de lanzar."""
        nuevos: list[str] = []
        for h, c in list(self._conexiones.items()):
            if c.proceso.poll() is not None:  # terminó: o falló pronto (no autorizado) o se cerró
                texto = c.salida.read_text(encoding="utf-8", errors="replace").strip()[-300:] if c.salida.exists() else ""
                del self._conexiones[h]
                if time.monotonic() - c.inicio < 8 or c.proceso.returncode not in (0, None):
                    self.rechazados[h] = texto or f"usbipd terminó con código {c.proceso.returncode}"
        for d in sdr_presentes(self.ids):
            if d.hardware_id in self._conexiones or d.hardware_id in self.rechazados:
                continue
            self._conexiones[d.hardware_id] = self._lanzar(d.hardware_id)
            nuevos.append(d.hardware_id)
        return nuevos

    # -- ciclo de vida -------------------------------------------------------------
    def conectar_iniciales(self, espera: float = 15.0) -> Aviso | None:
        """Conecta los SDR presentes y espera a que WSL los vea. Devuelve un aviso si no hay o no se pudo."""
        if usbipd_exe() is None:
            return None  # el usuario no instaló el soporte USB: no se avisa (puede usar un SDR remoto)
        presentes = sdr_presentes(self.ids)
        if not presentes:
            return Aviso("ninguno", "No se detecta ningún SDR conectado por USB.\n\nConecta tu SDR y reinicia PoorSDR4All. "
                                    "Si usas un SDR remoto (por red), puedes ignorar este aviso.")
        self.sincronizar()
        fin = time.monotonic() + espera
        faltan = {d.hardware_id for d in presentes}
        while faltan and time.monotonic() < fin:
            self.sincronizar()
            faltan -= visibles_en_wsl()
            if faltan - set(self.rechazados):
                time.sleep(1.0)
            else:
                break
        nombres = lambda hs: ", ".join(f"{self.ids[h]} ({h})" for h in sorted(hs))  # noqa: E731
        no_aut = {h for h in faltan if h in self.rechazados and re.search(r"bind|shared|share|administrator", self.rechazados[h], re.I)}
        if no_aut:
            return Aviso("no_autorizado", f"Hay un SDR conectado ({nombres(no_aut)}) pero Windows no ha autorizado compartirlo "
                                          "con el subsistema Linux.\n\nVuelve a ejecutar el instalador de PoorSDR4All (autoriza "
                                          "los SDR habituales una sola vez, con permisos de administrador).")
        if faltan:
            detalle = "; ".join(self.rechazados.get(h, "no apareció en WSL") for h in sorted(faltan))[:300]
            return Aviso("fallo", f"No se pudo conectar el SDR {nombres(faltan)} a OpenWebRX+.\n\n{detalle}")
        return None

    def vigilar(self, al_conectar_nuevo: Callable[[], None]) -> None:
        """Hilo: conecta los SDR que se enchufen mientras la app está abierta y avisa para reiniciar OpenWebRX+."""
        def bucle() -> None:
            while not self._parar.wait(5.0):
                try:
                    nuevos = self.sincronizar()
                    if nuevos:
                        time.sleep(4.0)
                        al_conectar_nuevo()
                except Exception:  # noqa: BLE001 - la vigilancia nunca debe tumbar la app
                    pass

        if self._hilo is None or not self._hilo.is_alive():
            self._parar.clear()
            self._hilo = threading.Thread(target=bucle, name="usb-sdr", daemon=True)
            self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        for h, c in list(self._conexiones.items()):
            if c.proceso.poll() is None:
                c.proceso.terminate()
                try:
                    c.proceso.wait(3)
                except subprocess.TimeoutExpired:
                    c.proceso.kill()
            _ejecutar(["detach", "--hardware-id", h], 15)  # vuelve a Windows
            try:  # en Windows no se puede borrar un fichero que el proceso aún tiene abierto
                c.salida.unlink(missing_ok=True)
            except OSError:
                pass
        self._conexiones.clear()


gestor = Gestor()
