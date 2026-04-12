from __future__ import annotations

import unittest

from src.siam_core.runtime_guardrail import GuardrailStatus
from src.siam_core.runtime_policy import decide_runtime
from src.siam_core.runtime_risk import RuntimeRiskAssessment


def _low_risk() -> RuntimeRiskAssessment:
    return RuntimeRiskAssessment("low", "risk_low_allowlisted_readonly", True)


def _high_risk() -> RuntimeRiskAssessment:
    return RuntimeRiskAssessment("high", "risk_blocked_streaming_not_supported", False)


def _healthy_guardrail() -> GuardrailStatus:
    return GuardrailStatus(False, "healthy", 100, 0.0, 0.0, 0.0)


def _disabled_guardrail() -> GuardrailStatus:
    return GuardrailStatus(True, "fallback_rate_exceeded", 100, 0.2, 0.0, 0.0)


class SiamRuntimePolicyTests(unittest.TestCase):
    def test_partial_disabled_routes_legacy(self) -> None:
        decision = decide_runtime(
            "review",
            partial_enabled=False,
            allowlisted_commands={"review"},
            rollout_percent=100,
            bucket_key="session-1",
            risk_assessment=_low_risk(),
            guardrail_status=_healthy_guardrail(),
        )
        self.assertEqual(decision.selected_runtime, "legacy")
        self.assertEqual(decision.reason, "partial_disabled")

    def test_not_allowlisted_routes_legacy(self) -> None:
        decision = decide_runtime(
            "logout",
            partial_enabled=True,
            allowlisted_commands={"review"},
            rollout_percent=100,
            bucket_key="session-1",
            risk_assessment=_low_risk(),
            guardrail_status=_healthy_guardrail(),
        )
        self.assertEqual(decision.selected_runtime, "legacy")
        self.assertEqual(decision.reason, "command_not_allowlisted")

    def test_allowlisted_with_partial_enabled_and_in_rollout_routes_v2(self) -> None:
        decision = decide_runtime(
            "review",
            partial_enabled=True,
            allowlisted_commands={"review"},
            rollout_percent=100,
            bucket_key="session-1",
            risk_assessment=_low_risk(),
            guardrail_status=_healthy_guardrail(),
        )
        self.assertEqual(decision.selected_runtime, "v2")
        self.assertEqual(decision.reason, "allowlisted_partial_route")
        self.assertTrue(decision.in_rollout)

    def test_allowlisted_with_partial_enabled_but_not_in_rollout_routes_legacy(self) -> None:
        decision = decide_runtime(
            "review",
            partial_enabled=True,
            allowlisted_commands={"review"},
            rollout_percent=0,
            bucket_key="session-1",
            risk_assessment=_low_risk(),
            guardrail_status=_healthy_guardrail(),
        )
        self.assertEqual(decision.selected_runtime, "legacy")
        self.assertEqual(decision.reason, "not_in_rollout_bucket")
        self.assertFalse(decision.in_rollout)

    def test_rollout_zero_always_legacy(self) -> None:
        decision = decide_runtime(
            "review",
            partial_enabled=True,
            allowlisted_commands={"review"},
            rollout_percent=0,
            bucket_key="another-session",
            risk_assessment=_low_risk(),
            guardrail_status=_healthy_guardrail(),
        )
        self.assertEqual(decision.selected_runtime, "legacy")
        self.assertEqual(decision.reason, "not_in_rollout_bucket")

    def test_allowlisted_high_risk_routes_legacy(self) -> None:
        decision = decide_runtime(
            "review",
            partial_enabled=True,
            allowlisted_commands={"review"},
            rollout_percent=100,
            bucket_key="session-1",
            risk_assessment=_high_risk(),
            guardrail_status=_healthy_guardrail(),
        )
        self.assertEqual(decision.selected_runtime, "legacy")
        self.assertEqual(decision.reason, "risk_blocked_streaming_not_supported")

    def test_allowlisted_unhealthy_guardrail_routes_legacy(self) -> None:
        decision = decide_runtime(
            "review",
            partial_enabled=True,
            allowlisted_commands={"review"},
            rollout_percent=100,
            bucket_key="session-1",
            risk_assessment=_low_risk(),
            guardrail_status=_disabled_guardrail(),
        )
        self.assertEqual(decision.selected_runtime, "legacy")
        self.assertEqual(decision.reason, "auto_disabled_due_to_guardrail")


if __name__ == "__main__":
    unittest.main()
