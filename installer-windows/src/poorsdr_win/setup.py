"""Pasos del asistente que instala OpenWebRX+ en WSL2 (sin interfaz: la ventana los llama).

Orden: comprobar WSL → descargar Ubuntu → crear la distribución → configurarla → instalar OpenWebRX+
(ejecuta el ``install.sh`` oficial de PoorSDR4All dentro) → comprobarlo. Cada paso se salta si ya está
hecho, así que se puede repetir (reanudar tras un reinicio, reparar, actualizar).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import DISTRO, wsl

URL_INFO_DISTROS = "https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json"
# Respaldo por si no se pudiera leer el listado oficial de Microsoft (Ubuntu 24.04.5, comprobado).
IMAGEN_RESPALDO = (
    "https://releases.ubuntu.com/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl",
    "bb415d824822c4b878125729af451a5d18fb13d1cf5cbed9a7393ad64ac6039e",
)
MARCADOR = "/home/poorsdr/.poorsdr_owrx_ok"

PASOS = [
    ("wsl", "Comprobando WSL"),
    ("descarga", "Descargando Ubuntu (unos 370 MB)"),
    ("crear", "Creando el sistema Linux de PoorSDR4All"),
    ("config", "Configurando"),
    ("owrx", "Instalando OpenWebRX+ (compila varios componentes: 20-40 min la primera vez)"),
    ("verificar", "Comprobando que OpenWebRX+ funciona"),
]

Log = Callable[[str], None]
Progreso = Callable[[int, str, float | None], None]  # (índice de paso, texto, fracción 0-1 o None)


class ErrorPaso(Exception):
    """Fallo de un paso; el texto es lo que se le enseña al usuario."""


def carpeta_datos() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "poorsdr" / "wsl"


def carpeta_recursos() -> Path:
    return Path(__file__).resolve().parent / "recursos"


def ruta_paquete() -> Path:
    """Paquete poorsdr4all-<versión>.tar.gz que lleva el instalador junto a la aplicación."""
    ajustado = os.environ.get("POORSDR_PAYLOAD")
    if ajustado:
        return Path(ajustado)
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    candidatos = sorted((base / "payload").glob("poorsdr4all-*.tar.gz"))
    if not candidatos:
        raise ErrorPaso("No encuentro el paquete de instalación de OpenWebRX+ (carpeta «payload»). "
                        "Vuelve a ejecutar el instalador de PoorSDR4All.")
    return candidatos[-1]


def version_paquete(p: Path) -> str:
    n = p.name
    return n.removeprefix("poorsdr4all-").removesuffix(".tar.gz")


# --------------------------------------------------------------------------- #
def imagen_ubuntu(log: Log) -> tuple[str, str]:
    try:
        with urllib.request.urlopen(URL_INFO_DISTROS, timeout=20) as r:  # noqa: S310
            info = json.load(r)
    except Exception:  # noqa: BLE001
        info = None
    try:
        e = info["ModernDistributions"]["Ubuntu-24.04"][0]["Amd64Url"]
        log(f"Imagen oficial según Microsoft: {e['Url']}")
        return e["Url"], e["Sha256"].lower()
    except Exception:  # noqa: BLE001
        log("No pude leer el listado de Microsoft; uso la imagen de respaldo.")
        return IMAGEN_RESPALDO


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def descargar(url: str, destino: Path, hash_esperado: str, progreso: Callable[[float], None], cancelado: Callable[[], bool]) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and sha256(destino) == hash_esperado:
        return
    parcial = destino.with_suffix(destino.suffix + ".parte")
    with urllib.request.urlopen(url, timeout=60) as r, open(parcial, "wb") as f:  # noqa: S310
        total = int(r.headers.get("Content-Length") or 0)
        hecho = 0
        while True:
            if cancelado():
                raise ErrorPaso("Instalación cancelada.")
            bloque = r.read(1 << 20)
            if not bloque:
                break
            f.write(bloque)
            hecho += len(bloque)
            if total:
                progreso(hecho / total)
    if sha256(parcial) != hash_esperado:
        parcial.unlink(missing_ok=True)
        raise ErrorPaso("La imagen de Ubuntu descargada no coincide con su huella oficial (SHA-256). "
                        "Prueba de nuevo; si se repite, puede haber un problema en la red.")
    os.replace(parcial, destino)


def ruta_wsl(ruta_windows: Path) -> str:
    rc, salida = wsl.en_distro(["wslpath", "-a", str(ruta_windows)], 20)
    rutas = [l.strip() for l in salida.splitlines() if l.strip().startswith("/")]
    if rc != 0 or not rutas:
        raise ErrorPaso(f"No pude traducir la ruta {ruta_windows} para WSL.")
    return rutas[-1]


def comando_script(nombre: str, *args: str) -> list[str]:
    """Comando para ejecutar dentro de la distribución uno de los scripts de ``recursos/``.

    Se traduce su ruta, se limpian los saltos de línea de Windows y se ejecuta desde /tmp: así no se pasa
    texto multilínea por la línea de comandos de wsl.exe ni se consume la entrada estándar del script.
    """
    origen = ruta_wsl(carpeta_recursos() / nombre)
    cola = " ".join(shlex.quote(a) for a in args)
    return ["bash", "-c", f"tr -d '\\r' < {shlex.quote(origen)} > /tmp/{nombre} && bash /tmp/{nombre} {cola}"]


def owrx_instalado(version: str | None = None) -> bool:
    rc, salida = wsl.en_distro(["cat", MARCADOR], 20)
    if rc != 0:
        return False
    return version is None or salida.strip() == version


@dataclass
class Opciones:
    forzar_owrx: bool = False  # repetir la instalación de OpenWebRX+ aunque ya esté hecha


def ejecutar(log: Log, progreso: Progreso, cancelado: Callable[[], bool] = lambda: False,
             opciones: Opciones | None = None) -> None:
    op = opciones or Opciones()
    n = len(PASOS)

    def paso(i: int, fraccion: float | None = None, texto: str | None = None) -> None:
        progreso(i, texto or PASOS[i][1], fraccion)

    # 1 -- WSL ---------------------------------------------------------------
    paso(0)
    if not wsl.wsl_disponible():
        raise ErrorPaso("WSL no está activado en este equipo. Vuelve a ejecutar el instalador de PoorSDR4All "
                        "(prepara WSL con permisos de administrador); si Windows pide reiniciar, hazlo primero.")
    log("WSL disponible.")

    # 2/3 -- distribución -------------------------------------------------------
    if wsl.distro_instalada():
        log(f"La distribución {DISTRO} ya existe: salto la descarga y la creación.")
        paso(1, 1.0)
        paso(2, 1.0)
    else:
        paso(1, 0.0)
        url, hash_esperado = imagen_ubuntu(log)
        imagen = carpeta_datos() / "ubuntu-24.04.wsl"
        descargar(url, imagen, hash_esperado, lambda f: paso(1, f), cancelado)
        log("Imagen descargada y verificada (SHA-256).")
        paso(2, None)
        destino = carpeta_datos() / "distro"
        destino.mkdir(parents=True, exist_ok=True)
        rc, salida = wsl.ejecutar(["--import", DISTRO, str(destino), str(imagen), "--version", "2"], 900)
        log(salida.strip())
        if rc != 0:
            raise ErrorPaso("WSL no pudo crear el sistema Linux. ¿Está activada la virtualización "
                            "(VT-x / AMD-V) en la BIOS del equipo?")
        imagen.unlink(missing_ok=True)

    # 4 -- configuración -------------------------------------------------------
    paso(3)
    rc, salida = wsl.en_distro(comando_script("usuario.sh"), 60)
    log(salida.strip())
    if rc != 0:
        raise ErrorPaso("No se pudo configurar el usuario del sistema Linux. " + (salida.strip()[-300:] or f"(código {rc})"))
    wsl.apagar_distro()
    time.sleep(2)
    if not wsl.esperar_systemd():
        raise ErrorPaso("El sistema Linux no arrancó con systemd tras configurarlo.")

    # 5 -- OpenWebRX+ ------------------------------------------------------------
    paquete = ruta_paquete()
    version = version_paquete(paquete)
    if owrx_instalado(version) and not op.forzar_owrx:
        log(f"OpenWebRX+ ya está instalado (versión del paquete {version}).")
        paso(4, 1.0)
    else:
        paso(4, None)
        wsl.abrir_sesion_viva()
        try:
            exe = wsl.wsl_exe()
            p = subprocess.Popen(
                [exe, "-d", DISTRO, "-u", "poorsdr", "--exec",
                 *comando_script("instalar.sh", ruta_wsl(paquete), version)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=wsl.CREATE_NO_WINDOW)
            assert p.stdout is not None
            for crudo in iter(p.stdout.readline, b""):
                linea = crudo.decode("utf-8", "replace").rstrip()
                log(linea)
                if linea.startswith("==> "):
                    paso(4, None, "Instalando OpenWebRX+: " + linea[4:].strip()[:70])
                if cancelado():
                    p.terminate()
                    raise ErrorPaso("Instalación cancelada.")
            rc = p.wait()
        finally:
            wsl.cerrar_sesion_viva()
        if rc != 0:
            raise ErrorPaso("La instalación de OpenWebRX+ falló. El detalle está en el registro; "
                            "puedes reintentarlo desde «Reparar OpenWebRX+» en el menú Inicio.")

    # 6 -- comprobación --------------------------------------------------------------
    paso(5)
    wsl.abrir_sesion_viva()
    try:
        ok, detalle = wsl.arrancar_servicio()
        if not ok:
            raise ErrorPaso(f"OpenWebRX+ se instaló pero no arranca. {detalle}")
        url = "http://127.0.0.1:8073/"
        for _ in range(60):
            if wsl.servicio_listo(url):
                break
            time.sleep(1)
        else:
            raise ErrorPaso("OpenWebRX+ arrancó pero no responde en el puerto 8073.")
        log("OpenWebRX+ responde en http://127.0.0.1:8073/")
    finally:
        wsl.parar_servicio()
        wsl.cerrar_sesion_viva()
        wsl.apagar_distro()
    paso(n - 1, 1.0)
