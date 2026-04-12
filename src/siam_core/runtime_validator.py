from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime_shadow import compare_legacy_vs_v2


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason: str
    details: dict[str, object]


def validate_v2_contract(v2_result: Any, legacy_result: Any) -> ValidationResult:
    compared = compare_legacy_vs_v2(legacy_result=legacy_result, v2_result=v2_result)
    passed = compared.get("shadow_event") == "shadow_match"
    return ValidationResult(
        passed=passed,
        reason="contract_passed" if passed else "contract_failed",
        details=compared,
    )
