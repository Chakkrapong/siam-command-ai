from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.siam_core.compat import (
    build_command_catalog_port,
    build_execution_registry_port,
    build_runtime_port,
    build_session_port,
    build_subsystem_catalog_port,
    build_tool_catalog_port,
    runtime_v2_partial_command_allowlist,
    runtime_v2_partial_enabled,
    runtime_v2_guardrail_max_exception_rate,
    runtime_v2_guardrail_max_fallback_rate,
    runtime_v2_guardrail_max_validation_fail_rate,
    runtime_v2_guardrail_min_sample_size,
    runtime_v2_rollout_percent,
    runtime_v2_shadow_command_allowlist,
    runtime_v2_shadow_enabled,
    runtime_v2_enabled,
)


class SiamCoreCompatFlagTests(unittest.TestCase):
    def test_runtime_v2_flag_defaults_false(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(runtime_v2_enabled())

    def test_runtime_v2_flag_true_switches_ports(self) -> None:
        with patch.dict(os.environ, {"USE_RUNTIME_V2": "1"}, clear=True):
            self.assertTrue(runtime_v2_enabled())
            self.assertIn("RuntimeV2", type(build_runtime_port()).__name__)
            self.assertIn("RuntimeV2", type(build_command_catalog_port()).__name__)
            self.assertIn("RuntimeV2", type(build_tool_catalog_port()).__name__)
            self.assertIn("RuntimeV2", type(build_session_port()).__name__)
            self.assertIn("RuntimeV2", type(build_execution_registry_port()).__name__)
            self.assertIn("RuntimeV2", type(build_subsystem_catalog_port()).__name__)

    def test_runtime_v2_flag_false_uses_compat_ports(self) -> None:
        with patch.dict(os.environ, {"USE_RUNTIME_V2": "0"}, clear=True):
            self.assertFalse(runtime_v2_enabled())
            self.assertIn("ClawCompat", type(build_runtime_port()).__name__)
            self.assertIn("ClawCompat", type(build_command_catalog_port()).__name__)
            self.assertIn("ClawCompat", type(build_tool_catalog_port()).__name__)
            self.assertIn("ClawCompat", type(build_session_port()).__name__)
            self.assertIn("ClawCompat", type(build_execution_registry_port()).__name__)
            self.assertIn("ClawCompat", type(build_subsystem_catalog_port()).__name__)

    def test_runtime_v2_shadow_defaults_false_with_read_only_allowlist(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(runtime_v2_shadow_enabled())
        self.assertIn("review", tuple(name.lower() for name in runtime_v2_shadow_command_allowlist()))

    def test_runtime_v2_partial_defaults_false_with_narrow_allowlist(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(runtime_v2_partial_enabled())
            self.assertEqual(runtime_v2_rollout_percent(), 0)
            self.assertEqual(runtime_v2_guardrail_min_sample_size(), 50)
            self.assertEqual(runtime_v2_guardrail_max_fallback_rate(), 0.05)
            self.assertEqual(runtime_v2_guardrail_max_validation_fail_rate(), 0.02)
            self.assertEqual(runtime_v2_guardrail_max_exception_rate(), 0.02)
        lowered = tuple(name.lower() for name in runtime_v2_partial_command_allowlist())
        self.assertIn("review", lowered)
        self.assertIn("ultrareviewoveragedialog", lowered)


if __name__ == "__main__":
    unittest.main()
