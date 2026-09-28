"""RTTY (Baudot/ITA2): codec puro + generación y detección de tonos FSK.

Sin E/S: recibe/devuelve texto y arrays de ``numpy``. La fuente de audio real
(``_vendor.audio.pop_rx_raw_chunk_digi()``) y la inyección en TX
(``_vendor.audio.inject_tx_audio()``) viven en :mod:`poorsdr_rtty_power.engine`.

IMPORTANTE — validar antes de usar en aire real: la tabla Baudot/ITA2 de abajo
sigue la variante "US" habitual en RTTY de radioaficionado (referencia estándar
tipo Wikipedia/fldigi), pero no se ha contrastado carácter a carácter contra
una grabación real ni contra otro decodificador ya probado (fldigi, MMTTY).
Los tests de este módulo comprueban que codificar y decodificar son inversos
entre sí (autoconsistencia), no que coincidan con lo que espera una estación
real al otro lado. Antes de confiar en esto en un concurso: decodificar una
grabación conocida (o comparar con fldigi) y confirmar que las letras/dígitos
salen bien — es lo único que de verdad importa para CALL/RST/zona.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime

import numpy as np

# --------------------------------------------------------------------------- #
# Bandas HF de referencia (RTTY es siempre HF de aficionado en la práctica).
# --------------------------------------------------------------------------- #
_HF_BANDS_HZ: tuple[tuple[float, float, str], ...] = (
    (1_800_000.0, 2_000_000.0, "160m"),
    (3_500_000.0, 4_000_000.0, "80m"),
    (5_250_000.0, 5_450_000.0, "60m"),
    (7_000_000.0, 7_300_000.0, "40m"),
    (10_100_000.0, 10_150_000.0, "30m"),
    (14_000_000.0, 14_350_000.0, "20m"),
    (18_068_000.0, 18_168_000.0, "17m"),
    (21_000_000.0, 21_450_000.0, "15m"),
    (24_890_000.0, 24_990_000.0, "12m"),
    (28_000_000.0, 29_700_000.0, "10m"),
)


def band_from_freq_hz(freq_hz: float) -> str:
    """Banda HF de aficionado a la que pertenece ``freq_hz`` (cadena vacía si
    no cae en ninguna): solo para rellenar el campo "Banda" del diálogo de
    guardar QSO por defecto, el operador puede corregirlo a mano."""
    for lo, hi, name in _HF_BANDS_HZ:
        if lo <= freq_hz <= hi:
            return name
    return ""

# --------------------------------------------------------------------------- #
# Baudot / ITA2 (variante US)
# --------------------------------------------------------------------------- #
# Índice = valor del código de 5 bits (bit0 = primer bit transmitido = LSB).
# None = no imprimible / sin uso en la variante US.
_LTRS_TABLE = [
    None, "E", "\n", "A", " ", "S", "I", "U",
    "\r", "D", "R", "J", "N", "F", "C", "K",
    "T", "Z", "L", "W", "H", "Y", "P", "Q",
    "O", "B", "G", None, "M", "X", "V", None,
]
_FIGS_TABLE = [
    None, "3", "\n", "-", " ", "\x07", "8", "7",
    "\r", "$", "4", "'", ",", "!", ":", "(",
    "5", '"', ")", "2", "#", "6", "0", "1",
    "9", "?", "&", None, ".", "/", ";", None,
]

FIGS_SHIFT = 27
LTRS_SHIFT = 31

BAUD_DEFAULT = 45.45
SHIFT_HZ_DEFAULT = 170.0

_CHAR_TO_CODE: dict[str, tuple[int, bool]] = {}
for _code, _ch in enumerate(_LTRS_TABLE):
    if _ch is not None and _ch not in _CHAR_TO_CODE:
        _CHAR_TO_CODE[_ch] = (_code, False)
for _code, _ch in enumerate(_FIGS_TABLE):
    if _ch is not None and _ch not in _CHAR_TO_CODE:
        _CHAR_TO_CODE[_ch] = (_code, True)
# Letras siempre en mayúscula en RTTY; aceptar minúsculas al codificar.
for _ch in list(_CHAR_TO_CODE):
    if _ch.isalpha():
        _CHAR_TO_CODE[_ch.lower()] = _CHAR_TO_CODE[_ch]


def encode_text_to_baudot(text: str) -> list[int]:
    """Texto -> lista de códigos de 5 bits, insertando LTRS/FIGS cuando cambia
    de banco.

    Vale para receptores con y sin UOS (Unshift On Space, lo habitual en
    MMTTY/N1MM/fldigi): tras un espacio en cifras, uno con UOS ha vuelto a
    letras y otro sin UOS sigue en cifras, así que el siguiente carácter
    lleva siempre su código de banco explícito. Sin esto, "599 14" se
    recibía como "599 QR" justo en el intercambio de concurso. También
    empieza siempre con un código de banco: no se puede suponer en qué banco
    dejó el ruido al receptor."""
    codes: list[int] = []
    figs: bool | None = None  # None = el receptor puede estar en cualquiera
    for ch in text:
        entry = _CHAR_TO_CODE.get(ch)
        if entry is None:
            continue  # carácter sin representación en Baudot US: se omite
        code, needs_figs = entry
        if ch in " \r\n":  # existen en los dos bancos: no fuerzan cambio
            codes.append(code)
            if ch == " " and figs:
                figs = None
            continue
        if needs_figs != figs:
            codes.append(FIGS_SHIFT if needs_figs else LTRS_SHIFT)
            figs = needs_figs
        codes.append(code)
    return codes


def decode_baudot_to_text(codes: list[int]) -> str:
    """Lista de códigos de 5 bits -> texto, siguiendo los shifts LTRS/FIGS."""
    out: list[str] = []
    figs = False
    for code in codes:
        if code == FIGS_SHIFT:
            figs = True
            continue
        if code == LTRS_SHIFT:
            figs = False
            continue
        ch = (_FIGS_TABLE if figs else _LTRS_TABLE)[code & 0x1F]
        if ch is not None:
            out.append(ch)
    return "".join(out)


# --------------------------------------------------------------------------- #
# TX: texto -> tono FSK (5N1.5: 1 bit de arranque + 5 de datos + 1.5 de parada)
# --------------------------------------------------------------------------- #
def generate_fsk_samples(
    text: str,
    *,
    sample_rate: int = 8000,
    baud: float = BAUD_DEFAULT,
    shift_hz: float = SHIFT_HZ_DEFAULT,
    center_hz: float = 1500.0,
    amplitude: float = 0.5,
    idle_marks: int = 8,
) -> np.ndarray:
    """Genera audio (float32 mono) para transmitir ``text`` en RTTY.

    Convención propia (consistente con :class:`RttyDemodulator`): "mark" = tono
    agudo = bit 1 = reposo/parada; "space" = tono grave = bit 0 = arranque.
    """
    mark_hz = center_hz + shift_hz / 2.0
    space_hz = center_hz - shift_hz / 2.0
    bit_len = int(round(sample_rate / baud))
    stop_len = int(round(bit_len * 1.5))

    codes = encode_text_to_baudot(text)
    # (frecuencia, duracion_en_muestras) por elemento — la parada dura 1.5
    # periodos de bit, no 1: si se codificara como un "bit" más de duración
    # normal, el reloj del decodificador se desincroniza carácter a carácter.
    elements: list[tuple[float, int]] = [(mark_hz, bit_len)] * idle_marks
    for code in codes:
        elements.append((space_hz, bit_len))  # arranque
        for i in range(5):
            elements.append((mark_hz if (code >> i) & 1 else space_hz, bit_len))
        elements.append((mark_hz, stop_len))  # parada (1.5 bits)

    # Construye la fase de forma continua (sin saltos) para no meter clics.
    phase = 0.0
    chunks: list[np.ndarray] = []
    for freq, length in elements:
        t = np.arange(length) / sample_rate
        chunk = np.sin(2 * np.pi * freq * t + phase).astype(np.float64)
        chunks.append(chunk)
        phase = (phase + 2 * np.pi * freq * length / sample_rate) % (2 * np.pi)
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(chunks) * amplitude
    return audio.astype(np.float32)


# --------------------------------------------------------------------------- #
# RX de calidad de concurso: demodulador FSK no coherente con ATC
# --------------------------------------------------------------------------- #
#: Frecuencia interna tras diezmar (~22 muestras por bit a 45.45 baudios):
#: suficiente para situar cada bit con precisión y muy barata de procesar.
_DEMOD_TARGET_RATE = 1000.0
#: Silenciador: contraste medio mark/space de un carácter (0 = solo ruido,
#: 1 = señal perfecta) por debajo del cual no se imprime. Medido con
#: scripts/rtty_bench.py: 0.35 deja ~17 caracteres basura por minuto de
#: ruido (54 con 0.30) sin perder nada a -6 dB; con 0.40 ya se pierden
#: señales débiles.
DEFAULT_SQUELCH = 0.35
#: Largo de los filtros de mark/space, en bits. Mejor que 1.0 exacto con
#: señal débil (medido), sin perder desvanecimiento ni selectividad.
_TONE_FILTER_BITS = 1.3
#: Zona central de cada bit que se promedia para decidirlo (fracción de bit).
_BIT_AVERAGE = 0.7
#: ATC: constantes de tiempo (en bits) de subida y bajada de los
#: seguidores de pico/fondo. Elegidas con el banco: más rápido persigue el
#: ruido; más lento no sigue el desvanecimiento selectivo.
_ATC_ATTACK_BITS = 2.0
_ATC_DECAY_BITS = 16.0


def _lowpass_taps(cutoff_hz: float, sample_rate: float, length: int) -> np.ndarray:
    n = np.arange(length) - (length - 1) / 2.0
    taps = np.sinc(2.0 * cutoff_hz / sample_rate * n) * np.blackman(length)
    return taps / taps.sum()


class RttyDemodulator:
    """Decodificador RTTY de UNA señal (centro conocido dentro de la
    pasabanda), pensado para condiciones reales de concurso. Alimentar con
    bloques sucesivos de audio via :meth:`feed`.

    Cadena, por este orden (técnicas clásicas de los decodificadores por
    tarjeta de sonido, implementadas aquí desde cero):

    1. Mezcla a banda base en torno a ``center_hz`` + paso bajo + diezmado a
       ~1 kHz: lo que queda a más de ~±250 Hz del centro (otras estaciones,
       ruido fuera de banda) desaparece antes de decidir nada.
    2. Filtro de mark y otro de space de ~1.3 bits y detección de envolvente.
    3. ATC "óptimo" (W7AY): seguidores de pico de cada tono y un fondo de
       ruido común; decisión cuadrática con umbral en el punto medio de cada
       tono. Con los dos tonos iguales se comporta como un detector
       mark-space normal; si el desvanecimiento selectivo hunde uno, el
       umbral se desplaza y la decisión no se tuerce.
    4. Encuadre: flanco mark->space con precisión de fracción de muestra,
       cada bit se promedia en su zona central, y el carácter solo se
       acepta si el bit de arranque es space y el de parada es mark.
    5. Silenciador por contraste mark/space, UOS (vuelta a letras tras un
       espacio) y polaridad invertida (``reverse``, p. ej. en LSB).
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        center_hz: float,
        shift_hz: float = SHIFT_HZ_DEFAULT,
        baud: float = BAUD_DEFAULT,
        reverse: bool = False,
        uos: bool = True,
        squelch: float = DEFAULT_SQUELCH,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.center_hz = float(center_hz)
        self.shift_hz = abs(float(shift_hz))
        self.baud = float(baud)
        #: Se puede cambiar en caliente (el motor lo sigue según USB/LSB).
        self.reverse = bool(reverse)
        self.uos = bool(uos)
        self.squelch = float(squelch)

        self._decim = max(1, int(round(self.sample_rate / _DEMOD_TARGET_RATE)))
        self._fs2 = self.sample_rate / self._decim
        self._spb = self._fs2 / self.baud  # muestras internas por bit

        cutoff = self.shift_hz / 2.0 + 2.0 * self.baud
        pre_len = int(5.5 * self.sample_rate / 200.0) | 1
        self._pre_taps = _lowpass_taps(cutoff, self.sample_rate, pre_len)[::-1].copy()
        self._pre_hist = np.zeros(pre_len - 1, dtype=np.complex128)
        self._pre_next = pre_len - 1  # final de la próxima ventana (en hist+nuevo)
        self._mix_phase = 0.0

        tone_len = max(3, int(round(_TONE_FILTER_BITS * self._spb)))
        tone = np.hanning(tone_len + 2)[1:-1]
        self._tone_taps = tone / tone.sum()
        self._tone_hist = np.zeros(tone_len - 1, dtype=np.complex128)
        self._k = 0  # índice absoluto de muestra interna (fase de los tonos)

        self._atc_attack = 1.0 - np.exp(-1.0 / (_ATC_ATTACK_BITS * self._spb))
        self._atc_decay = 1.0 - np.exp(-1.0 / (_ATC_DECAY_BITS * self._spb))
        self._mark_peak = self._space_peak = self._noise_floor = 0.0

        self._v = np.zeros(0)
        self._m = np.zeros(0)
        self._s = np.zeros(0)
        self._pos = 1
        self._figs = False
        self._text = ""

    # ---- API -------------------------------------------------------------- #
    def retune(self, center_hz: float) -> None:
        """Nuevo centro sin perder la sincronía (lo usa el AFC)."""
        self.center_hz = float(center_hz)

    @property
    def text(self) -> str:
        return self._text

    def feed(self, samples: np.ndarray) -> str:
        """Añade audio nuevo; devuelve el texto decodificado desde la última
        llamada (puede ser cadena vacía)."""
        if samples is None or samples.size == 0:
            return ""
        z = self._downconvert(np.asarray(samples, dtype=np.float64))
        if z.size:
            v, m, s = self._detect(z)
            self._v = np.concatenate([self._v, v])
            self._m = np.concatenate([self._m, m])
            self._s = np.concatenate([self._s, s])
        text = self._frame()
        self._text += text
        return text

    # ---- 1. banda base + diezmado ---------------------------------------- #
    def _downconvert(self, x: np.ndarray) -> np.ndarray:
        w = 2.0 * np.pi * self.center_hz / self.sample_rate
        phases = self._mix_phase + w * np.arange(x.size)
        self._mix_phase = float((self._mix_phase + w * x.size) % (2.0 * np.pi))
        mixed = x * np.exp(-1j * phases)

        buf = np.concatenate([self._pre_hist, mixed])
        length = self._pre_taps.size
        ends = np.arange(self._pre_next, buf.size, self._decim)
        if ends.size:
            windows = np.lib.stride_tricks.sliding_window_view(buf, length)
            out = windows[ends - (length - 1)] @ self._pre_taps
            next_end = int(ends[-1]) + self._decim
        else:
            out = np.zeros(0, dtype=np.complex128)
            next_end = self._pre_next
        keep = length - 1
        self._pre_next = next_end - (buf.size - keep)
        self._pre_hist = buf[-keep:]
        return out

    # ---- 2 y 3. filtros de tono, envolvente, ATC ------------------------- #
    def _detect(self, z: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        half = self.shift_hz / 2.0
        hist = self._tone_hist.size
        k = self._k - hist + np.arange(hist + z.size)
        self._k += z.size
        zz = np.concatenate([self._tone_hist, z])
        self._tone_hist = zz[-hist:]

        def envelope(offset_hz: float) -> np.ndarray:
            rot = np.exp(-2j * np.pi * offset_hz / self._fs2 * k)
            return np.abs(np.convolve(zz * rot, self._tone_taps, mode="valid"))

        upper = envelope(+half)
        lower = envelope(-half)
        mark, space = (lower, upper) if self.reverse else (upper, lower)

        v = np.empty(mark.size)
        a, d = self._atc_attack, self._atc_decay
        mp, sp, nf = self._mark_peak, self._space_peak, self._noise_floor
        for i in range(mark.size):
            me, se = mark[i], space[i]
            mp += (a if me > mp else d) * (me - mp)
            sp += (a if se > sp else d) * (se - sp)
            lo = me if me < se else se
            nf += (a if lo < nf else d) * (lo - nf)
            mc = min(max(me, nf), mp) - nf
            sc = min(max(se, nf), sp) - nf
            v[i] = mc * mc - sc * sc - 0.25 * ((mp - nf) ** 2 - (sp - nf) ** 2)
        self._mark_peak, self._space_peak, self._noise_floor = mp, sp, nf
        return v, mark, space

    # ---- 4 y 5. encuadre, silenciador, Baudot ---------------------------- #
    def _bit_mean(self, arr: np.ndarray, center: float) -> float:
        half_w = 0.5 * _BIT_AVERAGE * self._spb
        lo = max(0, int(np.ceil(center - half_w)))
        hi = min(arr.size, int(np.floor(center + half_w)) + 1)
        return float(arr[lo:hi].mean()) if hi > lo else 0.0

    def _frame(self) -> str:
        v = self._v
        nb = self._spb
        tail = 7.0 * nb + 2.0  # muestras necesarias tras el flanco
        out: list[str] = []
        pos = max(1, self._pos)
        while pos < v.size:
            edges = np.nonzero((v[pos - 1 : -1] > 0.0) & (v[pos:] <= 0.0))[0]
            if edges.size == 0:
                pos = v.size
                break
            i = int(edges[0]) + pos
            if i + tail > v.size:
                pos = i
                break
            a, b = v[i - 1], v[i]
            t0 = (i - 1) + a / (a - b) if a != b else float(i)
            centers = [t0 + (n + 0.5) * nb for n in range(7)]
            bits = [self._bit_mean(v, c) for c in centers]
            if bits[0] >= 0.0 or bits[6] <= 0.0:
                pos = i + 1  # arranque o parada falsos: no era un carácter
                continue
            pos = int(t0 + 6.8 * nb)  # admite 1 o 1.5 bits de parada
            contrast = 0.0
            for c in centers:
                mm, ss = self._bit_mean(self._m, c), self._bit_mean(self._s, c)
                contrast += abs(mm - ss) / (mm + ss + 1e-12)
            if contrast / 7.0 < self.squelch:
                continue
            code = sum(1 << n for n in range(5) if bits[n + 1] > 0.0)
            ch = self._to_char(code)
            if ch:
                out.append(ch)
        drop = max(0, pos - 1)
        if drop:
            self._v, self._m, self._s = self._v[drop:], self._m[drop:], self._s[drop:]
            pos -= drop
        self._pos = pos
        return "".join(out)

    def _to_char(self, code: int) -> str:
        if code == FIGS_SHIFT:
            self._figs = True
            return ""
        if code == LTRS_SHIFT:
            self._figs = False
            return ""
        ch = (_FIGS_TABLE if self._figs else _LTRS_TABLE)[code & 0x1F]
        if ch == " " and self.uos:
            self._figs = False
        return ch or ""


# --------------------------------------------------------------------------- #
# Escaneo multi-señal dentro de la pasabanda (estilo "multi-RTTY" de
# MMTTY/fldigi): no ve todo el sub-band, solo lo que entra por el filtro SSB
# del uSDX actualmente sintonizado.
# --------------------------------------------------------------------------- #
DEFAULT_SCAN_RANGE_HZ = (300.0, 2900.0)


def find_signal_candidates(
    samples: np.ndarray,
    sample_rate: int,
    *,
    shift_hz: float = SHIFT_HZ_DEFAULT,
    scan_range_hz: tuple[float, float] = DEFAULT_SCAN_RANGE_HZ,
    min_peak_db: float = -40.0,
) -> list[float]:
    """Busca pares de picos espaciados ``shift_hz`` en el espectro de
    ``samples`` dentro de ``scan_range_hz`` y devuelve sus frecuencias
    centrales candidatas (mark+space)/2, de mayor a menor energía."""
    if samples is None or samples.size < 256:
        return []
    n = int(2 ** np.ceil(np.log2(samples.size)))
    windowed = samples.astype(np.float64) * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed, n=n))
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    ref = np.max(spectrum) if spectrum.size else 0.0
    if ref <= 0:
        return []
    db = 20 * np.log10(np.maximum(spectrum / ref, 1e-12))

    lo, hi = scan_range_hz
    mask = (freqs >= lo) & (freqs <= hi)
    idxs = np.where(mask & (db >= min_peak_db))[0]
    if idxs.size == 0:
        return []

    bin_hz = sample_rate / n
    shift_bins = max(1, int(round(shift_hz / bin_hz)))
    tol = max(1, int(round(shift_bins * 0.15)))

    candidates: list[tuple[float, float]] = []  # (energia, centro)
    seen_centers: set[int] = set()
    for i in idxs:
        for d in range(shift_bins - tol, shift_bins + tol + 1):
            j = i + d
            if j >= freqs.size or j not in idxs and db[j] < min_peak_db:
                continue
            if j >= db.size:
                continue
            center = (freqs[i] + freqs[j]) / 2.0
            key = int(round(center))
            if key in seen_centers:
                continue
            seen_centers.add(key)
            energy = float(db[i] + db[j])
            candidates.append((energy, float(center)))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in candidates]


