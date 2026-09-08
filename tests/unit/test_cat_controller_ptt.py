"""PTT del ``CatController`` heredado (``_vendor/cat.py``): siempre por CAT
(``TX;``/``RX;``).

El mapa de modos/tramas puros vive en ``poorsdr.core.cat`` y se prueba en
``tests/core/test_cat.py``. PoorSDR4All soportó en su día un PTT alternativo
por línea serie (RTS) para variantes que no arman TX/RX por CAT; se retiró
por no formar parte de ningún perfil de radio soportado (todos los perfiles
documentados usan CAT) y para no dejar en Ajustes un campo ("Puerto PTT")
que solo tenía sentido para esa vía retirada.
"""

import unittest
from unittest.mock import patch

import cat


class FakeSerial:
    """Doble de ``serial.Serial`` que registra lo escrito."""

    def __init__(self, port=None, baudrate=9600, **kwargs):
        self.port = port
        self.baudrate = baudrate
        self.kwargs = kwargs
        self.is_open = True
        self.dtr = False
        self.rts = False
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass

    def read(self, size: int = 1) -> bytes:
        return b""

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    @property
    def in_waiting(self) -> int:
        return 0

    def close(self) -> None:
        self.is_open = False


class FakeSerialFactory:
    """``serial.Serial`` de pega: registra una instancia por puerto abierto."""

    def __init__(self):
        self.by_port: dict[str, FakeSerial] = {}

    def __call__(self, port=None, baudrate=9600, **kwargs):
        ser = FakeSerial(port=port, baudrate=baudrate, **kwargs)
        self.by_port[port] = ser
        return ser


class CatControllerPttTests(unittest.TestCase):
    def test_sends_tx_and_rx_over_the_cat_port(self):
        factory = FakeSerialFactory()
        with patch.object(cat.serial, "Serial", factory):
            ctrl = cat.CatController("/dev/ttyCAT0", baudrate=38400)
            ctrl.set_ptt(True)
            ctrl.set_ptt(False)
        ser = factory.by_port["/dev/ttyCAT0"]
        self.assertEqual(ser.written, [b"TX;", b"RX;"])


if __name__ == "__main__":
    unittest.main()
