from __future__ import annotations

import unittest

from src.siam_core.runtime_fallback import build_fallback_meta, classify_v2_exception


class SiamRuntimeFallbackTests(unittest.TestCase):
    def test_exception_classification_is_stable(self) -> None:
        reason = classify_v2_exception(RuntimeError("boom"))
        self.assertEqual(reason, "v2_execution_error")

    def test_fallback_meta_shape_consistent(self) -> None:
        payload = build_fallback_meta(
            attempted_runtime="v2",
            served_runtime="legacy",
            fallback_reason="contract_failed",
            validation_passed=False,
            validation_reason="contract_failed",
        )
        self.assertEqual(payload["attempted_runtime"], "v2")
        self.assertEqual(payload["served_runtime"], "legacy")
        self.assertTrue(payload["fallback"])
        self.assertEqual(payload["fallback_reason"], "contract_failed")
        self.assertFalse(payload["validation_passed"])
        self.assertEqual(payload["validation_reason"], "contract_failed")


if __name__ == "__main__":
    unittest.main()
