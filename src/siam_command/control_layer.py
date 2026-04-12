from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from ..models import PermissionDenial
from ..siam_core.compat import (
    ClawCompatExecutionRegistryPort,
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
)
from ..siam_core.runtime_fallback import build_fallback_meta, classify_v2_exception
from ..siam_core.runtime_guardrail import (
    GuardrailThresholds,
    GuardrailStatus,
    RuntimeV2Stats,
    evaluate_v2_guardrail,
)
from ..siam_core.runtime_error_kind import normalize_error_kind
from ..siam_core.runtime_phase4 import (
    compact_execution_report,
    compute_routing_decision,
    phase4_runtime_config,
    resolve_route_name,
)
from ..siam_core.runtime_risk import RuntimeRiskContext, assess_runtime_risk
from ..siam_core.runtime_shadow import execute_shadow_for_command
from ..siam_core.runtime_validator import validate_v2_contract
from ..siam_core.runtime_v2 import build_runtime_v2_execution_registry_port
from .config import load_siam_config_bundle
from .formatters import ExecutionLogFormatter, SessionSummaryFormatter
from .log_store import ExecutionLogStore
from .models import (
    ExecutionLogModel,
    HealthStatusModel,
    ManualOverrideModel,
    RouteDecisionModel,
    SessionSummaryModel,
    utc_now_iso,
)
from .policy import SiamRoutingPolicy
from .registry import SiamCommandRegistry, SiamSubsystemRegistry, SiamToolRegistry


