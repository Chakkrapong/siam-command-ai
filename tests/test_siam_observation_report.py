from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src.siam_command.observation_report import build_observation_window_report


def _event(
    *,
    timestamp: str,
    route: str,
    route_family: str,
    promotion_state: str,
    governance_source: str,
    sampled: bool,
    served_runtime: str,
    route_event: str = "legacy_default",
    fallback: bool = False,
    fallback_reason: str = "not_applicable",
    legacy_latency_ms: float | None = None,
    v2_latency_ms: float | None = None,
    mismatches: tuple[str, ...] | None = None,
) -> dict[str, object]:
    comparison = None
    if mismatches is not None:
        comparison = {"shadow_event": "shadow_diff", "match": False, "mismatches": list(mismatches)}
    runtime_execution = {
        "attempted_runtime": "v2" if served_runtime == "v2" else "legacy",
        "served_runtime": served_runtime,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "validation_passed": None,
        "validation_reason": None,
    }
    if legacy_latency_ms is not None:
        runtime_execution["legacy_latency_ms"] = legacy_latency_ms
    if v2_latency_ms is not None:
        runtime_execution["v2_latency_ms"] = v2_latency_ms
    payload = {
        "timestamp": timestamp,
        "runtime_v2_route_event": route_event,
        "runtime_v2_route_meta": {
            "route_name": route,
            "command_name": route,
            "reason": "test",
            "runtime_decision": {
                "route_name": route,
                "selected_runtime": served_runtime,
                "primary_runtime": served_runtime,
                "reason": "test",
                "promotion_state": promotion_state,
                "route_family": route_family,
                "governance_source": governance_source,
                "rollout_percent": 5,
                "sampled": sampled,
            },
            "runtime_execution": runtime_execution,
            "runtime_guardrail": {
                "auto_disabled": False,
                "reason": "healthy",
                "sample_size": 100,
                "fallback_rate": 0.0,
                "validation_fail_rate": 0.0,
                "exception_rate": 0.0,
            },
            "execution_report": {
                "route": route,
                "primary_runtime": served_runtime,
                "routing_reason": "test",
                "shadow": {"run": False, "event": "shadow_skipped", "reason": "eligible", "match": None},
                "guard": {"blocked": False, "reason": None, "status": "healthy"},
                "governance": {
                    "promotion_state": promotion_state,
                    "route_family": route_family,
                    "state_source": governance_source,
                },
            },
        },
        "shadow_event": "shadow_skipped",
        "shadow_meta": {"shadow_event": "shadow_skipped", "reason": "eligible"},
    }
    if comparison is not None:
        payload["runtime_v2_route_meta"]["comparison"] = comparison
    return payload


class SiamObservationReportTests(unittest.TestCase):
    def _build_report(self, rows: list[dict[str, object]], *, instance_count: int = 1, window_open: str | None = None) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "execution-log.jsonl"
            log_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            with patch("src.siam_command.observation_report._dashboard_instance_count", return_value=instance_count):
                return build_observation_window_report(
                    window_open_timestamp=window_open or "2026-04-12T00:00:00+00:00",
                    log_path=str(log_path),
                )

    def test_block_when_review_drifts(self) -> None:
        row = _event(
            timestamp="2026-04-12T01:00:00+00:00",
            route="review",
            route_family="review",
            promotion_state="sampled_v2",
            governance_source="default_policy",
            sampled=True,
            served_runtime="legacy",
        )
        report = self._build_report([row], instance_count=1)
        self.assertEqual(report["decision"]["result"], "BLOCK")
        reasons = set(report["decision"]["reasons"])
        self.assertIn("review_drift_other_state", reasons)
        self.assertIn("review_drift_sampled_v2", reasons)
        self.assertIn("review_drift_default_policy", reasons)

    def test_hold_when_sample_insufficient(self) -> None:
        base = datetime(2026, 4, 12, 1, 0, tzinfo=timezone.utc)
        rows = []
        for idx in range(10):
            rows.append(
                _event(
                    timestamp=(base + timedelta(minutes=idx)).isoformat(),
                    route="admin",
                    route_family="admin",
                    promotion_state="sampled_v2",
                    governance_source="family_policy",
                    sampled=idx < 2,
                    served_runtime="legacy",
                )
            )
        report = self._build_report(rows, instance_count=1)
        self.assertEqual(report["decision"]["result"], "HOLD")
        reasons = set(report["decision"]["reasons"])
        self.assertIn("rollout_readiness_threshold_not_met", reasons)
        self.assertIn("latency_metrics_missing", reasons)

    def test_move_when_all_gates_pass(self) -> None:
        base = datetime(2026, 4, 12, 1, 0, tzinfo=timezone.utc)
        rows: list[dict[str, object]] = []
        for idx in range(40):
            rows.append(
                _event(
                    timestamp=(base + timedelta(minutes=idx)).isoformat(),
                    route="admin",
                    route_family="admin",
                    promotion_state="sampled_v2",
                    governance_source="family_policy",
                    sampled=idx < 10,
                    served_runtime="v2" if idx % 2 == 0 else "legacy",
                    legacy_latency_ms=100.0,
                    v2_latency_ms=105.0,
                )
            )
        for idx in range(5):
            rows.append(
                _event(
                    timestamp=(base + timedelta(minutes=100 + idx)).isoformat(),
                    route="review",
                    route_family="review",
                    promotion_state="shadow_only",
                    governance_source="conservative_default",
                    sampled=False,
                    served_runtime="legacy",
                    legacy_latency_ms=100.0,
                    v2_latency_ms=105.0,
                )
            )
        report = self._build_report(rows, instance_count=1)
        self.assertEqual(report["decision"]["result"], "MOVE")
        self.assertEqual(report["admin_readiness"]["thresholds"]["rollout_readiness"]["met"], True)
        self.assertEqual(report["gates"]["review_integrity_gate"]["pass"], True)
        self.assertEqual(report["gates"]["admin_quality_gate"]["pass"], True)
        self.assertEqual(report["gates"]["latency_gate"]["pass"], True)


if __name__ == "__main__":
    unittest.main()
