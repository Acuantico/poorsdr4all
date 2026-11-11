#!/usr/bin/env python3
"""Banco de pruebas del control remoto (servidor web + WebRTC), sin radio real.

Mide lo que nota el operador en remoto:

* **RX**: retraso desde que el audio entra por la tarjeta de la radio hasta que
  llega al cliente WebRTC.
* **TX**: retraso desde que el cliente emite voz hasta que sale por la tarjeta
  hacia la radio, y cuánto tarda en salir la primera voz tras pulsar el PTT.
* **PTT seguro**: si el cliente desaparece con el PTT pulsado (red caída,
  móvil bloqueado), cuánto tarda el servidor en soltarlo.

Todo va aislado: crea salidas de audio virtuales de PipeWire/Pulse (que borra al
terminar), una configuración temporal (no toca la tuya) y arranca radio + audio +
web sin interfaz en 127.0.0.1. El cliente es aiortc, con el búfer de jitter
directo para medir el servidor y no el colchón del propio cliente.

Uso (desde la raíz del proyecto):
    uv run --extra web python scripts/bench_remoto.py [--rondas 8]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from fractions import Fraction
from pathlib import Path

RATE = 48_000
FRAME = 960                  # 20 ms
BLOCK = 480                  # 10 ms para grabar/reproducir por pacat/parec
PORT = 18_080
TONE_HZ = 1_000.0
BURST_MS = 40
THRESH = 0.05                # RMS por bloque de 2,5 ms para dar por detectado el pulso
SINKS = {
    "rx": "psdrb_rx",        # entrada de la radio (aquí se inyecta "lo que recibe")
    "tx": "psdrb_tx",        # salida hacia la radio (aquí sale la voz del cliente)
    "spk": "psdrb_spk",      # altavoz del PC
    "mic": "psdrb_mic",      # micrófono del PC (silencio)
}

ROOT = Path(__file__).resolve().parents[1]

# --vpn: todo pasa por el túnel WireGuard, como un móvil fuera de casa. El
# cliente WireGuard es scripts/vpn/wgrelay (compilado en WGRELAY): expone la
# web en 127.0.0.1:VPN_TCP_LOCAL y cada puerto de audio del túnel en
# <IP LAN>:(puerto + VPN_AUDIO_OFFSET). El cliente anuncia candidatos
# inalcanzables, así que el servidor no puede llegarle por fuera del túnel.
VPN_UDP = 51_871
VPN_TCP_LOCAL = 18_443
VPN_AUDIO_OFFSET = 100
WGRELAY = Path(os.environ.get("WGRELAY", Path.home() / ".cache" / "psdr-bench" / "wgrelay"))
_vpn = {"on": os.environ.get("BENCH_VPN_LAN", "") != "", "lan": os.environ.get("BENCH_VPN_LAN", "")}


def _lan_ip() -> str:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]


def _hide_candidates(sdp: str) -> str:
    """Candidatos del cliente inalcanzables (como un móvil en datos)."""
    import re

    return re.sub(r"(a=candidate:\S+ \d+ \S+ \d+ )(\S+)( \d+ typ)", r"\g<1>203.0.113.1\3", sdp)


def _answer_via_relay(sdp: str) -> str:
    """Los candidatos del servidor (10.9.0.1:518xx) apuntan al relé."""
    import re

    return re.sub(r"10\.9\.0\.1 (518\d\d)", lambda m: f"{_vpn['lan']} {int(m.group(1)) + VPN_AUDIO_OFFSET}", sdp)


# --------------------------------------------------------------------------- #
# Entorno aislado
# --------------------------------------------------------------------------- #
def prepare_env() -> Path:
    base = Path.home() / ".cache" / "psdr-bench" / time.strftime("run-%Y%m%d-%H%M%S")
    for sub in ("config", "data", "cache", "state"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = str(base / "config")
    os.environ["XDG_DATA_HOME"] = str(base / "data")
    os.environ["XDG_CACHE_HOME"] = str(base / "cache")
    os.environ["XDG_STATE_HOME"] = str(base / "state")
    os.environ["POORSDR_LEGACY_HOME"] = str(base / "sin-config-antigua")  # no leer la tuya
    sys.path.insert(0, str(ROOT / "src"))
    return base


def load_sinks() -> list[int]:
    ids = []
    for name in SINKS.values():
        out = subprocess.run(
            ["pactl", "load-module", "module-null-sink", f"sink_name={name}",
             f"sink_properties=device.description={name}", "rate=48000", "channels=2"],
            capture_output=True, text=True, check=True,
        )
        ids.append(int(out.stdout.strip()))
    # PoorSDR no admite monitores como micrófono/entrada: fuentes normales encima.
    for name in (SINKS["rx"], SINKS["mic"]):
        out = subprocess.run(
            ["pactl", "load-module", "module-remap-source", f"master={name}.monitor",
             f"source_name={name}_src", f"source_properties=device.description={name}_src"],
            capture_output=True, text=True, check=True,
        )
        ids.append(int(out.stdout.strip()))
    time.sleep(0.5)
    return ids


def unload_sinks(ids: list[int]) -> None:
    for mid in reversed(ids):
        subprocess.run(["pactl", "unload-module", str(mid)], capture_output=True)


def write_config(password: str, vpn: bool = False) -> object:
    from dataclasses import replace

    from poorsdr import runtime
    from poorsdr.config import loader
    from poorsdr.config.model import AudioDevice

    runtime.install_vendor_path()

    def hash_password(password: str, salt: str) -> str:
        # Igual que webserver.hash_password; no se importa webserver aquí porque
        # arrastra el módulo de audio, que leería su configuración antes de tiempo.
        import hashlib

        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000).hex()

    cfg = loader.load()
    salt = secrets.token_hex(16)

    def dev(name: str, ch: int = 2) -> AudioDevice:
        return AudioDevice(label=name, pulse=name, index=-1, channels=ch, framerate=RATE)

    audio = replace(
        cfg.audio,
        speaker_pc=dev(SINKS["spk"]),
        mic_pc=dev(SINKS["mic"] + "_src"),
        speaker_radio=dev(SINKS["rx"] + "_src"),       # lo que llega de la radio
        mic_radio=dev(SINKS["tx"]),                    # lo que se envía a la radio
        rx_source="radio",
    )
    web = replace(
        cfg.web, enabled=True, host="127.0.0.1", port=PORT, allow_wan=False, auto_https=False,
        user="bench", password_salt=salt, password_hash=hash_password(password, salt),
        secret=secrets.token_hex(32), vpn_enabled=vpn, vpn_port=VPN_UDP,
    )
    cfg = replace(cfg, audio=audio, web=web, cat=replace(cfg.cat, port=""))
    loader.save(cfg)
    return cfg


# --------------------------------------------------------------------------- #
# Grabación / reproducción en las salidas virtuales
# --------------------------------------------------------------------------- #
class Recorder(threading.Thread):
    """Lee un monitor con parec en bloques de 10 ms y guarda (instante, muestras)."""

    def __init__(self, source: str):
        super().__init__(daemon=True)
        self.proc = subprocess.Popen(
            ["parec", "-d", source, "--format=s16le", f"--rate={RATE}", "--channels=1",
             "--latency-msec=5", "--raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.blocks: list[tuple[float, object]] = []
        self.lock = threading.Lock()
        self.alive = True

    def run(self) -> None:
        import numpy as np

        n = BLOCK * 2
        while self.alive:
            data = self.proc.stdout.read(n)
            if not data:
                break
            t = time.monotonic()
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            with self.lock:
                self.blocks.append((t - len(x) / RATE, x))  # instante del 1.er dato del bloque

    def onset_after(self, t0: float) -> float | None:
        with self.lock:
            blocks = [b for b in self.blocks if b[0] >= t0 - 0.02]
        return _first_onset(blocks)

    def stop(self) -> None:
        self.alive = False
        self.proc.terminate()


class Player(threading.Thread):
    """Reproduce en tiempo real silencio y, cuando se pida, un pulso de tono."""

    def __init__(self, sink: str):
        super().__init__(daemon=True)
        self.proc = subprocess.Popen(
            ["pacat", "-d", sink, "--format=s16le", f"--rate={RATE}", "--channels=1",
             "--latency-msec=10", "--raw"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.pending = 0
        self.alive = True

    def burst(self) -> None:
        self.pending = int(RATE * BURST_MS / 1000)

    def run(self) -> None:
        import numpy as np

        t_next = time.monotonic()
        phase = 0
        while self.alive:
            block = np.zeros(BLOCK, dtype=np.float32)
            if self.pending > 0:
                n = min(BLOCK, self.pending)
                idx = np.arange(phase, phase + n)
                block[:n] = 0.5 * np.sin(2 * np.pi * TONE_HZ * idx / RATE)
                phase += n
                self.pending -= n
            try:
                self.proc.stdin.write((block * 32767).astype(np.int16).tobytes())
                self.proc.stdin.flush()
            except BrokenPipeError:
                return
            t_next += BLOCK / RATE
            time.sleep(max(0.0, t_next - time.monotonic()))

    def stop(self) -> None:
        self.alive = False
        self.proc.terminate()


def _first_onset(blocks) -> float | None:
    import numpy as np

    sub = 120  # 2,5 ms
    for t, x in blocks:
        for i in range(0, len(x) - sub + 1, sub):
            seg = x[i:i + sub]
            if float(np.sqrt(np.mean(seg * seg))) > THRESH:
                return t + i / RATE
    return None


# --------------------------------------------------------------------------- #
# Cliente WebRTC (aiortc)
# --------------------------------------------------------------------------- #
def patch_client_jitter() -> None:
    """Búfer de jitter directo en el cliente: medimos servidor + red, no su colchón."""
    import aiortc.rtcrtpreceiver as rx
    from aiortc.jitterbuffer import JitterBuffer, JitterFrame, uint16_add

    class Direct:
        def __init__(self, capacity=16, prefetch=0, is_video=False):
            self._capacity, self._last = capacity, None

        @property
        def capacity(self):
            return self._capacity

        def add(self, packet):
            sn = packet.sequence_number
            if self._last is not None:
                d = uint16_add(sn, -self._last)
                if d == 0 or d >= 0x8000:
                    return False, None
            self._last = sn
            return False, JitterFrame(data=packet._data, timestamp=packet.timestamp)

    def factory(capacity, prefetch=0, is_video=False):
        return JitterBuffer(capacity, prefetch, True) if is_video else Direct(capacity)

    rx.JitterBuffer = factory


def http(method: str, path: str, token: str = "", body: dict | None = None, timeout: float = 5.0):
    data = json.dumps(body).encode() if body is not None else None
    kw = {}
    if _vpn["on"]:
        import ssl

        req = urllib.request.Request(f"https://127.0.0.1:{VPN_TCP_LOCAL}{path}", data=data, method=method)
        req.add_header("Host", f"10.9.0.1:{PORT}")  # como el navegador del móvil
        kw["context"] = ssl._create_unverified_context()
    else:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout, **kw) as resp:
        body = resp.read() or b"{}"
        return json.loads(body) if path.startswith("/api") else {}


class Client:
    def __init__(self, token: str):
        import av
        import numpy as np
        from aiortc import MediaStreamTrack, RTCPeerConnection

        self.token = token
        self.pc = RTCPeerConnection()
        self.rx_frames: list[tuple[float, object]] = []
        self.emits: list[float] = []         # instante en que empieza cada pulso emitido
        self._emit_pending = 0
        self._continuous = False
        self.channel = None
        client = self

        class TxTrack(MediaStreamTrack):
            kind = "audio"

            def __init__(self):
                super().__init__()
                self.pts = 0
                self.t0 = None
                self.phase = 0

            async def recv(self):
                if self.t0 is None:
                    self.t0 = time.monotonic()
                target = self.t0 + self.pts / RATE
                await asyncio.sleep(max(0.0, target - time.monotonic()))
                x = np.zeros(FRAME, dtype=np.float32)
                start = None
                if client._continuous:
                    n = FRAME
                elif client._emit_pending > 0:
                    n = min(FRAME, client._emit_pending)
                    client._emit_pending -= n
                    start = 0
                else:
                    n = 0
                if n:
                    idx = np.arange(self.phase, self.phase + n)
                    x[:n] = 0.5 * np.sin(2 * np.pi * TONE_HZ * idx / RATE)
                    self.phase += n
                if start is not None and n == min(FRAME, int(RATE * BURST_MS / 1000)):
                    client.emits.append(time.monotonic())
                frame = av.AudioFrame(format="s16", layout="mono", samples=FRAME)
                frame.planes[0].update((x * 32767).astype(np.int16).tobytes())
                frame.sample_rate = RATE
                frame.pts = self.pts
                frame.time_base = Fraction(1, RATE)
                self.pts += FRAME
                return frame

        self.tx = TxTrack()

        @self.pc.on("track")
        def on_track(track):
            async def consume():
                while True:
                    try:
                        f = await track.recv()
                    except Exception:
                        return
                    t = time.monotonic()
                    a = f.to_ndarray().astype(np.float32).reshape(-1)
                    ch = len(f.layout.channels)
                    if ch > 1:
                        a = a.reshape(-1, ch).mean(axis=1)
                    a /= 32768.0
                    client.rx_frames.append((t - len(a) / f.sample_rate, a))
            asyncio.ensure_future(consume())

    def emit_burst(self) -> None:
        self._emit_pending = int(RATE * BURST_MS / 1000)

    async def connect(self, with_ptt_channel: bool) -> None:
        self.pc.addTransceiver(self.tx, direction="sendrecv")
        if with_ptt_channel:
            self.channel = self.pc.createDataChannel("ptt", ordered=True)
        await self.pc.setLocalDescription(await self.pc.createOffer())
        while self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.05)
        offer_sdp = self.pc.localDescription.sdp
        if _vpn["on"]:
            offer_sdp = _hide_candidates(offer_sdp)
        ans = await asyncio.to_thread(
            http, "POST", "/api/webrtc/offer", self.token,
            {"sdp": offer_sdp, "type": self.pc.localDescription.type},
        )
        from aiortc import RTCSessionDescription

        answer_sdp = _answer_via_relay(ans["sdp"]) if _vpn["on"] else ans["sdp"]
        self.via_tunnel = "10.9.0.1" in ans["sdp"]
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type=ans["type"]))
        t = time.monotonic()
        while self.pc.connectionState != "connected" and time.monotonic() - t < 10:
            await asyncio.sleep(0.05)

    def rx_onset_after(self, t0: float) -> float | None:
        return _first_onset([b for b in self.rx_frames if b[0] >= t0 - 0.02])


# --------------------------------------------------------------------------- #
# Pruebas
# --------------------------------------------------------------------------- #
def _stats(name: str, values: list[float]) -> dict:
    ok = [v for v in values if v is not None]
    if not ok:
        print(f"  {name}: sin detecciones")
        return {"n": 0}
    ms = [v * 1000 for v in ok]
    res = {"n": len(ms), "mediana_ms": round(statistics.median(ms), 1),
           "min_ms": round(min(ms), 1), "max_ms": round(max(ms), 1)}
    print(f"  {name}: mediana {res['mediana_ms']} ms (min {res['min_ms']}, max {res['max_ms']}, n={res['n']}/{len(values)})")
    return res


def _rx_gaps(t0: float, t1: float) -> tuple[int, int]:
    """(bloques servidos, bloques rellenos de silencio) por la pista RX entre
    t0 y t1 (hora de pared), del diagnóstico que el servidor anota cada 2 s."""
    import re

    path = sys.modules["paths"].runtime_path("web_server_requests.log")
    frames = gaps = 0
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0, 0
    for line in lines:
        m = re.match(r"ts=(\d+) media=webrtc_rx_diag frames=(\d+) underruns=(\d+)", line)
        if m and t0 + 2 <= int(m.group(1)) <= t1:
            frames += int(m.group(2))
            gaps += int(m.group(3))
    return frames, gaps


def _tap_rx_queue() -> dict:
    """Desglose del RX: fecha lo que entra y sale de la cola de audio_remote
    (envuelve sus funciones en este proceso; el producto no cambia)."""
    import numpy as np

    ar = sys.modules["audio_remote"]
    orig_push, orig_pop = ar.push_rx_audio, ar.pop_rx_audio
    taps: dict = {"push": [], "pop": [], "orig": (orig_push, orig_pop)}

    taps["depth"], taps["sizes"] = [], []

    def push(data, *a, **k):
        x = np.asarray(data, dtype=np.float32).ravel()
        taps["push"].append((time.monotonic() - len(x) / RATE, x.copy()))
        taps["sizes"].append(len(x))
        return orig_push(data, *a, **k)

    def pop(*a, **k):
        q = ar._listeners.get(a[0]) if a else None
        if q is not None:
            taps["depth"].append(len(q))
        out = orig_pop(*a, **k)
        if out is not None:
            x = np.asarray(out, dtype=np.float32).ravel()
            taps["pop"].append((time.monotonic(), x.copy()))
        return out

    ar.push_rx_audio, ar.pop_rx_audio = push, pop
    return taps


async def bench(rondas: int, ctx, ptt_mode: str, desglose: bool = False) -> dict:
    token = (await asyncio.to_thread(http, "POST", "/api/auth/login", "", {"username": "bench", "password": BENCH_PASS}))["token"]
    rec_rx = Recorder(SINKS["rx"] + ".monitor"); rec_rx.start()
    rec_tx = Recorder(SINKS["tx"] + ".monitor"); rec_tx.start()
    player = Player(SINKS["rx"]); player.start()
    client = Client(token)
    await client.connect(with_ptt_channel=(ptt_mode == "canal"))
    tunnel = " (audio por el túnel)" if getattr(client, "via_tunnel", False) else ""
    print(f"  conexión WebRTC: {client.pc.connectionState}{tunnel}")
    await asyncio.sleep(2.0)
    results: dict = {}

    # --- RX ---
    rx = []
    parts: dict = {"captura": [], "cola": [], "envio": []}
    taps = _tap_rx_queue() if desglose else None
    rx_wall0 = time.time()
    for _ in range(rondas):
        t0 = time.monotonic()
        player.burst()
        await asyncio.sleep(0.6)
        a = rec_rx.onset_after(t0)
        b = client.rx_onset_after(t0)
        rx.append((b - a) if (a and b) else None)
        if taps is not None:
            p = _first_onset([x for x in taps["push"] if x[0] >= t0 - 0.02])
            q = _first_onset([x for x in taps["pop"] if x[0] >= t0 - 0.02])
            parts["captura"].append((p - a) if (a and p) else None)
            parts["cola"].append((q - p) if (p and q) else None)
            parts["envio"].append((b - q) if (q and b) else None)
    results["rx"] = _stats("RX (radio → cliente)", rx)
    if taps is not None:
        ar = sys.modules["audio_remote"]
        ar.push_rx_audio, ar.pop_rx_audio = taps["orig"]
        results["rx_desglose"] = {k: _stats(f"  RX {k}", v) for k, v in parts.items()}
        from collections import Counter

        print(f"    cola al sacar (bloques: veces): {sorted(Counter(taps['depth']).items())}")
        print(f"    tamaños que entran: {sorted(Counter(taps['sizes']).items())[:6]}")
        pushes = [t for t, _ in taps["push"]]
        gaps = sorted(round((b - a) * 1000) for a, b in zip(pushes, pushes[1:]))
        if gaps:
            print(f"    entre entradas (ms): p10 {gaps[len(gaps)//10]}, mediana {gaps[len(gaps)//2]}, p90 {gaps[len(gaps)*9//10]}")
    await asyncio.sleep(2.2)  # que el servidor anote el último tramo
    frames, gaps = _rx_gaps(rx_wall0, time.time())
    results["rx_huecos"] = {"bloques": frames, "huecos": gaps}
    print(f"  RX huecos: {gaps} de {frames} bloques de 20 ms")

    radio = ctx.services.get("radio")

    # Como la web: cada pulsación tiene su número y los latidos lo repiten
    # (canal cada 100 ms, HTTP cada 250 ms).
    press = {"n": 0}

    async def send(on: bool) -> None:
        if ptt_mode == "canal" and client.channel is not None:
            client.channel.send(f"P{1 if on else 0}:{press['n']}")
        else:
            await asyncio.to_thread(http, "POST", "/api/ptt", token, {"state": on, "press": press["n"]})

    async def ptt(on: bool) -> float:
        t = time.monotonic()
        if on:
            press["n"] += 1
        await send(on)
        return t

    async def hold(seconds: float) -> None:
        end = time.monotonic() + seconds
        period = 0.1 if ptt_mode == "canal" else 0.25
        while time.monotonic() < end:
            await asyncio.sleep(min(period, max(0.0, end - time.monotonic())))
            if time.monotonic() < end:
                await send(True)

    # --- PTT -> primera voz en la salida a la radio ---
    first = []
    for _ in range(max(3, rondas // 2)):
        client._continuous = True
        t = await ptt(True)
        await hold(1.2)
        on = rec_tx.onset_after(t)
        first.append((on - t) if on else None)
        await ptt(False)
        client._continuous = False
        await asyncio.sleep(1.2)
    results["ptt_a_voz"] = _stats("PTT → primera voz en la radio", first)

    # --- TX: retraso de la voz con el PTT ya pulsado ---
    await ptt(True)
    await hold(1.0)
    tx = []
    for _ in range(rondas):
        client.emit_burst()
        n0 = len(client.emits)
        await hold(0.6)
        if len(client.emits) > n0:
            te = client.emits[n0]
            on = rec_tx.onset_after(te)
            tx.append((on - te) if on else None)
        else:
            tx.append(None)
    await ptt(False)
    results["tx"] = _stats("TX (cliente → radio)", tx)
    await asyncio.sleep(1.0)
    results["ptt_tras_soltar"] = bool(radio.ptt)
    print(f"  PTT tras soltar: {'PULSADO (mal)' if radio.ptt else 'suelto'}")
    # Un latido de esa pulsación que llega tarde no debe volver a transmitir.
    await send(True)
    await asyncio.sleep(0.4)
    results["latido_tardio_retransmite"] = bool(radio.ptt)
    print(f"  latido tardío tras soltar: {'VUELVE A TX (mal)' if radio.ptt else 'ignorado'}")
    if radio.ptt:
        await ptt(False)

    await client.pc.close()
    for r in (rec_rx, rec_tx, player):
        r.stop()
    return results


def start_relay() -> subprocess.Popen:
    """Da de alta un dispositivo en la VPN y conecta wgrelay como si fuera él."""
    import vpn as vpnmod  # _vendor/vpn.py, el mismo que usa el servidor

    if not vpnmod.get_manager().running:
        raise SystemExit(f"  la VPN no arrancó: {vpnmod.get_manager().error}")
    if not WGRELAY.is_file():
        raise SystemExit(f"  falta {WGRELAY} (cd scripts/vpn/wgrelay && go build -o {WGRELAY} .)")
    _vpn["on"], _vpn["lan"] = True, _lan_ip()
    os.environ["BENCH_VPN_LAN"] = _vpn["lan"]  # para el cliente colgado (otro proceso)
    peer = vpnmod.add_device("banco")
    cmd = [
        str(WGRELAY), "-priv", peer["private_key"], "-server-pub", vpnmod.load()["server_public_key"],
        "-endpoint", f"127.0.0.1:{VPN_UDP}", "-ip", peer["ip"], "-bind", _vpn["lan"],
        "-tcp", f"{VPN_TCP_LOCAL}:{PORT}",
    ]
    for port in vpnmod.AUDIO_PORTS:
        cmd += ["-udp", f"{port + VPN_AUDIO_OFFSET}:{port}"]
    relay = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    if relay.stdout.readline().strip() != "ready":
        raise SystemExit("  wgrelay no arrancó")
    print(f"  VPN: túnel {vpnmod.SERVER_IP} (UDP {VPN_UDP}), dispositivo {peer['ip']}")
    return relay


def deadman_test(ctx, ptt_mode: str) -> dict:
    """Cliente en otro proceso pulsa el PTT y se le mata (como una red caída)."""
    proc = subprocess.Popen(
        [sys.executable, __file__, "--cliente-colgado", ptt_mode],
        env=os.environ.copy(), stdout=subprocess.PIPE, text=True,
    )
    radio = ctx.services.get("radio")
    t = time.monotonic()
    while not radio.ptt and time.monotonic() - t < 20:
        time.sleep(0.02)
    if not radio.ptt:
        print("  hombre muerto: el cliente no llegó a pulsar el PTT")
        proc.kill()
        return {"ok": False}
    time.sleep(1.0)
    os.kill(proc.pid, signal.SIGKILL)
    t_kill = time.monotonic()
    while radio.ptt and time.monotonic() - t_kill < 45:
        time.sleep(0.02)
    if radio.ptt:
        print("  hombre muerto: el PTT SIGUE PULSADO 45 s después de perder el cliente")
        return {"suelta_ms": None}
    ms = round((time.monotonic() - t_kill) * 1000)
    print(f"  hombre muerto: PTT suelto {ms} ms después de perder el cliente")
    return {"suelta_ms": ms}


async def hung_client(ptt_mode: str) -> None:
    """Modo hijo: conecta, pulsa el PTT (y su latido) y se queda colgado."""
    patch_client_jitter()
    token = (await asyncio.to_thread(http, "POST", "/api/auth/login", "", {"username": "bench", "password": BENCH_PASS}))["token"]
    c = Client(token)
    await c.connect(with_ptt_channel=(ptt_mode == "canal"))
    press = 1
    if ptt_mode == "canal":
        while c.channel is None or c.channel.readyState != "open":
            await asyncio.sleep(0.02)
    while True:
        if ptt_mode == "canal":
            c.channel.send(f"P1:{press}")
            await asyncio.sleep(0.1)
        else:
            await asyncio.to_thread(http, "POST", "/api/ptt", token, {"state": True, "press": press})
            await asyncio.sleep(0.25)


BENCH_PASS = "bench-" + "x" * 8


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rondas", type=int, default=8)
    ap.add_argument("--ptt", choices=("http", "canal"), default="http",
                    help="cómo manda el PTT el cliente: peticiones HTTP o canal de datos WebRTC")
    ap.add_argument("--cliente-colgado", choices=("http", "canal"))
    ap.add_argument("--json", help="guardar resultados en este fichero")
    ap.add_argument("--desglose", action="store_true", help="desglosar el retraso RX (captura, cola, envío)")
    ap.add_argument("--vpn", action="store_true", help="todo por la VPN WireGuard (necesita WGRELAY)")
    args = ap.parse_args()

    if args.cliente_colgado:
        sys.path.insert(0, str(ROOT / "src"))
        asyncio.run(hung_client(args.cliente_colgado))
        return 0

    base = prepare_env()
    sinks = load_sinks()
    ctx = None
    relay = None
    try:
        write_config(BENCH_PASS, vpn=args.vpn)
        from poorsdr import runtime
        from poorsdr.config import loader

        cfg = loader.load()
        runtime.write_vendor_config(cfg)  # el audio heredado lee de aquí sus dispositivos
        ctx = runtime.build_context(cfg, services=("radio", "audio", "web"), plugins=False)
        ctx.start()
        if args.vpn:
            relay = start_relay()
        t = time.monotonic()
        while time.monotonic() - t < 15:
            try:
                if args.vpn:
                    http("GET", "/", timeout=2)
                else:
                    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            print("  el servidor no responde" + (" por el túnel" if args.vpn else ""))
            return 1
        patch_client_jitter()
        print(f"Banco remoto (PTT por {args.ptt}) — datos en {base}")
        res = asyncio.run(bench(args.rondas, ctx, args.ptt, args.desglose))
        res["hombre_muerto"] = deadman_test(ctx, args.ptt)
        if args.json:
            Path(args.json).write_text(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    finally:
        if relay is not None:
            relay.stdin.close()
            relay.wait(timeout=3)
        if ctx is not None:
            try:
                ctx.stop()
            except Exception:
                pass
        unload_sinks(sinks)


if __name__ == "__main__":
    raise SystemExit(main())
