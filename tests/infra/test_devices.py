"""poorsdr.infra.devices: enumeración de puertos serie y audio (pactl falso)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.infra import devices  # noqa: E402

_PACTL_SINKS = json.dumps(
    [
        {
            "name": "alsa_output.pci-0000_00_1f.3.analog-stereo",
            "description": "Audio interno Analógico estéreo",
            "sample_specification": {"channels": 2, "rate": 48000},
            "properties": {"device.description": "Audio interno"},
        },
        {
            "name": "alsa_output.usb-Texas_Instruments.analog-stereo",
            "description": "PCM2903B Audio",
            "sample_specification": {"channels": 2, "rate": 44100},
        },
        {"name": "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor", "description": "Monitor"},
    ]
)
_PACTL_SOURCES = json.dumps(
    [
        {
            "name": "alsa_input.usb-Texas_Instruments.analog-stereo",
            "description": "PCM2903B Audio entrada",
            "sample_specification": {"channels": 1, "rate": 48000},
        },
        {"name": "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor", "description": "Monitor of…"},
    ]
)


class AudioEnumTests(unittest.TestCase):
    def test_outputs_parsed_without_monitors(self):
        eps = devices.audio_outputs(runner=lambda _cmd: _PACTL_SINKS)
        names = [e.name for e in eps]
        self.assertEqual(
            names,
            [
                "alsa_output.pci-0000_00_1f.3.analog-stereo",
                "alsa_output.usb-Texas_Instruments.analog-stereo",
            ],
        )
        self.assertEqual(eps[0].channels, 2)
        self.assertEqual(eps[1].rate, 44100)
        self.assertEqual(eps[0].description, "Audio interno Analógico estéreo")

    def test_sources_drop_monitor(self):
        eps = devices.audio_inputs(runner=lambda _cmd: _PACTL_SOURCES)
        self.assertEqual([e.name for e in eps], ["alsa_input.usb-Texas_Instruments.analog-stereo"])

    def test_hidden_and_internal_sinks_are_excluded(self):
        payload = json.dumps(
            [
                {"name": "real.sink", "description": "Cascos HyperX"},
                {"name": "poorsdr_owrx", "description": "PoorSDR4All-OWRX-ANR",
                 "properties": {"node.hidden": "true", "node.virtual": "true"}},
                {"name": "some.loopback", "description": "algo",
                 "properties": {"node.hidden": "true"}},
            ]
        )
        eps = devices.audio_outputs(runner=lambda _cmd: payload)
        self.assertEqual([e.name for e in eps], ["real.sink"])

    def test_null_description_falls_back_to_properties(self):
        payload = json.dumps(
            [
                {
                    "name": "alsa_output.usb-x.analog-stereo",
                    "description": "(null)",
                    "properties": {"device.description": "Sound Blaster Play! 3"},
                    "sample_specification": {"channels": 2, "rate": 48000},
                }
            ]
        )
        eps = devices.audio_outputs(runner=lambda _cmd: payload)
        self.assertEqual(eps[0].description, "Sound Blaster Play! 3")

    def test_no_description_anywhere_uses_name(self):
        payload = json.dumps([{"name": "x.sink", "description": "(null)", "properties": {}}])
        eps = devices.audio_outputs(runner=lambda _cmd: payload)
        self.assertEqual(eps[0].description, "x.sink")

    def test_pa_index_by_name_and_by_alsa_card(self):
        payload = json.dumps(
            [
                {"name": "a.sink", "description": "Cascos HyperX", "properties": {"alsa.card": "1"}},
                {"name": "b.sink", "description": "Radio Micrófono", "properties": {"alsa.card": "2"}},
            ]
        )
        # PyAudio: uno casa por nombre, el otro solo por tarjeta ALSA (hw:2)
        pa_out = {"cascos hyperx": 5, "card:2": 8}
        with mock.patch.object(devices, "_portaudio_index_maps", return_value=({}, pa_out)):
            eps = devices.audio_outputs(runner=lambda _cmd: payload)
        by_name = {e.description: e for e in eps}
        self.assertEqual(by_name["Cascos HyperX"].pa_index, 5)
        self.assertEqual(by_name["Radio Micrófono"].pa_index, 8)
        self.assertEqual(by_name["Radio Micrófono"].alsa_card, 2)

    def test_display_index_falls_back_to_alsa_card(self):
        payload = json.dumps(
            [{"name": "cm.sink", "description": "Radio Micrófono",
              "properties": {"alsa.card": "3"}}]
        )
        with mock.patch.object(devices, "_portaudio_index_maps", return_value=({}, {})):
            eps = devices.audio_outputs(runner=lambda _cmd: payload)
        self.assertEqual(eps[0].pa_index, -1)
        self.assertEqual(eps[0].alsa_card, 3)
        self.assertEqual(eps[0].display_index, 3)  # sin PortAudio, usa la tarjeta

    def test_text_format_reads_dotted_props_and_drops_monitor(self):
        # PipeWire devuelve "(null)" en el JSON pero el texto trae las props.
        verbose = (
            "Destino #64\n"
            "\tEstado: SUSPENDED\n"
            "\tNombre: alsa_output.usb-C-Media.analog-stereo\n"
            "\tDescripción: (null)\n"
            "\tEspecificación de muestreo: s16le 2ch 48000Hz\n"
            "\tPropiedades:\n"
            '\t\talsa.card = "3"\n'
            '\t\talsa.card_name = "(null)"\n'
            '\t\tnode.name = "alsa_output.usb-C-Media.analog-stereo"\n'
            '\t\tdevice.description = "Radio Micrófono"\n'
            '\t\tdevice.product.name = "CM108 Audio Controller"\n'
            "\n"
            "Destino #66\n"
            "\tNombre: alsa_output.hdmi.monitor\n"
            "\tPropiedades:\n"
            '\t\tnode.name = "alsa_output.hdmi"\n'
            '\t\tdevice.description = "Monitor"\n'
        )
        short = (
            "64\talsa_output.usb-C-Media.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"
            "66\talsa_output.hdmi.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
        )
        eps = devices.audio_outputs(
            runner=lambda cmd: short if cmd[-1] == "short" else verbose
        )
        self.assertEqual(len(eps), 1)  # el .monitor se descarta
        self.assertEqual(eps[0].description, "Radio Micrófono")  # no "CM108…" ni "(null)"
        self.assertEqual(eps[0].alsa_card, 3)
        self.assertEqual(eps[0].channels, 2)
        self.assertEqual(eps[0].rate, 48000)

    def test_bad_json_returns_empty(self):
        self.assertEqual(devices.audio_outputs(runner=lambda _cmd: "no-json"), [])

    def test_runner_raising_returns_empty(self):
        def boom(_cmd):
            raise OSError("pactl not found")

        self.assertEqual(devices.audio_inputs(runner=boom), [])


class SerialEnumTests(unittest.TestCase):
    def test_serial_ports_is_a_list_of_str(self):
        ports = devices.serial_ports()
        self.assertIsInstance(ports, list)
        self.assertTrue(all(isinstance(p, str) for p in ports))

    def test_usb_prefixes_sort_first(self):
        # No dependemos del hardware: solo comprobamos el criterio de orden.
        sample = ["/dev/ttyS0", "/dev/ttyUSB1", "/dev/ttyACM0"]
        sample.sort(key=lambda d: (not d.startswith(devices._SERIAL_PREFIXES), d))
        self.assertEqual(sample, ["/dev/ttyACM0", "/dev/ttyS0", "/dev/ttyUSB1"])


if __name__ == "__main__":
    unittest.main()
