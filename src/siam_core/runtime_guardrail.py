from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeV2Stats:
    attempt_count: int = 0
    fallback_count: int = 0
    validation_fail_count: int = 0
    exception_count: int = 0


@dataclass(frozen=True)
class GuardrailThresholds:
    min_sample_size: int = 50
    max_fallback_rate: float = 0.05
    max_validation_fail_rate: float = 0.02
    max_exception_rate: float = 0.02


@dataclass(frozen=True)
class GuardrailStatus:
    auto_disabled: bool
    reason: str
    sample_size: int
    fallback_rate: float
    validation_fail_rate: float
    exception_rate: float


def evaluate_v2_guardrail(stats: RuntimeV2Stats, thresholds: GuardrailThresholds) -> GuardrailStatus:
    sample = max(0, stats.attempt_count)
    fallback_rate = _ratio(stats.fallback_count, sample)
    validation_fail_rate = _ratio(stats.validation_fail_count, sample)
    exception_rate = _ratio(stats.exception_count, sample)

    if sample < thresholds.min_sample_size:
        return GuardrailStatus(
            auto_disabled=False,
            reason="insufficient_sample",
            sample_size=sample,
            fallback_rate=fallback_rate,
            validation_fail_rate=validation_fail_rate,
            exception_rate=exception_rate,
        )
    if fallback_rate > thresholds.max_fallback_rate:
        return GuardrailStatus(
            auto_disabled=True,
            reason="fallback_rate_exceeded",
            sample_size=sample,
            fallback_rate=fallback_rate,
            validation_fail_rate=validation_fail_rate,
            exception_rate=exception_rate,
        )
    if validation_fail_rate > thresholds.max_validation_fail_rate:
        return GuardrailStatus(
            auto_disabled=True,
            reason="validation_fail_rate_exceeded",
            sample_size=sample,
            fallback_rate=fallback_rate,
            validation_fail_rate=validation_fail_rate,
            exception_rate=exception_rate,
        )
    if exception_rate > thresholds.max_exception_rate:
        return GuardrailStatus(
            auto_disabled=True,
            reason="exception_rate_exceeded",
            sample_size=sample,
            fallback_rate=fallback_rate,
            validation_fail_rate=validation_fail_rate,
            exception_rate=exception_rate,
        )
    return GuardrailStatus(
        auto_disabled=False,
        reason="healthy",
        sample_size=sample,
        fallback_rate=fallback_rate,
        validation_fail_rate=validation_fail_rate,
        exception_rate=exception_rate,
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)
