import unittest

try:
    import numpy as np
    from audio_gain_domain import (
        aplicar_auto_gain,
        aplicar_factor_lineal,
        aplicar_gain_extra_rx,
        aplicar_gain_manual,
        atenuar_entrada_radio,
        reforzar_salida_pc,
    )
    _HAS_NUMPY = True
except ModuleNotFoundError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy no disponible en este entorno")
class AudioGainDomainTests(unittest.TestCase):
    def test_factor_uno_no_toca_los_datos(self):
        data = np.array([100, -200, 300], dtype=np.int16).tobytes()
        self.assertEqual(aplicar_factor_lineal(data, 1.0), data)

    def test_factor_escala_y_recorta(self):
        data = np.array([20000, -20000], dtype=np.int16).tobytes()
        out = np.frombuffer(aplicar_factor_lineal(data, 2.0), dtype=np.int16)
        # 40000/-40000 se recortan al rango de int16
        self.assertEqual(out.tolist(), [32767, -32768])

    def test_atenuar_gain_extra_reforzar_delegan_en_el_factor(self):
        data = np.array([1000, -1000], dtype=np.int16).tobytes()
        self.assertEqual(atenuar_entrada_radio(data, 0.5), aplicar_factor_lineal(data, 0.5))
        self.assertEqual(aplicar_gain_extra_rx(data, 1.5), aplicar_factor_lineal(data, 1.5))
        self.assertEqual(reforzar_salida_pc(data, 1.2), aplicar_factor_lineal(data, 1.2))

    def test_gain_manual_no_op_cerca_de_uno(self):
        data = np.array([500, -500], dtype=np.int16).tobytes()
        self.assertEqual(aplicar_gain_manual(data, 1.0004), data)

    def test_gain_manual_aplica_factor(self):
        data = np.array([1000, -1000], dtype=np.int16).tobytes()
        out = np.frombuffer(aplicar_gain_manual(data, 0.5), dtype=np.int16)
        self.assertEqual(out.tolist(), [500, -500])

    def test_auto_gain_sube_la_ganancia_con_senal_floja(self):
        state = {"gain": 1.0}
        # señal muy floja: el AGC debe intentar subir la ganancia hacia el objetivo
        quiet = np.full(480, 50, dtype=np.int16).tobytes()
        aplicar_auto_gain(
            quiet, state=state, target=6500.0, min_gain=0.6, max_gain=2.0,
            attack=0.08, release=0.15,
        )
        self.assertGreater(state["gain"], 1.0)

    def test_auto_gain_respeta_los_limites(self):
        state = {"gain": 1.0}
        silence = np.zeros(480, dtype=np.int16).tobytes()  # rms=0 -> pide max_gain
        for _ in range(200):  # deja converger
            aplicar_auto_gain(
                silence, state=state, target=6500.0, min_gain=0.6, max_gain=2.0,
                attack=0.08, release=0.15,
            )
        self.assertLessEqual(state["gain"], 2.0)

    def test_auto_gain_conserva_el_estado_entre_llamadas(self):
        state = {"gain": 1.0}
        data = np.full(480, 200, dtype=np.int16).tobytes()
        aplicar_auto_gain(data, state=state, target=6500.0, min_gain=0.6, max_gain=2.0,
                           attack=0.5, release=0.1)
        first = state["gain"]
        aplicar_auto_gain(data, state=state, target=6500.0, min_gain=0.6, max_gain=2.0,
                           attack=0.5, release=0.1)
        second = state["gain"]
        self.assertNotEqual(first, 1.0)
        self.assertNotEqual(second, first)  # sigue moviéndose hacia el objetivo

    def test_auto_gain_limita_picos_sin_tocar_el_estado(self):
        # Regresión: un AGC que solo mira el RMS medio no ve venir un pico
        # puntual muy por encima de la media -- lo escala a la ganancia que
        # pide el RMS bajo y lo recorta en seco contra el rango de int16.
        # La mayoría de la señal es floja (rms bajo, el AGC pide ganancia
        # alta) salvo unas pocas muestras que sin limitador se irían muy
        # por encima de la escala completa al aplicar esa ganancia.
        state = {"gain": 1.0}
        samples = np.full(480, 40, dtype=np.int16)
        samples[100] = 30000  # pico puntual muy por encima de la media
        data = samples.tobytes()
        out = np.frombuffer(
            aplicar_auto_gain(
                # attack=1.0: la ganancia salta directa al objetivo en esta
                # misma llamada, para poder razonar el resultado exacto.
                data, state=state, target=6500.0, min_gain=0.6, max_gain=2.0,
                attack=1.0, release=0.15,
            ),
            dtype=np.int16,
        )
        # Sin limitador, 30000 * 2.0 (new_gain) = 60000 se recortaría en
        # seco a 32767 -- una distorsión audible ("saturado"). Con el
        # limitador, la salida de este bloque se reduce lo justo para que
        # el pico quede en el techo, no por encima recortado.
        self.assertLessEqual(int(np.max(np.abs(out.astype(np.int32)))), 32767)
        self.assertGreater(int(np.max(np.abs(out.astype(np.int32)))), 32000)
        # La ganancia que guarda el propio AGC para el siguiente bloque es
        # la que pide el objetivo de RMS sin más -- el limitador no la toca.
        self.assertAlmostEqual(state["gain"], 2.0, places=4)

    def test_auto_gain_no_toca_audio_bien_comportado(self):
        # Señal ya dentro de rango con la ganancia que el AGC aplicaría: el
        # limitador de picos no debe activarse ni cambiar nada.
        state = {"gain": 1.0}
        samples = np.full(480, 3000, dtype=np.int16)
        data = samples.tobytes()
        without_limiter = (samples.astype(np.float32) * 1.0)
        np.clip(without_limiter, -32768, 32767, out=without_limiter)
        out = np.frombuffer(
            aplicar_auto_gain(
                data, state=state, target=6500.0, min_gain=0.6, max_gain=2.0,
                attack=0.0, release=0.0,  # sin movimiento: gain se queda en 1.0
            ),
            dtype=np.int16,
        )
        self.assertEqual(out.tolist(), without_limiter.astype(np.int16).tolist())

    def test_auto_gain_con_bloque_vacio_no_falla(self):
        state = {"gain": 1.0}
        out = aplicar_auto_gain(
            b"", state=state, target=6500.0, min_gain=0.6, max_gain=2.0,
            attack=0.08, release=0.15,
        )
        self.assertEqual(out, b"")
        self.assertEqual(state["gain"], 1.0)  # sin datos, no toca el estado


if __name__ == "__main__":
    unittest.main()
