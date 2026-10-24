"""Punto de entrada del ejecutable de PoorSDR4All para Windows (PyInstaller).

Un único PoorSDR4All.exe hace varias cosas según cómo se le llame:

    PoorSDR4All.exe                          abre la aplicación (arranca OpenWebRX+ en WSL y lo para al salir)
    PoorSDR4All.exe <script.py> <args...>    ejecuta un script del propio paquete: así la app lanza sus ventanas
                                              auxiliares (cascada) cuando está empaquetada
    PoorSDR4All.exe -m <módulo> <args...>    equivalente a ``python -m``
    PoorSDR4All.exe --asistente-wsl          asistente que instala OpenWebRX+ en WSL2
    PoorSDR4All.exe --reparar-owrx           igual, repitiendo la instalación de OpenWebRX+
    PoorSDR4All.exe --asistente-wsl --sin-ventana   mismo trabajo, sin interfaz (pruebas / soporte)
    PoorSDR4All.exe --libro-guardia          abre el Libro de guardia (NMN1M) como programa independiente
    PoorSDR4All.exe --aviso-sdr <fichero>    ventana con el aviso de «SDR no disponible» (la lanza la propia app)
"""
import contextlib
import multiprocessing
import os
import runpy
import sys

# Sin consola (programa de ventanas) no hay salida estándar: algunas librerías la necesitan.
for _nombre in ("stdout", "stderr"):
    if getattr(sys, _nombre) is None:
        setattr(sys, _nombre, open(os.devnull, "w", encoding="utf-8"))
    else:  # la salida redirigida de Windows usa cp1252 y no admite lo que imprime install.sh (flechas, acentos...)
        try:
            getattr(sys, _nombre).reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _preparar_componentes_externos() -> None:
    """PyAV (con FFmpeg) no va dentro del ejecutable por la licencia de FFmpeg: el instalador lo descarga de
    PyPI en la carpeta ``extras`` junto al programa. Se añade al camino de importación (y sus DLL) antes de que
    nada intente ``import av``. También cubre las ventanas auxiliares, que se lanzan con este mismo ejecutable."""
    if not getattr(sys, "frozen", False):
        return
    extras = os.path.join(os.path.dirname(sys.executable), "extras")
    if not os.path.isdir(extras):
        return
    if extras not in sys.path:
        sys.path.insert(0, extras)
    libs = os.path.join(extras, "av.libs")
    if os.path.isdir(libs) and hasattr(os, "add_dll_directory"):
        with contextlib.suppress(OSError):
            os.add_dll_directory(libs)


_preparar_componentes_externos()


def _asistente(argumentos: list[str]) -> int:
    from poorsdr_win import ui

    forzar = "--reparar-owrx" in argumentos
    if "--sin-ventana" in argumentos:
        return ui.ejecutar_asistente_sin_ventana(forzar)
    return ui.ejecutar_asistente(forzar)


def _aplicacion() -> int:
    from poorsdr_win import ui, wsl

    resultado = wsl.Resultado(True)
    if sys.platform == "win32":
        resultado = ui.arrancar_con_owrx(lambda: _lanzar_asistente())
    try:
        from poorsdr.app import main

        return int(main() or 0)
    finally:
        wsl.parar_owrx(resultado.gestionado)


def _lanzar_asistente() -> None:
    import subprocess

    subprocess.Popen([sys.executable, "--asistente-wsl"], stdin=subprocess.DEVNULL, close_fds=True)


def _aviso(args: list[str]) -> int:
    from poorsdr_win import ui

    return ui.mostrar_aviso_sdr(args[1]) if len(args) > 1 else 1


def _libro() -> int:
    """Libro de guardia (NMN1M) como programa independiente: su propio acceso directo, icono y grupo en la barra."""
    import importlib.util
    import traceback
    from pathlib import Path

    def error(texto: str) -> int:
        try:
            import tkinter as tk
            from tkinter import messagebox

            raiz = tk.Tk()
            raiz.withdraw()
            messagebox.showerror("Libro de guardia (NMN1M)", texto)
        except Exception:  # noqa: BLE001
            pass
        return 1

    spec = importlib.util.find_spec("poorsdr_libro_guardia")
    if spec is None or not spec.submodule_search_locations:
        return error("El Libro de guardia no está instalado.\n\nVuelve a ejecutar el instalador de PoorSDR4All y marca "
                     "«Libro de guardia (NMN1M)».")
    script = Path(list(spec.submodule_search_locations)[0]) / "Libro-Guardia.py"
    if sys.platform == "win32":  # identidad propia: el botón de la barra de tareas usa el icono del libro, no el de PoorSDR4All
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Acuantico.NMN1M.LibroGuardia")
        except Exception:  # noqa: BLE001
            pass
    try:
        os.chdir(script.parent)
        sys.argv = [str(script)]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        registro = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "poorsdr" / "logs" / "libro-guardia-error.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        registro.write_text(traceback.format_exc(), encoding="utf-8")
        return error(f"No se pudo abrir el Libro de guardia.\n\nDetalle en: {registro}")


def main() -> int:
    multiprocessing.freeze_support()
    args = sys.argv[1:]
    if args and args[0] == "--libro-guardia":
        return _libro()
    if args and args[0] == "--aviso-sdr":
        return _aviso(args)
    if args and args[0] in ("--asistente-wsl", "--reparar-owrx"):
        return _asistente(args)
    if args and args[0] == "-m" and len(args) >= 2:
        modulo = args[1]
        sys.argv = [sys.argv[0]] + args[2:]
        runpy.run_module(modulo, run_name="__main__", alter_sys=True)
        return 0
    if args and args[0].lower().endswith(".py"):
        sys.argv = args
        runpy.run_path(args[0], run_name="__main__")
        return 0
    return _aplicacion()


if __name__ == "__main__":
    sys.exit(main())
