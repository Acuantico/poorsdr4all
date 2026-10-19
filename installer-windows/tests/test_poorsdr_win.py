"""Pruebas de la lógica pura de poorsdr_win (se ejecutan en cualquier sistema, sin WSL)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poorsdr_win import setup, wsl  # noqa: E402


def test_decodificar_utf16_de_wsl():
    assert wsl.decodificar("Ubuntu\r\n".encode("utf-16-le")) == "Ubuntu\r\n"
    assert wsl.decodificar(b"\xff\xfe" + "Hola".encode("utf-16-le")).strip("﻿") != ""


def test_decodificar_utf8_de_dentro_de_la_distro():
    assert wsl.decodificar("running\n".encode()) == "running\n"
    assert wsl.decodificar(None) == ""
    assert wsl.decodificar(b"\xc3\xa1") == "á"


def test_ajustes_por_defecto_si_no_hay_config(tmp_path):
    a = wsl.leer_ajustes(tmp_path / "no-existe.json")
    assert (a.habilitado, a.host, a.puerto, a.parar_al_salir) == (True, "127.0.0.1", 8073, True)
    assert a.local and a.url == "http://127.0.0.1:8073/"


def test_ajustes_formato_anidado(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"owrx": {"enabled": True, "host": "192.168.1.5", "port": 8080, "stop_on_exit": False}}))
    a = wsl.leer_ajustes(f)
    assert not a.local and a.puerto == 8080 and not a.parar_al_salir
    assert a.url == "http://192.168.1.5:8080/"


def test_ajustes_formato_plano_y_runtime_no_nativo(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"OWRX_ENABLED": True, "OWRX_RUNTIME": "docker"}))
    assert wsl.leer_ajustes(f).habilitado is False


def test_ajustes_con_config_corrupta(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("{no es json")
    assert wsl.leer_ajustes(f).habilitado is True


def test_owrx_remoto_o_desactivado_no_toca_wsl(tmp_path, monkeypatch):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"owrx": {"host": "10.0.0.9"}}))
    monkeypatch.setattr(wsl, "ruta_config", lambda: f)
    monkeypatch.setattr(wsl, "wsl_disponible", lambda: (_ for _ in ()).throw(AssertionError("no debe consultar WSL")))
    r = wsl.asegurar_owrx()
    assert r.ok and not r.gestionado


def test_parar_solo_si_lo_gestionamos(monkeypatch):
    llamadas = []
    monkeypatch.setattr(wsl, "parar_servicio", lambda: llamadas.append("parar"))
    monkeypatch.setattr(wsl, "cerrar_sesion_viva", lambda: llamadas.append("sesion"))
    monkeypatch.setattr(wsl, "apagar_distro", lambda: llamadas.append("apagar"))
    wsl.parar_owrx(False)
    assert llamadas == []


def test_parar_respeta_no_parar_al_salir(tmp_path, monkeypatch):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"owrx": {"stop_on_exit": False}}))
    monkeypatch.setattr(wsl, "ruta_config", lambda: f)
    monkeypatch.setattr(wsl, "parar_servicio", lambda: (_ for _ in ()).throw(AssertionError("no debe parar")))
    wsl.parar_owrx(True)


def test_version_paquete():
    assert setup.version_paquete(Path("poorsdr4all-1.0.0a3.tar.gz")) == "1.0.0a3"


def test_comando_script_limpia_saltos_de_linea_y_cita(monkeypatch):
    monkeypatch.setattr(setup, "ruta_wsl", lambda p: "/mnt/c/Program Files/PoorSDR4All/x's/instalar.sh")
    cmd = setup.comando_script("instalar.sh", "/mnt/c/a b/paquete.tar.gz", "1.0.0a3")
    assert cmd[:2] == ["bash", "-c"]
    assert "tr -d '\\r'" in cmd[2]
    assert "'/mnt/c/Program Files/PoorSDR4All/x'\"'\"'s/instalar.sh'" in cmd[2]
    assert cmd[2].endswith("'/mnt/c/a b/paquete.tar.gz' 1.0.0a3")


def test_hash_de_respaldo_es_sha256_valido():
    url, h = setup.IMAGEN_RESPALDO
    assert url.startswith("https://releases.ubuntu.com/") and len(h) == 64 and int(h, 16) >= 0


def test_scripts_de_recursos_usan_lf():
    for nombre in ("usuario.sh", "instalar.sh"):
        datos = (setup.carpeta_recursos() / nombre).read_bytes()
        assert b"\r" not in datos and datos.startswith(b"#!/bin/bash")


# --- spiderd (spots) ---
def test_spots_activados_por_defecto_y_se_pueden_desactivar(tmp_path):
    assert wsl.leer_ajustes(tmp_path / "no.json").spots is True
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"owrx": {"spots": {"enabled": False}}}))
    assert wsl.leer_ajustes(f).spots is False
    f.write_text(json.dumps({"OWRX_SPOTS_ENABLED": False}))
    assert wsl.leer_ajustes(f).spots is False


def test_sincronizar_spiderd_sin_conf_no_hace_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(wsl, "ruta_config", lambda: tmp_path / "config.json")
    monkeypatch.setattr(wsl, "en_distro", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe llamar a WSL")))
    assert wsl.sincronizar_spiderd() is False


def test_sincronizar_spiderd_copia_solo_si_cambia(tmp_path, monkeypatch):
    monkeypatch.setattr(wsl, "ruta_config", lambda: tmp_path / "config.json")
    conf = tmp_path / "spiderd.conf"
    conf.write_text("[server]\nport = 7373\n")
    wsl._spider["huella"] = None
    llamadas = []

    def falso(cmd, timeout=60.0, usuario="root"):
        llamadas.append(cmd)
        return (0, "/mnt/c/x/spiderd.conf\n") if cmd[0] == "wslpath" else (0, "")

    monkeypatch.setattr(wsl, "en_distro", falso)
    assert wsl.sincronizar_spiderd() is True
    n = len(llamadas)
    assert llamadas[0][0] == "wslpath" and "systemctl --user restart spiderd.service" in llamadas[1][2]
    assert wsl.sincronizar_spiderd() is True and len(llamadas) == n  # sin cambios: no vuelve a copiar
    conf.write_text("[server]\nport = 7373\n# cambio\n")
    assert wsl.sincronizar_spiderd() is True and len(llamadas) > n  # cambió: copia y reinicia


def test_instalar_sh_ya_no_omite_spiderd_y_hay_linger():
    recursos = setup.carpeta_recursos()
    assert "SKIP_SPIDER" not in (recursos / "instalar.sh").read_text(encoding="utf-8")
    assert "linger/poorsdr" in (recursos / "usuario.sh").read_text(encoding="utf-8")


# --- SDR por USB (usbipd) ---
from poorsdr_win import usb  # noqa: E402

ESTADO = json.dumps({"Devices": [
    {"BusId": "1-2", "Description": "Bulk-In, Interface", "InstanceId": "USB\\VID_0BDA&PID_2838\\0001", "ClientIPAddress": None},
    {"BusId": "1-3", "Description": "Dispositivo de entrada USB", "InstanceId": "USB\\VID_0627&PID_0001\\x", "ClientIPAddress": None},
    {"BusId": "1-4", "Description": "Airspy", "InstanceId": "USB\\VID_1D50&PID_60A1\\y", "ClientIPAddress": "172.19.0.2"},
]})


def test_lista_de_sdr_trae_los_habituales():
    ids = usb.leer_ids()
    for h in ("0bda:2838", "1d50:60a1", "1d50:6089", "1df7:3010"):  # RTL-SDR, Airspy, HackRF, SDRplay
        assert h in ids
    assert len(ids) > 50 and all(len(k) == 9 for k in ids)


def test_parsear_estado():
    assert usb.parsear_estado(ESTADO)[0] == ("0bda:2838", "1-2", "Bulk-In, Interface", False)
    assert usb.parsear_estado("no es json") == []


def test_sdr_presentes_solo_los_de_la_lista(monkeypatch):
    monkeypatch.setattr(usb, "_ejecutar", lambda *a, **k: (0, ESTADO))
    d = usb.sdr_presentes({"0bda:2838": "RTL-SDR", "1d50:60a1": "Airspy"})
    assert [x.hardware_id for x in d] == ["0bda:2838", "1d50:60a1"] and d[1].conectado is True


class _Proc:
    def __init__(self, rc=None): self.rc = rc; self.terminated = False
    def poll(self): return self.rc
    returncode = property(lambda s: s.rc)
    def terminate(self): self.terminated = True; self.rc = 0
    def wait(self, timeout=None): return self.rc
    def kill(self): self.rc = -9


def test_sincronizar_conecta_una_vez_y_no_reintenta_los_rechazados(monkeypatch, tmp_path):
    monkeypatch.setattr(usb, "_ejecutar", lambda *a, **k: (0, ESTADO))
    lanzados = []

    def lanzar(h):
        lanzados.append(h)
        f = tmp_path / f"{len(lanzados)}.log"
        f.write_text("Device is not shared. Run bind as administrator")
        return usb._Conexion(_Proc(rc=1), f)  # falla enseguida: no autorizado

    g = usb.Gestor({"0bda:2838": "RTL-SDR"}, lanzar)
    assert g.sincronizar() == ["0bda:2838"]
    assert g.sincronizar() == []  # terminó con error: queda rechazado, no se reintenta en bucle
    assert "administrator" in g.rechazados["0bda:2838"]
    assert lanzados == ["0bda:2838"]


def test_aviso_si_no_hay_ningun_sdr(monkeypatch):
    monkeypatch.setattr(usb, "usbipd_exe", lambda: Path("usbipd.exe"))
    monkeypatch.setattr(usb, "_ejecutar", lambda *a, **k: (0, json.dumps({"Devices": []})))
    a = usb.Gestor({"0bda:2838": "RTL-SDR"}).conectar_iniciales(espera=0.1)
    assert a is not None and a.tipo == "ninguno" and "SDR" in a.texto


def test_sin_usbipd_no_se_avisa(monkeypatch):
    monkeypatch.setattr(usb, "usbipd_exe", lambda: None)
    assert usb.Gestor({"0bda:2838": "RTL-SDR"}).conectar_iniciales() is None


def test_aviso_no_autorizado(monkeypatch, tmp_path):
    monkeypatch.setattr(usb, "usbipd_exe", lambda: Path("usbipd.exe"))
    monkeypatch.setattr(usb, "_ejecutar", lambda *a, **k: (0, ESTADO))
    monkeypatch.setattr(usb, "visibles_en_wsl", lambda: set())
    monkeypatch.setattr(usb.time, "sleep", lambda s: None)

    def lanzar(h):
        f = tmp_path / "x.log"; f.write_text("not shared: run bind as administrator")
        return usb._Conexion(_Proc(rc=1), f)

    a = usb.Gestor({"0bda:2838": "RTL-SDR"}, lanzar).conectar_iniciales(espera=0.5)
    assert a.tipo == "no_autorizado" and "instalador" in a.texto


def test_detener_suelta_los_sdr(monkeypatch, tmp_path):
    llamadas = []
    monkeypatch.setattr(usb, "_ejecutar", lambda args, timeout=20.0: (llamadas.append(args) or (0, "")))
    g = usb.Gestor({"0bda:2838": "RTL-SDR"})
    p = _Proc(rc=None)
    g._conexiones["0bda:2838"] = usb._Conexion(p, tmp_path / "a.log")
    g.detener()
    assert p.terminated and ["detach", "--hardware-id", "0bda:2838"] in llamadas


# --- el punto de entrada despacha cada modo (esto habría detectado el acceso directo del libro abriendo la app) ---
def _entrada(monkeypatch, argv):
    import launch_poorsdr as lp

    llamadas = []
    for nombre in ("_libro", "_asistente", "_aplicacion", "_aviso"):
        monkeypatch.setattr(lp, nombre, lambda *a, _n=nombre: llamadas.append(_n) or 0)
    monkeypatch.setattr(lp.sys, "argv", ["PoorSDR4All.exe", *argv])
    lp.main()
    return llamadas


def test_libro_guardia_abre_solo_el_libro(monkeypatch):
    assert _entrada(monkeypatch, ["--libro-guardia"]) == ["_libro"]  # NO la app, NO OpenWebRX+, NO el aviso del SDR


def test_asistente_y_app_siguen_despachando(monkeypatch):
    assert _entrada(monkeypatch, ["--asistente-wsl"]) == ["_asistente"]
    assert _entrada(monkeypatch, ["--reparar-owrx"]) == ["_asistente"]
    assert _entrada(monkeypatch, []) == ["_aplicacion"]


def test_aviso_sdr_va_en_su_propia_ventana_y_no_bloquea_la_app(monkeypatch):
    assert _entrada(monkeypatch, ["--aviso-sdr", "x.json"]) == ["_aviso"]
    texto = (Path(__file__).resolve().parents[1] / "src" / "poorsdr_win" / "ui.py").read_text(encoding="utf-8")
    assert "ventana.aviso_sdr" not in texto  # antes se mostraba modal ANTES de abrir la consola
    assert "lanzar_aviso_sdr(aviso_pendiente)" in texto


# --- el aviso de «virtualización anidada» de wsl.exe sale a ratos, antes o después de la salida real ---
AVISO = "wsl: No se admite la virtualización anidada en esta máquina."


def test_limpiar_quita_el_aviso_se_imprima_antes_o_despues():
    assert wsl.limpiar(f"/mnt/c/x/usuario.sh\n{AVISO}") == "/mnt/c/x/usuario.sh"
    assert wsl.limpiar(f"{AVISO}\nrunning") == "running"
    assert wsl.limpiar("wsl: Nested virtualization is not supported on this machine.\ndegraded") == "degraded"
    assert wsl.limpiar("wsl: otro error distinto") == "wsl: otro error distinto"  # los errores reales se conservan


def test_ruta_wsl_no_confunde_el_aviso_con_la_ruta(monkeypatch):
    for salida in (f"/mnt/c/Program Files/x/usuario.sh\n{AVISO}", f"{AVISO}\n/mnt/c/Program Files/x/usuario.sh"):
        monkeypatch.setattr(setup.wsl, "en_distro", lambda *a, _s=salida, **k: (0, _s))  # sin pasar por limpiar()
        assert setup.ruta_wsl(Path("C:/x")) == "/mnt/c/Program Files/x/usuario.sh"


def test_sincronizar_spiderd_tolera_el_aviso(tmp_path, monkeypatch):
    monkeypatch.setattr(wsl, "ruta_config", lambda: tmp_path / "config.json")
    (tmp_path / "spiderd.conf").write_text("[server]\n")
    wsl._spider["huella"] = None
    cmds = []

    def falso(cmd, timeout=60.0, usuario="root"):
        cmds.append(cmd)
        return (0, f"/mnt/c/x/spiderd.conf\n{AVISO}") if cmd[0] == "wslpath" else (0, "")

    monkeypatch.setattr(wsl, "en_distro", falso)
    assert wsl.sincronizar_spiderd() is True and "/mnt/c/x/spiderd.conf" in cmds[1][2] and "anidada" not in cmds[1][2]
