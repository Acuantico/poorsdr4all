"""
audio_remote.py - Módulo dedicado para audio WebRTC remoto
Arquitectura de baja latencia que recibe datos de audio.py
NO captura directamente de dispositivos para evitar conflictos

Solo gestiona el sentido RX (radio -> navegador) y el estado de PTT. El TX
(micrófono del navegador -> radio) vive aparte, en el propio ``audio.py``
(``inject_tx_audio``/``_pop_tx_inject``/``_tx_inject_buffer``), que ya tiene
su propia cancelación de pérdida de paquetes — un único camino TX, para no
confundir a quien lea el código.

Reparto RX a varios oyentes a la vez (``register_listener``/
``unregister_listener``/``pop_rx_audio(listener_id, ...)``): cada conexión
WebRTC (el mismo operador desde el móvil y el escritorio a la vez, por
ejemplo) tiene su propia cola independiente. Lo que se recibe se reparte
—una copia— a todas las colas activas, para que dos oyentes conectados a
la vez no compitan por vaciar un único buffer pensado para un solo
consumidor.
"""

import logging
import threading
import time
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Estado global del módulo
_listeners: dict[int, deque] = {}
_next_listener_id = 0
_ptt_active: bool = False
_remote_active: bool = False
_lock = threading.Lock()
_buffer_lock = threading.Lock()
_rx_pending: Optional[np.ndarray] = None

# Configuración de audio
_sample_rate: int = 48000
_chunk_size: int = 960  # 20ms a 48kHz (frame Opus estándar)

# Tope y recorte por oyente (cada uno tiene su propia cola de este tamaño).
#
# Antes en 14 (280 ms) con el vaciado en pop_rx_audio() solo activo por
# encima de 8 (160 ms): dos relojes independientes (el hilo que captura del
# dispositivo de audio real vs. el propio pacing de aiortc en recv(), cada
# 20 ms) nunca están perfectamente sincronizados, y en cuanto la producción
# adelantaba aunque fuera un poco al consumo, el buffer se quedaba instalado
# cerca de ese tope en vez de recuperarse — el oyente remoto terminaba
# escuchando con un retraso permanente de cientos de ms respecto al audio
# real (lo que se reportó como "relentizado"), y cuando el propio deque
# (maxlen) se llenaba del todo empezaba a tirar chunks sin avisar (lo que
# sonaba "cortado"). Ahora que `RxAudioTrack.recv()` respeta su propio
# ritmo de reloj real (ver `_clock_start` en webserver.py) ya no hay
# adelanto sistemático del consumo sobre la producción, así que el riesgo
# de que el retraso crezca sin parar ha desaparecido — un margen algo mayor
# aquí no reintroduce ese problema, y da más colchón contra el jitter normal
# del hilo de captura (absorbe huecos breves sin recurrir al relleno de
# silencio de recv(), que aun con crossfade sigue siendo peor que servir
# audio real).
_RX_BUFFER_SIZE = 8  # 160 ms de margen máximo absoluto por oyente

# Retraso fijo sobrante. La pista RX y la captura van al mismo ritmo, así que
# los bloques que deja en la cola una ráfaga (al conectar, al volver de TX) se
# quedaban ahí para siempre: 40-60 ms de retraso que no servían de colchón
# (medido con scripts/bench_remoto.py). Si en ``_RX_TRIM_WINDOW`` entregas la
# cola nunca bajó de un bloque de sobra, ese bloque es retraso y se descarta;
# si el jitter real llega a vaciarla, no se toca.
_RX_TRIM_WINDOW = 50  # ~1 s de bloques de 20 ms
_listener_min_depth: dict[int, list[int]] = {}  # id -> [profundidad mínima, entregas]
# Cuánto llevaba esperando en la cola el último bloque entregado a cada oyente
# (la pista RX lo usa para alinear su reloj con la captura).
_listener_last_age: dict[int, float] = {}


def start_remote_audio() -> bool:
    """
    Inicia el módulo de audio remoto (solo inicializa buffers)
    NO abre dispositivos PyAudio (audio.py los maneja)
    Retorna True si tuvo éxito, False si falló
    """
    global _remote_active, _rx_pending

    with _lock:
        if _remote_active:
            logger.warning("Remote audio already active")
            return True

        try:
            with _buffer_lock:
                _listeners.clear()
                _rx_pending = np.zeros(0, dtype=np.float32)

            _remote_active = True
            logger.info("Remote audio started successfully (buffer mode)")
            return True

        except Exception as e:
            logger.error(f"Failed to start remote audio: {e}")
            stop_remote_audio()
            return False


def stop_remote_audio():
    """
    Detiene el módulo de audio remoto y libera recursos
    """
    global _remote_active, _ptt_active, _rx_pending

    with _lock:
        if not _remote_active:
            return

        try:
            # Desactivar PTT
            _ptt_active = False

            # Limpiar todas las colas de todos los oyentes conectados.
            with _buffer_lock:
                _listeners.clear()
                _rx_pending = np.zeros(0, dtype=np.float32)

            _remote_active = False
            logger.info("Remote audio stopped")

        except Exception as e:
            logger.error(f"Error stopping remote audio: {e}")


def register_listener() -> int:
    """
    Da de alta un nuevo oyente RX (una conexión WebRTC nueva) con su propia
    cola independiente. Llamar una vez por ``RxAudioTrack`` al crearlo, y
    ``unregister_listener`` cuando esa conexión se cierra — si no se hace,
    la cola se queda huérfana ocupando memoria sin que nadie la vacíe nunca.

    Returns:
        Identificador a pasar a ``pop_rx_audio``/``unregister_listener``.
    """
    global _next_listener_id

    with _buffer_lock:
        listener_id = _next_listener_id
        _next_listener_id += 1
        _listeners[listener_id] = deque(maxlen=_RX_BUFFER_SIZE)
        _listener_min_depth[listener_id] = [_RX_BUFFER_SIZE, 0]
        return listener_id


