"""Sanitized snapshot exporter for private automation core."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..application.ports import ControlPlanePorts
from ..infrastructure.bootstrap import build_control_plane_ports
from ..infrastructure.settings import SiamInfrastructureSettings

try:
    from .readiness_alerts import (
        build_readiness_alert,
        get_readiness_snapshot,
        should_emit_readiness_alert,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from src.siam_command.automation.readiness_alerts import (  # type: ignore
        build_readiness_alert,
        get_readiness_snapshot,
        should_emit_readiness_alert,
    )

READINESS_SOURCE = "readiness_tracker"
SNAPSHOT_SOURCE = "snapshot_exporter"
ALLOWED_READINESS_METRICS = (
    "total_entries_in_window",
    "error_rate",
    "shadow_error_rate",
    "runtime_exception_count",
    "signal_count",
)
_DEFAULT_SCOPE_TYPE = "global"
_DEFAULT_SCOPE_KEY = "default"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sanitize_readiness_snapshot(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """Strip readiness payload down to UI-safe fields only."""
    safe_metrics: Dict[str, Any] = {}
    metrics = readiness.get("metrics")
    if isinstance(metrics, dict):
        for key in ALLOWED_READINESS_METRICS:
            value = metrics.get(key)
            if isinstance(value, (bool, int, float)):
                safe_metrics[key] = value

    reason_codes = readiness.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
    reasons = readiness.get("reasons")
    if not isinstance(reasons, list):
        reasons = []

    raw_status = str(readiness.get("status") or "not_ready")
    status = raw_status if raw_status in {"ready", "warning", "not_ready"} else "not_ready"

    return {
        "status": status,
        "score": float(readiness.get("score") or 0.0),
        "window": max(1, int(readiness.get("window") or 50)),
        "reason_codes": [str(code) for code in reason_codes],
        "reasons": [str(reason) for reason in reasons],
        "metrics": safe_metrics,
        "source": READINESS_SOURCE,
        "updated_at": utc_now_iso(),
    }


def sanitize_alert(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Strip alert payload down to minimal UI-safe fields only."""
    status = str(alert.get("status") or "not_ready")
    severity = "high" if status == "not_ready" else "medium"
    reason_codes = alert.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
    timestamp = str(alert.get("timestamp") or utc_now_iso()).replace("+00:00", "Z")

    return {
        "kind": "readiness_status",
        "severity": severity,
        "status": status,
        "message": f"Readiness status is {status}",
        "reason_codes": [str(code) for code in reason_codes],
        "score": float(alert.get("score") or 0.0),
        "source": READINESS_SOURCE,
        "timestamp": timestamp,
    }


def build_readiness_snapshot(
    log_path: str | Path = ".siam/execution-log.jsonl",
    window: int = 50,
) -> Dict[str, Any]:
    """Build current sanitized readiness snapshot."""
    safe_window = max(1, int(window))
    try:
        readiness = get_readiness_snapshot(str(log_path), window=safe_window)
    except Exception:
        readiness = {
            "status": "not_ready",
            "score": 0.0,
            "window": safe_window,
            "reason_codes": ["no_data"],
            "reasons": ["No readiness data available"],
            "metrics": {},
        }
    return sanitize_readiness_snapshot(readiness)


def build_alerts_snapshot(
    log_path: str | Path = ".siam/execution-log.jsonl",
    window: int = 50,
    previous_status: str | None = None,
) -> Dict[str, Any]:
    """Build current-state sanitized alerts snapshot."""
    alerts: list[Dict[str, Any]] = []
    try:
        readiness = get_readiness_snapshot(str(log_path), window=max(1, int(window)))
        if should_emit_readiness_alert(readiness, previous_status=previous_status):
            alerts.append(sanitize_alert(build_readiness_alert(readiness)))
    except Exception:
        alerts = []
    return {
        "alerts": alerts,
        "updated_at": utc_now_iso(),
        "source": SNAPSHOT_SOURCE,
    }


