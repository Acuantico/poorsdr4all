"""PTT remoto seguro (``webserver.RemotePttControl``): latido, hombre muerto,
cola al soltar y pulsaciones cerradas."""
from __future__ import annotations

import asyncio
import threading
import unittest

import pytest

# Necesita los extras web (``pip install .[web]``): sin ellos la prueba se omite en vez de fallar.
pytest.importorskip("fastapi", reason="faltan los extras web")


def _audio_sin_tarjeta() -> None:
    """Esta prueba no toca audio real. Si PortAudio falta o no puede arrancar (p. ej. en el CI, sin tarjeta de
    sonido), se usa un ``PyAudio`` vacío para que ``webserver`` pueda importarse."""
    import sys
    import types

    try:
        import pyaudio

        pyaudio.PyAudio().terminate()
        return
    except ImportError:
        pyaudio = types.ModuleType("pyaudio")
        pyaudio.paInt16 = 8
        sys.modules["pyaudio"] = pyaudio
    except OSError:
        pass

    class _PyAudio:
        def terminate(self) -> None:
            pass

        def get_device_count(self) -> int:
            return 0

        def get_default_input_device_info(self):
            raise OSError("sin dispositivo de entrada")

        def get_default_output_device_info(self):
            raise OSError("sin dispositivo de salida")

        def get_host_api_info_by_index(self, indice):
            return {}

        def get_device_info_by_index(self, indice):
            return {}

    pyaudio.PyAudio = _PyAudio


_audio_sin_tarjeta()

import webserver  # noqa: E402


class _Callbacks:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def set_ptt(self, state: bool) -> None:
        self.calls.append(bool(state))


class _Controller:
    def __init__(self) -> None:
        self.callbacks = _Callbacks()
        self._remote_lock = threading.Lock()
        self._remote_clients = 0

    def _set_remote_mode(self, _enabled: bool) -> None:
        pass


def _run(coro):
    return asyncio.run(coro)


def _make(deadman_ms=300, tail_ms=100):
    ctl = _Controller()
    ptt = webserver.RemotePttControl(ctl, {"REMOTE_PTT_DEADMAN_MS": deadman_ms, "REMOTE_PTT_TAIL_MS": tail_ms})
    return ctl, ptt


class RemotePttTests(unittest.TestCase):
    def test_pulsar_y_soltar_con_cola(self):
        async def go():
            ctl, ptt = _make()
            await ptt.request(True, "a", 1)
            self.assertTrue(ptt.active)
            await ptt.request(False, "a", 1)
            self.assertTrue(ptt.active)  # aún sale la cola
            self.assertFalse(ptt.web_state({"ptt": True})["ptt"])  # la web ya ve RX
            await asyncio.sleep(0.2)
            self.assertFalse(ptt.active)
            self.assertEqual([True, False], ctl.callbacks.calls)
        _run(go())

    def test_el_latido_mantiene_y_su_falta_suelta(self):
        async def go():
            ctl, ptt = _make(deadman_ms=300)
            await ptt.request(True, "a", 1)
            for _ in range(8):  # 0,8 s de latidos
                await asyncio.sleep(0.1)
                await ptt.request(True, "a", 1)
            self.assertTrue(ptt.active)
            await asyncio.sleep(0.5)  # sin latido
            self.assertFalse(ptt.active)
            self.assertEqual([True, False], ctl.callbacks.calls)
        _run(go())

    def test_latido_tardio_no_vuelve_a_transmitir(self):
        async def go():
            ctl, ptt = _make(deadman_ms=300)
            await ptt.request(True, "a", 1)
            await asyncio.sleep(0.5)  # hombre muerto
            self.assertFalse(ptt.active)
            await ptt.request(True, "a", 1)  # vuelve la red: latido de la pulsación vieja
            self.assertFalse(ptt.active)
            await ptt.request(True, "a", 2)  # pulsación nueva
            self.assertTrue(ptt.active)
            ptt.release_now("fin")
            await asyncio.sleep(0.05)
        _run(go())

    def test_volver_a_pulsar_durante_la_cola_sigue_en_tx(self):
        async def go():
            ctl, ptt = _make(tail_ms=150)
            await ptt.request(True, "a", 1)
            await ptt.request(False, "a", 1)
            await asyncio.sleep(0.05)
            await ptt.request(True, "a", 2)
            await asyncio.sleep(0.25)
            self.assertTrue(ptt.active)
            self.assertEqual([True], ctl.callbacks.calls)  # sin cortes
            ptt.release_now("fin")
            await asyncio.sleep(0.05)
        _run(go())

    def test_perder_la_conexion_que_lleva_el_latido_suelta(self):
        async def go():
            ctl, ptt = _make()
            await ptt.request(True, "a", 1, link="rtc:1")
            ptt.release_now("conexion closed", link="rtc:2")  # otra conexión: no
            self.assertTrue(ptt.active)
            ptt.release_now("conexion closed", link="rtc:1")
            await asyncio.sleep(0.05)
            self.assertFalse(ptt.active)
        _run(go())


if __name__ == "__main__":
    unittest.main()
