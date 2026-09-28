"""Motor RTTY: escaneo multi-señal en la pasabanda del uSDX + TX asistido.

No es un ``Service`` del ``ServiceManager`` (no necesita reconfigurarse al
guardar Ajustes ni arrancar con la app): vive mientras el panel RTTY esté
abierto, igual que la cascada nativa solo calcula FFT mientras alguien la está
mirando (ver ``app.py:_tick_waterfall``). La UI (``poorsdr_rtty_power.panel``)
llama a :meth:`RttyEngine.tick` periódicamente desde el bucle de Tk.

Fuentes de audio/TX ya existentes que se reutilizan tal cual, sin tocarlas:

- RX: ``_vendor.audio.pop_rx_raw_chunk_digi()`` — cola independiente de audio
  RX "pre-volumen" pensada para decodificadores digitales, ya presente y sin
  consumidor en Python antes de esto. Trae lo que sea que esté sonando como
  fuente RX en ese momento (uSDX si "Audio RX: Radio" está seleccionado).
- TX: ``_vendor.audio.inject_tx_audio(samples, sample_rate)`` — el mismo
  camino que ya usa el panel WebRTC para meter audio ajeno en la cadena TX.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from poorsdr.infra.logging import get_logger
from poorsdr_rtty_power.rtty import (
    BAUD_DEFAULT,
    DEFAULT_SCAN_RANGE_HZ,
    SHIFT_HZ_DEFAULT,
    RttyDemodulator,
    find_signal_candidates,
    generate_fsk_samples,
)

_log = get_logger("plugins.rtty_power.engine")

#: Coincide con el sample rate que ya usa la cascada nativa (WaterfallConfig).
DEFAULT_SAMPLE_RATE = 48000
SCAN_INTERVAL_SEC = 1.5
SIGNAL_TIMEOUT_SEC = 6.0
MAX_ACTIVE_SIGNALS = 4
#: Dos señales a menos de esto se consideran la MISMA estación. Antes solo
#: se agrupaban si caían en el mismo tramo de 10 Hz: cada clic sobre la
#: cresta (que resuelve unos Hz distinto) creaba otro decodificador
#: enganchado, y la lista acababa con la misma estación 4 veces.
SIGNAL_MERGE_HZ = 25.0
#: Audio reciente que se analiza (scope/scan/AFC/clic): el mismo tamaño que
#: el trozo que se usaba antes (una trama DSP_FRAME_SIZE de _vendor.audio),
#: para que la cascada se vea exactamente igual que siempre. Lo importante es
#: que sea FIJO: así el coste no crece aunque se acumule audio.
ANALYSIS_WINDOW_SAMPLES = 1440
#: Audio para la cascada en vistas ESTRECHAS (filtro de 500/200 del uSDX):
#: ~170 ms a 48 kHz. Con solo 1440 muestras (30 ms) cada tono sale como una
#: mancha de >100 Hz y casi nunca suenan los dos a la vez, así que en una
#: ventana de 500 Hz no se distinguían las dos crestas (medido: cresta
#: izquierda 0.10 frente a 0.67 con esta ventana). Solo se usa para dibujar.
SCOPE_WINDOW_SAMPLES = 8192
#: Seguimiento fino (AFC): NO es un buscador de señal -- el operador es
#: quien sintoniza (clic en la cascada o "Enganchar"). Esto solo hace un
#: ajuste extrafino de LA SEÑAL YA SINTONIZADA, corrigiendo la imprecisión
#: normal de un clic/enganche aproximado, sin ir a buscar nada por su
#: cuenta. Por eso solo se aplica a señales enganchadas a mano
#: (``sig.locked``) y con una franja de búsqueda deliberadamente estrecha
#: (``AFC_SEARCH_HALF_HZ``) -- lo bastante ancha para pulir un clic
#: impreciso, demasiado estrecha para llegar nunca a otra estación.
AFC_INTERVAL_SEC = 0.4
#: Cuánto puede apartarse como máximo el pico medido del centro actual para
#: seguir considerándose la MISMA señal. Deliberadamente pequeño: esto NO
#: debe poder "saltar" a una estación vecina más fuerte en un pileup de
#: concurso -- solo pulir la sintonía que ya eligió el operador.
AFC_SEARCH_HALF_HZ = 25.0
#: Fracción de la corrección medida que se aplica en cada paso -- de golpe
#: daría saltos audibles/visuales; así converge suave en un par de segundos.
AFC_SMOOTH_ALPHA = 0.3
#: El AFC solo corrige mientras la estación trabajada está transmitiendo: la
#: cresta más fuerte de las dos (mark/space) debe superar este múltiplo del
#: fondo (mediana del espectro 300-2900 Hz). Medido con trozos de 1440
#: muestras a 48 kHz: solo ruido nunca pasó de 4.2; la estación, incluso muy
#: débil y con mucho ruido, nunca bajó de 6.8. Sin esto, en cuanto el
#: corresponsal paraba, el AFC seguía "corrigiendo" hacia el ruido o hacia
#: otra señal y desintonizaba la estación del QSO.
AFC_PRESENCE_RATIO = 6.0
#: El PTT se mantiene esto tras el final teórico del audio: el audio
#: inyectado sale en tramas de 20 ms hacia la tarjeta, que tiene su propio
#: búfer, así que llega a la radio con retardo. Soltar el PTT justo al final
#: teórico cortaba el final del mensaje -- en un concurso, el número del
#: intercambio. Margen conservador, no medido en el equipo real.
TX_TAIL_SEC = 0.4
#: Red de seguridad: si pasado el final previsto (+ margen) el PTT sigue
#: armado, se fuerza a soltar. Antes eran 8 s fijos desde el inicio, que
#: cortaban cualquier texto libre de más de ~45 caracteres.
TX_WATCHDOG_SEC = 3.0


@dataclass
class RttySignal:
    """Una señal RTTY detectada dentro de la pasabanda actual."""

    center_hz: float
    decoder: RttyDemodulator
    text: str = ""
    last_seen: float = field(default_factory=time.monotonic)
    #: Fijada a mano por el operador (botón "Enganchar"): no se retira por
    #: inactividad aunque de momento no se oiga nada ahí.
    locked: bool = False
    #: Dónde la sintonizó el operador (clic/"Enganchar"). El AFC nunca la
    #: aparta más de ``AFC_SEARCH_HALF_HZ`` de aquí, por muchas correcciones
    #: que acumule -- antes cada paso partía del anterior y podía ir
    #: alejándose poco a poco sin límite.
    anchor_hz: float | None = None


class RttyEngine:
    """RX (banco de decodificadores) + TX (tono inyectado) + watchdog de PTT."""

    def __init__(
        self,
        *,
        audio_module: Any,
        radio: Any,
        audio_service: Any = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        shift_hz: float = SHIFT_HZ_DEFAULT,
        baud: float = BAUD_DEFAULT,
    ) -> None:
        self._audio = audio_module
        # AudioService (no el módulo bajo) para start_tx()/stop_tx(): sin
        # esto, send_text() armaba el PTT pero nunca pasaba el pipeline de
        # audio a modo TX -- la radio transmitía, pero sin nada que
        # modulara la portadora. Es justo lo que ya hace el botón "Hablar"
        # de la consola además de armar el PTT (ver app.py:_set_ptt).
        self._audio_service = audio_service
        self.radio = radio
        self.sample_rate = sample_rate
        self.shift_hz = shift_hz
        self.baud = baud
        self.signals: dict[int, RttySignal] = {}
        self.on_signal_update: Callable[[], None] | None = None
        #: Si se apaga, ``tick()`` sigue decodificando las señales ya
        #: detectadas (incluida cualquier "enganchada" a mano) pero deja de
        #: buscar otras nuevas — útil para no perder de vista la que se está
        #: trabajando si el escaneo detecta ruido como señal nueva.
        self.auto_scan = True
        #: Zona de audio donde el auto-scan busca señales: la que deja pasar
        #: el filtro del uSDX (el panel la ajusta con su selector de filtro).
        self.scan_range_hz: tuple[float, float] = DEFAULT_SCAN_RANGE_HZ
        #: Casilla "AFC" del panel: con esto apagado las señales enganchadas
        #: se quedan exactamente donde las sintonizó el operador.
        self.afc = True
        #: Interruptor "Rev" del panel: invierte mark/space SOLO al recibir,
        #: para leer a una estación que transmite al revés. La polaridad
        #: normal ya sale sola del modo del equipo (ver ``_sideband_reversed``).
        self.rx_reverse = False
        #: Último bloque de audio recibido; lo usa el panel para dibujar un
        #: mini-espectro de sintonía (no hace falta pasar por rtty).
        self.last_samples: np.ndarray | None = None
        #: Audio reciente más largo, solo para dibujar la cascada estrecha.
        self.scope_samples: np.ndarray | None = None
        self._last_scan = 0.0
        self._last_afc = 0.0
        self._tx_deadline: float | None = None
        self._tx_release_at: float | None = None
        self._tx_audio_end: float | None = None

    # ---- RX ------------------------------------------------------------ #
    def tick(self) -> None:
        """Llamar periódicamente (p.ej. cada 40-100 ms) desde la UI."""
        self._check_tx_watchdog()
        pop = getattr(self._audio, "pop_rx_raw_chunk_digi", None)
        if pop is None:
            return
        samples = pop()
        if samples is None or getattr(samples, "size", 0) == 0:
            return
        # Ventana FIJA de audio reciente para scope/scan/AFC/clic: el
        # decodificador recibe todo el audio (barato), pero
        # find_signal_candidates crece más que linealmente con el tamaño del
        # bloque (0.1 s = 12 ms, 1 s = 775 ms, 2 s = 3.4 s). Si se le pasaba
        # el bloque entero, cualquier retraso de la UI hacía el siguiente
        # bloque más grande, más lento, más atraso... y la ventana se
        # congelaba (ni se cerraba).
        scope = samples if self.scope_samples is None else np.concatenate([self.scope_samples, samples])
        self.scope_samples = scope[-SCOPE_WINDOW_SAMPLES:]
        self.last_samples = self.scope_samples[-ANALYSIS_WINDOW_SAMPLES:]
        analysis = self.last_samples

        now = time.monotonic()
        if self.auto_scan and now - self._last_scan >= SCAN_INTERVAL_SEC:
            self._last_scan = now
            self._rescan(analysis)

        if self.afc and now - self._last_afc >= AFC_INTERVAL_SEC:
            self._last_afc = now
            self._run_afc(analysis)

        rx_rev = self.rx_polarity_reversed()
        changed = False
        for signal in list(self.signals.values()):
            signal.decoder.reverse = rx_rev
            new_text = signal.decoder.feed(samples)
            if new_text:
                signal.text += new_text
                signal.last_seen = now
                changed = True

        stale = [
            key
            for key, sig in self.signals.items()
            if not sig.locked and now - sig.last_seen > SIGNAL_TIMEOUT_SEC
        ]
        for key in stale:
            del self.signals[key]
            changed = True

        if changed and self.on_signal_update is not None:
            with contextlib.suppress(Exception):
                self.on_signal_update()

    def _rescan(self, samples: np.ndarray) -> None:
        candidates = find_signal_candidates(
            samples, self.sample_rate, shift_hz=self.shift_hz, scan_range_hz=self.scan_range_hz
        )
        for center in candidates:
            if len(self.signals) >= MAX_ACTIVE_SIGNALS:
                break
            if self._near_signal(center) is not None:
                continue
            key = int(round(center / 10.0))
            self.signals[key] = RttySignal(
                center_hz=center,
                decoder=self._make_decoder(center),
            )

    def _run_afc(self, samples: np.ndarray) -> None:
        """Ajuste extrafino de las señales que el OPERADOR ya enganchó a
        mano (clic en la cascada o "Enganchar") -- nunca busca ni elige qué
        sintonizar por su cuenta. Las detectadas solo por el auto-scan y
        todavía sin enganchar se dejan tal cual: no es su trabajo "mejorar"
        algo que el operador no ha elegido trabajar. La franja de búsqueda
        (``AFC_SEARCH_HALF_HZ``) es deliberadamente estrecha para que esto
        sea un pulido de la sintonía ya elegida, no un buscador de la señal
        más fuerte cercana."""
        half = self.shift_hz / 2.0
        locked = [sig for sig in self.signals.values() if sig.locked]
        if not locked:
            return
        n = 8192
        spectrum = np.abs(np.fft.rfft(samples.astype(np.float64) * np.hanning(samples.size), n=n))
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sample_rate)
        floor = float(np.median(spectrum[(freqs >= 300.0) & (freqs <= 2900.0)])) + 1e-12

        def tone_level(hz: float) -> float:
            window = spectrum[(freqs >= hz - 15.0) & (freqs <= hz + 15.0)]
            return float(window.max()) if window.size else 0.0

        for sig in locked:
            # ¿Está transmitiendo AHORA la estación trabajada? Si no (el
            # corresponsal ha parado), no se toca nada: se queda donde está.
            present = max(tone_level(sig.center_hz - half), tone_level(sig.center_hz + half))
            if present < AFC_PRESENCE_RATIO * floor:
                continue
            anchor = sig.anchor_hz if sig.anchor_hz is not None else sig.center_hz
            lo = max(0.0, anchor - half - AFC_SEARCH_HALF_HZ)
            hi = anchor + half + AFC_SEARCH_HALF_HZ
            candidates = find_signal_candidates(
                samples, self.sample_rate, shift_hz=self.shift_hz, scan_range_hz=(lo, hi)
            )
            if not candidates:
                continue
            # OJO: candidates[0] (más energía), NO "el más cercano al centro
            # actual" -- ese criterio se probó y falla: la lista trae muchos
            # pares de bins de poca energía (ruido/lóbulos laterales de la
            # propia FSK), y casi siempre hay alguno casi exactamente donde
            # ya está el centro actual por pura coincidencia numérica, así
            # que "el más cercano" se queda pegado ahí para siempre y nunca
            # converge hacia el pico real (confirmado con una señal
            # sintética: el AFC no se movía ni un Hz en 10 pasos). La
            # candidata con más energía dentro de esta franja estrecha sí es
            # de fiar -- por eso se restringe scan_range_hz antes de mirar
            # la lista.
            best = candidates[0]
            # Cada medida oscila ~±10 Hz (trozo de audio corto): se aceptan
            # medidas hasta 2x la franja para no descartar sistemáticamente
            # las de un lado (sesgaba el centrado), pero el CENTRO resultante
            # se recorta a ±AFC_SEARCH_HALF_HZ de la sintonía del operador.
            if abs(best - anchor) > 2 * AFC_SEARCH_HALF_HZ:
                continue
            new_center = sig.center_hz + AFC_SMOOTH_ALPHA * (best - sig.center_hz)
            new_center = min(max(new_center, anchor - AFC_SEARCH_HALF_HZ), anchor + AFC_SEARCH_HALF_HZ)
            if abs(new_center - sig.center_hz) < 0.5:
                continue
            sig.center_hz = new_center
            sig.decoder.retune(new_center)

    def _sideband_reversed(self) -> bool:
        """En LSB el audio sale invertido respecto a la RF: el tono de mark
        (la frecuencia de RF más alta, convenio de RTTY de aficionado) queda
        como el tono de audio MÁS GRAVE. En USB/DIGU no se invierte."""
        return str(getattr(self.radio, "mode", "") or "").upper() == "LSB"

    def rx_polarity_reversed(self) -> bool:
        return self._sideband_reversed() != self.rx_reverse

    def _make_decoder(self, center_hz: float) -> RttyDemodulator:
        return RttyDemodulator(
            sample_rate=self.sample_rate,
            center_hz=center_hz,
            shift_hz=self.shift_hz,
            baud=self.baud,
            reverse=self.rx_polarity_reversed(),
        )

    def _near_signal(self, center_hz: float) -> int | None:
        best = None
        for key, sig in self.signals.items():
            dist = abs(sig.center_hz - center_hz)
            if dist < SIGNAL_MERGE_HZ and (best is None or dist < best[0]):
                best = (dist, key)
        return best[1] if best else None

    def lock_signal(self, center_hz: float) -> int:
        """Fija a mano un decodificador en ``center_hz`` (botón "Enganchar"),
        por si el escaneo automático no la encuentra sola (señal débil, ya
        sintonizada de oído). Devuelve la clave para seleccionarla en la UI."""
        near = self._near_signal(center_hz)
        if near is not None:
            # La misma estación ya tiene decodificador: se reutiliza (con su
            # sincronía) y se lleva a la sintonía nueva del operador.
            existing = self.signals[near]
            existing.locked = True
            existing.anchor_hz = center_hz
            existing.center_hz = center_hz
            existing.decoder.retune(center_hz)
            existing.last_seen = time.monotonic()
            return near
        key = int(round(center_hz / 10.0))
        self.signals[key] = RttySignal(
            center_hz=center_hz,
            decoder=self._make_decoder(center_hz),
            locked=True,
            anchor_hz=center_hz,
        )
        return key

    def clear_signal(self, key: int) -> None:
        self.signals.pop(key, None)

    def reset(self) -> None:
        self.signals.clear()

    # ---- TX -------------------------------------------------------------#
    def send_text(self, text: str, *, center_hz: float = 1500.0) -> bool:
        """Genera el tono AFSK y lo inyecta en la cadena TX ya existente.

        Arma el PTT antes de inyectar y programa el watchdog; el propio
        :meth:`tick` suelta el PTT ``TX_TAIL_SEC`` después del final previsto
        del audio o, como red de seguridad, ``TX_WATCHDOG_SEC`` más tarde.
        Si ya se está transmitiendo, el mensaje se encadena detrás del que
        suena (macro pulsada antes de que termine la anterior).
        """
        inject = getattr(self._audio, "inject_tx_audio", None)
        if inject is None:
            _log.warning("inject_tx_audio no disponible; no se puede transmitir RTTY")
            return False
        # La polaridad de TX sigue SOLO al modo del equipo (nunca al "Rev"
        # manual de RX): en LSB el mark tiene que salir como tono grave para
        # que en RF quede arriba, que es lo que esperan los demás.
        shift = -self.shift_hz if self._sideband_reversed() else self.shift_hz
        audio = generate_fsk_samples(
            text,
            sample_rate=self.sample_rate,
            center_hz=center_hz,
            shift_hz=shift,
            baud=self.baud,
        )
        if audio.size == 0:
            return False

        start_tx = getattr(self._audio_service, "start_tx", None)
        if start_tx is not None:
            with contextlib.suppress(Exception):
                start_tx()
        # El bucle TX nativo descarta cualquier audio de inject_tx_audio()
        # salvo en remoto/WebRTC o con el tono de prueba activo -- sin esto
        # la radio arma el PTT pero no modula nada (bug real reportado).
        set_digi = getattr(self._audio, "set_tx_digi_inject_active", None)
        if set_digi is not None:
            with contextlib.suppress(Exception):
                set_digi(True)
        set_ptt = getattr(self.radio, "set_ptt", None)
        if set_ptt is not None:
            with contextlib.suppress(Exception):
                set_ptt(True, source="rtty")

        now = time.monotonic()
        duration = audio.size / float(self.sample_rate)
        start = max(now, self._tx_audio_end) if self._tx_audio_end is not None else now
        self._tx_audio_end = start + duration
        self._tx_release_at = self._tx_audio_end + TX_TAIL_SEC
        self._tx_deadline = self._tx_release_at + TX_WATCHDOG_SEC
        _log.info(
            "TX RTTY: PTT ON, %.2f s de audio a %d Hz (suelta PTT en %.2f s): %r",
            duration, self.sample_rate, self._tx_release_at - now, text,
        )
        try:
            inject(audio, self.sample_rate)
        except Exception:
            _log.exception("fallo inyectando audio TX RTTY")
            self._force_ptt_off()
            return False
        return True

    def _check_tx_watchdog(self) -> None:
        if self._tx_deadline is None:
            return
        now = time.monotonic()
        if self._tx_release_at is not None and now >= self._tx_release_at:
            # Medido en el equipo real: el audio empieza a sonar hasta ~0.5 s
            # después del PTT, así que la hora calculada puede llegar con
            # audio aún en cola. Mientras quede audio por enviar se aplaza
            # (siempre dentro del watchdog), y se suelta TX_TAIL_SEC después
            # de que la cola se vacíe.
            pending = getattr(self._audio, "tx_inject_pending_samples", None)
            still_queued = False
            if pending is not None:
                with contextlib.suppress(Exception):
                    still_queued = pending() > 0
            if still_queued and now < self._tx_deadline:
                self._tx_release_at = now + TX_TAIL_SEC
                return
            self._force_ptt_off()
        elif now >= self._tx_deadline:
            _log.warning("watchdog TX RTTY: forzando PTT OFF (tiempo agotado)")
            self._force_ptt_off()

    @property
    def transmitting(self) -> bool:
        return self._tx_deadline is not None

    def abort_tx(self) -> None:
        """Corta YA la transmisión (tecla Esc del panel, como en N1MM/MMTTY)."""
        if self.transmitting:
            self._force_ptt_off()

    def _force_ptt_off(self) -> None:
        _log.info("TX RTTY: PTT OFF")
        # Vacía lo que quede en cola: si el PTT se suelta antes de tiempo
        # (Esc o watchdog), ese audio sonaría al principio de la siguiente
        # transmisión.
        clear = getattr(self._audio, "clear_tx_inject_buffer", None)
        if clear is not None:
            with contextlib.suppress(Exception):
                clear()
        set_digi = getattr(self._audio, "set_tx_digi_inject_active", None)
        if set_digi is not None:
            with contextlib.suppress(Exception):
                set_digi(False)
        stop_tx = getattr(self._audio_service, "stop_tx", None)
        if stop_tx is not None:
            with contextlib.suppress(Exception):
                stop_tx()
        set_ptt = getattr(self.radio, "set_ptt", None)
        if set_ptt is not None:
            with contextlib.suppress(Exception):
                set_ptt(False, source="rtty")
        self._tx_deadline = None
        self._tx_release_at = None
        self._tx_audio_end = None


__all__ = ["RttyEngine", "RttySignal", "TX_WATCHDOG_SEC"]
