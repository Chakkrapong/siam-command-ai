from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.siam_command import ManualOverrideModel, SiamCommandControlLayer
from src.siam_command.models import RouteDecisionModel
from src.siam_core.runtime_guardrail import GuardrailStatus
from src.siam_core.runtime_phase4 import Phase4RuntimeConfig, PromotionGovernance
from src.siam_core.runtime_risk import RuntimeRiskAssessment


class _FakeExecutable:
    def __init__(self, value: str | None = None, error: Exception | None = None) -> None:
        self._value = value
        self._error = error

    def execute(self, payload: str) -> str | None:
        if self._error is not None:
            raise self._error
        return self._value


class _FakeRegistry:
    def __init__(self, executable: _FakeExecutable | None) -> None:
        self._executable = executable

    def command(self, name: str):
        return self._executable


class _ValidationResult:
    def __init__(self, passed: bool, reason: str, details: dict[str, object]) -> None:
        self.passed = passed
        self.reason = reason
        self.details = details


def _healthy_guardrail() -> GuardrailStatus:
    return GuardrailStatus(False, "healthy", 100, 0.0, 0.0, 0.0)


def _disabled_guardrail() -> GuardrailStatus:
    return GuardrailStatus(True, "fallback_rate_exceeded", 100, 0.2, 0.0, 0.0)


def _low_risk() -> RuntimeRiskAssessment:
    return RuntimeRiskAssessment("low", "risk_low_allowlisted_readonly", True)


def _high_risk() -> RuntimeRiskAssessment:
    return RuntimeRiskAssessment("high", "risk_blocked_streaming_not_supported", False)


def _phase4_config(
    *,
    runtime_v2_enabled: bool,
    default_route_split: int,
) -> Phase4RuntimeConfig:
    return Phase4RuntimeConfig(
        runtime_v2_enabled=runtime_v2_enabled,
        default_route_split=default_route_split,
        route_split={},
        shadow_enabled=True,
        default_shadow_split=100,
        shadow_route_split={},
        shadow_only_high_value=True,
        force_legacy_routes=set(),
        force_v2_routes=set(),
        skip_shadow_routes=set(),
        high_value_routes={"review", "ultrareviewoveragedialog"},
        governance=PromotionGovernance(
            default_state="sampled_v2" if runtime_v2_enabled else "shadow_only",
            route_family_map={},
            family_states={},
            route_overrides={},
            rollback_state=None,
            rollback_active=False,
            conservative_routes=set(),
            conservative_state="shadow_only",
        ),
    )


class SiamCommandLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._log_path = str(Path(self._tmpdir.name) / "execution-log.jsonl")
        self._old_log_path = os.environ.get("SIAM_EXECUTION_LOG_JSONL_PATH")
        self._old_persist = os.environ.get("SIAM_PERSIST_EXECUTION_LOGS")
        os.environ["SIAM_EXECUTION_LOG_JSONL_PATH"] = self._log_path
        os.environ["SIAM_PERSIST_EXECUTION_LOGS"] = "1"

    def tearDown(self) -> None:
        if self._old_log_path is None:
            os.environ.pop("SIAM_EXECUTION_LOG_JSONL_PATH", None)
        else:
            os.environ["SIAM_EXECUTION_LOG_JSONL_PATH"] = self._old_log_path
        if self._old_persist is None:
            os.environ.pop("SIAM_PERSIST_EXECUTION_LOGS", None)
        else:
            os.environ["SIAM_PERSIST_EXECUTION_LOGS"] = self._old_persist
        self._tmpdir.cleanup()
        super().tearDown()

    def test_layer_bootstraps_and_reports_health(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        health = layer.health_status()
        self.assertEqual(health.mode, "isolated")
        self.assertGreaterEqual(health.command_count, 100)
        self.assertGreaterEqual(health.tool_count, 50)
        self.assertGreaterEqual(health.allowed_tool_count, 1)

    def test_tool_whitelist_filters_available_tools(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        available = set(name.lower() for name in layer.list_available_tools())
        allowed = set(name.lower() for name in layer.list_allowed_tools())
        self.assertTrue(allowed)
        self.assertTrue(allowed.issubset(available))

    def test_route_policy_and_execution_log(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = layer.apply_route_policy("review MCP tool permissions")
        self.assertEqual(decision.policy_name, "techin-default-v1")
        log = layer.execute_with_control("review MCP tool permissions", payload="fetch")
        self.assertFalse(log.blocked)
        self.assertEqual(len(layer.execution_logs()), 1)
        self.assertIn("session_id", layer.format_latest_session_summary())

    def test_manual_override_can_block_tool_execution(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        layer.set_manual_override(
            ManualOverrideModel(
                mode="block_all_tools",
                allow_commands=("review",),
                allow_tools=(),
            )
        )
        decision = layer.apply_route_policy("review MCP tool permissions")
        self.assertIsNone(decision.selected_tool)

    def test_subsystem_catalog_contains_siam_control(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        names = {item.name for item in layer.list_subsystems()}
        self.assertIn("Siam Command Control Layer", names)
        self.assertIn("Techin Routing Authority", names)

    def test_cli_json_surfaces(self) -> None:
        checks = [
            ("status",),
            ("list-commands",),
            ("list-tools",),
            ("list-subsystems",),
            ("route", "review MCP"),
            ("session",),
            ("control-state",),
        ]
        for args in checks:
            result = subprocess.run(
                [sys.executable, "-m", "src.siam_command.main", "--output", "json", *args],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertIsInstance(payload, (dict, list))

    def test_execution_log_jsonl_persistence(self) -> None:
        log_path = Path(self._log_path)
        before = 0
        if log_path.exists():
            before = len(
                [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.siam_command.main",
                "--output",
                "json",
                "execute",
                "review MCP tool permissions",
                "--payload",
                "fetch resource list",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        response_payload = json.loads(result.stdout)
        self.assertTrue(log_path.exists())
        lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), before)
        self.assertIn("execution_id", response_payload)
        self.assertIn("session_id", response_payload)
        if len(lines) > before:
            payload = json.loads(lines[-1])
            self.assertIn("execution_id", payload)
            self.assertIn("session_id", payload)

    def test_observability_env_log_path_override_is_applied(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        state = layer.log_persistence_state()
        self.assertEqual(state["path"], self._log_path)
        self.assertEqual(state["enabled"], True)

    def test_persistence_disabled_does_not_write_log_file(self) -> None:
        disabled_path = Path(self._tmpdir.name) / "disabled-execution-log.jsonl"
        old_persist = os.environ.get("SIAM_PERSIST_EXECUTION_LOGS")
        old_path = os.environ.get("SIAM_EXECUTION_LOG_JSONL_PATH")
        try:
            os.environ["SIAM_PERSIST_EXECUTION_LOGS"] = "0"
            os.environ["SIAM_EXECUTION_LOG_JSONL_PATH"] = str(disabled_path)
            layer = SiamCommandControlLayer.from_defaults()
            self.assertEqual(layer.log_persistence_state()["enabled"], False)
            layer.execute_with_control("review MCP tool permissions", payload="fetch")
            self.assertFalse(disabled_path.exists())
        finally:
            if old_persist is None:
                os.environ.pop("SIAM_PERSIST_EXECUTION_LOGS", None)
            else:
                os.environ["SIAM_PERSIST_EXECUTION_LOGS"] = old_persist
            if old_path is None:
                os.environ.pop("SIAM_EXECUTION_LOG_JSONL_PATH", None)
            else:
                os.environ["SIAM_EXECUTION_LOG_JSONL_PATH"] = old_path

    def test_shadow_disabled_keeps_legacy_behavior(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.execute_shadow_for_command",
            return_value={"shadow_event": "shadow_skipped", "reason": "disabled", "match": None},
        ), patch.dict("os.environ", {"USE_RUNTIME_V2_SHADOW": "0", "RUNTIME_V2_ROLLOUT_PERCENT": "0"}):
            log = layer.execute_with_control("review prompt")
        self.assertFalse(log.blocked)
        self.assertIsNotNone(log.command_message)
        self.assertEqual(log.shadow_event, "shadow_skipped")
        self.assertEqual((log.shadow_meta or {}).get("reason"), "disabled")
        self.assertEqual(log.runtime_v2_route_event, "legacy_default")
        self.assertEqual(((log.runtime_v2_route_meta or {}).get("runtime_decision") or {}).get("reason"), "partial_disabled")

    def test_shadow_enabled_safe_command_executes_but_returns_legacy(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.execute_shadow_for_command",
            return_value={"shadow_event": "shadow_match", "reason": "eligible", "match": True},
        ) as shadow_mock, patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=False, default_route_split=0),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertTrue(shadow_mock.called)
        self.assertIsNotNone(log.command_message)
        self.assertEqual(log.shadow_event, "shadow_match")
        self.assertTrue((log.shadow_meta or {}).get("match"))

    def test_shadow_exception_is_swallowed(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.execute_shadow_for_command",
            side_effect=RuntimeError("shadow crash"),
        ), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=False, default_route_split=0),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertFalse(log.blocked)
        self.assertIsNotNone(log.command_message)
        self.assertEqual(log.shadow_event, "shadow_error")
        self.assertEqual((log.shadow_meta or {}).get("reason"), "shadow_runtime_exception")

    def test_shadow_enabled_non_safe_command_is_logged_as_skipped(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="logout prompt",
            selected_command="logout",
            selected_tool=None,
            candidate_commands=("logout",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.execute_shadow_for_command",
            return_value={"shadow_event": "shadow_skipped", "reason": "command_not_allowlisted", "match": None},
        ), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=False, default_route_split=0),
        ):
            log = layer.execute_with_control("logout prompt")
        self.assertEqual(log.shadow_event, "shadow_skipped")
        self.assertEqual((log.shadow_meta or {}).get("reason"), "command_not_allowlisted")

    def test_partial_routing_uses_v2_primary_when_contract_passes(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        layer._legacy_execution_registry = _FakeRegistry(_FakeExecutable("legacy"))
        layer._runtime_v2_execution_registry = _FakeRegistry(_FakeExecutable("v2"))
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=True, default_route_split=100),
        ), patch(
            "src.siam_command.control_layer.assess_runtime_risk",
            return_value=_low_risk(),
        ), patch(
            "src.siam_command.control_layer.evaluate_v2_guardrail",
            return_value=_healthy_guardrail(),
        ), patch(
            "src.siam_command.control_layer.validate_v2_contract",
            return_value=_ValidationResult(True, "contract_passed", {"shadow_event": "shadow_match", "match": True}),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertEqual(log.command_message, "v2")
        self.assertEqual(log.runtime_v2_route_event, "routed_v2")
        self.assertEqual((log.runtime_v2_route_meta or {}).get("reason"), "contract_passed")
        self.assertEqual(((log.runtime_v2_route_meta or {}).get("runtime_decision") or {}).get("selected_runtime"), "v2")
        self.assertEqual(((log.runtime_v2_route_meta or {}).get("runtime_execution") or {}).get("served_runtime"), "v2")

    def test_partial_routing_falls_back_when_contract_fails(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        layer._legacy_execution_registry = _FakeRegistry(_FakeExecutable("legacy"))
        layer._runtime_v2_execution_registry = _FakeRegistry(_FakeExecutable("v2"))
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=True, default_route_split=100),
        ), patch(
            "src.siam_command.control_layer.assess_runtime_risk",
            return_value=_low_risk(),
        ), patch(
            "src.siam_command.control_layer.evaluate_v2_guardrail",
            return_value=_healthy_guardrail(),
        ), patch(
            "src.siam_command.control_layer.validate_v2_contract",
            return_value=_ValidationResult(False, "contract_failed", {"shadow_event": "shadow_diff", "match": False}),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertEqual(log.command_message, "legacy")
        self.assertEqual(log.runtime_v2_route_event, "fallback_legacy")
        self.assertEqual((log.runtime_v2_route_meta or {}).get("reason"), "contract_failed")
        self.assertTrue(((log.runtime_v2_route_meta or {}).get("runtime_execution") or {}).get("fallback"))

    def test_partial_routing_falls_back_on_v2_error(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        layer._legacy_execution_registry = _FakeRegistry(_FakeExecutable("legacy"))
        layer._runtime_v2_execution_registry = _FakeRegistry(_FakeExecutable(error=RuntimeError("v2 boom")))
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=True, default_route_split=100),
        ), patch(
            "src.siam_command.control_layer.assess_runtime_risk",
            return_value=_low_risk(),
        ), patch(
            "src.siam_command.control_layer.evaluate_v2_guardrail",
            return_value=_healthy_guardrail(),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertEqual(log.command_message, "legacy")
        self.assertEqual(log.runtime_v2_route_event, "fallback_legacy")
        self.assertEqual((log.runtime_v2_route_meta or {}).get("reason"), "v2_execution_recovered_runtime_exception")
        self.assertEqual((log.runtime_v2_route_meta or {}).get("error_kind"), "runtime_exception")
        self.assertTrue(((log.runtime_v2_route_meta or {}).get("runtime_execution") or {}).get("fallback"))

    def test_review_preflight_blocks_empty_prompt_before_v2_execute(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        layer._legacy_execution_registry = _FakeRegistry(_FakeExecutable("legacy"))
        layer._runtime_v2_execution_registry = _FakeRegistry(_FakeExecutable("v2"))
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=True, default_route_split=100),
        ), patch(
            "src.siam_command.control_layer.assess_runtime_risk",
            return_value=_low_risk(),
        ), patch(
            "src.siam_command.control_layer.evaluate_v2_guardrail",
            return_value=_healthy_guardrail(),
        ):
            log = layer.execute_with_control("")
        self.assertEqual(log.runtime_v2_route_event, "fallback_legacy")
        self.assertEqual((log.runtime_v2_route_meta or {}).get("reason"), "review_preflight_empty_prompt")

    def test_partial_allowlisted_but_not_in_rollout_keeps_legacy_default(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=True, default_route_split=0),
        ), patch(
            "src.siam_command.control_layer.assess_runtime_risk",
            return_value=_low_risk(),
        ), patch(
            "src.siam_command.control_layer.evaluate_v2_guardrail",
            return_value=_healthy_guardrail(),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertEqual(log.runtime_v2_route_event, "legacy_default")
        self.assertEqual(((log.runtime_v2_route_meta or {}).get("runtime_decision") or {}).get("reason"), "not_in_rollout_bucket")

    def test_unhealthy_guardrail_forces_legacy_routing(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=True, default_route_split=100),
        ), patch(
            "src.siam_command.control_layer.assess_runtime_risk",
            return_value=_low_risk(),
        ), patch(
            "src.siam_command.control_layer.evaluate_v2_guardrail",
            return_value=_disabled_guardrail(),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertEqual(log.runtime_v2_route_event, "legacy_default")
        self.assertEqual(((log.runtime_v2_route_meta or {}).get("runtime_decision") or {}).get("reason"), "auto_disabled_due_to_guardrail")
        self.assertTrue(((log.runtime_v2_route_meta or {}).get("runtime_decision") or {}).get("auto_disabled"))

    def test_high_risk_request_forces_legacy_routing(self) -> None:
        layer = SiamCommandControlLayer.from_defaults()
        decision = RouteDecisionModel(
            prompt="review prompt",
            selected_command="review",
            selected_tool=None,
            candidate_commands=("review",),
            candidate_tools=(),
            blocked_commands=(),
            blocked_tools=(),
            reason="test",
            policy_name="techin-default-v1",
        )
        with patch.object(layer, "apply_route_policy", return_value=decision), patch(
            "src.siam_command.control_layer.phase4_runtime_config",
            return_value=_phase4_config(runtime_v2_enabled=True, default_route_split=100),
        ), patch(
            "src.siam_command.control_layer.assess_runtime_risk",
            return_value=_high_risk(),
        ), patch(
            "src.siam_command.control_layer.evaluate_v2_guardrail",
            return_value=_healthy_guardrail(),
        ):
            log = layer.execute_with_control("review prompt")
        self.assertEqual(log.runtime_v2_route_event, "legacy_default")
        self.assertEqual(((log.runtime_v2_route_meta or {}).get("runtime_decision") or {}).get("reason"), "risk_blocked_streaming_not_supported")
        self.assertEqual(((log.runtime_v2_route_meta or {}).get("runtime_decision") or {}).get("risk_level"), "high")


if __name__ == "__main__":
    unittest.main()
