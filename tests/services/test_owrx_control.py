"""OwrxControlService: servidor de control del visor (socket TCP real)."""

from __future__ import annotations

import base64
import json
import socket
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dataclasses import replace as _dc_replace  # noqa: E402

from poorsdr.config.model import AppConfig  # noqa: E402
from poorsdr.infra.events import EventBus  # noqa: E402
from poorsdr.services.base import ServiceState  # noqa: E402
from poorsdr.services.owrx_control import OwrxControlService, resolve_profile  # noqa: E402


def _sdr_cfg(source="sdr"):
    base = AppConfig()
    return replace(base, audio=replace(base.audio, rx_source=source))


class OwrxControlServiceTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.pushes: list[tuple] = []
        self.tunes: list[dict] = []
        self.bus.subscribe("owrx.tune", lambda ev: self.tunes.append(ev.data))
        self.svc = OwrxControlService(
            self.bus, _sdr_cfg(), audio_push=lambda d, r, c: self.pushes.append((len(d), r, c))
        )
        self.svc.start()
        self.addCleanup(self.svc.stop)

    def _connect(self) -> socket.socket:
        s = socket.create_connection(("127.0.0.1", self.svc.port), timeout=2)
        self.addCleanup(s.close)
        return s

    def _drain(self, sock: socket.socket, *, timeout: float = 0.15) -> list[dict]:
        sock.settimeout(timeout)
        buf = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except (TimeoutError, OSError):
            pass
        return [json.loads(line) for line in buf.split(b"\n") if line.strip()]

    def _fake_viewer(self) -> list[dict]:
        """Registra un visor falso; devuelve la lista donde se acumulan sus mensajes."""
        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        srv.settimeout(1.0)
        port = srv.getsockname()[1]

        def accept_loop() -> None:
            for _ in range(12):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    for line in conn.recv(4096).split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()
        self.addCleanup(srv.close)
        self.svc.set_viewer_port("waterfall", port)
        return received

    def test_running_with_port(self):
        self.assertEqual(self.svc.status.state, ServiceState.RUNNING)
        self.assertGreater(self.svc.port, 0)

    def test_sends_audio_capture_to_viewer(self):
        received = self._fake_viewer()
        time.sleep(0.2)
        self.assertIn({"type": "audio_capture", "enabled": True}, received)

    def test_audio_chunk_is_pushed(self):
        s = self._connect()
        self._drain(s)
        pcm = base64.b64encode(b"\x00\x01" * 480).decode()
        s.sendall((json.dumps({"type": "audio_chunk", "pcm": pcm, "sample_rate": 48000, "channels": 2}) + "\n").encode())
        for _ in range(50):
            if self.pushes:
                break
            time.sleep(0.01)
        self.assertEqual(self.pushes, [(960, 48000, 2)])

    def test_audio_chunk_ignored_in_radio_mode(self):
        self.svc.reconfigure(_sdr_cfg("radio"))
        s = self._connect()
        self._drain(s)
        pcm = base64.b64encode(b"xx").decode()
        s.sendall((json.dumps({"type": "audio_chunk", "pcm": pcm}) + "\n").encode())
        time.sleep(0.05)
        self.assertEqual(self.pushes, [])

    def test_tune_message_publishes_event(self):
        s = self._connect()
        self._drain(s)
        s.sendall((json.dumps({"type": "tune", "frequency": 14074000, "mode": "usb"}) + "\n").encode())
        for _ in range(50):
            if self.tunes:
                break
            time.sleep(0.01)
        self.assertEqual(self.tunes[0]["hz"], 14074000)

    def test_smeter_message_publishes_event(self):
        levels: list[dict] = []
        self.bus.subscribe("owrx.smeter", lambda ev: levels.append(ev.data))
        s = self._connect()
        self._drain(s)
        s.sendall((json.dumps({"type": "smeter", "dbfs": -42.5}) + "\n").encode())
        for _ in range(50):
            if levels:
                break
            time.sleep(0.01)
        self.assertEqual(levels[0]["dbfs"], -42.5)

    def test_smeter_message_ignores_unknown_extra_fields(self):
        # El S-metro se autocalibra en el lado de PoorSDR (NoiseFloorTracker);
        # campos extra que mande un visor viejo/futuro no deben romper nada.
        levels: list[dict] = []
        self.bus.subscribe("owrx.smeter", lambda ev: levels.append(ev.data))
        s = self._connect()
        self._drain(s)
        s.sendall((
            json.dumps({"type": "smeter", "dbfs": -20.0, "floor": -70.0, "ceiling": -15.0}) + "\n"
        ).encode())
        for _ in range(50):
            if levels:
                break
            time.sleep(0.01)
        self.assertEqual(levels[0], {"dbfs": -20.0})

    def test_smeter_message_without_dbfs_is_ignored(self):
        levels: list[dict] = []
        self.bus.subscribe("owrx.smeter", lambda ev: levels.append(ev.data))
        s = self._connect()
        self._drain(s)
        s.sendall((json.dumps({"type": "smeter"}) + "\n").encode())
        time.sleep(0.05)
        self.assertEqual(levels, [])

    def test_reconfigure_sends_capture_change_to_viewer(self):
        received = self._fake_viewer()
        time.sleep(0.1)
        received.clear()
        self.svc.reconfigure(_sdr_cfg("radio"))
        time.sleep(0.2)
        self.assertIn({"type": "audio_capture", "enabled": False}, received)

    def test_stop_closes_server(self):
        port = self.svc.port
        self.svc.stop()
        self.assertEqual(self.svc.status.state, ServiceState.STOPPED)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)


