from __future__ import annotations

import unittest
from unittest.mock import patch

from src.siam_core.runtime_shadow import execute_shadow_for_command, should_shadow_command


class _FakeExecutable:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute(self, payload: str) -> object:
        if self._error is not None:
            raise self._error
        return self._result


class _FakeRegistry:
    def __init__(self, executable: _FakeExecutable | None) -> None:
        self._executable = executable

    def command(self, name: str):
        return self._executable


class SiamRuntimeShadowTests(unittest.TestCase):
    def test_should_shadow_command_disabled(self) -> None:
        should_run, reason = should_shadow_command("review", enabled=False, allowlist=("review",))
        self.assertFalse(should_run)
        self.assertEqual(reason, "disabled")

    def test_should_shadow_command_non_safe_skips(self) -> None:
        should_run, reason = should_shadow_command("delete", enabled=True, allowlist=("review",))
        self.assertFalse(should_run)
        self.assertEqual(reason, "command_not_allowlisted")

    def test_shadow_safe_command_executes_and_returns_match_event(self) -> None:
        with patch(
            "src.siam_core.runtime_shadow.build_runtime_v2_execution_registry_port",
            return_value=_FakeRegistry(_FakeExecutable("legacy-result")),
        ), patch(
            "src.siam_core.runtime_shadow.runtime_v2_shadow_enabled",
            return_value=True,
        ), patch(
            "src.siam_core.runtime_shadow.runtime_v2_shadow_command_allowlist",
            return_value=("review",),
        ):
            meta = execute_shadow_for_command("review", "prompt", "legacy-result")
        self.assertEqual(meta["shadow_event"], "shadow_match")
        self.assertEqual(meta["command_name"], "review")
        self.assertTrue(meta["match"])

    def test_shadow_non_safe_command_returns_explicit_skip(self) -> None:
        with patch(
            "src.siam_core.runtime_shadow.runtime_v2_shadow_enabled",
            return_value=True,
        ), patch(
            "src.siam_core.runtime_shadow.runtime_v2_shadow_command_allowlist",
            return_value=("review",),
        ):
            meta = execute_shadow_for_command("logout", "prompt", "legacy-result")
        self.assertEqual(meta["shadow_event"], "shadow_skipped")
        self.assertEqual(meta["reason"], "command_not_allowlisted")

    def test_shadow_exception_is_captured_as_error(self) -> None:
        with patch(
            "src.siam_core.runtime_shadow.build_runtime_v2_execution_registry_port",
            return_value=_FakeRegistry(_FakeExecutable(error=RuntimeError("boom"))),
        ), patch(
            "src.siam_core.runtime_shadow.runtime_v2_shadow_enabled",
            return_value=True,
        ), patch(
            "src.siam_core.runtime_shadow.runtime_v2_shadow_command_allowlist",
            return_value=("review",),
        ):
            meta = execute_shadow_for_command("review", "prompt", "legacy-result")
        self.assertEqual(meta["shadow_event"], "shadow_error")
        self.assertEqual(meta["reason"], "v2_execution_error")
        self.assertEqual(meta["error_class"], "RuntimeError")
        self.assertEqual(meta["error_kind"], "runtime_exception")


if __name__ == "__main__":
    unittest.main()
