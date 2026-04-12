from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeRiskAssessment:
    risk_level: str
    risk_reason: str
    eligible_for_v2: bool


@dataclass(frozen=True)
class RuntimeRiskContext:
    command_name: str
    allowlisted_commands: set[str]
    prompt: str
    payload: Any
    max_payload_chars: int = 4096


def assess_runtime_risk(ctx: RuntimeRiskContext) -> RuntimeRiskAssessment:
    command = (ctx.command_name or "").strip().lower()
    if not command or command not in ctx.allowlisted_commands:
        return RuntimeRiskAssessment(
            risk_level="high",
            risk_reason="risk_blocked_unknown_command_family",
            eligible_for_v2=False,
        )

    if _is_streaming_request(ctx.prompt, ctx.payload):
        return RuntimeRiskAssessment(
            risk_level="high",
            risk_reason="risk_blocked_streaming_not_supported",
            eligible_for_v2=False,
        )

    if _is_binary_payload(ctx.payload):
        return RuntimeRiskAssessment(
            risk_level="high",
            risk_reason="risk_blocked_binary_payload",
            eligible_for_v2=False,
        )

    if _is_abnormal_shape(ctx.payload):
        return RuntimeRiskAssessment(
            risk_level="high",
            risk_reason="risk_blocked_unsupported_shape",
            eligible_for_v2=False,
        )

    if _is_oversized_payload(ctx.payload, ctx.max_payload_chars):
        return RuntimeRiskAssessment(
            risk_level="high",
            risk_reason="risk_blocked_oversized_payload",
            eligible_for_v2=False,
        )

    return RuntimeRiskAssessment(
        risk_level="low",
        risk_reason="risk_low_allowlisted_readonly",
        eligible_for_v2=True,
    )


def _is_streaming_request(prompt: str, payload: Any) -> bool:
    lowered_prompt = (prompt or "").lower()
    if "stream" in lowered_prompt:
        return True
    if isinstance(payload, dict):
        streaming = payload.get("stream")
        streaming_alt = payload.get("streaming")
        return bool(streaming is True or streaming_alt is True)
    return False


def _is_binary_payload(payload: Any) -> bool:
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return True
    if isinstance(payload, dict):
        payload_type = str(payload.get("type", "")).strip().lower()
        return payload_type in {"binary", "blob", "bytes"}
    return False


def _is_abnormal_shape(payload: Any) -> bool:
    return payload is not None and not isinstance(payload, (str, bytes, bytearray, memoryview, dict))


def _is_oversized_payload(payload: Any, limit: int) -> bool:
    if isinstance(payload, str):
        return len(payload) > limit
    if isinstance(payload, dict):
        serialized = str(payload)
        return len(serialized) > limit
    return False