# --------------------------------------------------------------------------- #
# Autoguardado en el libro de guardia: ADIF + paquete UDP estilo WSJT-X
# --------------------------------------------------------------------------- #
# En vez de hablar el schema propio de NMN1M (o de cualquier otro libro de
# guardia), reutilizamos el protocolo UDP de WSJT-X: NMN1M ya sabe escucharlo
# ("Escuchar WSJT-X por UDP", puerto 2237 por defecto) para importar QSOs de
# WSJT-X/JTDX automáticamente, así que basta con imitar su mensaje "Logged
# ADIF" (tipo 12) -- funciona igual para cualquier otro programa que también
# hable ese mismo protocolo, sin acoplar RTTY a un log concreto.
#
# Formato verificado línea a línea contra el parser real de NMN1M
# (``Libro-Guardia.py::_extract_wsjtx_logged_adif``/``_read_qbytearray_utf8``):
# magic(u32 BE) + schema(u32 BE) + tipo(u32 BE)=12 + QByteArray(id) +
# QByteArray(adif), donde QByteArray = longitud en bytes (u32 BE) + UTF-8.
_WSJTX_MAGIC = 0xADBCCBDA
_WSJTX_SCHEMA = 2
_WSJTX_MSG_TYPE_LOGGED_ADIF = 12