class ProfilePushTests(unittest.TestCase):
    def test_resolve_profile(self):
        base = AppConfig()
        cfg = _dc_replace(base, owrx=_dc_replace(base.owrx, band_profiles={"40m": "RTL 40m"}))
        self.assertEqual(resolve_profile(cfg, "40m"), "RTL 40m")
        # sin mapa: usa el hint
        cfg2 = _dc_replace(base, owrx=_dc_replace(base.owrx, sdr_hint="RTL", band_profiles={}))
        self.assertEqual(resolve_profile(cfg2, "20m"), "RTL 20m")
        # sin nada: la propia banda
        self.assertEqual(resolve_profile(base, "15m"), "15m")

    def test_band_change_sends_profile_to_viewer(self):
        bus = EventBus()
        base = AppConfig()
        cfg = _dc_replace(base, owrx=_dc_replace(base.owrx, band_profiles={"20m": "RTL 20m"}))
        svc = OwrxControlService(bus, cfg)
        svc.start()
        self.addCleanup(svc.stop)

        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        srv.settimeout(1.0)
        fake_viewer_port = srv.getsockname()[1]

        def accept_loop():
            for _ in range(16):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    data = conn.recv(4096)
                    for line in data.split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()

        svc.set_viewer_port("waterfall", fake_viewer_port)  # dispara un profile push
        bus.publish("radio.frequency", hz=14_074_000, source="ui")  # 20m
        time.sleep(0.3)
        srv.close()
        th.join(timeout=1)

        profiles = [m for m in received if m.get("type") == "profile"]
        self.assertTrue(profiles)
        self.assertEqual(profiles[-1]["profile"], "RTL 20m")
        # set_viewer_port también manda el estado de spots
        spots = [m for m in received if m.get("type") == "spots"]
        self.assertTrue(spots)
        self.assertEqual(set(spots[-1]), {"type", "enabled", "off", "modes", "retention_sec"})
        self.assertEqual(spots[-1]["modes"], ["CW", "DIGI", "SSB"])
        self.assertTrue(spots[-1]["enabled"])
        self.assertEqual(spots[-1]["retention_sec"], 600)

    def test_set_viewer_port_sends_current_tune(self):
        # El perfil por sí solo no sintoniza nada: al conectar un visor debe
        # llegarle también la frecuencia/modo reales del equipo.
        bus = EventBus()
        base = AppConfig()
        cfg = _dc_replace(base, cat=_dc_replace(base.cat, start_freq_hz=7_074_000))
        svc = OwrxControlService(bus, cfg)
        svc.start()
        self.addCleanup(svc.stop)

        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        srv.settimeout(1.0)
        port = srv.getsockname()[1]

        def accept_loop():
            for _ in range(16):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    for line in conn.recv(4096).split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()

        svc.set_viewer_port("waterfall", port)
        time.sleep(0.3)
        srv.close()
        th.join(timeout=1)

        tunes = [m for m in received if m.get("type") == "tune"]
        self.assertTrue(tunes)
        self.assertEqual(tunes[-1]["frequency"], 7_074_000)

    def test_viewer_opened_mid_session_gets_the_frequency_already_set(self):
        # El equipo ya cambió de frecuencia/modo antes de abrir el visor
        # (p.ej. desde el arranque): un visor nuevo debe recibir ese estado,
        # no el centro por defecto del perfil de banda.
        bus = EventBus()
        svc = OwrxControlService(bus, AppConfig())
        svc.start()
        self.addCleanup(svc.stop)
        bus.publish("radio.frequency", hz=21_074_000, source="ui")
        bus.publish("radio.mode", mode="cw", source="ui")

        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        srv.settimeout(1.0)
        port = srv.getsockname()[1]

        def accept_loop():
            for _ in range(16):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    for line in conn.recv(4096).split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()

        svc.set_viewer_port("waterfall", port)  # visor recién abierto, a media sesión
        time.sleep(0.3)
        srv.close()
        th.join(timeout=1)

        tunes = [m for m in received if m.get("type") == "tune"]
        self.assertTrue(tunes)
        self.assertEqual(tunes[-1]["frequency"], 21_074_000)
        self.assertEqual(tunes[-1]["mode"], "CW")

    def test_reconfigure_sends_spots_on_filter_change(self):
        bus = EventBus()
        svc = OwrxControlService(bus, AppConfig())
        svc.start()
        self.addCleanup(svc.stop)

        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        srv.settimeout(1.0)
        port = srv.getsockname()[1]

        def accept_loop():
            for _ in range(16):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    for line in conn.recv(4096).split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()
        svc.set_viewer_port("waterfall", port)
        received.clear()

        base = AppConfig()
        new = _dc_replace(
            base, owrx=_dc_replace(base.owrx, spots=_dc_replace(base.owrx.spots, filter_cw=False))
        )
        svc.reconfigure(new)
        time.sleep(0.2)
        srv.close()
        th.join(timeout=1)

        spots = [m for m in received if m.get("type") == "spots"]
        self.assertTrue(spots)
        self.assertEqual(spots[-1]["modes"], ["DIGI", "SSB"])

    def test_reconfigure_sends_new_retention(self):
        bus = EventBus()
        svc = OwrxControlService(bus, AppConfig())
        svc.start()
        self.addCleanup(svc.stop)

        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        srv.settimeout(1.0)
        port = srv.getsockname()[1]

        def accept_loop():
            for _ in range(16):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    for line in conn.recv(4096).split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()
        svc.set_viewer_port("waterfall", port)
        received.clear()

        base = AppConfig()
        new = _dc_replace(
            base, owrx=_dc_replace(base.owrx, spots=_dc_replace(base.owrx.spots, retention_min=3))
        )
        svc.reconfigure(new)
        time.sleep(0.2)
        srv.close()
        th.join(timeout=1)

        spots = [m for m in received if m.get("type") == "spots"]
        self.assertTrue(spots)
        self.assertEqual(spots[-1]["retention_sec"], 180)

    def test_set_step_sends_step_to_viewer(self):
        bus = EventBus()
        svc = OwrxControlService(bus, AppConfig())
        svc.start()
        self.addCleanup(svc.stop)

        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        srv.settimeout(1.0)
        port = srv.getsockname()[1]

        def accept_loop():
            for _ in range(16):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    for line in conn.recv(4096).split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()

        svc.set_viewer_port("waterfall", port)  # manda el step inicial
        svc.set_step(5000)  # cambio de paso desde la consola
        time.sleep(0.2)
        srv.close()
        th.join(timeout=1)

        steps = [m for m in received if m.get("type") == "step"]
        self.assertTrue(steps)
        self.assertEqual(steps[-1]["step_hz"], 5000)

    def test_viewer_reconnect_resends_step_and_spots(self):
        # set_viewer_port() ocurre antes de que el visor arranque; cuando el
        # visor conecta de vuelta a control debe recibir paso y spots de nuevo.
        bus = EventBus()
        cfg = _dc_replace(
            AppConfig(),
            cat=_dc_replace(AppConfig().cat, step_hz=5000),
        )
        svc = OwrxControlService(bus, cfg)
        svc.start()
        self.addCleanup(svc.stop)

        received: list[dict] = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        srv.settimeout(1.0)
        port = srv.getsockname()[1]

        def accept_loop():
            for _ in range(16):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    for line in conn.recv(4096).split(b"\n"):
                        if line.strip():
                            received.append(json.loads(line))

        th = __import__("threading").Thread(target=accept_loop, daemon=True)
        th.start()

        svc.set_viewer_port("waterfall", port)
        received.clear()
        # simula que el visor conecta de vuelta al socket de control
        back = socket.create_connection(("127.0.0.1", svc.port), timeout=2)
        self.addCleanup(back.close)
        time.sleep(0.3)
        srv.close()
        th.join(timeout=1)

        steps = [m for m in received if m.get("type") == "step"]
        spots = [m for m in received if m.get("type") == "spots"]
        self.assertTrue(steps)
        self.assertEqual(steps[-1]["step_hz"], 5000)
        self.assertTrue(spots)
        self.assertEqual(spots[-1]["modes"], ["CW", "DIGI", "SSB"])


if __name__ == "__main__":
    unittest.main()
