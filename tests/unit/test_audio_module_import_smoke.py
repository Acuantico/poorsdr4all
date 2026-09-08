"""Smoke test: ``_vendor/audio.py`` importa de verdad y sus wrappers delegan bien.

Ningún test de ``audio_*_domain.py`` importa el propio ``audio.py`` (usan los
módulos de dominio directamente, o un doble en ``tests/services/test_audio.py``)
— así que nada detecta si una extracción rompe la cadena de imports/alias
``_domain_*`` del módulo real. Este test sí lo hace: instala un stub mínimo de
``pyaudio`` (no hay hardware de audio en este sandbox) y comprueba que
``import audio`` funciona y que unos cuantos wrappers tocados en el refactor
siguen llamando correctamente a su función de dominio. No abre streams, no
llama a ``p.open(...)``, no arranca ningún hilo.
"""

import sys
import types
import unittest


def _install_pyaudio_stub_if_needed() -> None:
    """Solo stubea si no hay ya un ``pyaudio`` real disponible."""
    if "pyaudio" in sys.modules:
        return
    try:
        import pyaudio  # noqa: F401 - si existe de verdad, se usa tal cual

        return
    except ModuleNotFoundError:
        pass

    stub = types.ModuleType("pyaudio")
    stub.paInt16 = 8

    class _PyAudio:
        def __init__(self) -> None:
            pass

        def terminate(self) -> None:
            pass

        def get_device_count(self) -> int:
            return 0

        def get_default_input_device_info(self):
            raise OSError("sin dispositivo de entrada (stub)")

        def get_default_output_device_info(self):
            raise OSError("sin dispositivo de salida (stub)")

    stub.PyAudio = _PyAudio
    sys.modules["pyaudio"] = stub


_install_pyaudio_stub_if_needed()

try:
    import audio  # el módulo real de _vendor/, no un doble

    _HAS_AUDIO = True
except Exception:
    _HAS_AUDIO = False


@unittest.skipUnless(_HAS_AUDIO, "audio.py no se pudo importar en este entorno")
class AudioModuleImportSmokeTest(unittest.TestCase):
    def test_pulse_text_wrappers_delegan_en_el_dominio(self):
        self.assertEqual(audio._normalize_linux_audio_name("ALSA_Output: Foo Bar"), "foo bar")
        self.assertEqual(audio._clean_pulse_text("(null)"), "")
        self.assertEqual(audio._describe_tx_app_entry(None), "App digital")

    def test_resolve_pulse_device_wrapper_no_hace_io_con_target_vacio(self):
        # Con configured_label vacío no debe intentar listar dispositivos
        # (ni fallar por no tener pactl real disponible en el sandbox).
        self.assertIsNone(audio._resolve_pulse_device("sinks", ""))

    def test_pcm_wrappers_delegan_en_el_dominio(self):
        self.assertEqual(audio._domain_pad_or_truncate_frame(b"\x01\x02", 4), b"\x01\x02\x00\x00")

    def test_sdr_chain_light_wrappers_no_fallan(self):
        silence = b"\x00\x00" * 4
        self.assertEqual(audio._sdr_chain_light_gui(silence, 1.0), silence)
        self.assertEqual(audio._sdr_chain_light_web(silence, 1.0), silence)

    def test_get_rx_meter_dbfs_no_lanza_sin_datos_previos(self):
        # Cubre indirectamente que el bloque muerto borrado de
        # get_rx_meter_dbfs no dejó la función rota.
        self.assertIsNone(audio.get_rx_meter_dbfs(window_s=0.0))


if __name__ == "__main__":
    unittest.main()
