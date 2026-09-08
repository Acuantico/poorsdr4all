"""S-metro de aguja alimentado por el nivel de señal del propio OWRX.

El µSDX no informa el S-metro por CAT, pero el visor nativo ya calcula un
nivel en dBFS dentro de la banda de paso (la misma señal que dibuja el
espectro/cascada). Este módulo es el *functional core*: conversión pura
dBFS → unidades de aguja (S0-S9, luego "+dB" sobre S9) y grados de deflexión,
más una pequeña clase de balística (ataque rápido, caída más lenta) para que
la aguja se mueva como un medidor mecánico real y no salte a trompicones.

No hay una calibración absoluta posible sin conocer la ganancia del SDR (cada
receptor/perfil OWRX mide dBFS distinto): en vez de fijar un dBFS de S0/S9 a
ciegas, :class:`NoiseFloorTracker` sigue el "suelo" real de la banda (ruido +
QRM ambiente, sin señal) y calibra la escala para que ese suelo caiga donde
cae en una radio real (S3-S5 típico, no S0) — así el S-metro se autocalibra
solo, sin depender de un dBFS absoluto que no tiene por qué coincidir con el
de este SDR/ganancia concretos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Unidades totales de la escala: 9 (S0..S9) + las de "sobre S9".
_S_UNITS = 9.0


@dataclass(frozen=True, slots=True)
class SMeterConfig:
    # Por defecto S9 coincide con 0 dBFS (a plena escala): con
    # ``max_over_units=3`` y 10 dB/unidad, el tope de la escala (S9+30) cae
    # justo en 0 dBFS, que es el techo físico real (no se puede pasar de
    # ahí). ``db_per_s_unit`` se deriva para que S9 caiga exactamente en
    # ``s9_dbfs`` (sin "meseta" antes de llegar).
    noise_floor_dbfs: float = -66.0
    s9_dbfs: float = -30.0
    db_per_s_unit: float = 4.0  # (s9_dbfs - noise_floor_dbfs) / 9
    db_per_over_unit: float = 10.0  # una unidad "sobre S9" = 10 dB
    max_over_units: float = 3.0  # tope de la escala: S9 + 30 dB
    angle_min_deg: float = -45.0  # reposo (izquierda)
    angle_max_deg: float = 45.0  # fondo de escala (derecha)

    def __post_init__(self) -> None:
        if self.s9_dbfs <= self.noise_floor_dbfs:
            raise ValueError("s9_dbfs debe ser mayor que noise_floor_dbfs")
        if self.db_per_s_unit <= 0 or self.db_per_over_unit <= 0:
            raise ValueError("los dB por unidad deben ser positivos")

    @property
    def span_units(self) -> float:
        return _S_UNITS + self.max_over_units


_DEFAULT_CFG = SMeterConfig()


def dbfs_to_meter_units(dbfs: float, cfg: SMeterConfig = _DEFAULT_CFG) -> float:
    """dBFS -> unidades de aguja: 0..9 son S0..S9; por encima, "sobre S9"."""
    if dbfs <= cfg.noise_floor_dbfs:
        return 0.0
    if dbfs <= cfg.s9_dbfs:
        units = (dbfs - cfg.noise_floor_dbfs) / cfg.db_per_s_unit
        return max(0.0, min(_S_UNITS, units))
    over = (dbfs - cfg.s9_dbfs) / cfg.db_per_over_unit
    return min(cfg.span_units, _S_UNITS + over)


def meter_units_to_angle_deg(units: float, cfg: SMeterConfig = _DEFAULT_CFG) -> float:
    """Unidades de aguja -> grados de deflexión (0 = reposo, span = fondo)."""
    frac = max(0.0, min(1.0, units / cfg.span_units))
    return cfg.angle_min_deg + frac * (cfg.angle_max_deg - cfg.angle_min_deg)


def dbfs_to_angle_deg(dbfs: float, cfg: SMeterConfig = _DEFAULT_CFG) -> float:
    return meter_units_to_angle_deg(dbfs_to_meter_units(dbfs, cfg), cfg)


def format_s_label(units: float, cfg: SMeterConfig = _DEFAULT_CFG) -> str:
    """'S0'..'S9', o 'S9+20' por encima de S9 (redondeado a 10 dB)."""
    if units <= _S_UNITS:
        return f"S{round(units)}"
    over_db = round((units - _S_UNITS) * cfg.db_per_over_unit / 10.0) * 10
    return f"S9+{int(over_db)}" if over_db > 0 else "S9"


class SMeterBallistics:
    """Suaviza el valor de la aguja como un medidor mecánico: sube deprisa
    (ataque) y baja despacio (caída), en las mismas unidades que
    :func:`dbfs_to_meter_units`.
    """

    def __init__(
        self,
        cfg: SMeterConfig | None = None,
        *,
        attack_per_s: float = 30.0,
        release_per_s: float = 8.0,
    ) -> None:
        self.cfg = cfg or SMeterConfig()
        self._attack = attack_per_s
        self._release = release_per_s
        self.value = 0.0

    def reset(self) -> None:
        self.value = 0.0

    def push_dbfs(self, dbfs: float, dt: float) -> float:
        """Actualiza la aguja con una nueva lectura y devuelve el valor suavizado."""
        target = dbfs_to_meter_units(dbfs, self.cfg)
        rate = self._attack if target > self.value else self._release
        step = rate * max(0.0, dt)
        if target > self.value:
            self.value = min(target, self.value + step)
        else:
            self.value = max(target, self.value - step)
        return self.value

    @property
    def angle_deg(self) -> float:
        return meter_units_to_angle_deg(self.value, self.cfg)

    @property
    def label(self) -> str:
        return format_s_label(self.value, self.cfg)


@dataclass(frozen=True, slots=True)
class SMeterAutoCalibration:
    """Parámetros de la autocalibración: dónde debe caer el "suelo" de banda
    (ruido + QRM ambiente, sin señal) y cuántos dB representa cada unidad S.
    """

    ambient_units: float = 5.0  # el suelo detectado se calibra en S5 (típico)
    db_per_unit: float = 6.0  # convención de radioafición
    attack_tau_s: float = 2.0  # sigue deprisa las lecturas más flojas
    release_tau_s: float = 120.0  # sube muy despacio: no lo engaña una señal larga

    def __post_init__(self) -> None:
        if self.db_per_unit <= 0:
            raise ValueError("db_per_unit debe ser positivo")
        if self.attack_tau_s <= 0 or self.release_tau_s <= 0:
            raise ValueError("las constantes de tiempo deben ser positivas")
        if not 0.0 <= self.ambient_units <= _S_UNITS:
            raise ValueError(f"ambient_units debe estar entre 0 y {_S_UNITS:g}")


class NoiseFloorTracker:
    """Sigue el "suelo" de la banda bajo las señales: baja deprisa hacia
    lecturas más flojas (el receptor encuentra un hueco más silencioso) y
    sube muy despacio en caso contrario, para que una señal fuerte o larga no
    lo arrastre hacia arriba. El suelo detectado se calibra como
    :attr:`SMeterAutoCalibration.ambient_units` (S3-S5 típico, el ruido de
    banda de una radio real), no como S0 — así el S-metro no se queda pegado
    a S0 con QRM real presente.
    """

    def __init__(
        self, cal: SMeterAutoCalibration | None = None, *, initial_dbfs: float = -60.0
    ) -> None:
        self.cal = cal or SMeterAutoCalibration()
        self.floor_dbfs = initial_dbfs
        self._seen = False

    def reset(self, initial_dbfs: float = -60.0) -> None:
        self.floor_dbfs = initial_dbfs
        self._seen = False

    def push(self, dbfs: float, dt: float) -> float:
        """Actualiza el suelo detectado con una nueva lectura."""
        if not self._seen:
            self.floor_dbfs = dbfs
            self._seen = True
            return self.floor_dbfs
        tau = self.cal.attack_tau_s if dbfs < self.floor_dbfs else self.cal.release_tau_s
        frac = 1.0 - math.exp(-max(0.0, dt) / tau)
        self.floor_dbfs += (dbfs - self.floor_dbfs) * frac
        return self.floor_dbfs

    @property
    def meter_config(self) -> SMeterConfig:
        """Escala calibrada para que el suelo detectado caiga en ``ambient_units``."""
        cal = self.cal
        noise_floor = self.floor_dbfs - cal.ambient_units * cal.db_per_unit
        s9 = noise_floor + _S_UNITS * cal.db_per_unit
        return SMeterConfig(noise_floor_dbfs=noise_floor, s9_dbfs=s9, db_per_s_unit=cal.db_per_unit)


__all__ = [
    "NoiseFloorTracker",
    "SMeterAutoCalibration",
    "SMeterBallistics",
    "SMeterConfig",
    "dbfs_to_angle_deg",
    "dbfs_to_meter_units",
    "format_s_label",
    "meter_units_to_angle_deg",
]