def write_json_file(path: str | Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Write JSON atomically and return structured result."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    raw = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=False) + "\n"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent) as handle:
            handle.write(raw)
            temp_path = Path(handle.name)
        try:
            os.replace(temp_path, target)
        except PermissionError:
            # Best-effort fallback for restricted Windows environments.
            target.write_text(raw, encoding="utf-8")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        return {"ok": True, "path": str(target), "bytes_written": len(raw.encode("utf-8"))}
    except OSError as exc:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        return {"ok": False, "path": str(target), "error": str(exc)}


def export_readiness_snapshot(
    path: str | Path = ".siam/readiness_snapshot.json",
    log_path: str | Path = ".siam/execution-log.jsonl",
    window: int = 50,
    *,
    ports: ControlPlanePorts | None = None,
    settings: SiamInfrastructureSettings | None = None,
) -> Dict[str, Any]:
    """Compute and export sanitized readiness snapshot."""
    payload = build_readiness_snapshot(log_path=log_path, window=window)
    file_result = write_json_file(path, payload)
    _persist_readiness_snapshot_via_port(payload, ports=ports, settings=settings)
    return file_result


def export_alerts_snapshot(
    path: str | Path = ".siam/alerts_snapshot.json",
    log_path: str | Path = ".siam/execution-log.jsonl",
    window: int = 50,
    previous_status: str | None = None,
    *,
    ports: ControlPlanePorts | None = None,
    settings: SiamInfrastructureSettings | None = None,
) -> Dict[str, Any]:
    """Compute and export current-state sanitized alerts snapshot."""
    payload = build_alerts_snapshot(log_path=log_path, window=window, previous_status=previous_status)
    file_result = write_json_file(path, payload)
    _persist_alerts_snapshot_via_port(payload, ports=ports, settings=settings)
    return file_result


def export_all_snapshots(
    *,
    readiness_path: str | Path = ".siam/readiness_snapshot.json",
    alerts_path: str | Path = ".siam/alerts_snapshot.json",
    log_path: str | Path = ".siam/execution-log.jsonl",
    window: int = 50,
    previous_status: str | None = None,
    ports: ControlPlanePorts | None = None,
    settings: SiamInfrastructureSettings | None = None,
) -> Dict[str, Any]:
    """Export readiness and alerts snapshots in one call."""
    readiness_result = export_readiness_snapshot(
        path=readiness_path,
        log_path=log_path,
        window=window,
        ports=ports,
        settings=settings,
    )
    alerts_result = export_alerts_snapshot(
        path=alerts_path,
        log_path=log_path,
        window=window,
        previous_status=previous_status,
        ports=ports,
        settings=settings,
    )
    ok = bool(readiness_result.get("ok")) and bool(alerts_result.get("ok"))
    return {
        "ok": ok,
        "readiness": readiness_result,
        "alerts": alerts_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export sanitized readiness/alerts snapshots")
    parser.add_argument("--window", type=int, default=50, help="Readiness window size")
    parser.add_argument("--log-path", default=".siam/execution-log.jsonl", help="Execution log JSONL path")
    parser.add_argument(
        "--readiness-path",
        default=".siam/readiness_snapshot.json",
        help="Output path for readiness snapshot",
    )
    parser.add_argument(
        "--alerts-path",
        default=".siam/alerts_snapshot.json",
        help="Output path for alerts snapshot",
    )
    parser.add_argument(
        "--previous-status",
        default=None,
        choices=["ready", "warning", "not_ready", None],
        help="Optional prior readiness status for anti-spam behavior",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.window <= 0:
        print(json.dumps({"ok": False, "error": "--window must be greater than 0"}, ensure_ascii=True))
        return 2
    result = export_all_snapshots(
        readiness_path=args.readiness_path,
        alerts_path=args.alerts_path,
        log_path=args.log_path,
        window=args.window,
        previous_status=args.previous_status,
    )
    compact = {
        "ok": result["ok"],
        "readiness": {
            "ok": result["readiness"].get("ok"),
            "path": result["readiness"].get("path"),
            "bytes_written": result["readiness"].get("bytes_written"),
        },
        "alerts": {
            "ok": result["alerts"].get("ok"),
            "path": result["alerts"].get("path"),
            "bytes_written": result["alerts"].get("bytes_written"),
        },
    }
    print(json.dumps(compact, ensure_ascii=True))
    return 0 if result["ok"] else 1


def _persist_readiness_snapshot_via_port(
    payload: Dict[str, Any],
    *,
    ports: ControlPlanePorts | None = None,
    settings: SiamInfrastructureSettings | None = None,
) -> None:
    resolved_settings = settings or SiamInfrastructureSettings.from_env()
    if resolved_settings.readiness_provider.strip().lower() == "local":
        return
    resolved_ports = ports or build_control_plane_ports(resolved_settings)
    port_payload = dict(payload)
    port_payload["scope_type"] = _DEFAULT_SCOPE_TYPE
    port_payload["scope_key"] = _DEFAULT_SCOPE_KEY
    resolved_ports.readiness.save_snapshot(port_payload)


def _persist_alerts_snapshot_via_port(
    payload: Dict[str, Any],
    *,
    ports: ControlPlanePorts | None = None,
    settings: SiamInfrastructureSettings | None = None,
) -> None:
    resolved_settings = settings or SiamInfrastructureSettings.from_env()
    if resolved_settings.alert_provider.strip().lower() == "local":
        return
    resolved_ports = ports or build_control_plane_ports(resolved_settings)
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        item = dict(alert)
        item.setdefault("scope_type", _DEFAULT_SCOPE_TYPE)
        item.setdefault("scope_key", _DEFAULT_SCOPE_KEY)
        item.setdefault("status", "open")
        resolved_ports.alerts.create_alert(item)


if __name__ == "__main__":
    raise SystemExit(main())
