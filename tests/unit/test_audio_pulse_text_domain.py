import unittest

from audio_pulse_text_domain import (
    best_pulse_description,
    clean_pulse_text,
    describe_tx_app_entry,
    filter_dict_entries,
    normalize_linux_audio_name,
    parse_pulse_device_entries,
    resolve_pulse_device_from_list,
    tx_entry_matches_hints,
)


class AudioPulseTextDomainTests(unittest.TestCase):
    def test_normalize_linux_audio_name_quita_prefijo_y_acentos(self):
        # El prefijo antes de ":" se descarta y los acentos se pierden (NFKD).
        self.assertEqual(
            normalize_linux_audio_name("alsa_output.pci-0000_00_1f.3.analog-stereo: Micrófono"),
            "microfono",
        )

    def test_normalize_linux_audio_name_colapsa_espacios(self):
        self.assertEqual(normalize_linux_audio_name("  Foo   Bar  "), "foo bar")

    def test_normalize_linux_audio_name_valor_vacio(self):
        self.assertEqual(normalize_linux_audio_name(None), "")

    def test_clean_pulse_text_filtra_null(self):
        self.assertEqual(clean_pulse_text("(null)"), "")
        self.assertEqual(clean_pulse_text("  "), "")
        self.assertEqual(clean_pulse_text("Altavoces"), "Altavoces")

    def test_best_pulse_description_fallback_en_cascada(self):
        entry = {"description": "(null)", "properties": {"device.description": "Tarjeta USB"}}
        self.assertEqual(best_pulse_description(entry), "Tarjeta USB")

    def test_best_pulse_description_usa_name_como_ultimo_recurso(self):
        entry = {"name": "alsa_output.usb-Foo"}
        self.assertEqual(best_pulse_description(entry), "alsa_output.usb-Foo")

    def test_best_pulse_description_sin_nada_valido(self):
        self.assertEqual(best_pulse_description({}), "")

    def test_parse_pulse_device_entries_sample_spec_dict(self):
        payload = [
            {
                "name": "sink1",
                "description": "Altavoces",
                "sample_spec": {"channels": 2, "rate": 44100},
            }
        ]
        entries = parse_pulse_device_entries(payload)
        self.assertEqual(
            entries,
            [{"name": "sink1", "description": "Altavoces", "channels": 2, "rate": 44100}],
        )

    def test_parse_pulse_device_entries_sample_spec_texto(self):
        payload = [{"name": "sink1", "sample_specification": "s16le 2ch 48000Hz"}]
        entries = parse_pulse_device_entries(payload)
        self.assertEqual(entries[0]["channels"], 2)
        self.assertEqual(entries[0]["rate"], 48000)

    def test_parse_pulse_device_entries_descarta_sin_nombre(self):
        payload = [{"description": "Sin nombre"}, {"name": ""}]
        self.assertEqual(parse_pulse_device_entries(payload), [])

    def test_parse_pulse_device_entries_payload_no_lista(self):
        self.assertEqual(parse_pulse_device_entries(None), [])
        self.assertEqual(parse_pulse_device_entries({"no": "es lista"}), [])

    def test_filter_dict_entries_lista_mixta(self):
        payload = [{"a": 1}, "no es dict", 3, {"b": 2}]
        self.assertEqual(filter_dict_entries(payload), [{"a": 1}, {"b": 2}])

    def test_filter_dict_entries_no_lista(self):
        self.assertEqual(filter_dict_entries(None), [])
        self.assertEqual(filter_dict_entries("texto"), [])

    def test_resolve_pulse_device_from_list_coincidencia_exacta(self):
        devices = [
            {"name": "alsa_output.pci-1", "description": "Altavoces integrados"},
            {"name": "alsa_output.usb-2", "description": "USB Audio"},
        ]
        self.assertEqual(
            resolve_pulse_device_from_list("USB Audio", devices), "alsa_output.usb-2"
        )

    def test_resolve_pulse_device_from_list_substring(self):
        devices = [{"name": "alsa_output.usb-2", "description": "USB Audio CODEC Stereo"}]
        self.assertEqual(
            resolve_pulse_device_from_list("usb audio codec", devices), "alsa_output.usb-2"
        )

    def test_resolve_pulse_device_from_list_scoring_por_tokens(self):
        devices = [
            {"name": "dev1", "description": "Realtek USB2.0 Audio Device Analog"},
            {"name": "dev2", "description": "Focusrite Scarlett Solo USB"},
        ]
        # Ni coincidencia exacta ni substring (el orden de las palabras no
        # calza), pero comparte 3 tokens con "dev1" -> gana por puntuación.
        self.assertEqual(
            resolve_pulse_device_from_list("usb2.0 realtek audio", devices), "dev1"
        )

    def test_resolve_pulse_device_from_list_sin_coincidencia(self):
        devices = [{"name": "dev1", "description": "Altavoces"}]
        self.assertIsNone(resolve_pulse_device_from_list("Dispositivo inexistente", devices))

    def test_resolve_pulse_device_from_list_target_vacio(self):
        self.assertIsNone(resolve_pulse_device_from_list("", [{"name": "x"}]))
        self.assertIsNone(resolve_pulse_device_from_list(None, [{"name": "x"}]))

    def test_tx_entry_matches_hints_encuentra_en_media_name(self):
        entry = {"properties": {"media.name": "WSJT-X Output"}}
        self.assertTrue(tx_entry_matches_hints(entry, ("wsjt-x",)))

    def test_tx_entry_matches_hints_sin_properties(self):
        self.assertFalse(tx_entry_matches_hints({}, ("wsjt-x",)))

    def test_tx_entry_matches_hints_sin_coincidencia(self):
        entry = {"properties": {"application.name": "Firefox"}}
        self.assertFalse(tx_entry_matches_hints(entry, ("wsjt-x", "fldigi")))

    def test_describe_tx_app_entry_combina_app_y_media(self):
        entry = {"properties": {"application.name": "WSJT-X", "media.name": "playback"}}
        self.assertEqual(describe_tx_app_entry(entry), "WSJT-X (playback)")

    def test_describe_tx_app_entry_evita_repetir_si_son_iguales(self):
        entry = {"properties": {"application.name": "WSJT-X", "media.name": "wsjt-x"}}
        self.assertEqual(describe_tx_app_entry(entry), "WSJT-X")

    def test_describe_tx_app_entry_sin_entry(self):
        self.assertEqual(describe_tx_app_entry(None), "App digital")

    def test_describe_tx_app_entry_sin_nombres(self):
        self.assertEqual(describe_tx_app_entry({"properties": {}}), "App digital")


if __name__ == "__main__":
    unittest.main()
