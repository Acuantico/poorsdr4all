"""VPN integrada (``_vendor/vpn.py``): claves, dispositivos y configuración del móvil."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

import vpn


class VpnStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("POORSDR_RUNTIME_DIR")
        os.environ["POORSDR_RUNTIME_DIR"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("POORSDR_RUNTIME_DIR", None)
        else:
            os.environ["POORSDR_RUNTIME_DIR"] = self._old
        self._tmp.cleanup()

    def test_dispositivos_reciben_ips_consecutivas_y_se_quitan(self):
        a = vpn.add_device("Móvil")
        b = vpn.add_device("Tablet")
        self.assertEqual(("10.9.0.2", "10.9.0.3"), (a["ip"], b["ip"]))
        vpn.remove_device(a["public_key"])
        self.assertEqual(["Tablet"], [p["name"] for p in vpn.load()["peers"]])
        # el hueco libre se reutiliza
        self.assertEqual("10.9.0.2", vpn.add_device("Otro")["ip"])

    def test_el_almacen_solo_lo_lee_el_usuario(self):
        vpn.add_device("Móvil")
        mode = stat.S_IMODE(Path(self._tmp.name, "vpn.json").stat().st_mode)
        self.assertEqual(0o600, mode)

    def test_claves_del_servidor_coherentes(self):
        data = vpn.ensure_server_keys(vpn.load())
        self.assertEqual(data["server_public_key"], vpn.public_key_of(data["server_private_key"]))

    def test_configuracion_del_movil(self):
        peer = vpn.add_device("Móvil")
        text = vpn.client_config(peer, "1.2.3.4", 51821)
        self.assertIn(f"PrivateKey = {peer['private_key']}", text)
        self.assertIn("Address = 10.9.0.2/32", text)
        self.assertIn("Endpoint = 1.2.3.4:51821", text)
        self.assertIn("AllowedIPs = 10.9.0.1/32", text)
        self.assertIn(f"PublicKey = {vpn.load()['server_public_key']}", text)

    def test_endpoint_con_puerto_ipv6_y_nombre(self):
        peer = vpn.add_device("Móvil")
        self.assertIn("Endpoint = casa.example.org:4000", vpn.client_config(peer, "casa.example.org:4000", 51821))
        self.assertIn("Endpoint = [2001:db8::1]:51821", vpn.client_config(peer, "2001:db8::1", 51821))

    def test_endpoint_manual_manda_sobre_el_detectado(self):
        data = vpn.load()
        data["detected_endpoint"] = "5.6.7.8"
        vpn.save(data)
        self.assertEqual("5.6.7.8", vpn.endpoint_for(""))
        self.assertEqual("casa.example.org", vpn.endpoint_for("casa.example.org"))


class VpnMiscTests(unittest.TestCase):
    def test_cgnat_y_privadas(self):
        self.assertTrue(vpn.is_shared_or_private("100.64.1.2"))
        self.assertTrue(vpn.is_shared_or_private("192.168.1.10"))
        self.assertFalse(vpn.is_shared_or_private("8.8.8.8"))

    def test_red_y_puertos_distintos_de_ircb(self):
        self.assertEqual("10.9.0.1", vpn.SERVER_IP)
        self.assertNotEqual(51820, vpn.DEFAULT_UDP_PORT)
        self.assertFalse(set(vpn.AUDIO_PORTS) & set(range(51830, 51840)))

    def test_el_ayudante_de_esta_plataforma_existe(self):
        self.assertTrue(Path(vpn.binary_path()).is_file(), vpn.binary_path())


if __name__ == "__main__":
    unittest.main()
