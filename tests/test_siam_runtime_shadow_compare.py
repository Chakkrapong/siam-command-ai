from __future__ import annotations

import unittest

from src.siam_core.runtime_shadow import compare_legacy_vs_v2


class SiamRuntimeShadowComparatorTests(unittest.TestCase):
    def test_comparator_returns_match_for_equal_payload(self) -> None:
        meta = compare_legacy_vs_v2(
            legacy_result={"status": "ok", "success": True, "message": "done"},
            v2_result={"status": "ok", "success": True, "message": "done"},
        )
        self.assertEqual(meta["shadow_event"], "shadow_match")
        self.assertTrue(meta["match"])

    def test_comparator_returns_diff_for_changed_key_fields(self) -> None:
        meta = compare_legacy_vs_v2(
            legacy_result={"status": "ok", "success": True},
            v2_result={"status": "failed", "success": False},
        )
        self.assertEqual(meta["shadow_event"], "shadow_diff")
        self.assertFalse(meta["match"])
        self.assertIn("key_fields", meta["mismatches"])
        self.assertIn("success_indicator", meta["mismatches"])

    def test_comparator_returns_error_when_v2_errors(self) -> None:
        meta = compare_legacy_vs_v2(
            legacy_result={"status": "ok"},
            v2_error=RuntimeError("shadow failure"),
        )
        self.assertEqual(meta["shadow_event"], "shadow_error")
        self.assertEqual(meta["v2_error_class"], "RuntimeError")
        self.assertEqual(meta["v2_error_kind"], "runtime_exception")

    def test_comparator_classifies_legacy_only_error_as_diff(self) -> None:
        meta = compare_legacy_vs_v2(
            legacy_error=ValueError("legacy failed"),
            v2_result={"status": "ok"},
        )
        self.assertEqual(meta["shadow_event"], "shadow_diff")
        self.assertEqual(meta["reason"], "legacy_error_only")

    def test_comparator_handles_top_level_shape_diff(self) -> None:
        meta = compare_legacy_vs_v2(legacy_result={"status": "ok"}, v2_result="ok")
        self.assertEqual(meta["shadow_event"], "shadow_diff")
        self.assertIn("shape", meta["mismatches"])


if __name__ == "__main__":
    unittest.main()
