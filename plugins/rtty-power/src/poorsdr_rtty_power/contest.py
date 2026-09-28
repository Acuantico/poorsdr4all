"""Reglas de concurso RTTY (CQ WW RTTY, https://cqwwrtty.com/rules.htm).

Lógica pura (sin Tk ni ficheros) para el panel RTTY: qué indicativos ya se
han trabajado, cuáles llaman CQ, qué intercambio se ha recibido y si la banda
cuenta. Así se puede probar sin interfaz.

Reglas que se aplican aquí:
- intercambio: RST + zona CQ ("599 14"); EE.UU. continental y Canadá
  añaden estado/provincia ("599 05 MA");
- cada estación se puede trabajar una vez POR BANDA;
- solo 80, 40, 20, 15 y 10 m;
- 48 h, de sábado 00:00 a domingo 23:59:59 UTC.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: Indicativo de aficionado: prefijo (1-3), cifra, sufijo (1-4 letras).
CALL_RE = re.compile(r"\b[A-Z0-9]{1,3}\d[A-Z]{1,4}\b")

CONTEST_BANDS = ("80m", "40m", "20m", "15m", "10m")

#: QTH que mandan EE.UU. continental (48 estados + DC) y Canadá (áreas).
US_STATES = frozenset(
    ["AL", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
)
CANADA_AREAS = frozenset(["NB", "NS", "PE", "QC", "ON", "MB", "SK", "AB", "BC", "NT", "NU", "YT", "NL", "LB", "NF"])
WVE_QTHS = US_STATES | CANADA_AREAS

#: Fuera de un fin de semana UTC (pruebas entre semana), un QSO cuenta como
#: trabajado durante esto.
WORKED_WINDOW_SEC = 48 * 3600
#: El fichero de trabajados no guarda nada más viejo que esto.
_KEEP_SEC = 7 * 24 * 3600
#: Hasta cuántos caracteres antes de un indicativo se busca "CQ" para saber
#: si ese indicativo está llamando CQ ("CQ TEST DE K1XYZ K1XYZ").
CQ_LOOKBACK_CHARS = 60
#: ...y hasta cuántos DESPUÉS ("K1XYZ K1XYZ TEST").
CQ_LOOKAHEAD_CHARS = 25

# RST (3 cifras), zona 1-40 (quizá repetida), y opcionalmente estado/provincia
# (quizá repetido). El QTH se valida contra WVE_QTHS aparte.
_EXCHANGE_RE = re.compile(
    r"\b([1-5][1-9][1-9])\s+(\d{1,2})\b(?:\s+\2\b)*(?:\s+([A-Z]{2})\b(?:\s+\3\b)*)?"
)


def contest_window_start(now: float) -> float:
    """Desde cuándo cuentan los QSOs como "trabajados". En fin de semana UTC
    (el CQ WW va de sábado 00:00 a domingo 23:59 UTC) desde el sábado a las
    00:00 UTC: los QSOs de prueba del viernes NO salen como duplicados en el
    concurso. Entre semana, las últimas 48 h."""
    dt = datetime.fromtimestamp(now, tz=UTC)
    if dt.weekday() in (5, 6):  # sábado, domingo
        saturday = (dt - timedelta(days=dt.weekday() - 5)).replace(hour=0, minute=0, second=0, microsecond=0)
        return saturday.timestamp()
    return now - WORKED_WINDOW_SEC


def is_contest_band(band: str) -> bool:
    return band.strip().lower() in CONTEST_BANDS


@dataclass(frozen=True)
class WorkedQso:
    call: str
    band: str
    timestamp: float


class WorkedLog:
    """QSOs guardados desde el panel. En concurso se puede trabajar a la
    misma estación una vez por banda: "trabajado" es por banda."""

    def __init__(self, entries: list[WorkedQso] | None = None) -> None:
        self.entries: list[WorkedQso] = list(entries or [])

    def add(self, call: str, band: str, timestamp: float | None = None) -> None:
        self.entries.append(
            WorkedQso(call.strip().upper(), band.strip().lower(), time.time() if timestamp is None else timestamp)
        )

    def is_worked(self, call: str, band: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        since = contest_window_start(now)
        call, band = call.strip().upper(), band.strip().lower()
        return any(e.call == call and e.band == band and e.timestamp >= since for e in self.entries)

    def to_json(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        return [
            {"call": e.call, "band": e.band, "ts": e.timestamp}
            for e in self.entries
            if now - e.timestamp <= _KEEP_SEC
        ]

    @classmethod
    def from_json(cls, data: object) -> WorkedLog:
        entries = []
        for item in data if isinstance(data, list) else []:
            try:
                entries.append(WorkedQso(str(item["call"]).upper(), str(item["band"]).lower(), float(item["ts"])))
            except (KeyError, TypeError, ValueError):
                continue
        return cls(entries)


@dataclass(frozen=True)
class Exchange:
    rst: str
    zone: str
    qth: str = ""

    def __str__(self) -> str:
        return " ".join(part for part in (self.rst, self.zone, self.qth) if part)


def parse_exchange(text: str) -> Exchange | None:
    """ÚLTIMO intercambio CQ WW válido del texto ("599 05 05 MA" -> 599,
    05, MA). La zona tiene que ser 1-40; un par de letras solo cuenta como
    QTH si es un estado/provincia de verdad (no "TU", "DE", "BK"...)."""
    upper = text.upper()
    found = None
    for match in _EXCHANGE_RE.finditer(upper):
        zone = int(match.group(2))
        if not 1 <= zone <= 40:
            continue
        qth = match.group(3) or ""
        # Solo EE.UU./Canadá (zonas 1-5) mandan QTH; y "DE" seguido de un
        # indicativo es "de", no Delaware ("599 05 DE K1XYZ").
        if qth not in WVE_QTHS or zone > 5 or qth == "DE" and CALL_RE.match(upper[match.end() :].lstrip()):
            qth = ""
        found = Exchange(match.group(1), f"{zone:02d}", qth)
    return found


def split_exchange(text: str) -> Exchange:
    """Campo "Exchange"/"Recibido" escrito a mano -> partes, tolerante
    ("599 14", "599 14 14", "599 05 MA", "14")."""
    parts = text.strip().upper().split()
    rst = parts[0] if parts and len(parts[0]) == 3 and parts[0].isdigit() else ""
    rest = parts[1:] if rst else parts
    zone = next((p for p in rest if p.isdigit()), "")
    qth = next((p for p in rest if p in WVE_QTHS), "")
    return Exchange(rst, zone, qth)


#: Palabras con las que una estación "llama" en concurso: no todos mandan
#: "CQ" -- muchos lanzan "TEST K1XYZ K1XYZ", "K1XYZ K1XYZ TEST" o "QRZ".
_CALL_MARKERS = frozenset({"CQ", "TEST", "QRZ"})
_CALL_FILLER = frozenset({"DE", "WW", "RTTY", "CONTEST", "K", "PSE"})


def _walk_is_calling(tokens: list[str], call: str, markers: frozenset[str] = _CALL_MARKERS) -> bool:
    # Tolerante con la decodificación real: la basura suele llegar pegada
    # ("VTFEMCQ YT3YT3X YT3X", confirmado en el aire), así que una palabra
    # que empieza o acaba en CQ/TEST/QRZ cuenta como llamada, y una que
    # contiene el indicativo cuenta como su repetición.
    for token in tokens:
        if any(token.startswith(m) or token.endswith(m) for m in markers):
            return True
        if call in token or token in _CALL_FILLER:
            continue
        return False  # otro indicativo, "599", "TU"...: no es su llamada
    return False


def is_calling_cq(text: str, call_start: int, call_end: int | None = None) -> bool:
    """¿El indicativo en ``text[call_start:call_end]`` está llamando?

    Se lee por palabras, como una llamada de concurso: desde el indicativo
    hacia atrás ("CQ TEST DE K1XYZ K1XYZ") y hacia delante ("K1XYZ K1XYZ
    TEST", "TU K1XYZ TEST"), saltando solo el propio indicativo repetido y
    relleno de llamada (DE, WW, RTTY...). "TU" justo antes también cuenta
    ("W9EXL TU CN3A": cierre y nueva llamada). Si antes de llegar a CQ/TEST/QRZ
    aparece otra cosa (otro indicativo, "599", "TU"), no es su llamada: así
    "DL1ZZZ 599 14 / CQ DE K1XYZ" no toma el CQ de otra estación."""
    upper = text.upper()
    if call_end is None:
        match = CALL_RE.match(upper, call_start)
        call_end = match.end() if match else call_start
    call = upper[call_start:call_end]
    before = upper[max(0, call_start - CQ_LOOKBACK_CHARS) : call_start].split()
    after = upper[call_end : call_end + CQ_LOOKAHEAD_CHARS].split()
    # Hacia atrás también vale "TU": "W9EXL TU CN3A" es el cierre del que
    # llama CQ ("gracias W9EXL, aquí CN3A, adelante el siguiente"), aunque
    # no diga CQ ni TEST. Hacia delante no: "TU 599 14" es de quien contesta.
    return _walk_is_calling(list(reversed(before)), call, _CALL_MARKERS | {"TU"}) or _walk_is_calling(
        after, call
    )


def cq_caller(text: str, my_call: str = "") -> str | None:
    """Indicativo que está llamando en la ÚLTIMA llamada del texto ("CQ TEST
    DE K1XYZ", "K1XYZ K1XYZ TEST" -> "K1XYZ"), sin contar el propio."""
    upper = text.upper()
    mine = my_call.strip().upper()
    for match in reversed(list(CALL_RE.finditer(upper))):
        if match.group(0) != mine and is_calling_cq(upper, match.start(), match.end()):
            return match.group(0)
    return None


#: Hasta cuántos caracteres tras tu indicativo se busca el intercambio que
#: te da la estación a la que has llamado ("EA1ABC 599 05 05 MA").
REPLY_EXCHANGE_CHARS = 40
_RST_RE = re.compile(r"\b([1-5][1-9][1-9])\b")


def find_reply_exchange(text: str, my_call: str, *, require_zone: bool = False) -> Exchange | None:
    """Intercambio que te ha dado la estación a la que respondiste: tu
    indicativo (entero, aunque llegue pegado a basura o repetido) seguido de
    un intercambio válido. Si contesta a otro ("DL1ZZZ 599 14 14") o tu
    indicativo llega mal, ``None``: mejor no enviar nada que mandar el
    intercambio a quien no te ha contestado. En concurso (``require_zone``)
    el RST solo no basta: hay que esperar también a su zona."""
    upper = text.upper()
    mine = my_call.strip().upper()
    if not mine:
        return None
    found = None
    start = upper.find(mine)
    while start != -1:
        window = upper[start + len(mine) : start + len(mine) + REPLY_EXCHANGE_CHARS]
        exchange = parse_exchange(window)
        if exchange is None and not require_zone:
            # QSO normal: solo llega el RST ("EA0XXX DE LZ3ND UR 599 599"),
            # sin zona -- también es su reporte.
            rst = _RST_RE.search(window)
            if rst is not None:
                exchange = Exchange(rst.group(1), "")
        if exchange is not None:
            found = exchange
        start = upper.find(mine, start + 1)
    return found


def cq_answer(my_call: str) -> str:
    """Respuesta a un CQ en concurso: el indicativo propio, dos veces."""
    call = my_call.strip().upper()
    return f"{call} {call}"


def report_text(call: str, my_call: str) -> str:
    """Reporte de un QSO normal: "LZ3ND DE EA0XXX 599 599"."""
    return f"{call.strip().upper()} DE {my_call.strip().upper()} 599 599"


def reply_text(call: str, my_call: str, exchange: str) -> str:
    """Lo que se envía al responder a una estación (botón Responder y envío
    automático al recibir su reporte). Si el campo Exchange lleva zona es
    concurso -> formato corto ("LZ3ND 599 14 14"); si solo lleva "599" o
    está vacío es un QSO normal -> reporte completo con los dos indicativos."""
    if split_exchange(exchange).zone:
        return f"{call.strip().upper()} {exchange.strip().upper()}"
    return report_text(call, my_call)


#: Fases de un QSO para el botón Responder: "none" (aún nada), "called"
#: (le has contestado a su CQ con tu indicativo), "report_tx" (ya le has
#: dado tu reporte), "done" (ya os habéis despedido).
QSO_PHASES = ("none", "called", "report_tx", "done")


def closing_text(call: str, my_call: str, exchange: str) -> str:
    """Despedida: "TU 73 LZ3ND DE EA0XXX SK"; en concurso, solo "TU"."""
    if split_exchange(exchange).zone:
        return "TU"
    return f"TU 73 {call.strip().upper()} DE {my_call.strip().upper()} SK"


def responder_step(
    phase: str, *, call: str, my_call: str, exchange: str, calling_cq: bool
) -> tuple[str, str]:
    """Qué envía Responder según la fase del QSO, y la fase siguiente.

    - Nada aún y la estación llama CQ -> tu indicativo dos veces.
    - Nada aún y NO llama CQ (te ha llamado a ti) -> tu reporte.
    - Ya le contestaste al CQ (te habrá dado su reporte) -> tu reporte.
    - Ya le diste tu reporte -> despedida.
    """
    if phase == "none":
        if calling_cq:
            return cq_answer(my_call), "called"
        return reply_text(call, my_call, exchange), "report_tx"
    if phase == "called":
        return reply_text(call, my_call, exchange), "report_tx"
    return closing_text(call, my_call, exchange), "done"


def exchange_to_send(zone: str) -> str:
    """Intercambio a enviar: "599 14 14" (zona repetida, como en N1MM para
    RTTY: si se pierde una por QRM, se copia la otra)."""
    zone = zone.strip()
    return f"599 {zone} {zone}" if zone else "599"


__all__ = [
    "CALL_RE",
    "CANADA_AREAS",
    "CONTEST_BANDS",
    "CQ_LOOKAHEAD_CHARS",
    "CQ_LOOKBACK_CHARS",
    "US_STATES",
    "WORKED_WINDOW_SEC",
    "WVE_QTHS",
    "Exchange",
    "WorkedLog",
    "WorkedQso",
    "contest_window_start",
    "cq_answer",
    "cq_caller",
    "exchange_to_send",
    "find_reply_exchange",
    "is_calling_cq",
    "is_contest_band",
    "QSO_PHASES",
    "closing_text",
    "parse_exchange",
    "responder_step",
    "reply_text",
    "report_text",
    "split_exchange",
]
