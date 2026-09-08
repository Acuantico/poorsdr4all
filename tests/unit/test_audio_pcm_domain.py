import unittest

try:
    import numpy as np
    from audio_pcm_domain import (
        fade_in_pcm16,
        frame_from_chunks,
        pad_or_truncate_frame,
        parse_sample_spec,
        resample_linear,
        soft_repeat_block_pcm16,
        tx_frame_size_for_rate,
        verificar_datos,
    )
    _HAS_NUMPY = True
except ModuleNotFoundError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy no disponible en este entorno")
class AudioPcmDomainTests(unittest.TestCase):
    def test_parse_sample_spec_desde_dict(self):
        self.assertEqual(parse_sample_spec({"channels": 2, "rate": 48000}), (2, 48000))

    def test_parse_sample_spec_desde_texto_pulseaudio(self):
        self.assertEqual(parse_sample_spec("s16le 2ch 44100Hz"), (2, 44100))

    def test_parse_sample_spec_valor_no_reconocido(self):
        self.assertEqual(parse_sample_spec(None), (0, 0))
        self.assertEqual(parse_sample_spec("sin números"), (0, 0))

    def test_tx_frame_size_for_rate_veinte_ms(self):
        self.assertEqual(tx_frame_size_for_rate(48000), 960)
        self.assertEqual(tx_frame_size_for_rate(8000), 160)

    def test_tx_frame_size_for_rate_valor_invalido_usa_48k(self):
        self.assertEqual(tx_frame_size_for_rate(0), tx_frame_size_for_rate(48000))
        self.assertEqual(tx_frame_size_for_rate(None), tx_frame_size_for_rate(48000))
        self.assertEqual(tx_frame_size_for_rate("no numérico"), tx_frame_size_for_rate(48000))

    def test_fade_in_pcm16_arranca_en_silencio_y_sube(self):
        data = np.full(480, 10000, dtype=np.int16).tobytes()
        out = np.frombuffer(fade_in_pcm16(data, 1, 10, 48000), dtype=np.int16)
        self.assertEqual(out[0], 0)
        self.assertGreater(out[-1], out[0])

    def test_fade_in_pcm16_sin_datos_o_sin_duracion(self):
        self.assertEqual(fade_in_pcm16(b"", 1, 10), b"")
        data = np.full(10, 1000, dtype=np.int16).tobytes()
        self.assertEqual(fade_in_pcm16(data, 1, 0), data)

    def test_soft_repeat_block_pcm16_atenua(self):
        data = np.full(10, 10000, dtype=np.int16).tobytes()
        out = np.frombuffer(soft_repeat_block_pcm16(data, 0.5), dtype=np.int16)
        self.assertTrue((out == 5000).all())

    def test_soft_repeat_block_pcm16_decay_fuera_de_rango_usa_defecto(self):
        data = np.full(10, 10000, dtype=np.int16).tobytes()
        out_cero = np.frombuffer(soft_repeat_block_pcm16(data, 0.0), dtype=np.int16)
        out_defecto = np.frombuffer(soft_repeat_block_pcm16(data, 0.96), dtype=np.int16)
        self.assertTrue((out_cero == out_defecto).all())

    def test_verificar_datos_longitud_valida_no_levanta(self):
        data = np.zeros(6, dtype=np.int16).tobytes()  # 6 muestras / 2 canales = 3, exacto
        verificar_datos(data, 2)

    def test_verificar_datos_longitud_invalida_levanta(self):
        data = np.zeros(5, dtype=np.int16).tobytes()  # 5 muestras no divisibles entre 2
        with self.assertRaises(ValueError):
            verificar_datos(data, 2)

    # -- pad_or_truncate_frame (usado en RX Linux y RX/TX Windows/fallback) - #

    def test_pad_or_truncate_frame_longitud_exacta_no_toca(self):
        data = b"\x01\x02\x03\x04"
        self.assertEqual(pad_or_truncate_frame(data, 4), data)

    def test_pad_or_truncate_frame_corto_rellena_con_ceros(self):
        out = pad_or_truncate_frame(b"\x01\x02", 4)
        self.assertEqual(out, b"\x01\x02\x00\x00")

    def test_pad_or_truncate_frame_largo_recorta(self):
        out = pad_or_truncate_frame(b"\x01\x02\x03\x04\x05\x06", 4)
        self.assertEqual(out, b"\x01\x02\x03\x04")

    def test_pad_or_truncate_frame_expected_cero(self):
        self.assertEqual(pad_or_truncate_frame(b"\x01\x02", 0), b"")

    # -- resample_linear (usado por la inyección TX vía _pop_tx_inject) ----- #

    def test_resample_linear_mismas_tasas_no_op(self):
        data = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        out = resample_linear(data, 48000, 48000)
        self.assertIs(out, data)

    def test_resample_linear_tasa_invalida_no_op(self):
        data = np.array([1.0, 2.0], dtype=np.float32)
        out = resample_linear(data, 0, 48000)
        self.assertIs(out, data)

    def test_resample_linear_upsample_duplica_longitud(self):
        data = np.linspace(0.0, 1.0, 100, dtype=np.float32)
        out = resample_linear(data, 24000, 48000)
        self.assertEqual(len(out), 200)

    def test_resample_linear_downsample_reduce_longitud(self):
        data = np.linspace(0.0, 1.0, 200, dtype=np.float32)
        out = resample_linear(data, 48000, 24000)
        self.assertEqual(len(out), 100)

    # -- frame_from_chunks (idem) --------------------------------------- #

    def test_frame_from_chunks_lista_vacia(self):
        samples, leftover = frame_from_chunks([], 10)
        self.assertEqual(len(samples), 10)
        self.assertTrue((samples == 0).all())
        self.assertIsNone(leftover)

    def test_frame_from_chunks_exacto(self):
        chunk = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        samples, leftover = frame_from_chunks([chunk], 3)
        self.assertTrue((samples == chunk).all())
        self.assertIsNone(leftover)

    def test_frame_from_chunks_corto_rellena(self):
        chunk = np.array([1.0, 2.0], dtype=np.float32)
        samples, leftover = frame_from_chunks([chunk], 4)
        self.assertEqual(samples.tolist(), [1.0, 2.0, 0.0, 0.0])
        self.assertIsNone(leftover)

    def test_frame_from_chunks_largo_devuelve_remanente(self):
        chunk = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        samples, leftover = frame_from_chunks([chunk], 3)
        self.assertEqual(samples.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(leftover.tolist(), [4.0, 5.0])

    def test_frame_from_chunks_multiples_chunks_se_concatenan(self):
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.array([3.0, 4.0], dtype=np.float32)
        samples, leftover = frame_from_chunks([a, b], 4)
        self.assertEqual(samples.tolist(), [1.0, 2.0, 3.0, 4.0])
        self.assertIsNone(leftover)


if __name__ == "__main__":
    unittest.main()