def _adif_field(name: str, value: str) -> str:
    return f"<{name}:{len(value)}>{value} "


def build_qso_adif(
    *,
    call: str,
    band: str,
    freq_hz: float,
    rst_sent: str,
    rst_recv: str,
    zone_sent: str = "",
    zone_recv: str = "",
    qth_recv: str = "",
    my_call: str = "",
    my_grid: str = "",
    notes: str = "",
    timestamp_utc: str | None = None,
) -> str:
    """Un registro ADIF (con ``<EOR>``) de un QSO RTTY, listo para meter
    dentro de un paquete "Logged ADIF" de WSJT-X. ``timestamp_utc`` en
    ISO 8601 UTC (por defecto, el instante actual)."""
    dt = timestamp_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    date = dt[0:10].replace("-", "")
    time_on = dt[11:19].replace(":", "")
    fields: dict[str, str] = {
        "CALL": call.strip().upper(),
        "QSO_DATE": date,
        "TIME_ON": time_on,
        "MODE": "RTTY",
        "FREQ": f"{float(freq_hz) / 1_000_000:.6f}",
        "RST_SENT": rst_sent.strip(),
        "RST_RCVD": rst_recv.strip(),
    }
    band_clean = band.strip().upper()
    if band_clean:
        fields["BAND"] = band_clean
    zone_sent_clean = zone_sent.strip().upper()
    if zone_sent_clean:
        # STX_STRING/SRX_STRING (texto) es lo que ya usa la propia plantilla
        # "CQ WW RTTY" de NMN1M; STX/SRX (numérico) es lo único que además
        # lee el importador genérico de ADIF (el que atiende este mismo
        # paquete WSJT-X) -- se manda en los dos formatos por compatibilidad.
        fields["STX_STRING"] = zone_sent_clean
        if zone_sent_clean.isdigit():
            fields["STX"] = zone_sent_clean
    zone_recv_clean = zone_recv.strip().upper()
    if zone_recv_clean:
        fields["SRX_STRING"] = zone_recv_clean
        if zone_recv_clean.isdigit():
            fields["SRX"] = zone_recv_clean
    qth_recv_clean = qth_recv.strip().upper()
    if qth_recv_clean:
        # Estado/provincia de EE.UU./Canadá (CQ WW RTTY: "599 05 MA"). STATE
        # es el campo ADIF estándar y el que lee NMN1M para su Cabrillo.
        fields["STATE"] = qth_recv_clean
    if my_call.strip():
        fields["OPERATOR"] = my_call.strip().upper()
    if my_grid.strip():
        fields["MY_GRIDSQUARE"] = my_grid.strip().upper()
    if notes.strip():
        fields["COMMENT"] = notes.strip()
    body = "".join(_adif_field(k, v) for k, v in fields.items() if v)
    return body + "<EOR>\n"


