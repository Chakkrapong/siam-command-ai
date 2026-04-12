from __future__ import annotations

from dataclasses import dataclass

from .runtime_bucket import in_rollout, stable_bucket
from .runtime_guardrail import GuardrailStatus
from .runtime_risk import RuntimeRiskAssessment


@dataclass(frozen=True)
class RuntimeDecision:
    selected_runtime: str
    reason: str
    partial_enabled: bool
    allowlisted: bool
    rollout_bucket: int
    rollout_percent: int
    in_rollout: bool
    risk_level: str
    risk_reason: str
    auto_disabled: bool


def is_partial_v2_eligible(
    command_name: str,
    *,
    partial_enabled: bool,
    allowlisted_commands: set[str],
) -> tuple[bool, str]:
    if not partial_enabled:
        return False, "partial_disabled"
    if command_name.lower() not in allowlisted_commands:
        return False, "command_not_allowlisted"
    return True, "allowlisted_partial_route"


def decide_runtime(
    command_name: str,
    *,
    partial_enabled: bool,
    allowlisted_commands: set[str],
    rollout_percent: int,
    bucket_key: str,
    risk_assessment: RuntimeRiskAssessment,
    guardrail_status: GuardrailStatus,
) -> RuntimeDecision:
    allowlisted = command_name.lower() in allowlisted_commands
    bounded_rollout = max(0, min(100, int(rollout_percent)))
    rollout_bucket = stable_bucket(bucket_key)
    bucket_in_rollout = in_rollout(bucket_key, bounded_rollout)
    eligible, reason = is_partial_v2_eligible(
        command_name,
        partial_enabled=partial_enabled,
        allowlisted_commands=allowlisted_commands,
    )
    if eligible and not bucket_in_rollout:
        return RuntimeDecision(
            selected_runtime="legacy",
            reason="not_in_rollout_bucket",
            partial_enabled=partial_enabled,
            allowlisted=allowlisted,
            rollout_bucket=rollout_bucket,
            rollout_percent=bounded_rollout,
            in_rollout=bucket_in_rollout,
            risk_level=risk_assessment.risk_level,
            risk_reason=risk_assessment.risk_reason,
            auto_disabled=guardrail_status.auto_disabled,
        )
    if eligible and not risk_assessment.eligible_for_v2:
        return RuntimeDecision(
            selected_runtime="legacy",
            reason=risk_assessment.risk_reason,
            partial_enabled=partial_enabled,
            allowlisted=allowlisted,
            rollout_bucket=rollout_bucket,
            rollout_percent=bounded_rollout,
            in_rollout=bucket_in_rollout,
            risk_level=risk_assessment.risk_level,
            risk_reason=risk_assessment.risk_reason,
            auto_disabled=guardrail_status.auto_disabled,
        )
    if eligible and guardrail_status.auto_disabled:
        return RuntimeDecision(
            selected_runtime="legacy",
            reason="auto_disabled_due_to_guardrail",
            partial_enabled=partial_enabled,
            allowlisted=allowlisted,
            rollout_bucket=rollout_bucket,
            rollout_percent=bounded_rollout,
            in_rollout=bucket_in_rollout,
            risk_level=risk_assessment.risk_level,
            risk_reason=risk_assessment.risk_reason,
            auto_disabled=guardrail_status.auto_disabled,
        )
    if eligible and bucket_in_rollout:
        return RuntimeDecision(
            selected_runtime="v2",
            reason=reason,
            partial_enabled=partial_enabled,
            allowlisted=allowlisted,
            rollout_bucket=rollout_bucket,
            rollout_percent=bounded_rollout,
            in_rollout=bucket_in_rollout,
            risk_level=risk_assessment.risk_level,
            risk_reason=risk_assessment.risk_reason,
            auto_disabled=guardrail_status.auto_disabled,
        )
    return RuntimeDecision(
        selected_runtime="legacy",
        reason=reason,
        partial_enabled=partial_enabled,
        allowlisted=allowlisted,
        rollout_bucket=rollout_bucket,
        rollout_percent=bounded_rollout,
        in_rollout=bucket_in_rollout,
        risk_level=risk_assessment.risk_level,
        risk_reason=risk_assessment.risk_reason,
        auto_disabled=guardrail_status.auto_disabled,
    )