class SiamCommandControlLayer:
    def __init__(self, config_root: str | None = None) -> None:
        root = Path(config_root) if config_root else None
        bundle = load_siam_config_bundle(root)
        self._bundle = bundle
        self._runtime = build_runtime_port()
        self._session = build_session_port()
        self._execution_registry = build_execution_registry_port()
        self._legacy_execution_registry = ClawCompatExecutionRegistryPort()
        self._runtime_v2_execution_registry = build_runtime_v2_execution_registry_port()
        self._command_registry = SiamCommandRegistry.from_interface(build_command_catalog_port())
        self._tool_registry = SiamToolRegistry.from_interface(build_tool_catalog_port(), bundle.tool_whitelist)
        self._subsystem_registry = SiamSubsystemRegistry.from_interface(bundle.subsystems, build_subsystem_catalog_port())
        self._routing_policy = SiamRoutingPolicy(bundle.route_policy)
        self._manual_override = bundle.route_policy.default_override
        self._execution_logs: list[ExecutionLogModel] = []
        self._last_route_decision: RouteDecisionModel | None = None
        self._is_isolated = True
        self._runtime_v2_stats = RuntimeV2Stats()
        self._log_store = ExecutionLogStore(
            path=bundle.observability.execution_log_jsonl_path,
            enabled=bundle.observability.persist_execution_logs,
        )

    @classmethod
    def from_defaults(cls) -> "SiamCommandControlLayer":
        return cls()

    def list_available_commands(self) -> tuple[str, ...]:
        return self._command_registry.list_available()

    def list_available_tools(self) -> tuple[str, ...]:
        return self._tool_registry.list_available()

    def list_allowed_tools(self) -> tuple[str, ...]:
        return self._tool_registry.list_allowed()

    def list_subsystems(self):
        return self._subsystem_registry.list_all()

    def manual_override_state(self) -> ManualOverrideModel:
        return self._manual_override

    def policy_name(self) -> str:
        return self._routing_policy.config.policy_name

    def whitelist_state(self) -> tuple[str, ...]:
        return self._tool_registry.allowed_tool_names

    def log_persistence_state(self) -> dict[str, object]:
        return {
            "enabled": self._log_store.enabled,
            "path": str(self._log_store.path),
        }

    def set_manual_override(self, override: ManualOverrideModel) -> None:
        self._manual_override = override

    def patch_manual_override(
        self,
        mode: str | None = None,
        allow_commands: tuple[str, ...] | None = None,
        block_commands: tuple[str, ...] | None = None,
        allow_tools: tuple[str, ...] | None = None,
        block_tools: tuple[str, ...] | None = None,
    ) -> None:
        self._manual_override = replace(
            self._manual_override,
            mode=self._manual_override.mode if mode is None else mode,  # type: ignore[arg-type]
            allow_commands=self._manual_override.allow_commands if allow_commands is None else allow_commands,
            block_commands=self._manual_override.block_commands if block_commands is None else block_commands,
            allow_tools=self._manual_override.allow_tools if allow_tools is None else allow_tools,
            block_tools=self._manual_override.block_tools if block_tools is None else block_tools,
        )

    def apply_route_policy(self, prompt: str) -> RouteDecisionModel:
        matches = self._runtime.route_prompt(prompt, limit=self._routing_policy.config.max_candidates)
        command_candidates = tuple(dict.fromkeys(match.name for match in matches if match.kind == "command"))
        tool_candidates = tuple(dict.fromkeys(match.name for match in matches if match.kind == "tool"))
        allowed_candidates = self._tool_registry.filter_allowed(tool_candidates)
        decision = self._routing_policy.decide(
            prompt=prompt,
            candidate_commands=command_candidates,
            candidate_tools=allowed_candidates,
            manual_override=self._manual_override,
        )
        self._last_route_decision = decision
        return decision

    def execute_with_control(self, prompt: str, payload: str = "") -> ExecutionLogModel:
        decision = self.apply_route_policy(prompt)
        request_id = uuid4().hex
        command_message = None
        tool_message = None
        runtime_v2_route_event = None
        runtime_v2_route_meta: dict[str, object] | None = None
        shadow_meta: dict[str, object] | None = None
        shadow_event: str | None = None
        denied_tools: tuple[PermissionDenial, ...] = ()
        if decision.selected_command:
            route_name = resolve_route_name(selected_command=decision.selected_command, selected_tool=decision.selected_tool)
            phase4_config = phase4_runtime_config()
            command_name = route_name
            allowlisted_commands = {item.lower() for item in runtime_v2_partial_command_allowlist()}
            allowlisted_commands.update(name.lower() for name in phase4_config.route_split.keys())
            allowlisted_commands.update(name.lower() for name in phase4_config.force_v2_routes)
            risk_assessment = assess_runtime_risk(
                RuntimeRiskContext(
                    command_name=command_name,
                    allowlisted_commands=allowlisted_commands,
                    prompt=prompt,
                    payload=payload,
                )
            )
            guardrail_status = evaluate_v2_guardrail(self._runtime_v2_stats, self._guardrail_thresholds())
            route = compute_routing_decision(
                route_name=route_name,
                request_id=request_id,
                config=phase4_config,
                risk_assessment=risk_assessment,
                guardrail_status=guardrail_status,
            )
            runtime_decision = {
                "route_name": route.route_name,
                "selected_runtime": route.primary_runtime,
                "primary_runtime": route.primary_runtime,
                "reason": route.reason,
                "promotion_state": route.promotion_state,
                "route_family": route.route_family,
                "governance_source": route.governance_source,
                "downgraded": route.downgraded,
                "downgrade_reason": route.downgrade_reason,
                "rollback_state": route.rollback_state,
                "partial_enabled": phase4_config.runtime_v2_enabled,
                "allowlisted": command_name in allowlisted_commands,
                "rollout_bucket": route.route_bucket,
                "rollout_percent": route.route_split_percent,
                "in_rollout": route.sampled,
                "sampled": route.sampled,
                "forced": route.forced,
                "guard_blocked": route.guard_blocked,
                "guard_reason": route.guard_reason,
                "risk_level": risk_assessment.risk_level,
                "risk_reason": risk_assessment.risk_reason,
                "auto_disabled": guardrail_status.auto_disabled,
                "shadow_sample_bucket": route.shadow_bucket,
                "shadow_split_percent": route.shadow_split_percent,
            }
            if route.primary_runtime == "v2":
                command_message, runtime_v2_route_event, runtime_v2_route_meta = self._execute_partial_primary_command(
                    command_name=command_name,
                    prompt=prompt,
                    runtime_decision=runtime_decision,
                    runtime_guardrail=self._guardrail_status_to_dict(guardrail_status),
                )
                shadow_meta = {
                    "shadow_event": "shadow_skipped",
                    "match": None,
                    "reason": route.shadow_reason,
                    "route_name": route.route_name,
                    "command_name": command_name,
                }
                shadow_event = "shadow_skipped"
            else:
                command = self._execution_registry.command(command_name)
                if command is not None:
                    command_message = command.execute(prompt)
                runtime_v2_route_event = "legacy_default"
                runtime_v2_route_meta = {
                    "reason": route.reason,
                    "command_name": command_name,
                    "route_name": route.route_name,
                    "runtime_decision": runtime_decision,
                    "runtime_execution": build_fallback_meta(
                        attempted_runtime="legacy",
                        served_runtime="legacy",
                        fallback_reason="not_applicable",
                        validation_passed=None,
                        validation_reason=None,
                    ),
                    "runtime_guardrail": self._guardrail_status_to_dict(guardrail_status),
                }
                if route.run_shadow:
                    try:
                        shadow_meta = execute_shadow_for_command(command_name, prompt, command_message)
                    except Exception as exc:  # pragma: no cover - safety net
                        shadow_meta = {
                            "shadow_event": "shadow_error",
                            "match": False,
                            "reason": "shadow_runtime_exception",
                            "command_name": command_name,
                            "error_class": type(exc).__name__,
                            "error_kind": normalize_error_kind(
                                error_class=type(exc).__name__,
                                reason="shadow_runtime_exception",
                                message=str(exc),
                            ),
                            "error": str(exc),
                        }
                else:
                    shadow_meta = {
                        "shadow_event": "shadow_skipped",
                        "match": None,
                        "reason": route.shadow_reason,
                        "route_name": route.route_name,
                        "command_name": command_name,
                    }
                shadow_event = str(shadow_meta.get("shadow_event")) if shadow_meta else None
            if runtime_v2_route_meta is not None:
                runtime_v2_route_meta["execution_report"] = compact_execution_report(
                    decision=route,
                    shadow_event=shadow_event,
                    shadow_meta=shadow_meta,
                    runtime_guardrail=runtime_v2_route_meta.get("runtime_guardrail", {}),
                    runtime_execution=runtime_v2_route_meta.get("runtime_execution", {}),
                )
        else:
            phase4_config = phase4_runtime_config()
            shadow_meta = execute_shadow_for_command(None, prompt, None)
            shadow_event = str(shadow_meta.get("shadow_event")) if shadow_meta else None
            runtime_v2_route_event = "legacy_default"
            runtime_v2_route_meta = {
                "reason": "no_command_selected",
                "runtime_decision": {
                    "route_name": "none",
                    "selected_runtime": "legacy",
                    "reason": "no_command_selected",
                    "promotion_state": "legacy_only",
                    "route_family": "default",
                    "governance_source": "default_policy",
                    "downgraded": False,
                    "downgrade_reason": None,
                    "rollback_state": None,
                    "partial_enabled": phase4_config.runtime_v2_enabled,
                    "allowlisted": False,
                    "rollout_bucket": -1,
                    "rollout_percent": phase4_config.default_route_split,
                    "in_rollout": False,
                    "risk_level": "high",
                    "risk_reason": "risk_blocked_unsupported_shape",
                    "auto_disabled": False,
                },
                "runtime_execution": build_fallback_meta(
                    attempted_runtime="legacy",
                    served_runtime="legacy",
                    fallback_reason="not_applicable",
                    validation_passed=None,
                    validation_reason=None,
                ),
                "runtime_guardrail": self._guardrail_status_to_dict(
                    evaluate_v2_guardrail(self._runtime_v2_stats, self._guardrail_thresholds())
                ),
            }
        if decision.selected_tool:
            tool = self._execution_registry.tool(decision.selected_tool)
            if tool is not None:
                tool_message = tool.execute(payload or prompt)
        blocked = decision.selected_command is None and decision.selected_tool is None
        if blocked:
            denied_tools = tuple(
                PermissionDenial(tool_name=tool_name, reason="blocked by siam manual override or whitelist")
                for tool_name in decision.blocked_tools
            )
        turn = self._session.submit_message(
            prompt=prompt,
            matched_commands=tuple([decision.selected_command] if decision.selected_command else []),
            matched_tools=tuple([decision.selected_tool] if decision.selected_tool else []),
            denied_tools=denied_tools,
        )
        log = ExecutionLogModel(
            execution_id=request_id,
            timestamp=utc_now_iso(),
            prompt=prompt,
            selected_command=decision.selected_command,
            selected_tool=decision.selected_tool,
            command_message=command_message,
            tool_message=tool_message,
            stop_reason=turn.stop_reason,
            blocked=blocked,
            policy_name=decision.policy_name,
            session_id=self._session.session_id,
            runtime_v2_route_event=runtime_v2_route_event,
            runtime_v2_route_meta=runtime_v2_route_meta,
            shadow_event=shadow_event,
            shadow_meta=shadow_meta,
        )
        self._execution_logs.append(log)
        self._log_store.append(log)
        return log

    def latest_session_summary(self) -> SessionSummaryModel:
        return SessionSummaryModel(
            session_id=self._session.session_id,
            turn_count=self._session.turn_count(),
            total_input_tokens=self._session.usage_totals()[0],
            total_output_tokens=self._session.usage_totals()[1],
            last_stop_reason=self._execution_logs[-1].stop_reason if self._execution_logs else None,
            latest_route=self._last_route_decision,
        )

    def health_status(self) -> HealthStatusModel:
        return HealthStatusModel(
            mode="isolated" if self._is_isolated else "inline",
            policy_name=self._routing_policy.config.policy_name,
            command_count=len(self._command_registry.command_names),
            tool_count=len(self._tool_registry.tool_names),
            allowed_tool_count=len(self._tool_registry.allowed_tool_names),
            subsystem_count=len(self._subsystem_registry.subsystem_items),
            override_mode=self._manual_override.mode,
            last_execution_at=self._execution_logs[-1].timestamp if self._execution_logs else None,
        )

    def execution_logs(self) -> tuple[ExecutionLogModel, ...]:
        return tuple(self._execution_logs)

    def persisted_execution_logs(self) -> tuple[dict[str, object], ...]:
        return self._log_store.read_all()

    def format_execution_logs(self) -> tuple[str, ...]:
        return tuple(ExecutionLogFormatter.to_json_line(item) for item in self._execution_logs)

    def format_latest_session_summary(self) -> str:
        return SessionSummaryFormatter.to_pretty_json(self.latest_session_summary())

    def _execute_partial_primary_command(
        self,
        *,
        command_name: str,
        prompt: str,
        runtime_decision: dict[str, object],
        runtime_guardrail: dict[str, object],
    ) -> tuple[str | None, str, dict[str, object]]:
        self._runtime_v2_stats = RuntimeV2Stats(
            attempt_count=self._runtime_v2_stats.attempt_count + 1,
            fallback_count=self._runtime_v2_stats.fallback_count,
            validation_fail_count=self._runtime_v2_stats.validation_fail_count,
            exception_count=self._runtime_v2_stats.exception_count,
        )
        legacy_command = self._legacy_execution_registry.command(command_name)
        v2_command = self._runtime_v2_execution_registry.command(command_name)
        preflight = self._preflight_v2_command(
            command_name=command_name,
            prompt=prompt,
            legacy_command=legacy_command,
            v2_command=v2_command,
        )
        if not preflight["ok"]:
            self._runtime_v2_stats = RuntimeV2Stats(
                attempt_count=self._runtime_v2_stats.attempt_count,
                fallback_count=self._runtime_v2_stats.fallback_count + 1,
                validation_fail_count=self._runtime_v2_stats.validation_fail_count,
                exception_count=self._runtime_v2_stats.exception_count,
            )
            legacy_result = legacy_command.execute(prompt) if legacy_command is not None else None
            return legacy_result, "fallback_legacy", self._with_runtime_meta(
                runtime_decision=runtime_decision,
                command_name=command_name,
                reason=str(preflight["reason"]),
                runtime_execution=build_fallback_meta(
                    attempted_runtime="v2",
                    served_runtime="legacy",
                    fallback_reason=str(preflight["reason"]),
                    validation_passed=None,
                    validation_reason=None,
                ),
                runtime_guardrail=runtime_guardrail,
                input_contract=self._runtime_input_contract(command_name=command_name, prompt=prompt),
                preflight=preflight,
            )
        if legacy_command is None:
            self._runtime_v2_stats = RuntimeV2Stats(
                attempt_count=self._runtime_v2_stats.attempt_count,
                fallback_count=self._runtime_v2_stats.fallback_count + 1,
                validation_fail_count=self._runtime_v2_stats.validation_fail_count,
                exception_count=self._runtime_v2_stats.exception_count,
            )
            return None, "fallback_legacy", self._with_runtime_meta(
                runtime_decision=runtime_decision,
                command_name=command_name,
                reason="missing_legacy_command",
                runtime_execution=build_fallback_meta(
                    attempted_runtime="v2",
                    served_runtime="legacy",
                    fallback_reason="missing_legacy_command",
                    validation_passed=None,
                    validation_reason=None,
                ),
                runtime_guardrail=runtime_guardrail,
                input_contract=self._runtime_input_contract(command_name=command_name, prompt=prompt),
            )
        if v2_command is None:
            self._runtime_v2_stats = RuntimeV2Stats(
                attempt_count=self._runtime_v2_stats.attempt_count,
                fallback_count=self._runtime_v2_stats.fallback_count + 1,
                validation_fail_count=self._runtime_v2_stats.validation_fail_count,
                exception_count=self._runtime_v2_stats.exception_count,
            )
            return legacy_command.execute(prompt), "fallback_legacy", self._with_runtime_meta(
                runtime_decision=runtime_decision,
                command_name=command_name,
                reason="missing_v2_command",
                runtime_execution=build_fallback_meta(
                    attempted_runtime="v2",
                    served_runtime="legacy",
                    fallback_reason="missing_v2_command",
                    validation_passed=None,
                    validation_reason=None,
                ),
                runtime_guardrail=runtime_guardrail,
                input_contract=self._runtime_input_contract(command_name=command_name, prompt=prompt),
            )
        try:
            v2_message = v2_command.execute(prompt)
        except Exception as exc:
            exception_reason = classify_v2_exception(exc)
            error_kind = normalize_error_kind(
                error_class=type(exc).__name__,
                reason=exception_reason,
                message=str(exc),
            )
            self._runtime_v2_stats = RuntimeV2Stats(
                attempt_count=self._runtime_v2_stats.attempt_count,
                fallback_count=self._runtime_v2_stats.fallback_count + 1,
                validation_fail_count=self._runtime_v2_stats.validation_fail_count,
                exception_count=self._runtime_v2_stats.exception_count + 1,
            )
            # Recover to deterministic legacy fallback to avoid noisy runtime error spikes.
            return legacy_command.execute(prompt), "fallback_legacy", self._with_runtime_meta(
                runtime_decision=runtime_decision,
                command_name=command_name,
                reason=f"v2_execution_recovered_{error_kind}",
                runtime_execution=build_fallback_meta(
                    attempted_runtime="v2",
                    served_runtime="legacy",
                    fallback_reason=f"v2_execution_recovered_{error_kind}",
                    validation_passed=None,
                    validation_reason=None,
                ),
                runtime_guardrail=runtime_guardrail,
                error_class=type(exc).__name__,
                error_kind=error_kind,
                error=str(exc),
                input_contract=self._runtime_input_contract(command_name=command_name, prompt=prompt),
            )

        legacy_message = legacy_command.execute(prompt)
        validation = validate_v2_contract(v2_message, legacy_message)
        if validation.passed:
            return v2_message, "routed_v2", self._with_runtime_meta(
                runtime_decision=runtime_decision,
                command_name=command_name,
                reason=validation.reason,
                runtime_execution=build_fallback_meta(
                    attempted_runtime="v2",
                    served_runtime="v2",
                    fallback_reason="not_applicable",
                    validation_passed=validation.passed,
                    validation_reason=validation.reason,
                ),
                runtime_guardrail=runtime_guardrail,
                comparison=validation.details,
                input_contract=self._runtime_input_contract(command_name=command_name, prompt=prompt),
            )
        self._runtime_v2_stats = RuntimeV2Stats(
            attempt_count=self._runtime_v2_stats.attempt_count,
            fallback_count=self._runtime_v2_stats.fallback_count + 1,
            validation_fail_count=self._runtime_v2_stats.validation_fail_count + 1,
            exception_count=self._runtime_v2_stats.exception_count,
        )
        return legacy_message, "fallback_legacy", self._with_runtime_meta(
            runtime_decision=runtime_decision,
            command_name=command_name,
            reason=validation.reason,
            runtime_execution=build_fallback_meta(
                attempted_runtime="v2",
                served_runtime="legacy",
                fallback_reason=validation.reason,
                validation_passed=validation.passed,
                validation_reason=validation.reason,
            ),
            runtime_guardrail=runtime_guardrail,
            comparison=validation.details,
            input_contract=self._runtime_input_contract(command_name=command_name, prompt=prompt),
        )

    @staticmethod
    def _with_runtime_meta(
        *,
        runtime_decision: dict[str, object],
        runtime_execution: dict[str, object],
        runtime_guardrail: dict[str, object],
        command_name: str,
        reason: str,
        comparison: dict[str, object] | None = None,
        error_class: str | None = None,
        error_kind: str | None = None,
        error: str | None = None,
        input_contract: dict[str, object] | None = None,
        preflight: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "reason": reason,
            "command_name": command_name,
            "runtime_decision": runtime_decision,
            "runtime_execution": runtime_execution,
            "runtime_guardrail": runtime_guardrail,
        }
        if comparison is not None:
            payload["comparison"] = comparison
        if error_class is not None:
            payload["error_class"] = error_class
        if error_kind is not None:
            payload["error_kind"] = error_kind
        if error is not None:
            payload["error"] = error
        if input_contract is not None:
            payload["input_contract"] = input_contract
        if preflight is not None:
            payload["preflight"] = preflight
        return payload

    @staticmethod
    def _runtime_input_contract(*, command_name: str, prompt: str) -> dict[str, object]:
        return {
            "command_name": command_name.lower(),
            "prompt_chars": len(prompt or ""),
            "same_input_for_legacy_and_v2": True,
        }

    @staticmethod
    def _preflight_v2_command(
        *,
        command_name: str,
        prompt: str,
        legacy_command: object | None,
        v2_command: object | None,
    ) -> dict[str, object]:
        lowered = command_name.lower()
        if legacy_command is None:
            return {"ok": False, "reason": "missing_legacy_command"}
        if v2_command is None:
            return {"ok": False, "reason": "missing_v2_command"}
        if not isinstance(prompt, str):
            return {"ok": False, "reason": "review_preflight_invalid_prompt_type"}
        if lowered in {"review", "ultrareviewoveragedialog"}:
            if not prompt.strip():
                return {"ok": False, "reason": "review_preflight_empty_prompt"}
            if len(prompt) > 20000:
                return {"ok": False, "reason": "review_preflight_oversized_prompt"}
        return {"ok": True, "reason": "preflight_passed"}

    @staticmethod
    def _guardrail_status_to_dict(status: GuardrailStatus) -> dict[str, object]:
        return {
            "auto_disabled": status.auto_disabled,
            "reason": status.reason,
            "sample_size": status.sample_size,
            "fallback_rate": status.fallback_rate,
            "validation_fail_rate": status.validation_fail_rate,
            "exception_rate": status.exception_rate,
        }

    @staticmethod
    def _guardrail_thresholds() -> GuardrailThresholds:
        return GuardrailThresholds(
            min_sample_size=runtime_v2_guardrail_min_sample_size(),
            max_fallback_rate=runtime_v2_guardrail_max_fallback_rate(),
            max_validation_fail_rate=runtime_v2_guardrail_max_validation_fail_rate(),
            max_exception_rate=runtime_v2_guardrail_max_exception_rate(),
        )
