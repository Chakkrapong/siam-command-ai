from __future__ import annotations

import unittest

from src.siam_core.runtime_risk import RuntimeRiskContext, assess_runtime_risk


class SiamRuntimeRiskTests(unittest.TestCase):
    def test_normal_readonly_allowlisted_request_is_eligible(self) -> None:
        result = assess_runtime_risk(
            RuntimeRiskContext(
                command_name="review",
                allowlisted_commands={"review"},
                prompt="review prompt",
                payload="ok",
            )
        )
        self.assertEqual(result.risk_level, "low")
        self.assertTrue(result.eligible_for_v2)

    def test_streaming_request_is_blocked(self) -> None:
        result = assess_runtime_risk(
            RuntimeRiskContext(
                command_name="review",
                allowlisted_commands={"review"},
                prompt="please stream this response",
                payload={"stream": True},
            )
        )
        self.assertEqual(result.risk_level, "high")
        self.assertFalse(result.eligible_for_v2)
        self.assertEqual(result.risk_reason, "risk_blocked_streaming_not_supported")

    def test_binary_payload_request_is_blocked(self) -> None:
        result = assess_runtime_risk(
            RuntimeRiskContext(
                command_name="review",
                allowlisted_commands={"review"},
                prompt="review prompt",
                payload=b"\x00\x01",
            )
        )
        self.assertEqual(result.risk_level, "high")
        self.assertFalse(result.eligible_for_v2)
        self.assertEqual(result.risk_reason, "risk_blocked_binary_payload")

    def test_oversized_payload_is_conservatively_blocked(self) -> None:
        result = assess_runtime_risk(
            RuntimeRiskContext(
                command_name="review",
                allowlisted_commands={"review"},
                prompt="review prompt",
                payload="x" * 5000,
                max_payload_chars=4096,
            )
        )
        self.assertEqual(result.risk_level, "high")
        self.assertFalse(result.eligible_for_v2)
        self.assertEqual(result.risk_reason, "risk_blocked_oversized_payload")

    def test_abnormal_request_shape_is_blocked(self) -> None:
        result = assess_runtime_risk(
            RuntimeRiskContext(
                command_name="review",
                allowlisted_commands={"review"},
                prompt="review prompt",
                payload=["unexpected", "shape"],
            )
        )
        self.assertEqual(result.risk_level, "high")
        self.assertFalse(result.eligible_for_v2)
        self.assertEqual(result.risk_reason, "risk_blocked_unsupported_shape")


if __name__ == "__main__":
    unittest.main()
