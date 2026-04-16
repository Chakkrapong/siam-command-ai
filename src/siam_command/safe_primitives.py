from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .automation.monitoring_api import get_monitoring_bundle_response


_BLOCKED_KEYS = {
    "operator_action_required",
    "recommendation_strength",
    "policy_posture",
    "escalation_readiness",
}


def _read_log_entries(log_path: str | Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with open(log_path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except Exception:
                    continue
                if isinstance(value, dict):
                    entries.append(value)
    except OSError:
        return []
    return entries


def _detect_flags(entry: dict[str, Any]) -> tuple[bool, bool]:
    shadow_error = entry.get("shadow_event") == "shadow_error"
    shadow_meta = entry.get("shadow_meta")
    runtime_exception = isinstance(shadow_meta, dict) and shadow_meta.get("error_kind") == "runtime_exception"
    return shadow_error, runtime_exception


def _sanitize(payload: Any) -> Any:
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if key_text in _BLOCKED_KEYS or key_text.startswith("techin_"):
                continue
            out[key_text] = _sanitize(value)
        return out
    if isinstance(payload, list):
        return [_sanitize(item) for item in payload]
    return payload


def compute_state_check(log_path: str | Path, *, window: int = 50) -> dict[str, Any]:
    entries = _read_log_entries(log_path)
    safe_window = max(1, int(window))
    windowed = entries[-safe_window:]
    total_entries = len(windowed)
    success_count = 0
    error_count = 0
    shadow_error_count = 0
    runtime_exception_count = 0
    execution_ids: set[str] = set()

    for item in windowed:
        execution_id = str(item.get("execution_id", "")).strip()
        if execution_id:
            execution_ids.add(execution_id)
        shadow_error, runtime_exception = _detect_flags(item)
        if shadow_error:
            shadow_error_count += 1
        if runtime_exception:
            runtime_exception_count += 1
        if shadow_error or runtime_exception:
            error_count += 1
        else:
            success_count += 1

    error_rate = (error_count / total_entries) if total_entries else 0.0
    shadow_error_rate = (shadow_error_count / total_entries) if total_entries else 0.0
    status = "ready" if (runtime_exception_count == 0 and shadow_error_count == 0) else "not_ready"
    reason_codes: list[str] = []
    reasons: list[str] = []
    if runtime_exception_count > 0:
        reason_codes.append("runtime_exceptions_present")
        reasons.append("Runtime exceptions were detected in the recent execution window.")
    if shadow_error_count > 0:
        reason_codes.append("shadow_errors_present")
        reasons.append("Shadow errors were detected in the recent execution window.")
    if not reason_codes:
        reason_codes.append("healthy_window")
        reasons.append("No runtime exceptions or shadow errors were detected in the recent execution window.")
    score = max(0.0, 1.0 - min(1.0, error_rate + shadow_error_rate))

    return _sanitize(
        {
            "status": status,
            "score": score,
            "reason_codes": reason_codes,
            "reasons": reasons,
            "window": safe_window,
            "metrics": {
                "total_entries_in_window": total_entries,
                "success_count": success_count,
                "error_count": error_count,
                "runtime_exception_count": runtime_exception_count,
                "shadow_error_count": shadow_error_count,
                "signal_count": runtime_exception_count + shadow_error_count,
                "unique_execution_ids": len(execution_ids),
                "error_rate": error_rate,
                "shadow_error_rate": shadow_error_rate,
            },
        }
    )


def build_review_surface(log_path: str | Path, *, tail: int = 5) -> dict[str, Any]:
    entries = _read_log_entries(log_path)
    safe_tail = max(0, int(tail))
    recent = entries[-safe_tail:] if safe_tail else []
    timeline_lines = []
    for item in recent:
        execution_id = str(item.get("execution_id", "")).strip() or "-"
        shadow_error, runtime_exception = _detect_flags(item)
        timeline_lines.append(
            f"{execution_id} | shadow_error={'yes' if shadow_error else 'no'} | runtime_exception={'yes' if runtime_exception else 'no'}"
        )

    return _sanitize(
        {
            "recent_cycles": [],
            "timeline_lines": timeline_lines,
            "total_cycles_observed": 0,
            "latest_cycle": None,
            "review_queue": {"items": [], "total_items": 0},
            "recent_cycle_drill_downs": [],
            "latest_cycle_drill_down": None,
            "trend_signals": [],
            "repeated_patterns": [],
            "repeated_rule_triggers": [],
            "repeated_failed_actions": [],
            "repeated_unresolved_risks": [],
            "repeated_blocked_important_decisions": [],
            "repeated_suppressed_low_value_outputs": [],
            "recent_audit_trail": [],
            "audit_entries": [],
            "audit_summary": {"total_audit_entries": 0, "cycle_span": 0},
        }
    )


def build_operator_report(log_path: str | Path, *, tail: int = 5) -> dict[str, Any]:
    entries = _read_log_entries(log_path)
    safe_tail = max(0, int(tail))
    total_entries = len(entries)
    total_shadow_errors = 0
    total_runtime_exceptions = 0
    unique_execution_ids: set[str] = set()
    for entry in entries:
        execution_id = str(entry.get("execution_id", "")).strip()
        if execution_id:
            unique_execution_ids.add(execution_id)
        shadow_error, runtime_exception = _detect_flags(entry)
        if shadow_error:
            total_shadow_errors += 1
        if runtime_exception:
            total_runtime_exceptions += 1

    recent_entries: list[dict[str, str]] = []
    if safe_tail:
        for entry in entries[-safe_tail:]:
            execution_id = str(entry.get("execution_id", "")).strip() or "-"
            shadow_error, runtime_exception = _detect_flags(entry)
            recent_entries.append(
                {
                    "execution_id": execution_id,
                    "shadow_error": "yes" if shadow_error else "no",
                    "runtime_exception": "yes" if runtime_exception else "no",
                }
            )

    summary = {
        "total_entries": total_entries,
        "unique_execution_ids": len(unique_execution_ids),
        "total_shadow_errors": total_shadow_errors,
        "total_runtime_exceptions": total_runtime_exceptions,
        "total_signals": total_shadow_errors + total_runtime_exceptions,
        "shadow_error_rate": (total_shadow_errors / total_entries) if total_entries else 0.0,
        "runtime_exception_rate": (total_runtime_exceptions / total_entries) if total_entries else 0.0,
    }

    return _sanitize(
        {
            "summary": summary,
            "recent_entries": recent_entries,
            "review_surface": {
                "timeline_lines": build_review_surface(log_path, tail=safe_tail).get("timeline_lines", []),
                "review_queue": {"items": [], "total_items": 0},
                "trend_signals": [],
                "recent_audit_trail": [],
            },
        }
    )


def build_monitoring_snapshot_view(
    *,
    readiness_path: str | Path = ".siam/readiness_snapshot.json",
    alerts_path: str | Path = ".siam/alerts_snapshot.json",
    automation_log_path: str | Path = ".siam/execution-log.jsonl",
) -> dict[str, Any]:
    bundle = get_monitoring_bundle_response(readiness_path=readiness_path, alerts_path=alerts_path)
    readiness = bundle.get("readiness", {})
    alerts = bundle.get("alerts", {})
    return _sanitize(
        {
            "readiness": readiness,
            "alerts": alerts,
            "automation_review": build_review_surface(automation_log_path, tail=5),
        }
    )


__all__ = [
    "build_monitoring_snapshot_view",
    "build_operator_report",
    "build_review_surface",
    "compute_state_check",
]
