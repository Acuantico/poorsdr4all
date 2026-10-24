"""Reúne las licencias de las dependencias de Python que acaban dentro del ejecutable de Windows.

Lo ejecuta ``construir.ps1`` con el Python del entorno de construcción, para que el
fichero instalado en ``licenses\\`` refleje exactamente lo que PyInstaller empaquetó
(BSD, MIT y Apache exigen conservar su aviso y su texto en las distribuciones binarias).

    python licencias_empaquetadas.py SALIDA.txt RAIZ[extra,...] [--excluir NOMBRE ...]

Recorre las dependencias (con sus extras) desde las raíces dadas, omite las excluidas
(p. ej. ``av``, que no va dentro del ejecutable) y escribe, por paquete: nombre, versión,
licencia declarada, web y el texto de cada fichero de licencia que trae en su metadato.
Falla si algún paquete no declara licencia ni trae su texto: así no se distribuye nada
sin revisar.
"""

from __future__ import annotations

import glob
import importlib.metadata as md
import os
import re
import sys

from packaging.requirements import Requirement

#: Herramientas de construcción que PyInstaller no empaqueta.
_NO_EMPAQUETADOS = {
    "pip", "wheel", "setuptools", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph",
    "pefile", "pywin32-ctypes", "packaging", "poorsdr4all", "poorsdr-rtty-power",
    "poorsdr-libro-guardia", "nmn1m",
}

_PATRON_LICENCIA = re.compile(r"(licen[sc]e|copying|notice|authors)", re.IGNORECASE)


def _norm(nombre: str) -> str:
    return re.sub(r"[-_.]+", "-", nombre).lower()


def _resolver(raices: list[str], excluir: set[str]) -> dict[str, md.Distribution]:
    vistos: dict[str, md.Distribution] = {}
    cola: list[tuple[str, tuple[str, ...]]] = []
    for raiz in raices:
        r = Requirement(raiz)
        cola.append((r.name, tuple(sorted(r.extras))))
    visitados: set[tuple[str, tuple[str, ...]]] = set()
    while cola:
        nombre, extras = cola.pop()
        clave = (_norm(nombre), extras)
        if clave in visitados:
            continue
        visitados.add(clave)
        try:
            dist = md.distribution(nombre)
        except md.PackageNotFoundError:
            continue  # dependencia de otra plataforma (p. ej. evdev en Windows)
        if _norm(nombre) not in excluir:
            vistos[_norm(nombre)] = dist
        for texto in dist.requires or []:
            req = Requirement(texto)
            if _norm(req.name) in excluir:
                continue
            if req.marker is not None and not any(
                req.marker.evaluate({"extra": e}) for e in (extras or ("",))
            ):
                continue
            cola.append((req.name, tuple(sorted(req.extras))))
    return vistos


def _licencia_declarada(dist: md.Distribution) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr
    texto = (meta.get("License") or "").strip().replace("\n", " ")
    if texto and len(texto) < 80:
        return texto
    clasif = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return "; ".join(clasif)


def _ficheros_licencia(dist: md.Distribution) -> list[tuple[str, str]]:
    salida: list[tuple[str, str]] = []
    for f in dist.files or []:
        partes = str(f).replace("\\", "/").split("/")
        if len(partes) < 2 or not partes[0].endswith(".dist-info"):
            continue
        if not _PATRON_LICENCIA.search(partes[-1]) or partes[-1].endswith((".py", ".pyc")):
            continue
        try:
            contenido = f.locate().read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if contenido.strip():
            salida.append(("/".join(partes[1:]), contenido.strip()))
    return salida


def _licencias_del_runtime() -> list[tuple[str, str, str]]:
    """Python y Tcl/Tk van dentro del ejecutable; sus licencias están en la instalación de Python."""
    base = sys.base_prefix
    candidatos = [
        ("Python", "PSF-2.0", [os.path.join(base, "LICENSE.txt"), os.path.join(base, "LICENSE")]),
        ("Tcl/Tk", "TCL (BSD-style)", glob.glob(os.path.join(base, "tcl", "**", "license.terms"), recursive=True)),
    ]
    filas = []
    for nombre, licencia, rutas in candidatos:
        for ruta in rutas:
            if os.path.isfile(ruta):
                with open(ruta, encoding="utf-8", errors="replace") as fh:
                    filas.append((nombre, licencia, fh.read().strip()))
                break
    return filas


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    salida, raices = argv[1], []
    excluir: set[str] = set()
    modo_excluir = False
    for a in argv[2:]:
        if a == "--excluir":
            modo_excluir = True
        elif modo_excluir:
            excluir.add(_norm(a))
        else:
            raices.append(a)
    paquetes = _resolver(raices, excluir | {_norm(n) for n in _NO_EMPAQUETADOS})
    sin_licencia = []
    bloques = [
        "LICENCIAS DE LOS COMPONENTES INCLUIDOS EN EL EJECUTABLE\n"
        + "=" * 56
        + "\n\nGenerado automáticamente al compilar el instalador. Cada componente conserva su\n"
        "licencia y sus avisos de copyright; los textos siguen a continuación.\n"
        "Los componentes de PoorSDR4All y de terceros que no van en el ejecutable están en\n"
        "THIRD_PARTY_NOTICES.md y LICENSES\\.\n"
    ]
    for nombre, licencia, texto in _licencias_del_runtime():
        bloques.append(f"\n{'-' * 72}\n{nombre}  —  {licencia}\n{'-' * 72}\n\n{texto}\n")
    for clave in sorted(paquetes):
        dist = paquetes[clave]
        meta = dist.metadata
        textos = _ficheros_licencia(dist)
        declarada = _licencia_declarada(dist)
        if not declarada and not textos:
            sin_licencia.append(clave)
        cabecera = f"{meta.get('Name', clave)} {dist.version}  —  {declarada or '(sin licencia declarada)'}"
        web = meta.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in meta.get_all("Project-URL") or [] if "," in u), ""
        )
        bloque = [f"\n{'-' * 72}\n{cabecera}\n"]
        if web:
            bloque.append(f"{web}\n")
        bloque.append(f"{'-' * 72}\n")
        for ruta, contenido in textos:
            bloque.append(f"\n[{ruta}]\n\n{contenido}\n")
        if not textos:
            bloque.append("\n(el paquete no incluye el texto en su metadato; ver la web indicada)\n")
        bloques.append("".join(bloque))
    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    with open(salida, "w", encoding="utf-8") as fh:
        fh.write("".join(bloques))
    print(f"{len(paquetes)} paquetes -> {salida}")
    if sin_licencia:
        print("SIN LICENCIA DECLARADA: " + ", ".join(sin_licencia), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
