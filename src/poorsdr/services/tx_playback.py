"""Reproducción de audio TX hacia la radio con temporización exacta.

Sustituye, para las macros de llamada, a ``reproducir_audio_en_radio`` del
módulo heredado. Corrige tres defectos de aquel:

* **Se perdía el final** (Linux/Pulse). ``ffmpeg`` decodifica mucho más rápido
  que el tiempo real, así que al acabar de escribir quedaba medio segundo de
  audio sin sonar en la tubería hacia ``pacat``, y se le hacía ``terminate()``
  en vez de esperar a que lo reprodujese. Aquí se cierra su entrada y se espera
  a que vacíe (``pacat`` drena al recibir EOF).
* **El PTT y el audio no estaban sincronizados.** El PTT se activaba antes de
  que el decodificador y el dispositivo estuvieran listos, así que la pausa real
  entre PTT y primera muestra dependía de lo que tardase el arranque. Aquí se
  prepara todo, se decodifica el primer bloque y *entonces* se llama a
  ``on_ready`` (que activa el PTT y espera la pausa exacta); el audio sale
  justo después.
* **Dependía siempre de ``ffmpeg``.** Los WAV se leen con un decodificador
  propio (``wave`` + numpy), sin ``ffmpeg`` ni PyAV; para otros formatos (mp3…)
  se usa ``ffmpeg`` si existe y, si no, PyAV. Así una instalación sin ``ffmpeg``
  (típico en Windows) reproduce las macros en WAV, y PyAV puede llegar como
  componente que descarga el instalador sin ir dentro del ejecutable.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
import wave
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

#: Tamaño de lectura/escritura (bytes). Igual que el módulo heredado.
CHUNK_BYTES = 4096

#: Margen extra (s) sobre la duración del audio al esperar a que ``pacat`` vacíe.
DRAIN_MARGIN_S = 2.0


class UnsupportedAudio(Exception):  # noqa: N818 - no es un error "fatal", es "pruebe otro decodificador"
    """El decodificador no puede con este archivo; se prueba el siguiente."""


class PcmSource(Protocol):
    """Origen de audio PCM s16le ya convertido a la frecuencia/canales del dispositivo."""

    def read(self, size: int) -> bytes: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# Espera exacta
# --------------------------------------------------------------------------- #
def precise_wait(
    seconds: float,
    cancelled: Callable[[], bool],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    spin_s: float = 0.002,
) -> bool:
    """Espera ``seconds`` con precisión de sub-milisegundo. ``False`` si se cancela.

    Duerme de forma gruesa hasta ``spin_s`` antes del plazo (el sueño del SO
    puede pasarse por un par de ms) y el último tramo lo cubre con una espera
    activa breve sobre el reloj monotónico.
    """
    if seconds <= 0:
        return not cancelled()
    deadline = clock() + seconds
    while True:
        if cancelled():
            return False
        remaining = deadline - clock()
        if remaining <= 0:
            return True
        if remaining > spin_s:
            sleep(min(0.01, remaining - spin_s))


# --------------------------------------------------------------------------- #
# Decodificadores
# --------------------------------------------------------------------------- #
class _BytesSource:
    """PCM ya en memoria, servido por bloques."""

    def __init__(self, data: bytes) -> None:
        self._data = memoryview(data)
        self._pos = 0

    def read(self, size: int) -> bytes:
        chunk = bytes(self._data[self._pos : self._pos + size])
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self._data = memoryview(b"")


def decode_wav(path: str, rate: int, channels: int) -> _BytesSource:
    """Lee un WAV PCM (8/16/24/32 bits) y lo convierte a s16le ``rate``/``channels``.

    Solo ``wave`` + numpy: no necesita ``ffmpeg`` ni PyAV. Lanza
    :class:`UnsupportedAudio` si no es un WAV PCM estándar (p. ej. float o
    comprimido) para que se pruebe otro decodificador.
    """
    import numpy as np

    try:
        with wave.open(path, "rb") as wf:
            src_ch, width, src_rate, frames = (
                wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
            )
            raw = wf.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise UnsupportedAudio(str(exc)) from exc
    if src_ch < 1 or src_rate < 1 or not raw:
        raise UnsupportedAudio("WAV vacío o inválido")

    if width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        raw8 = np.frombuffer(raw, dtype=np.uint8)
        trios = raw8[: len(raw8) - len(raw8) % 3].reshape(-1, 3).astype(np.int32)
        v = trios[:, 0] | (trios[:, 1] << 8) | (trios[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        x = v.astype(np.float32) / 8388608.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise UnsupportedAudio(f"anchura de muestra no soportada: {width}")

    x = x[: len(x) - len(x) % src_ch].reshape(-1, src_ch)
    # Canales: a mono promediando; a estéreo duplicando o conservando L/R.
    if channels == 1:
        x = x.mean(axis=1, keepdims=True)
    elif x.shape[1] == 1:
        x = np.repeat(x, channels, axis=1)
    elif x.shape[1] != channels:
        x = x[:, :channels] if x.shape[1] > channels else np.repeat(x.mean(axis=1, keepdims=True), channels, axis=1)
    # Frecuencia: interpolación lineal (suficiente para voz de macros).
    if src_rate != rate:
        n_out = max(1, int(round(x.shape[0] * rate / src_rate)))
        t_out = np.linspace(0.0, x.shape[0] - 1, n_out)
        t_in = np.arange(x.shape[0])
        x = np.stack([np.interp(t_out, t_in, x[:, c]) for c in range(x.shape[1])], axis=1)
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    return _BytesSource(pcm.tobytes())


class _FfmpegSource:
    """Decodificación con el ejecutable ``ffmpeg`` por tubería."""

    def __init__(self, process: Any) -> None:
        self._p = process

    def read(self, size: int) -> bytes:
        return self._p.stdout.read(size)

    def close(self) -> None:
        for stream in (self._p.stdout, self._p.stdin):
            with contextlib.suppress(Exception):
                if stream:
                    stream.close()
        with contextlib.suppress(Exception):
            if self._p.poll() is None:
                self._p.terminate()
                self._p.wait(timeout=0.5)


def decode_ffmpeg(
    path: str, rate: int, channels: int, ffmpeg: str, popen: Callable[..., Any] = subprocess.Popen
) -> _FfmpegSource:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = popen(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", path,
             "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(rate), "-ac", str(channels), "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
    except OSError as exc:
        raise UnsupportedAudio(f"no se pudo lanzar ffmpeg: {exc}") from exc
    return _FfmpegSource(proc)


class _AvSource:
    """Decodificación en proceso con PyAV (``import av``), sin ejecutable externo."""

    def __init__(self, path: str, rate: int, channels: int) -> None:
        try:
            import av
        except ImportError as exc:
            raise UnsupportedAudio("PyAV no está disponible") from exc
        try:
            self._container = av.open(path)
            stream = next(s for s in self._container.streams if s.type == "audio")
        except Exception as exc:  # noqa: BLE001
            raise UnsupportedAudio(f"PyAV no puede abrir el archivo: {exc}") from exc
        self._av = av
        self._resampler = av.AudioResampler(
            format="s16", layout="mono" if channels == 1 else "stereo", rate=rate
        )
        self._frames = self._container.decode(stream)
        self._buf = bytearray()
        self._done = False

    def _fill(self, size: int) -> None:
        while len(self._buf) < size and not self._done:
            try:
                frame = next(self._frames)
            except StopIteration:
                self._done = True
                for out in self._resampler.resample(None):
                    self._buf += bytes(out.planes[0])[: out.samples * out.layout.nb_channels * 2]
                return
            if not isinstance(frame, self._av.AudioFrame):
                continue
            for out in self._resampler.resample(frame):
                self._buf += bytes(out.planes[0])[: out.samples * out.layout.nb_channels * 2]

    def read(self, size: int) -> bytes:
        self._fill(size)
        chunk = bytes(self._buf[:size])
        del self._buf[:size]
        return chunk

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._container.close()


def _ffmpeg_executable(ffmpeg: str) -> str | None:
    if os.path.isfile(ffmpeg):
        return ffmpeg
    return shutil.which(ffmpeg)


def open_source(
    path: str,
    rate: int,
    channels: int,
    *,
    ffmpeg: str = "ffmpeg",
    popen: Callable[..., Any] = subprocess.Popen,
) -> PcmSource | None:
    """Abre ``path`` con el primer decodificador que pueda: WAV propio → ``ffmpeg`` → PyAV.

    ``None`` si el archivo no existe o ninguno puede decodificarlo.
    """
    if not path or not os.path.isfile(path):
        return None
    with contextlib.suppress(UnsupportedAudio):
        return decode_wav(path, rate, channels)
    exe = _ffmpeg_executable(ffmpeg)
    if exe:
        with contextlib.suppress(UnsupportedAudio):
            return decode_ffmpeg(path, rate, channels, exe, popen)
    with contextlib.suppress(UnsupportedAudio):
        return _AvSource(path, rate, channels)
    return None


# --------------------------------------------------------------------------- #
# Reproducción
# --------------------------------------------------------------------------- #
def play_through_pacat(
    path: str,
    *,
    ffmpeg: str = "ffmpeg",
    sink: str,
    rate: int,
    channels: int,
    latency_ms: int,
    stop_checker: Callable[[], bool] | None = None,
    on_ready: Callable[[], bool] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    source_factory: Callable[..., PcmSource | None] = open_source,
) -> bool:
    """Decodifica ``path`` y lo reproduce en el ``sink`` de Pulse con ``pacat``.

    ``on_ready`` se llama cuando el decodificador ya produce audio y ``pacat``
    está lanzado, justo antes de escribir la primera muestra; si devuelve
    ``False`` no se reproduce nada. Devuelve ``False`` si el archivo no se
    puede decodificar; ``True`` si se reprodujo (o se cortó por ``stop_checker``).
    """
    source = source_factory(path, rate, channels, ffmpeg=ffmpeg, popen=popen)
    if source is None:
        return False
    player = None
    try:
        chunk = source.read(CHUNK_BYTES)
        if not chunk:
            return False
        player = popen(
            ["pacat", "--device", sink, "--playback", "--format=s16le",
             "--rate", str(rate), "--channels", str(channels), "--latency-msec", str(latency_ms)],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        if on_ready is not None and not on_ready():
            return False
        written = 0
        while chunk:
            if stop_checker and stop_checker():
                return True
            player.stdin.write(chunk)
            player.stdin.flush()
            written += len(chunk)
            chunk = source.read(CHUNK_BYTES)
        # Fin del archivo: dejar que pacat vacíe lo que tiene en cola.
        player.stdin.close()
        duration_s = written / float(rate * channels * 2)
        with contextlib.suppress(subprocess.TimeoutExpired):
            player.wait(timeout=duration_s + DRAIN_MARGIN_S)
        return True
    finally:
        source.close()
        if player is not None:
            with contextlib.suppress(Exception):
                if player.stdin:
                    player.stdin.close()
            with contextlib.suppress(Exception):
                if player.poll() is None:
                    player.terminate()
                    player.wait(timeout=0.5)


def play_through_stream(
    path: str,
    *,
    open_stream: Callable[[], Any],
    ffmpeg: str = "ffmpeg",
    rate: int,
    channels: int,
    stop_checker: Callable[[], bool] | None = None,
    on_ready: Callable[[], bool] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    source_factory: Callable[..., PcmSource | None] = open_source,
) -> bool:
    """Igual que :func:`play_through_pacat` pero hacia un stream de salida PyAudio.

    ``open_stream`` abre el dispositivo (``None`` si no está configurado). La
    escritura de PyAudio es bloqueante y ``stop_stream`` espera a que se
    reproduzca lo pendiente, así que aquí no hace falta un vaciado aparte.
    """
    source = source_factory(path, rate, channels, ffmpeg=ffmpeg, popen=popen)
    if source is None:
        return False
    stream = None
    try:
        chunk = source.read(CHUNK_BYTES)
        if not chunk:
            return False
        stream = open_stream()
        if stream is None:
            return False
        if on_ready is not None and not on_ready():
            return False
        while chunk:
            if stop_checker and stop_checker():
                return True
            stream.write(chunk)
            chunk = source.read(CHUNK_BYTES)
        return True
    finally:
        source.close()
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.stop_stream()
            with contextlib.suppress(Exception):
                stream.close()


__all__ = [
    "CHUNK_BYTES",
    "DRAIN_MARGIN_S",
    "UnsupportedAudio",
    "decode_wav",
    "open_source",
    "play_through_pacat",
    "play_through_stream",
    "precise_wait",
]
