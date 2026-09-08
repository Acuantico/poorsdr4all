import unittest

from filter_relays_wifi import BandRelayWifiController


class BandRelayWifiControllerTests(unittest.TestCase):
    def test_build_candidate_urls_base_host(self):
        ctrl = BandRelayWifiController(enabled=True, base_url="http://192.168.1.50")
        urls = ctrl._build_candidate_urls("group=40")
        self.assertIn("http://192.168.1.50/set?group=40", urls)
        self.assertEqual(1, len(urls))

    def test_build_candidate_urls_with_path(self):
        ctrl = BandRelayWifiController(enabled=True, base_url="http://192.168.1.50/set")
        urls = ctrl._build_candidate_urls("group=40")
        self.assertEqual("http://192.168.1.50/set?group=40", urls[0])

    def test_build_status_urls_base_host(self):
        ctrl = BandRelayWifiController(enabled=True, base_url="http://192.168.1.50")
        urls = ctrl._build_status_urls()
        self.assertEqual(["http://192.168.1.50/status"], urls)

    def test_send_group_accepts_when_set_times_out_but_status_matches(self):
        class _Fake(BandRelayWifiController):
            def __init__(self):
                super().__init__(enabled=True, base_url="http://dummy")
                self.MAX_SET_ROUNDS = 1
                self.STATUS_PROBES_PER_ROUND = 1
                self._status_calls = 0

            def _build_candidate_urls(self, query: str) -> list[str]:
                return ["http://dummy/set?" + query]

            def _build_status_urls(self) -> list[str]:
                return ["http://dummy/status"]

            def _request_url(self, url: str) -> bool:
                raise TimeoutError("timed out")

            def _request_status_group(self, url: str) -> str:
                self._status_calls += 1
                return "40"

        ctrl = _Fake()
        self.assertTrue(ctrl._send_group("40"))
        self.assertGreaterEqual(ctrl._status_calls, 1)

    def test_send_group_retries_until_status_matches(self):
        class _Fake(BandRelayWifiController):
            def __init__(self):
                super().__init__(enabled=True, base_url="http://dummy")
                self.MAX_SET_ROUNDS = 3
                self.STATUS_PROBES_PER_ROUND = 1
                self.STATUS_PROBE_DELAY_S = 0.0
                self._status = ["off", "off", "17_20"]
                self.set_calls = 0

            def _build_candidate_urls(self, query: str) -> list[str]:
                return ["http://dummy/set?" + query]

            def _build_status_urls(self) -> list[str]:
                return ["http://dummy/status"]

            def _request_url(self, url: str) -> bool:
                self.set_calls += 1
                return True

            def _request_status_group(self, url: str) -> str:
                if self._status:
                    return self._status.pop(0)
                return "17_20"

        ctrl = _Fake()
        self.assertTrue(ctrl._send_group("17_20"))
        self.assertGreaterEqual(ctrl.set_calls, 2)

    def test_apply_band_coalesces_same_group_without_force(self):
        calls = {"n": 0}

        class _Fake(BandRelayWifiController):
            def _send_group(self, group: str) -> bool:  # noqa: D401
                calls["n"] += 1
                return True

        ctrl = _Fake(
            enabled=True,
            base_url="http://192.168.1.50",
            band_groups={"40": ["40m"], "17_20": ["20m"]},
        )
        self.assertTrue(ctrl.apply_band("40m"))
        self.assertTrue(ctrl.apply_band("40m"))
        self.assertEqual(1, calls["n"])
        self.assertTrue(ctrl.apply_band("40m", force=True))
        self.assertEqual(2, calls["n"])


if __name__ == "__main__":
    unittest.main()