def unregister_listener(listener_id: int) -> None:
    """Da de baja un oyente RX (conexión WebRTC cerrada)."""
    with _buffer_lock:
        _listeners.pop(listener_id, None)
        _listener_min_depth.pop(listener_id, None)
        _listener_last_age.pop(listener_id, None)


def push_rx_audio(audio_data: np.ndarray):
    """
    Alimenta audio RX al buffer (llamado por audio.py)

    Reparte una copia de cada chunk producido a la cola de cada oyente
    conectado en este momento — no es un único buffer compartido entre
    todos, cada oyente ve el flujo completo indepen­dientemente de cuántos
    más estén conectados a la vez.

    Args:
        audio_data: Array numpy float32 mono normalizado [-1.0, 1.0]
                   Puede ser cualquier tamaño, se dividirá en chunks de 960 samples (20ms mono)
    """
    global _ptt_active, _rx_pending

    if not _remote_active:
        return

    # Solo agregar si no estamos en PTT (RX activo)
    if _ptt_active:
        return

    try:
        # Validar entrada
        if audio_data is None or len(audio_data) == 0:
            return

        # Asegurar que sea float32
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        # Simple clip - audio.py ya hace normalización
        audio_data = np.clip(audio_data, -1.0, 1.0)

        with _buffer_lock:
            if not _listeners:
                # Nadie escuchando todavía: no acumular pendiente sin límite.
                _rx_pending = np.zeros(0, dtype=np.float32)
                return
            if _rx_pending is None or _rx_pending.size == 0:
                _rx_pending = audio_data.copy()
            else:
                _rx_pending = np.concatenate([_rx_pending, audio_data])
            now = time.monotonic()
            while _rx_pending.size >= _chunk_size:
                chunk = _rx_pending[:_chunk_size].copy()
                _rx_pending = _rx_pending[_chunk_size:]
                for queue in _listeners.values():
                    queue.append((now, chunk.copy()))

    except Exception as e:
        logger.error(f"Error pushing RX audio: {e}")


def pop_rx_audio(listener_id: int, timeout_ms: int = 100) -> Optional[np.ndarray]:
    """
    Obtiene un chunk de audio RX de la cola de un oyente concreto (llamado
    por webserver.py, una vez por ``RxAudioTrack``/conexión).

    Args:
        listener_id: id devuelto por ``register_listener`` para esta conexión.
        timeout_ms: Timeout en milisegundos (no usado, compatibilidad con API)

    Returns:
        Array numpy float32 mono [samples], o None si no hay audio
    """
    if not _remote_active:
        return None

    try:
        with _buffer_lock:
            queue = _listeners.get(listener_id)
            depth = _listener_min_depth.get(listener_id)
            if not queue:
                if depth is not None:
                    depth[0] = 0  # se vació: el colchón hace falta
                return None
            # Recorta hacia un margen pequeño en cada pop, no solo cuando el
            # buffer está a punto de desbordar: así el retraso acumulado se
            # mantiene bajo y estable en vez de instalarse cerca del tope
            # (ver el comentario de _RX_BUFFER_SIZE más arriba).
            while len(queue) > 3:
                queue.popleft()
            if depth is not None:
                depth[0] = min(depth[0], len(queue) - 1)
                depth[1] += 1
                if depth[1] >= _RX_TRIM_WINDOW:
                    if depth[0] >= 1 and len(queue) >= 2:
                        queue.popleft()  # retraso fijo sobrante (ver _RX_TRIM_WINDOW)
                    depth[0], depth[1] = _RX_BUFFER_SIZE, 0
            arrived, chunk = queue.popleft()
            _listener_last_age[listener_id] = time.monotonic() - arrived
            return chunk
    except Exception:
        return None


def last_rx_age(listener_id: int) -> Optional[float]:
    """Segundos que esperó en la cola el último bloque entregado a ese oyente."""
    return _listener_last_age.get(listener_id)


def set_ptt(state: bool):
    """
    Activa o desactiva PTT (cambio instantáneo)

    Args:
        state: True para TX, False para RX
    """
    global _ptt_active, _rx_pending

    if not _remote_active:
        return

    _ptt_active = state

    # Cambio de sentido (TX<->RX): limpiar la cola de cada oyente para no
    # dejar cola cruzada de un sentido en el otro.
    with _buffer_lock:
        for queue in _listeners.values():
            queue.clear()
        _rx_pending = np.zeros(0, dtype=np.float32)
    logger.debug("PTT %s", "activated (TX)" if state else "deactivated (RX)")


def get_ptt_state() -> bool:
    """
    Obtiene el estado actual del PTT

    Returns:
        True si PTT está activo (TX), False si está en RX
    """
    return _ptt_active


def is_active() -> bool:
    """
    Verifica si el módulo de audio remoto está activo

    Returns:
        True si está activo, False si no
    """
    return _remote_active


def get_buffer_status() -> dict:
    """
    Obtiene el estado de las colas RX (útil para debugging)

    Returns:
        Dict con información agregada: {listeners, rx_sizes, rx_capacity,
        ptt_active, remote_active} — ``rx_sizes`` es la lista de tamaños de
        cola, uno por oyente conectado, en vez de un único ``rx_size`` ahora
        que puede haber más de un oyente a la vez.
    """
    with _buffer_lock:
        rx_sizes = [len(q) for q in _listeners.values()]

    return {
        "listeners": len(rx_sizes),
        "rx_sizes": rx_sizes,
        "rx_capacity": _RX_BUFFER_SIZE,
        "ptt_active": _ptt_active,
        "remote_active": _remote_active,
    }
