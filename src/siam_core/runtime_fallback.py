from __future__ import annotations


def classify_v2_exception(exc: Exception) -> str:
    name = type(exc).__name__
    lowered = name.lower()
    if "timeout" in lowered:
        return "v2_timeout"
    if "permission" in lowered:
        return "v2_permission_error"
    return "v2_execution_error"


def build_fallback_meta(
    *,
    attempted_runtime: str,
    served_runtime: str,
    fallback_reason: str,
    validation_passed: bool | None,
    validation_reason: str | None,
) -> dict[str, object]:
    return {
        "attempted_runtime": attempted_runtime,
        "served_runtime": served_runtime,
        "fallback": served_runtime != attempted_runtime,
        "fallback_reason": fallback_reason,
        "validation_passed": validation_passed,
        "validation_reason": validation_reason,
    }
