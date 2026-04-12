from __future__ import annotations

import unittest

from src.siam_core.runtime_guardrail import GuardrailThresholds, RuntimeV2Stats, evaluate_v2_guardrail


class SiamRuntimeGuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = GuardrailThresholds(
            min_sample_size=50,
            max_fallback_rate=0.05,
            max_validation_fail_rate=0.02,
            max_exception_rate=0.02,
        )

    def test_insufficient_sample_not_auto_disabled(self) -> None:
        status = evaluate_v2_guardrail(RuntimeV2Stats(attempt_count=10), self.thresholds)
        self.assertFalse(status.auto_disabled)
        self.assertEqual(status.reason, "insufficient_sample")

    def test_healthy_sample_not_auto_disabled(self) -> None:
        status = evaluate_v2_guardrail(
            RuntimeV2Stats(attempt_count=100, fallback_count=1, validation_fail_count=1, exception_count=1),
            self.thresholds,
        )
        self.assertFalse(status.auto_disabled)
        self.assertEqual(status.reason, "healthy")

    def test_high_fallback_rate_auto_disabled(self) -> None:
        status = evaluate_v2_guardrail(
            RuntimeV2Stats(attempt_count=100, fallback_count=10, validation_fail_count=0, exception_count=0),
            self.thresholds,
        )
        self.assertTrue(status.auto_disabled)
        self.assertEqual(status.reason, "fallback_rate_exceeded")

    def test_high_validation_fail_rate_auto_disabled(self) -> None:
        status = evaluate_v2_guardrail(
            RuntimeV2Stats(attempt_count=100, fallback_count=1, validation_fail_count=10, exception_count=0),
            self.thresholds,
        )
        self.assertTrue(status.auto_disabled)
        self.assertEqual(status.reason, "validation_fail_rate_exceeded")

    def test_high_exception_rate_auto_disabled(self) -> None:
        status = evaluate_v2_guardrail(
            RuntimeV2Stats(attempt_count=100, fallback_count=1, validation_fail_count=1, exception_count=10),
            self.thresholds,
        )
        self.assertTrue(status.auto_disabled)
        self.assertEqual(status.reason, "exception_rate_exceeded")


if __name__ == "__main__":
    unittest.main()
