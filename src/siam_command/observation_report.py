from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..siam_core.runtime_phase4 import (
    compute_routing_decision,
    dashboard_instance_validation,
    phase4_runtime_config,
)
from ..siam_core.runtime_risk import RuntimeRiskAssessment
from ..siam_core.runtime_guardrail import GuardrailStatus

PROMOTION_STATES = {"legacy_only", "shadow_only", "sampled_v2", "partial_v2", "full_v2"}
ALLOWED_REVIEW_GOVERNANCE_SOURCES = {"route_override", "conservative_default"}
KNOWN_ERROR_KINDS = {
    "missing_command",
    "contract_validation",
    "permission",
    "timeout",
    "input_contract",
    "runtime_exception",
    "other",
    "none",
}
UNKNOWN_ERROR_KINDS = {"", "unknown", "other", "none"}
UNKNOWN_FALLBACK_REASONS = {"", "unknown", "unknown_reason", "none", "not_reported"}


@dataclass(frozen=True)
class _Threshold:
    name: str
    admin_total_requests: int
    admin_sampled_v2_requests: int


TREND_ONLY_THRESHOLD = _Threshold("trend_only", 20, 5)
ROLLOUT_READINESS_THRESHOLD = _Threshold("rollout_readiness", 40, 10)
PREFERRED_CONFIDENCE_THRESHOLD = _Threshold("preferred_confidence", 100, 20)


