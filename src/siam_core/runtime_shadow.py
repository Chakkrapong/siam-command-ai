from __future__ import annotations

from typing import Any

from .compat import runtime_v2_shadow_command_allowlist, runtime_v2_shadow_enabled
from .runtime_error_kind import normalize_error_kind
from .runtime_v2 import build_runtime_v2_execution_registry_port


def _shape_name(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, (list, tuple)):
        return "sequence"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _key_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    important = ("status", "success", "ok", "error", "message", "code")
    return {key: value.get(key) for key in important if key in value}


def _success_indicator(value: Any) -> bool | None:
    if not isinstance(value, dict):
        return None
    if "success" in value and isinstance(value.get("success"), bool):
        return value["success"]
    if "ok" in value and isinstance(value.get("ok"), bool):
        return value["ok"]
    status = value.get("status")
    if isinstance(status, str):
        lowered = status.strip().lower()
        if lowered in {"ok", "success", "succeeded"}:
            return True
        if lowered in {"error", "failed", "failure"}:
            return False
    if value.get("error"):
        return False
    return None


def should_shadow_command(
    command_name: str | None,
    *,
    enabled: bool | None = None,
    allowlist: tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    if not (runtime_v2_shadow_enabled() if enabled is None else enabled):
        return False, "disabled"
    if not command_name:
        return False, "no_command_selected"
    allowed = allowlist if allowlist is not None else runtime_v2_shadow_command_allowlist()
    allow = {name.lower() for name in allowed}
    if command_name.lower() not in allow:
        return False, "command_not_allowlisted"
    return True, "eligible"


def compare_legacy_vs_v2(
    *,
    legacy_result: Any = None,
    v2_result: Any = None,
    legacy_error: BaseException | None = None,
    v2_error: BaseException | None = None,
) -> dict[str, object]:
    if legacy_error is not None or v2_error is not None:
        legacy_class = type(legacy_error).__name__ if legacy_error else None
        v2_class = type(v2_error).__name__ if v2_error else None
        if v2_error is not None:
            legacy_kind = normalize_error_kind(error_class=legacy_class)
            v2_kind = normalize_error_kind(error_class=v2_class, reason="v2_execution_error", message=str(v2_error))
            return {
                "shadow_event": "shadow_error",
                "match": False,
                "legacy_error_class": legacy_class,
                "v2_error_class": v2_class,
                "legacy_error_kind": legacy_kind,
                "v2_error_kind": v2_kind,
                "error_kind_match": legacy_kind == v2_kind,
                "v2_error": str(v2_error),
            }
        legacy_kind = normalize_error_kind(error_class=legacy_class)
        v2_kind = normalize_error_kind(error_class=v2_class)
        return {
            "shadow_event": "shadow_diff",
            "match": False,
            "legacy_error_class": legacy_class,
            "v2_error_class": v2_class,
            "legacy_error_kind": legacy_kind,
            "v2_error_kind": v2_kind,
            "error_kind_match": legacy_kind == v2_kind,
            "reason": "legacy_error_only",
        }

    legacy_shape = _shape_name(legacy_result)
    v2_shape = _shape_name(v2_result)
    legacy_keys = _key_fields(legacy_result)
    v2_keys = _key_fields(v2_result)
    legacy_success = _success_indicator(legacy_result)
    v2_success = _success_indicator(v2_result)

    mismatches: list[str] = []
    if legacy_shape != v2_shape:
        mismatches.append("shape")
    if legacy_keys != v2_keys:
        mismatches.append("key_fields")
    if legacy_success != v2_success:
        mismatches.append("success_indicator")
    if legacy_result != v2_result:
        mismatches.append("value")

    if mismatches:
        return {
            "shadow_event": "shadow_diff",
            "match": False,
            "legacy_shape": legacy_shape,
            "v2_shape": v2_shape,
            "legacy_key_fields": legacy_keys,
            "v2_key_fields": v2_keys,
            "legacy_success": legacy_success,
            "v2_success": v2_success,
            "mismatches": tuple(mismatches),
        }

    return {
        "shadow_event": "shadow_match",
        "match": True,
        "legacy_shape": legacy_shape,
        "v2_shape": v2_shape,
        "legacy_success": legacy_success,
        "v2_success": v2_success,
    }


def execute_shadow_for_command(command_name: str | None, prompt: str, legacy_result: Any) -> dict[str, object]:
    should_run, reason = should_shadow_command(command_name)
    if not should_run:
        return {
            "shadow_event": "shadow_skipped",
            "match": None,
            "reason": reason,
            "command_name": command_name,
        }
    registry = build_runtime_v2_execution_registry_port()
    command = registry.command(command_name or "")
    if command is None:
        return {
            "shadow_event": "shadow_skipped",
            "match": None,
            "reason": "missing_v2_command",
            "command_name": command_name,
        }
    try:
        v2_result = command.execute(prompt)
    except Exception as exc:  # pragma: no cover - exercised via control-layer swallow tests
        return {
            "shadow_event": "shadow_error",
            "match": False,
            "reason": "v2_execution_error",
            "command_name": command_name,
            "error_class": type(exc).__name__,
            "error_kind": normalize_error_kind(
                error_class=type(exc).__name__,
                reason="v2_execution_error",
                message=str(exc),
            ),
            "error": str(exc),
        }
    compared = compare_legacy_vs_v2(legacy_result=legacy_result, v2_result=v2_result)
    compared["command_name"] = command_name
    return compared
