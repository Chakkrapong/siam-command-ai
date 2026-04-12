from __future__ import annotations


def normalize_error_kind(
    *,
    error_class: str | None = None,
    reason: str | None = None,
    message: str | None = None,
) -> str:
    lowered_class = (error_class or "").strip().lower()
    lowered_reason = (reason or "").strip().lower()
    lowered_message = (message or "").strip().lower()

    if lowered_reason in {"missing_v2_command", "missing_legacy_command"}:
        return "missing_command"
    if lowered_reason in {"contract_failed", "validation_failed"}:
        return "contract_validation"
    if "permission" in lowered_class or "permission" in lowered_message:
        return "permission"
    if "timeout" in lowered_class or "timeout" in lowered_message:
        return "timeout"
    if "valueerror" in lowered_class or "typeerror" in lowered_class:
        return "input_contract"
    if lowered_reason in {"v2_execution_error", "shadow_runtime_exception", "v2_error"}:
        return "runtime_exception"
    if lowered_class:
        return "runtime_exception"
    if lowered_reason:
        return "other"
    return "none"
