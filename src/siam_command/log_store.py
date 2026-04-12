from __future__ import annotations

import json
import time
from pathlib import Path

from .models import ExecutionLogModel


class ExecutionLogStore:
    def __init__(self, path: str, enabled: bool) -> None:
        self._path = Path(path)
        self._enabled = enabled
        self._last_io_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> Path:
        return self._path

    @property
    def last_io_error(self) -> str | None:
        return self._last_io_error

    def append(self, log: ExecutionLogModel) -> None:
        if not self._enabled:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(self._normalize_record(log.to_dict()), ensure_ascii=True)
        # Best-effort retry to tolerate temporary Windows file locks.
        for _ in range(3):
            try:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                self._last_io_error = None
                return
            except PermissionError as exc:
                self._last_io_error = str(exc)
                time.sleep(0.05)
            except OSError as exc:
                self._last_io_error = str(exc)
                return

    def read_all(self) -> tuple[dict[str, object], ...]:
        if not self._enabled or not self._path.exists():
            return ()
        records: list[dict[str, object]] = []
        try:
            for raw in self._path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        records.append(self._normalize_record(payload))
                except json.JSONDecodeError:
                    # Skip partial/corrupt lines from interrupted writes.
                    continue
            self._last_io_error = None
        except PermissionError as exc:
            self._last_io_error = str(exc)
            return ()
        except OSError as exc:
            self._last_io_error = str(exc)
            return ()
        return tuple(records)

    @staticmethod
    def _normalize_record(record: dict[str, object]) -> dict[str, object]:
        payload = dict(record)
        route_event = payload.get("runtime_v2_route_event")
        if route_event not in {"routed_v2", "fallback_legacy", "v2_error", "legacy_default"}:
            payload["runtime_v2_route_event"] = "legacy_default"
        if not isinstance(payload.get("runtime_v2_route_meta"), dict):
            payload["runtime_v2_route_meta"] = None
        route_meta = payload.get("runtime_v2_route_meta")
        if isinstance(route_meta, dict):
            if isinstance(route_meta.get("route_name"), str):
                route_meta["route_name"] = str(route_meta["route_name"]).strip().lower()
            if isinstance(route_meta.get("command_name"), str):
                route_meta["command_name"] = str(route_meta["command_name"]).strip().lower()
            runtime_decision = route_meta.get("runtime_decision")
            if not isinstance(runtime_decision, dict):
                route_meta["runtime_decision"] = {
                    "selected_runtime": "legacy",
                    "reason": str(route_meta.get("reason", "legacy_default")),
                    "promotion_state": "legacy_only",
                    "route_family": "default",
                    "governance_source": "default_policy",
                    "downgraded": False,
                    "downgrade_reason": None,
                    "rollback_state": None,
                    "partial_enabled": False,
                    "allowlisted": False,
                    "rollout_bucket": -1,
                    "rollout_percent": 0,
                    "in_rollout": False,
                    "risk_level": "high",
                    "risk_reason": "risk_blocked_unsupported_shape",
                    "auto_disabled": False,
                }
            else:
                if isinstance(runtime_decision.get("route_name"), str):
                    runtime_decision["route_name"] = str(runtime_decision["route_name"]).strip().lower()
                runtime_decision.setdefault("rollout_bucket", -1)
                runtime_decision.setdefault("rollout_percent", 0)
                runtime_decision.setdefault("in_rollout", False)
                runtime_decision.setdefault("risk_level", "high")
                runtime_decision.setdefault("risk_reason", "risk_blocked_unsupported_shape")
                runtime_decision.setdefault("auto_disabled", False)
                runtime_decision.setdefault("promotion_state", "legacy_only")
                runtime_decision.setdefault("route_family", "default")
                runtime_decision.setdefault("governance_source", "default_policy")
                runtime_decision.setdefault("downgraded", False)
                runtime_decision.setdefault("downgrade_reason", None)
                runtime_decision.setdefault("rollback_state", None)
            runtime_execution = route_meta.get("runtime_execution")
            if not isinstance(runtime_execution, dict):
                route_meta["runtime_execution"] = {
                    "attempted_runtime": "legacy",
                    "served_runtime": "legacy",
                    "fallback": False,
                    "fallback_reason": "not_applicable",
                    "validation_passed": None,
                    "validation_reason": None,
                }
            runtime_guardrail = route_meta.get("runtime_guardrail")
            if not isinstance(runtime_guardrail, dict):
                route_meta["runtime_guardrail"] = {
                    "auto_disabled": False,
                    "reason": "insufficient_sample",
                    "sample_size": 0,
                    "fallback_rate": 0.0,
                    "validation_fail_rate": 0.0,
                    "exception_rate": 0.0,
                }
            execution_report = route_meta.get("execution_report")
            if not isinstance(execution_report, dict):
                route_meta["execution_report"] = {
                    "route": route_meta.get("command_name", "none"),
                    "primary_runtime": ((route_meta.get("runtime_execution") or {}).get("served_runtime") if isinstance(route_meta.get("runtime_execution"), dict) else "legacy"),
                    "routing_reason": str(route_meta.get("reason", "legacy_default")),
                    "shadow": {"run": False, "event": payload.get("shadow_event"), "reason": None, "match": None},
                    "guard": {
                        "blocked": bool(((route_meta.get("runtime_decision") or {}).get("guard_blocked")) if isinstance(route_meta.get("runtime_decision"), dict) else False),
                        "reason": ((route_meta.get("runtime_decision") or {}).get("guard_reason")) if isinstance(route_meta.get("runtime_decision"), dict) else None,
                        "status": ((route_meta.get("runtime_guardrail") or {}).get("reason")) if isinstance(route_meta.get("runtime_guardrail"), dict) else None,
                    },
                    "governance": {
                        "promotion_state": ((route_meta.get("runtime_decision") or {}).get("promotion_state")) if isinstance(route_meta.get("runtime_decision"), dict) else "legacy_only",
                        "route_family": ((route_meta.get("runtime_decision") or {}).get("route_family")) if isinstance(route_meta.get("runtime_decision"), dict) else "default",
                        "state_source": ((route_meta.get("runtime_decision") or {}).get("governance_source")) if isinstance(route_meta.get("runtime_decision"), dict) else "default_policy",
                        "downgraded": ((route_meta.get("runtime_decision") or {}).get("downgraded")) if isinstance(route_meta.get("runtime_decision"), dict) else False,
                        "downgrade_reason": ((route_meta.get("runtime_decision") or {}).get("downgrade_reason")) if isinstance(route_meta.get("runtime_decision"), dict) else None,
                        "rollback_state": ((route_meta.get("runtime_decision") or {}).get("rollback_state")) if isinstance(route_meta.get("runtime_decision"), dict) else None,
                    },
                }
                execution_report = route_meta.get("execution_report")
            if isinstance(execution_report, dict):
                route = execution_report.get("route")
                if isinstance(route, str):
                    execution_report["route"] = route.strip().lower()
                shadow = execution_report.get("shadow")
                if not isinstance(shadow, dict):
                    execution_report["shadow"] = {"run": False, "event": payload.get("shadow_event"), "reason": None, "match": None}
                else:
                    shadow.setdefault("error_kind", None)
                    shadow.setdefault("error_kind_match", None)
                governance = execution_report.get("governance")
                if not isinstance(governance, dict):
                    execution_report["governance"] = {
                        "promotion_state": "legacy_only",
                        "route_family": "default",
                        "state_source": "default_policy",
                        "downgraded": False,
                        "downgrade_reason": None,
                        "rollback_state": None,
                    }
        event = payload.get("shadow_event")
        if event not in {"shadow_match", "shadow_diff", "shadow_error", "shadow_skipped"}:
            payload["shadow_event"] = "shadow_skipped" if payload.get("selected_command") else None
        if not isinstance(payload.get("shadow_meta"), dict):
            payload["shadow_meta"] = None
        return payload
