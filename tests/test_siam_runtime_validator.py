from __future__ import annotations

import unittest

from src.siam_core.runtime_validator import validate_v2_contract


class SiamRuntimeValidatorTests(unittest.TestCase):
    def test_contract_pass_case(self) -> None:
        result = validate_v2_contract("same", "same")
        self.assertTrue(result.passed)
        self.assertEqual(result.reason, "contract_passed")

    def test_contract_fail_case(self) -> None:
        result = validate_v2_contract("v2", "legacy")
        self.assertFalse(result.passed)
        self.assertEqual(result.reason, "contract_failed")


if __name__ == "__main__":
    unittest.main()
