from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from src.siam_api.server import build_api_handler
from src.siam_command.automation.monitoring_api import (
    get_alerts_snapshot_response,
    get_readiness_snapshot_response,
)


class MonitoringApiTests(unittest.TestCase):
    def test_readiness_response_uses_injected_ports(self) -> None:
        class _ReadinessPort:
            def get_latest_snapshot(self, scope_type: str, scope_key: str):
                self.scope = (scope_type, scope_key)
                return {
                    "status": "ready",
                    "score": 0.98,
                    "window": 50,
                    "reason_codes": ["healthy_window"],
                    "reasons": ["healthy"],
                    "metrics": {
                        "total_entries_in_window": 50,
                        "error_rate": 0.0,
                        "shadow_error_rate": 0.0,
                        "runtime_exception_count": 0,
                        "signal_count": 0,
                    },
                }

        readiness = _ReadinessPort()
        ports = SimpleNamespace(readiness=readiness)
        payload = get_readiness_snapshot_response(".siam/does-not-matter.json", ports=ports)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(readiness.scope, ("global", "default"))

    def test_alerts_response_uses_injected_ports(self) -> None:
        class _AlertPort:
            def list_open_alerts(self, scope_type: str | None = None, scope_key: str | None = None):
                self.scope = (scope_type, scope_key)
                return [
                    {
                        "kind": "readiness_status",
                        "severity": "high",
                        "status": "not_ready",
                        "message": "degraded",
                        "reason_codes": ["runtime_exceptions_present"],
                        "score": 0.2,
                        "source": "port",
                        "timestamp": "2026-04-14T07:00:00Z",
                    }
                ]

        alerts = _AlertPort()
        ports = SimpleNamespace(alerts=alerts)
        payload = get_alerts_snapshot_response(".siam/does-not-matter.json", ports=ports)
        self.assertEqual(len(payload["alerts"]), 1)
        self.assertEqual(alerts.scope, ("global", "default"))

    def test_readiness_response_from_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "readiness_snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "warning",
                        "score": 0.82,
                        "window": 50,
                        "reason_codes": ["low_sample"],
                        "reasons": ["Low sample size"],
                        "metrics": {
                            "total_entries_in_window": 12,
                            "error_rate": 0.1667,
                            "shadow_error_rate": 0.0833,
                            "runtime_exception_count": 0,
                            "signal_count": 2,
                        },
                        "source": "readiness_tracker",
                        "updated_at": "2026-04-14T07:00:00Z",
                        "debug": {"private": True},
                    },
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )

            payload = get_readiness_snapshot_response(path)
            self.assertEqual(payload["status"], "warning")
            self.assertNotIn("debug", payload)
            self.assertEqual(
                set(payload.keys()),
                {"status", "score", "window", "reason_codes", "reasons", "metrics", "source", "updated_at"},
            )

    def test_alerts_response_from_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts_snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "alerts": [
                            {
                                "kind": "readiness_status",
                                "severity": "high",
                                "status": "not_ready",
                                "message": "Readiness status is not_ready",
                                "reason_codes": ["runtime_exceptions_present"],
                                "score": 0.2,
                                "source": "readiness_tracker",
                                "timestamp": "2026-04-14T07:00:00Z",
                                "traceback": "do-not-leak",
                            }
                        ],
                        "source": "snapshot_exporter",
                        "updated_at": "2026-04-14T07:00:00Z",
                    },
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )

            payload = get_alerts_snapshot_response(path)
            self.assertEqual(len(payload["alerts"]), 1)
            self.assertNotIn("traceback", payload["alerts"][0])
            self.assertEqual(
                set(payload["alerts"][0].keys()),
                {"kind", "severity", "status", "message", "reason_codes", "score", "source", "timestamp"},
            )

    def test_readiness_fallback_when_snapshot_missing(self) -> None:
        payload = get_readiness_snapshot_response(".siam/not-found-readiness-snapshot.json")
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["reason_codes"], ["no_data"])

    def test_alerts_fallback_when_snapshot_missing(self) -> None:
        payload = get_alerts_snapshot_response(".siam/not-found-alerts-snapshot.json")
        self.assertEqual(payload["alerts"], [])
        self.assertEqual(payload["source"], "monitoring_api")

    def test_malformed_readiness_is_coerced_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "readiness_snapshot.json"
            path.write_text('{"status":"unknown","metrics":{"error_rate":"bad"}}', encoding="utf-8")
            payload = get_readiness_snapshot_response(path)
            self.assertEqual(payload["status"], "not_ready")
            self.assertEqual(payload["metrics"]["error_rate"], 0.0)

    def test_malformed_alert_entries_are_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts_snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "alerts": [
                            {"kind": "readiness_status", "severity": "low", "status": "warning"},
                            {"kind": "other", "severity": "high", "status": "not_ready"},
                        ]
                    },
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )
            payload = get_alerts_snapshot_response(path)
            self.assertEqual(payload["alerts"], [])

    def test_monitoring_endpoints_do_not_require_log_path_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness_path = Path(tmp) / "readiness_snapshot.json"
            alerts_path = Path(tmp) / "alerts_snapshot.json"
            readiness_path.write_text(json.dumps({"status": "ready"}, ensure_ascii=True), encoding="utf-8")
            alerts_path.write_text(json.dumps({"alerts": []}, ensure_ascii=True), encoding="utf-8")

            def bad_log_path_provider() -> str:
                raise AssertionError("raw log path provider must not be used by monitoring endpoints")

            handler = build_api_handler(
                bad_log_path_provider,
                readiness_snapshot_path_provider=lambda: str(readiness_path),
                alerts_snapshot_path_provider=lambda: str(alerts_path),
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(f"{base}/api/monitoring/readiness") as response:
                    readiness_payload = json.loads(response.read().decode("utf-8"))
                with urlopen(f"{base}/api/monitoring/alerts") as response:
                    alerts_payload = json.loads(response.read().decode("utf-8"))
                with urlopen(f"{base}/api/monitoring") as response:
                    bundle_payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            self.assertEqual(readiness_payload["status"], "ready")
            self.assertEqual(alerts_payload["alerts"], [])
            self.assertIn("readiness", bundle_payload)
            self.assertIn("alerts", bundle_payload)


if __name__ == "__main__":
    unittest.main()
