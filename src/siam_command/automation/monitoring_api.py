"""Boundary-safe monitoring snapshot reader for serving layer endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_READINESS_SNAPSHOT_PATH = ".siam/readiness_snapshot.json"
DEFAULT_ALERTS_SNAPSHOT_PATH = ".siam/alerts_snapshot.json"
_DEFAULT_SCOPE_TYPE = "global"
_DEFAULT_SCOPE_KEY = "default"

_READINESS_FALLBACK = {
    "status": "not_ready",
    "score": 0.0,
    "window": 0,
    "reason_codes": ["no_data"],
    "reasons": ["No readiness data available"],
    "metrics": {
        "total_entries_in_window": 0,
        "error_rate": 0.0,
        "shadow_error_rate": 0.0,
        "runtime_exception_count": 0,
        "signal_count": 0,
    },
    "source": "monitoring_api",
    "updated_at": "",
}

_ALERTS_FALLBACK = {
    "alerts": [],
    "updated_at": "",
    "source": "monitoring_api",
}


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    if out != out:  # NaN guard
        return fallback
    return out


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _to_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def read_json_file(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def coerce_readiness_snapshot(payload: Any) -> dict[str, Any]:
    if not _is_record(payload):
        return json.loads(json.dumps(_READINESS_FALLBACK))

    metrics_in = payload.get("metrics")
    metrics = {
        "total_entries_in_window": _to_int(metrics_in.get("total_entries_in_window")) if _is_record(metrics_in) else 0,
        "error_rate": _to_float(metrics_in.get("error_rate")) if _is_record(metrics_in) else 0.0,
        "shadow_error_rate": _to_float(metrics_in.get("shadow_error_rate")) if _is_record(metrics_in) else 0.0,
        "runtime_exception_count": _to_int(metrics_in.get("runtime_exception_count")) if _is_record(metrics_in) else 0,
        "signal_count": _to_int(metrics_in.get("signal_count")) if _is_record(metrics_in) else 0,
    }

    raw_status = str(payload.get("status") or "not_ready")
    status = raw_status if raw_status in {"ready", "warning", "not_ready"} else "not_ready"

    return {
        "status": status,
        "score": _to_float(payload.get("score")),
        "window": max(0, _to_int(payload.get("window"))),
        "reason_codes": _to_str_list(payload.get("reason_codes")),
        "reasons": _to_str_list(payload.get("reasons")),
        "metrics": metrics,
        "source": str(payload.get("source") or "monitoring_api"),
        "updated_at": str(payload.get("updated_at") or ""),
    }


def _coerce_alert(payload: Any) -> dict[str, Any] | None:
    if not _is_record(payload):
        return None
    severity = str(payload.get("severity") or "")
    status = str(payload.get("status") or "")
    kind = str(payload.get("kind") or "")
    if kind != "readiness_status":
        return None
    if severity not in {"medium", "high"}:
        return None
    if status not in {"warning", "not_ready"}:
        return None
    return {
        "kind": "readiness_status",
        "severity": severity,
        "status": status,
        "message": str(payload.get("message") or ""),
        "reason_codes": _to_str_list(payload.get("reason_codes")),
        "score": _to_float(payload.get("score")),
        "source": str(payload.get("source") or "monitoring_api"),
        "timestamp": str(payload.get("timestamp") or ""),
    }


def coerce_alerts_snapshot(payload: Any) -> dict[str, Any]:
    if not _is_record(payload):
        return json.loads(json.dumps(_ALERTS_FALLBACK))
    alerts_in = payload.get("alerts")
    alerts: list[dict[str, Any]] = []
    if isinstance(alerts_in, list):
        for item in alerts_in:
            safe = _coerce_alert(item)
            if safe is not None:
                alerts.append(safe)
    return {
        "alerts": alerts,
        "updated_at": str(payload.get("updated_at") or ""),
        "source": str(payload.get("source") or "monitoring_api"),
    }


def get_readiness_snapshot_response(
    path: str | Path = DEFAULT_READINESS_SNAPSHOT_PATH,
    *,
    ports: Any = None,
    settings: Any = None,
) -> dict[str, Any]:
    _ = settings
    if ports is not None and hasattr(ports, "readiness"):
        latest = ports.readiness.get_latest_snapshot(_DEFAULT_SCOPE_TYPE, _DEFAULT_SCOPE_KEY)
        if isinstance(latest, dict):
            return coerce_readiness_snapshot(latest)
    return coerce_readiness_snapshot(read_json_file(path))


def get_alerts_snapshot_response(
    path: str | Path = DEFAULT_ALERTS_SNAPSHOT_PATH,
    *,
    ports: Any = None,
    settings: Any = None,
) -> dict[str, Any]:
    _ = settings
    if ports is not None and hasattr(ports, "alerts"):
        alerts = ports.alerts.list_open_alerts(scope_type=_DEFAULT_SCOPE_TYPE, scope_key=_DEFAULT_SCOPE_KEY)
        return coerce_alerts_snapshot(
            {
                "alerts": alerts,
                "updated_at": "",
                "source": "monitoring_api_port",
            }
        )
    return coerce_alerts_snapshot(read_json_file(path))


def get_monitoring_bundle_response(
    readiness_path: str | Path = DEFAULT_READINESS_SNAPSHOT_PATH,
    alerts_path: str | Path = DEFAULT_ALERTS_SNAPSHOT_PATH,
    *,
    ports: Any = None,
    settings: Any = None,
) -> dict[str, Any]:
    return {
        "readiness": get_readiness_snapshot_response(readiness_path, ports=ports, settings=settings),
        "alerts": get_alerts_snapshot_response(alerts_path, ports=ports, settings=settings),
    }
