"""poorsdr.core.smeter: conversión dBFS -> unidades de aguja / grados."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.core.smeter import (  # noqa: E402
    NoiseFloorTracker,
    SMeterAutoCalibration,
    SMeterBallistics,
    SMeterConfig,
    dbfs_to_angle_deg,
    dbfs_to_meter_units,
    format_s_label,
    meter_units_to_angle_deg,
)


class SMeterConversionTests(unittest.TestCase):
    def test_at_or_below_noise_floor_is_zero(self):
        cfg = SMeterConfig()
        self.assertEqual(dbfs_to_meter_units(cfg.noise_floor_dbfs, cfg), 0.0)
        self.assertEqual(dbfs_to_meter_units(cfg.noise_floor_dbfs - 20, cfg), 0.0)

    def test_at_s9_reference_is_nine_units(self):
        cfg = SMeterConfig()
        self.assertAlmostEqual(dbfs_to_meter_units(cfg.s9_dbfs, cfg), 9.0)

    def test_midpoint_between_floor_and_s9_is_half_scale(self):
        cfg = SMeterConfig(noise_floor_dbfs=-100.0, s9_dbfs=-30.0, db_per_s_unit=70.0 / 9.0)
        mid = (-100.0 + -30.0) / 2.0
        self.assertAlmostEqual(dbfs_to_meter_units(mid, cfg), 4.5, places=3)

    def test_over_s9_adds_units_and_clamps_at_max(self):
        cfg = SMeterConfig()
        self.assertAlmostEqual(dbfs_to_meter_units(cfg.s9_dbfs + 10, cfg), 10.0)
        self.assertAlmostEqual(dbfs_to_meter_units(cfg.s9_dbfs + 30, cfg), 12.0)  # tope: S9+30
        self.assertAlmostEqual(dbfs_to_meter_units(cfg.s9_dbfs + 200, cfg), 12.0)  # se satura

    def test_angle_spans_min_to_max_over_full_scale(self):
        cfg = SMeterConfig()
        self.assertAlmostEqual(meter_units_to_angle_deg(0.0, cfg), cfg.angle_min_deg)
        self.assertAlmostEqual(meter_units_to_angle_deg(cfg.span_units, cfg), cfg.angle_max_deg)
        self.assertAlmostEqual(
            meter_units_to_angle_deg(cfg.span_units / 2, cfg),
            (cfg.angle_min_deg + cfg.angle_max_deg) / 2,
        )

    def test_dbfs_to_angle_deg_is_the_composition(self):
        cfg = SMeterConfig()
        units = dbfs_to_meter_units(-40.0, cfg)
        self.assertAlmostEqual(dbfs_to_angle_deg(-40.0, cfg), meter_units_to_angle_deg(units, cfg))

    def test_format_s_label_below_and_at_s9(self):
        self.assertEqual(format_s_label(0.0), "S0")
        self.assertEqual(format_s_label(5.4), "S5")
        self.assertEqual(format_s_label(9.0), "S9")

    def test_format_s_label_over_s9_rounds_to_ten_db(self):
        cfg = SMeterConfig()
        self.assertEqual(format_s_label(11.0, cfg), "S9+20")  # 2 unidades * 10 dB
        self.assertEqual(format_s_label(9.05, cfg), "S9")  # redondea a 0 dB extra

    def test_invalid_config_raises(self):
        with self.assertRaises(ValueError):
            SMeterConfig(s9_dbfs=-100.0, noise_floor_dbfs=-30.0)
        with self.assertRaises(ValueError):
            SMeterConfig(db_per_s_unit=0.0)


class SMeterBallisticsTests(unittest.TestCase):
    def test_starts_at_zero(self):
        meter = SMeterBallistics()
        self.assertEqual(meter.value, 0.0)

    def test_attack_moves_towards_target_but_not_instantly(self):
        meter = SMeterBallistics(attack_per_s=10.0, release_per_s=1.0)
        target = dbfs_to_meter_units(meter.cfg.s9_dbfs)  # 9.0
        value = meter.push_dbfs(meter.cfg.s9_dbfs, dt=0.1)
        self.assertGreater(value, 0.0)
        self.assertLess(value, target)

    def test_attack_reaches_target_with_enough_time(self):
        meter = SMeterBallistics(attack_per_s=1000.0)
        value = meter.push_dbfs(meter.cfg.s9_dbfs, dt=1.0)
        self.assertAlmostEqual(value, 9.0)

    def test_release_is_slower_than_attack_by_default(self):
        meter = SMeterBallistics()
        meter.push_dbfs(meter.cfg.s9_dbfs, dt=10.0)  # sube a fondo
        after_one_attack_step = meter.value
        meter.push_dbfs(meter.cfg.noise_floor_dbfs, dt=0.1)  # cae
        drop = after_one_attack_step - meter.value
        meter2 = SMeterBallistics()
        meter2.push_dbfs(meter2.cfg.s9_dbfs, dt=0.1)
        self.assertGreater(meter2.value, drop)  # subir 0.1s > lo que baja en 0.1s

    def test_never_overshoots_target(self):
        meter = SMeterBallistics(attack_per_s=1000.0)
        value = meter.push_dbfs(meter.cfg.s9_dbfs, dt=5.0)
        self.assertLessEqual(value, 9.0)

    def test_angle_and_label_properties_track_value(self):
        meter = SMeterBallistics(attack_per_s=1000.0)
        meter.push_dbfs(meter.cfg.s9_dbfs, dt=5.0)
        self.assertAlmostEqual(meter.angle_deg, meter_units_to_angle_deg(meter.value, meter.cfg))
        self.assertEqual(meter.label, format_s_label(meter.value, meter.cfg))

    def test_reset_returns_to_zero(self):
        meter = SMeterBallistics(attack_per_s=1000.0)
        meter.push_dbfs(meter.cfg.s9_dbfs, dt=5.0)
        meter.reset()
        self.assertEqual(meter.value, 0.0)

    def test_negative_dt_does_not_move_needle(self):
        meter = SMeterBallistics()
        meter.push_dbfs(meter.cfg.s9_dbfs, dt=-1.0)
        self.assertEqual(meter.value, 0.0)


class NoiseFloorTrackerTests(unittest.TestCase):
    def test_first_reading_sets_the_floor_immediately(self):
        tracker = NoiseFloorTracker()
        tracker.push(-55.0, dt=0.15)
        self.assertEqual(tracker.floor_dbfs, -55.0)

    def test_ambient_qrm_reads_mid_scale_not_s0(self):
        # Caso real reportado: una radio de verdad marca ~S5 de QRM de banda
        # sin señal. Tras converger, esa misma lectura constante debe caer
        # cerca de S5 en nuestra escala, no en S0.
        cal = SMeterAutoCalibration(ambient_units=5.0, db_per_unit=6.0)
        tracker = NoiseFloorTracker(cal)
        qrm_dbfs = -55.0
        for _ in range(200):  # converge de sobra con el ataque rápido
            tracker.push(qrm_dbfs, dt=0.15)
        units = dbfs_to_meter_units(qrm_dbfs, tracker.meter_config)
        self.assertAlmostEqual(units, 5.0, places=1)

    def test_tracks_down_fast_when_band_gets_quieter(self):
        tracker = NoiseFloorTracker(initial_dbfs=-40.0)
        for _ in range(50):  # ataque: baja deprisa hacia lecturas más flojas
            tracker.push(-70.0, dt=0.5)
        self.assertLess(tracker.floor_dbfs, -65.0)

    def test_does_not_chase_a_strong_transient_signal(self):
        cal = SMeterAutoCalibration()
        tracker = NoiseFloorTracker(cal, initial_dbfs=-60.0)
        tracker.push(-60.0, dt=0.01)  # siembra el suelo
        # una señal fuerte de unos segundos no debe arrastrar el suelo arriba
        for _ in range(50):
            tracker.push(-10.0, dt=0.15)  # ~7.5 s de señal fuerte
        self.assertLess(tracker.floor_dbfs, -55.0)

    def test_eventually_adapts_up_to_a_sustained_louder_band(self):
        cal = SMeterAutoCalibration(release_tau_s=1.0)  # rápido para el test
        tracker = NoiseFloorTracker(cal, initial_dbfs=-80.0)
        for _ in range(200):
            tracker.push(-40.0, dt=0.2)  # ~40 s, muchas constantes de tiempo
        self.assertGreater(tracker.floor_dbfs, -50.0)

    def test_meter_config_places_floor_at_ambient_units(self):
        cal = SMeterAutoCalibration(ambient_units=4.0, db_per_unit=5.0)
        tracker = NoiseFloorTracker(cal, initial_dbfs=-72.0)
        tracker.push(-72.0, dt=0.15)
        cfg = tracker.meter_config
        self.assertAlmostEqual(dbfs_to_meter_units(-72.0, cfg), 4.0)
        self.assertAlmostEqual(cfg.s9_dbfs, -72.0 + (9.0 - 4.0) * 5.0)

    def test_reset_forgets_the_tracked_floor(self):
        tracker = NoiseFloorTracker(initial_dbfs=-60.0)
        tracker.push(-20.0, dt=5.0)
        tracker.reset(-90.0)
        self.assertEqual(tracker.floor_dbfs, -90.0)
        tracker.push(-10.0, dt=0.01)  # tras reset, la próxima lectura fija el suelo
        self.assertEqual(tracker.floor_dbfs, -10.0)

    def test_invalid_calibration_raises(self):
        with self.assertRaises(ValueError):
            SMeterAutoCalibration(db_per_unit=0.0)
        with self.assertRaises(ValueError):
            SMeterAutoCalibration(attack_tau_s=0.0)
        with self.assertRaises(ValueError):
            SMeterAutoCalibration(release_tau_s=-1.0)

    def test_ambient_units_out_of_range_raises(self):
        # Cada estación tiene su propio QRM de fondo (no todas marcan S5), así
        # que ambient_units es configurable por el usuario — pero sigue
        # teniendo que caer dentro de la propia escala S0-S9.
        with self.assertRaises(ValueError):
            SMeterAutoCalibration(ambient_units=-1.0)
        with self.assertRaises(ValueError):
            SMeterAutoCalibration(ambient_units=9.1)

    def test_ambient_units_configurable_per_station_qrm(self):
        # Una estación con QRM más flojo (S3) o más fuerte (S7) que el
        # supuesto por defecto (S5) debe poder calibrarse a su propio suelo,
        # no a un valor fijo pensado para una sola situación de desarrollo.
        for ambient in (0.0, 3.0, 7.0, 9.0):
            cal = SMeterAutoCalibration(ambient_units=ambient, db_per_unit=6.0)
            tracker = NoiseFloorTracker(cal)
            qrm_dbfs = -55.0
            for _ in range(200):
                tracker.push(qrm_dbfs, dt=0.15)
            units = dbfs_to_meter_units(qrm_dbfs, tracker.meter_config)
            self.assertAlmostEqual(units, ambient, places=1)


if __name__ == "__main__":
    unittest.main()
