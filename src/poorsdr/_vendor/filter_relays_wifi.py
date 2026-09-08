from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional


def _to_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


class BandRelayWifiController:
    DEFAULT_BAND_GROUPS = {
        "10_15": ["10m", "11m", "12m", "13m", "14m", "15m"],
        "17_20": ["17m", "18m", "19m", "20m"],
        "40": ["40m"],
        "80": ["80m"],
    }
    MAX_SET_ROUNDS = 4
    STATUS_PROBES_PER_ROUND = 2
    STATUS_PROBE_DELAY_S = 0.12

    def __init__(
        self,
        enabled: bool,
        base_url: str,
        *,
        api_key: str = "",
        timeout_s: float = 2.0,
        band_groups: Optional[dict] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout_s = max(0.3, float(timeout_s))
        self.log_fn = log_fn
        self._lock = threading.Lock()
        self._last_group = ""
        self._band_to_group = self._build_band_index(band_groups)

    @classmethod
    def from_config(
        cls,
        config: dict,
        *,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> "BandRelayWifiController":
        cfg = dict(config or {})
        enabled = _to_bool(cfg.get("FILTER_RELAY_WIFI_ENABLED", False))
        base_url = str(cfg.get("FILTER_RELAY_WIFI_URL", "") or "").strip()
        api_key = str(cfg.get("FILTER_RELAY_WIFI_API_KEY", "") or "").strip()
        try:
            timeout_s = float(cfg.get("FILTER_RELAY_WIFI_TIMEOUT_MS", 2000) or 2000) / 1000.0
        except Exception:
            timeout_s = 2.0
        timeout_s = max(1.8, timeout_s)
        band_groups = cfg.get("FILTER_RELAY_BAND_GROUPS")
        if not isinstance(band_groups, dict):
            band_groups = None
        return cls(
            enabled=enabled,
            base_url=base_url,
            api_key=api_key,
            timeout_s=timeout_s,
            band_groups=band_groups,
            log_fn=log_fn,
        )

    def _log(self, message: str) -> None:
        if callable(self.log_fn):
            try:
                self.log_fn(message)
            except Exception:
                return

    def _build_band_index(self, band_groups: Optional[dict]) -> dict[str, str]:
        source = self.DEFAULT_BAND_GROUPS
        if isinstance(band_groups, dict) and band_groups:
            source = band_groups
        mapping: dict[str, str] = {}
        for group_name, bands in source.items():
            group = str(group_name or "").strip().lower()
            if not group:
                continue
            if not isinstance(bands, (list, tuple, set)):
                continue
            for band in bands:
                label = str(band or "").strip().lower()
                if label:
                    mapping[label] = group
        return mapping

    def _group_for_band(self, band: str) -> str:
        return self._band_to_group.get(str(band or "").strip().lower(), "off")

    def apply_band(self, band: str, *, force: bool = False, source: str = "") -> bool:
        if not self.enabled:
            return False
        if not self.base_url:
            self._log("filter_relays wifi_skip reason=empty_url")
            return False
        group = self._group_for_band(band)
        with self._lock:
            if not force and group == self._last_group:
                return True
        ok = self._send_group(group)
        if ok:
            with self._lock:
                self._last_group = group
        src = str(source or "").strip().lower() or "unknown"
        self._log(
            "filter_relays apply src=%s band=%s group=%s ok=%s"
            % (src, str(band), str(group), int(bool(ok)))
        )
        return ok

    def _send_group(self, group: str) -> bool:
        params = {"group": str(group or "off")}
        if self.api_key:
            params["key"] = self.api_key
        query = urllib.parse.urlencode(params)
        candidates = self._build_candidate_urls(query)
        status_urls = self._build_status_urls()
        if not candidates:
            return False
        for round_idx in range(1, self.MAX_SET_ROUNDS + 1):
            for idx, url in enumerate(candidates, start=1):
                try:
                    self._request_url(url)
                except Exception as exc:
                    self._log(
                        "filter_relays wifi_error group=%s round=%s try=%s/%s url=%s err=%r"
                        % (str(group), int(round_idx), int(idx), int(len(candidates)), str(url), exc)
                    )
                # Even with timeout while reading, the ESP may have applied the relay.
                if self._confirm_group(group, status_urls=status_urls):
                    return True
            # Small incremental backoff helps ESP32/WiFi recover from transient stalls.
            if round_idx < self.MAX_SET_ROUNDS:
                time.sleep(0.10 * float(round_idx))
        return False

    def _build_candidate_urls(self, query: str) -> list[str]:
        raw = str(self.base_url or "").strip().rstrip("/")
        if not raw:
            return []
        parsed = urllib.parse.urlsplit(raw)
        root = raw
        if parsed.scheme and parsed.netloc:
            root = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
        urls: list[str] = []
        if parsed.path and parsed.path not in ("", "/"):
            sep = "&" if parsed.query else "?"
            urls.append(f"{raw}{sep}{query}")
        else:
            urls.append(f"{raw}/set?{query}")
        # Primary endpoint used by ESP relay firmware.
        urls.append(f"{root}/set?{query}")
        seen = set()
        deduped: list[str] = []
        for item in urls:
            key = str(item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    def _build_status_urls(self) -> list[str]:
        raw = str(self.base_url or "").strip().rstrip("/")
        if not raw:
            return []
        parsed = urllib.parse.urlsplit(raw)
        root = raw
        if parsed.scheme and parsed.netloc:
            root = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
        urls = [f"{root}/status"]
        if parsed.path and parsed.path not in ("", "/"):
            path = parsed.path.rstrip("/")
            if path.endswith("/set"):
                maybe = path[: -len("/set")] or "/"
                urls.append(urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, f"{maybe.rstrip('/')}/status", "", "")))
            elif path.endswith("set"):
                urls.append(f"{raw}/status")
        seen = set()
        deduped: list[str] = []
        for item in urls:
            key = str(item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    def _confirm_group(self, group: str, *, status_urls: list[str]) -> bool:
        expected = str(group or "off").strip().lower()
        if not expected:
            expected = "off"
        for _probe in range(self.STATUS_PROBES_PER_ROUND):
            for url in status_urls:
                try:
                    current = self._request_status_group(url)
                except Exception as exc:
                    self._log("filter_relays status_error url=%s err=%r" % (str(url), exc))
                    continue
                if current == expected:
                    return True
            time.sleep(self.STATUS_PROBE_DELAY_S)
        return False

    def _request_url(self, url: str) -> bool:
        request = urllib.request.Request(url=url, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = response.read().decode("utf-8", errors="ignore")
            status_ok = int(response.status) < 400
            if not payload:
                return bool(status_ok)
            try:
                body = json.loads(payload)
                # Assume success when endpoint is 2xx and body does not expose "ok".
                if "ok" not in body:
                    return bool(status_ok)
                return bool(body.get("ok"))
            except Exception:
                return bool(status_ok)

    def _request_status_group(self, url: str) -> str:
        request = urllib.request.Request(url=url, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = response.read().decode("utf-8", errors="ignore")
            body = json.loads(payload or "{}")
        group = str(body.get("group", "")).strip().lower()
        if not group:
            return ""
        return group