def _qbytearray_utf8(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack(">I", len(data)) + data


def build_wsjtx_logged_adif_packet(adif_text: str, *, client_id: str = "PoorSDR4All-RTTY") -> bytes:
    """Datagrama UDP "Logged ADIF" (tipo 12) del protocolo de WSJT-X: es lo
    mínimo que hace falta para que un programa que ya escucha ese protocolo
    (como NMN1M) importe un QSO como si lo hubiera logueado WSJT-X."""
    header = struct.pack(">III", _WSJTX_MAGIC, _WSJTX_SCHEMA, _WSJTX_MSG_TYPE_LOGGED_ADIF)
    return header + _qbytearray_utf8(client_id) + _qbytearray_utf8(adif_text)


__all__ = [
    "BAUD_DEFAULT",
    "SHIFT_HZ_DEFAULT",
    "FIGS_SHIFT",
    "LTRS_SHIFT",
    "encode_text_to_baudot",
    "decode_baudot_to_text",
    "generate_fsk_samples",
    "RttyDemodulator",
    "DEFAULT_SQUELCH",
    "find_signal_candidates",
    "DEFAULT_SCAN_RANGE_HZ",
    "band_from_freq_hz",
    "build_qso_adif",
    "build_wsjtx_logged_adif_packet",
]