def _parse_iso8601(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _dashboard_instance_count() -> int:
    cmd_exact = "(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'src\\\\.siam_dashboard\\\\.main' }).Count"
    exact = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd_exact],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        count = int((exact.stdout or "0").strip() or 0)
    except ValueError:
        count = 0
    if count > 0:
        return count

    # Fallback path for restricted environments where Win32_Process commandline
    # enumeration is blocked: infer dashboard instance from the default listener port.
    fallback_script = r"""
$lines = netstat -ano | Select-String ':8765' | Where-Object { $_.ToString() -match 'LISTENING' }
$pids = @()
foreach ($line in $lines) {
  $parts = ($line.ToString() -replace '\s+', ' ').Trim().Split(' ')
  if ($parts.Length -ge 5) {
    $pids += $parts[-1]
  }
}
$count = 0
foreach ($pidRaw in ($pids | Select-Object -Unique)) {
  $procId = 0
  if ([int]::TryParse($pidRaw, [ref]$procId)) {
    try {
      $p = Get-Process -Id $procId -ErrorAction Stop
      if ($p.ProcessName -ieq 'python') {
        $count += 1
      }
    } catch {}
  }
}
Write-Output $count
"""
    fallback = subprocess.run(
        ["powershell", "-NoProfile", "-Command", fallback_script],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return int((fallback.stdout or "0").strip() or 0)
    except ValueError:
        return 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _is_schema_qualified(record: dict[str, Any]) -> bool:
    route_meta = record.get("runtime_v2_route_meta")
    if not isinstance(route_meta, dict):
        return False
    runtime_decision = route_meta.get("runtime_decision")
    runtime_execution = route_meta.get("runtime_execution")
    execution_report = route_meta.get("execution_report")
    if not isinstance(runtime_decision, dict):
        return False
    if not isinstance(runtime_execution, dict):
        return False
    if not isinstance(execution_report, dict):
        return False
    governance = execution_report.get("governance")
    if not isinstance(governance, dict):
        return False
    required_decision_keys = {"promotion_state", "governance_source", "route_family", "rollout_percent", "sampled"}
    required_execution_keys = {"served_runtime", "fallback", "fallback_reason"}
    required_governance_keys = {"promotion_state", "route_family", "state_source"}
    if not required_decision_keys.issubset(runtime_decision.keys()):
        return False
    if not required_execution_keys.issubset(runtime_execution.keys()):
        return False
    if not required_governance_keys.issubset(governance.keys()):
        return False
    promotion_state = str(runtime_decision.get("promotion_state") or "").lower()
    if promotion_state not in PROMOTION_STATES:
        return False
    return True


def _bucket_records(records: list[dict[str, Any]], window_open_timestamp: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    window_open = _parse_iso8601(window_open_timestamp)
    in_window: list[dict[str, Any]] = []
    qualified: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in records:
        raw_ts = item.get("timestamp")
        if not isinstance(raw_ts, str):
            continue
        try:
            ts = _parse_iso8601(raw_ts)
        except ValueError:
            continue
        if ts < window_open:
            continue
        in_window.append(item)
        if _is_schema_qualified(item):
            qualified.append(item)
        else:
            excluded.append(item)
    return in_window, qualified, excluded


def _record_route_family(record: dict[str, Any]) -> str:
    route_meta = record.get("runtime_v2_route_meta")
    if not isinstance(route_meta, dict):
        return "default"
    runtime_decision = route_meta.get("runtime_decision")
    if not isinstance(runtime_decision, dict):
        return "default"
    return str(runtime_decision.get("route_family") or "default").lower()


def _extract_latency_ms(runtime_execution: dict[str, Any]) -> dict[str, float | None]:
    legacy = runtime_execution.get("legacy_latency_ms")
    v2 = runtime_execution.get("v2_latency_ms")
    if legacy is None and v2 is None and isinstance(runtime_execution.get("latency_ms"), (int, float)):
        latency = float(runtime_execution["latency_ms"])
        served_runtime = str(runtime_execution.get("served_runtime") or "").lower()
        if served_runtime == "legacy":
            legacy = latency
        if served_runtime == "v2":
            v2 = latency
    out: dict[str, float | None] = {"legacy": None, "v2": None}
    if isinstance(legacy, (int, float)):
        out["legacy"] = float(legacy)
    if isinstance(v2, (int, float)):
        out["v2"] = float(v2)
    return out


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round(0.95 * (len(ordered) - 1)))
    return ordered[idx]


def _threshold_passed(value_total: int, value_sampled: int, threshold: _Threshold) -> bool:
    return value_total >= threshold.admin_total_requests and value_sampled >= threshold.admin_sampled_v2_requests


def build_observation_window_report(*, window_open_timestamp: str, log_path: str) -> dict[str, Any]:
    config = phase4_runtime_config()
    low_risk = RuntimeRiskAssessment(
        risk_level="low",
        risk_reason="risk_low_allowlisted_readonly",
        eligible_for_v2=True,
    )
    healthy_guard = GuardrailStatus(
        auto_disabled=False,
        reason="healthy",
        sample_size=100,
        fallback_rate=0.0,
        validation_fail_rate=0.0,
        exception_rate=0.0,
    )

    review_decision = compute_routing_decision(
        route_name="review",
        request_id="pre-open-review",
        config=config,
        risk_assessment=low_risk,
        guardrail_status=healthy_guard,
    )
    admin_decision = compute_routing_decision(
        route_name="admin",
        request_id="pre-open-admin",
        config=config,
        risk_assessment=low_risk,
        guardrail_status=healthy_guard,
    )
    default_decision = compute_routing_decision(
        route_name="unknown-default-route",
        request_id="pre-open-default",
        config=config,
        risk_assessment=low_risk,
        guardrail_status=healthy_guard,
    )

    records = _read_jsonl(Path(log_path))
    in_window, schema_qualified, excluded = _bucket_records(records, window_open_timestamp)

    route_distribution: Counter[str] = Counter()
    runtime_distribution: Counter[str] = Counter()
    fallback_distribution: Counter[str] = Counter()
    error_kind_distribution: Counter[str] = Counter()
    review_rows: list[dict[str, Any]] = []
    admin_rows: list[dict[str, Any]] = []
    legacy_latencies: list[float] = []
    v2_latencies: list[float] = []

    for row in schema_qualified:
        route_meta = row["runtime_v2_route_meta"]
        runtime_decision = route_meta["runtime_decision"]
        runtime_execution = route_meta["runtime_execution"]
        execution_report = route_meta["execution_report"]

        route = str(execution_report.get("route") or runtime_decision.get("route_name") or "unknown").lower()
        route_distribution[route] += 1
        served_runtime = str(runtime_execution.get("served_runtime") or "unknown").lower()
        runtime_distribution[served_runtime] += 1

        fallback_reason = str(runtime_execution.get("fallback_reason") or "not_reported").lower()
        if bool(runtime_execution.get("fallback")):
            fallback_distribution[fallback_reason] += 1
        else:
            fallback_distribution["not_applicable"] += 1

        error_kind = str(route_meta.get("error_kind") or "").lower()
        if not error_kind:
            shadow = execution_report.get("shadow")
            if isinstance(shadow, dict):
                error_kind = str(shadow.get("error_kind") or "").lower()
        if not error_kind:
            shadow_meta = row.get("shadow_meta")
            if isinstance(shadow_meta, dict):
                error_kind = str(shadow_meta.get("error_kind") or "").lower()
        if error_kind:
            error_kind_distribution[error_kind] += 1

        latency = _extract_latency_ms(runtime_execution)
        if latency["legacy"] is not None:
            legacy_latencies.append(float(latency["legacy"]))
        if latency["v2"] is not None:
            v2_latencies.append(float(latency["v2"]))

        route_family = _record_route_family(row)
        if route == "review" or route_family == "review":
            review_rows.append(row)
        if route == "admin" or route_family == "admin":
            admin_rows.append(row)

    def _decision_and_execution(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        route_meta = row["runtime_v2_route_meta"]
        return route_meta["runtime_decision"], route_meta["runtime_execution"], route_meta

    review_governance_sources: Counter[str] = Counter()
    review_other_state_count = 0
    review_sampled_v2_count = 0
    review_default_policy_count = 0
    for row in review_rows:
        runtime_decision, _, _ = _decision_and_execution(row)
        state = str(runtime_decision.get("promotion_state") or "").lower()
        source = str(runtime_decision.get("governance_source") or "").lower()
        review_governance_sources[source] += 1
        if state != "shadow_only":
            review_other_state_count += 1
        if state == "sampled_v2":
            review_sampled_v2_count += 1
        if source == "default_policy":
            review_default_policy_count += 1

    admin_total_requests = len(admin_rows)
    admin_sampled_v2_requests = 0
    admin_fallback_count = 0
    admin_v2_error_count = 0
    admin_unknown_error_kind_count = 0
    admin_shape_mismatch_count = 0
    admin_key_field_mismatch_count = 0
    unknown_fallback_reason_count = 0

    for row in admin_rows:
        runtime_decision, runtime_execution, route_meta = _decision_and_execution(row)
        route_event = str(row.get("runtime_v2_route_event") or "").lower()
        promotion_state = str(runtime_decision.get("promotion_state") or "").lower()
        sampled = bool(runtime_decision.get("sampled"))
        if promotion_state == "sampled_v2" and sampled:
            admin_sampled_v2_requests += 1

        fallback = bool(runtime_execution.get("fallback"))
        fallback_reason = str(runtime_execution.get("fallback_reason") or "").lower()
        if fallback:
            admin_fallback_count += 1
            if fallback_reason in UNKNOWN_FALLBACK_REASONS:
                unknown_fallback_reason_count += 1

        error_kind = str(route_meta.get("error_kind") or "").lower()
        if not error_kind:
            error_kind = str((row.get("shadow_meta") or {}).get("error_kind") or "").lower()
        has_error = route_event == "v2_error" or bool(route_meta.get("error_class"))
        if has_error:
            admin_v2_error_count += 1
            if error_kind in UNKNOWN_ERROR_KINDS or error_kind not in KNOWN_ERROR_KINDS:
                admin_unknown_error_kind_count += 1

        comparison = route_meta.get("comparison")
        if isinstance(comparison, dict):
            mismatches = comparison.get("mismatches")
            if isinstance(mismatches, (list, tuple)):
                lowered = {str(item).lower() for item in mismatches}
                if "shape" in lowered:
                    admin_shape_mismatch_count += 1
                if "key_fields" in lowered:
                    admin_key_field_mismatch_count += 1

    admin_fallback_rate = (admin_fallback_count / admin_total_requests) if admin_total_requests > 0 else None

    legacy_avg_ms = (sum(legacy_latencies) / len(legacy_latencies)) if legacy_latencies else None
    legacy_p95_ms = _percentile_95(legacy_latencies)
    v2_avg_ms = (sum(v2_latencies) / len(v2_latencies)) if v2_latencies else None
    v2_p95_ms = _percentile_95(v2_latencies)

    latency_metrics_present = all(
        value is not None for value in (legacy_avg_ms, legacy_p95_ms, v2_avg_ms, v2_p95_ms)
    )
    latency_gate_pass = (
        latency_metrics_present
        and float(v2_avg_ms) <= float(legacy_avg_ms) * 1.10
        and float(v2_p95_ms) <= float(legacy_p95_ms) * 1.10
        and float(v2_p95_ms) - float(legacy_p95_ms) <= 150.0
    )

    thresholds = {
        TREND_ONLY_THRESHOLD.name: _threshold_passed(admin_total_requests, admin_sampled_v2_requests, TREND_ONLY_THRESHOLD),
        ROLLOUT_READINESS_THRESHOLD.name: _threshold_passed(admin_total_requests, admin_sampled_v2_requests, ROLLOUT_READINESS_THRESHOLD),
        PREFERRED_CONFIDENCE_THRESHOLD.name: _threshold_passed(admin_total_requests, admin_sampled_v2_requests, PREFERRED_CONFIDENCE_THRESHOLD),
    }

    instance_count = _dashboard_instance_count()
    instance_validation = dashboard_instance_validation(instance_count)
    rollback_active = bool(config.governance.rollback_active and config.governance.rollback_state is not None)

    review_allowed_sources_only = set(review_governance_sources.keys()).issubset(ALLOWED_REVIEW_GOVERNANCE_SOURCES)

    admin_quality_gate = (
        admin_v2_error_count == 0
        and admin_unknown_error_kind_count == 0
        and admin_shape_mismatch_count == 0
        and admin_key_field_mismatch_count == 0
        and (admin_fallback_rate is not None and admin_fallback_rate <= 0.05)
        and unknown_fallback_reason_count == 0
    )

    review_integrity_gate = (
        review_other_state_count == 0
        and review_sampled_v2_count == 0
        and review_default_policy_count == 0
        and review_allowed_sources_only
    )

    global_safety_gate = instance_count == 1 and not rollback_active

    block_reasons: list[str] = []
    if instance_count != 1:
        block_reasons.append("instance_count_not_equal_1")
    if rollback_active:
        block_reasons.append("rollback_active")
    if review_other_state_count > 0:
        block_reasons.append("review_drift_other_state")
    if review_sampled_v2_count > 0:
        block_reasons.append("review_drift_sampled_v2")
    if review_default_policy_count > 0:
        block_reasons.append("review_drift_default_policy")
    if not review_allowed_sources_only:
        block_reasons.append("review_governance_source_not_allowed")
    if admin_shape_mismatch_count > 0:
        block_reasons.append("admin_shape_mismatch_present")
    if admin_key_field_mismatch_count > 0:
        block_reasons.append("admin_key_field_mismatch_present")
    if admin_unknown_error_kind_count > 0:
        block_reasons.append("admin_unknown_error_kind_present")
    if unknown_fallback_reason_count > 0:
        block_reasons.append("admin_unknown_fallback_reason_present")

    hold_reasons: list[str] = []
    if not thresholds[ROLLOUT_READINESS_THRESHOLD.name]:
        hold_reasons.append("rollout_readiness_threshold_not_met")
    if not latency_metrics_present:
        hold_reasons.append("latency_metrics_missing")
    if latency_metrics_present and not latency_gate_pass:
        hold_reasons.append("latency_gate_failed")
    if admin_total_requests == 0:
        hold_reasons.append("no_admin_evidence_in_window")
    if admin_fallback_rate is None:
        hold_reasons.append("admin_fallback_rate_missing")
    if not admin_quality_gate and not (
        admin_shape_mismatch_count > 0
        or admin_key_field_mismatch_count > 0
        or admin_unknown_error_kind_count > 0
        or unknown_fallback_reason_count > 0
    ):
        hold_reasons.append("admin_quality_gate_failed_without_blocker")

    all_rollout_gates_pass = (
        thresholds[ROLLOUT_READINESS_THRESHOLD.name]
        and latency_gate_pass
        and admin_quality_gate
        and review_integrity_gate
        and global_safety_gate
    )

    if block_reasons:
        decision = "BLOCK"
        decision_reasons = block_reasons
    elif all_rollout_gates_pass:
        decision = "MOVE"
        decision_reasons = []
    else:
        decision = "HOLD"
        decision_reasons = hold_reasons

    return {
        "window_open_timestamp": window_open_timestamp,
        "log_path": log_path,
        "pre_open_validation": {
            "instance_count": instance_count,
            "instance_validation": instance_validation,
            "rollback_available": config.governance.rollback_state,
            "rollback_active": rollback_active,
            "review": {
                "promotion_state": review_decision.promotion_state,
                "governance_source": review_decision.governance_source,
                "split_percent": review_decision.route_split_percent,
            },
            "admin": {
                "promotion_state": admin_decision.promotion_state,
                "governance_source": admin_decision.governance_source,
                "split_percent": admin_decision.route_split_percent,
            },
            "default": {
                "promotion_state": default_decision.promotion_state,
                "governance_source": default_decision.governance_source,
                "split_percent": default_decision.route_split_percent,
            },
        },
        "observation_summary": {
            "total_events_in_window": len(in_window),
            "schema_qualified_events": len(schema_qualified),
            "excluded_mixed_legacy_schema_events": len(excluded),
            "route_distribution": dict(route_distribution),
            "runtime_distribution": dict(runtime_distribution),
            "fallback_distribution": dict(fallback_distribution),
            "error_kind_distribution": dict(error_kind_distribution),
            "latency": {
                "legacy_avg_ms": legacy_avg_ms,
                "legacy_p95_ms": legacy_p95_ms,
                "v2_avg_ms": v2_avg_ms,
                "v2_p95_ms": v2_p95_ms,
            },
        },
        "review_focused_breakdown": {
            "review_total": len(review_rows),
            "review_shadow_only_count": len(review_rows) - review_other_state_count,
            "review_other_state_count": review_other_state_count,
            "review_sampled_v2_count": review_sampled_v2_count,
            "review_default_policy_count": review_default_policy_count,
            "review_governance_source_distribution": dict(review_governance_sources),
            "allowed_governance_sources": sorted(ALLOWED_REVIEW_GOVERNANCE_SOURCES),
            "review_allowed_governance_sources_only": review_allowed_sources_only,
        },
        "admin_readiness": {
            "admin_total_requests": admin_total_requests,
            "admin_sampled_v2_requests": admin_sampled_v2_requests,
            "thresholds": {
                TREND_ONLY_THRESHOLD.name: {
                    "min_admin_total_requests": TREND_ONLY_THRESHOLD.admin_total_requests,
                    "min_admin_sampled_v2_requests": TREND_ONLY_THRESHOLD.admin_sampled_v2_requests,
                    "met": thresholds[TREND_ONLY_THRESHOLD.name],
                },
                ROLLOUT_READINESS_THRESHOLD.name: {
                    "min_admin_total_requests": ROLLOUT_READINESS_THRESHOLD.admin_total_requests,
                    "min_admin_sampled_v2_requests": ROLLOUT_READINESS_THRESHOLD.admin_sampled_v2_requests,
                    "met": thresholds[ROLLOUT_READINESS_THRESHOLD.name],
                },
                PREFERRED_CONFIDENCE_THRESHOLD.name: {
                    "min_admin_total_requests": PREFERRED_CONFIDENCE_THRESHOLD.admin_total_requests,
                    "min_admin_sampled_v2_requests": PREFERRED_CONFIDENCE_THRESHOLD.admin_sampled_v2_requests,
                    "met": thresholds[PREFERRED_CONFIDENCE_THRESHOLD.name],
                },
            },
        },
        "gates": {
            "latency_gate": {
                "metrics_present": latency_metrics_present,
                "pass": bool(latency_gate_pass),
                "conditions": {
                    "v2_avg_le_legacy_avg_x_1_10": latency_metrics_present and float(v2_avg_ms) <= float(legacy_avg_ms) * 1.10 if latency_metrics_present else False,
                    "v2_p95_le_legacy_p95_x_1_10": latency_metrics_present and float(v2_p95_ms) <= float(legacy_p95_ms) * 1.10 if latency_metrics_present else False,
                    "v2_p95_minus_legacy_p95_le_150_ms": latency_metrics_present and (float(v2_p95_ms) - float(legacy_p95_ms)) <= 150.0 if latency_metrics_present else False,
                },
            },
            "admin_quality_gate": {
                "pass": admin_quality_gate,
                "admin_v2_error_count": admin_v2_error_count,
                "admin_unknown_error_kind_count": admin_unknown_error_kind_count,
                "admin_shape_mismatch_count": admin_shape_mismatch_count,
                "admin_key_field_mismatch_count": admin_key_field_mismatch_count,
                "admin_fallback_rate": admin_fallback_rate,
                "unknown_fallback_reason_count": unknown_fallback_reason_count,
            },
            "review_integrity_gate": {
                "pass": review_integrity_gate,
                "review_other_state_count": review_other_state_count,
                "review_sampled_v2_count": review_sampled_v2_count,
                "review_default_policy_count": review_default_policy_count,
                "review_allowed_governance_sources_only": review_allowed_sources_only,
            },
            "global_safety_gate": {
                "pass": global_safety_gate,
                "instance_count_is_1": instance_count == 1,
                "rollback_active_is_false": not rollback_active,
            },
        },
        "decision": {
            "result": decision,
            "reasons": decision_reasons,
            "rule": "MOVE only if rollout-readiness threshold and all gates pass; HOLD if evidence/sample insufficient; BLOCK on drift/mismatch/unknown errors/rollback/instance mismatch.",
        },
    }
