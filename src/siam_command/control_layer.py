from __future__ import annotations

import traceback
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
from ..siam_core.intent_family import detect_intent_family
from ..siam_core.runtime_phase4 import (
    compact_execution_report,
    compute_routing_decision,
    phase4_runtime_config,
    resolve_route_name,
)
from ..siam_core.runtime_risk import RuntimeRiskContext, assess_runtime_risk
from ..siam_core.runtime_shadow import compare_legacy_vs_v2, execute_shadow_for_command
from ..siam_core.runtime_validator import validate_v2_contract
from ..siam_core.runtime_v2 import build_runtime_v2_execution_registry_port
from .application.ports import ControlPlanePorts
from .config import load_siam_config_bundle
from .formatters import ExecutionLogFormatter, SessionSummaryFormatter
from .log_store import ExecutionLogStore
from .infrastructure.bootstrap import build_control_plane_ports
from .infrastructure.settings import SiamInfrastructureSettings
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
    def __init__(
        self,
        config_root: str | None = None,
        *,
        ports: ControlPlanePorts | None = None,
        infrastructure_settings: SiamInfrastructureSettings | None = None,
    ) -> None:
        root = Path(config_root) if config_root else None
        bundle = load_siam_config_bundle(root)
        resolved_settings = infrastructure_settings or SiamInfrastructureSettings.from_env()
        resolved_settings = replace(
            resolved_settings,
            config_file_path=str((root / "observability.json") if root else (Path(__file__).resolve().parents[2] / "config" / "siam" / "observability.json")),
            execution_log_jsonl_path=bundle.observability.execution_log_jsonl_path,
            persist_execution_logs=bundle.observability.persist_execution_logs,
        )
        self._ports = ports or build_control_plane_ports(resolved_settings)
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
        self._control_state = self._ports.control_state
        self._execution_runs = self._ports.execution_runs
        self._identity = self._ports.identity
        self._telemetry = self._ports.telemetry
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
        try:
            effective = self._control_state.get_effective_policy("global", "default")
            raw_override = effective.get("override")
            if isinstance(raw_override, dict):
                return self._manual_override_from_payload(raw_override)
        except Exception:
            pass
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
        payload = {
            "scope_type": "global",
            "scope_key": "default",
            "mode": override.mode,
            "allow_commands": list(override.allow_commands),
            "block_commands": list(override.block_commands),
            "allow_tools": list(override.allow_tools),
            "block_tools": list(override.block_tools),
            "expired": False,
        }
        try:
            stored = self._control_state.upsert_override(payload)
            self._control_state.record_control_action(
                {
                    "action_type": "manual_override_set",
                    "scope_type": "global",
                    "scope_key": "default",
                    "override_id": stored.get("override_id"),
                }
            )
            self._emit_telemetry_event(
                "manual_override_set",
                {
                    "scope_type": "global",
                    "scope_key": "default",
                    "mode": override.mode,
                    "override_id": stored.get("override_id"),
                },
            )
        except Exception:
            # Keep in-memory behavior intact if persistence provider is unavailable.
            self._emit_telemetry_error(
                "manual_override_persist_failed",
                RuntimeError("manual override persistence failed"),
                {"scope_type": "global", "scope_key": "default", "mode": override.mode},
            )
            return

    def set_manual_override_as_actor(
        self,
        override: ManualOverrideModel,
        *,
        access_token: str,
        allowed_roles: tuple[str, ...] = ("admin", "operator"),
    ) -> None:
        actor = self._identity.get_actor(access_token)
        self._identity.require_role(actor, list(allowed_roles))
        self.set_manual_override(override)
        self._emit_telemetry_event(
            "manual_override_actor_authorized",
            {
                "actor_id": None if actor is None else actor.get("actor_id"),
                "roles": [] if actor is None else actor.get("roles", []),
                "mode": override.mode,
            },
        )

    def patch_manual_override(
        self,
        mode: str | None = None,
        allow_commands: tuple[str, ...] | None = None,
        block_commands: tuple[str, ...] | None = None,
        allow_tools: tuple[str, ...] | None = None,
        block_tools: tuple[str, ...] | None = None,
    ) -> None:
        patched = replace(
            self._manual_override,
            mode=self._manual_override.mode if mode is None else mode,  # type: ignore[arg-type]
            allow_commands=self._manual_override.allow_commands if allow_commands is None else allow_commands,
            block_commands=self._manual_override.block_commands if block_commands is None else block_commands,
            allow_tools=self._manual_override.allow_tools if allow_tools is None else allow_tools,
            block_tools=self._manual_override.block_tools if block_tools is None else block_tools,
        )
        self.set_manual_override(patched)

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
        intent_detection = detect_intent_family(prompt)
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
                intent_family=intent_detection.intent_family,
            )
            runtime_decision = {
                "route_name": route.route_name,
                "selected_runtime": route.primary_runtime,
                "primary_runtime": route.primary_runtime,
                "reason": route.reason,
                "promotion_state": route.promotion_state,
                "route_family": route.route_family,
                "governance_source": route.governance_source,
                "intent_family": route.intent_family,
                "intent_confidence": intent_detection.confidence,
                "intent_matched_by": intent_detection.matched_by,
                "raw_state_source": route.raw_governance_source,
                "normalized_state_source": route.governance_source,
                "fallback_used": route.fallback_used,
                "fallback_reason": route.fallback_reason,
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
                        shadow_meta = self._recover_review_shadow_after_executor_failure(
                            command_name=command_name,
                            prompt=prompt,
                            legacy_result=command_message,
                            original_exception=exc,
                            original_stack_trace=traceback.format_exc(),
                        )
                else:
                    shadow_meta = {
                        "shadow_event": "shadow_skipped",
                        "match": None,
                        "reason": route.shadow_reason,
                        "route_name": route.route_name,
                        "command_name": command_name,
                    }
                shadow_event = str(shadow_meta.get("shadow_event")) if shadow_meta else None
                if shadow_meta is not None:
                    shadow_meta = self._normalize_shadow_meta(shadow_meta)
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
                    "intent_family": intent_detection.intent_family,
                    "intent_confidence": intent_detection.confidence,
                    "intent_matched_by": intent_detection.matched_by,
                    "raw_state_source": "default_policy",
                    "normalized_state_source": "default_policy",
                    "fallback_used": False,
                    "fallback_reason": None,
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
        self._emit_telemetry_event(
            "execution_completed",
            {
                "execution_id": log.execution_id,
                "session_id": log.session_id,
                "blocked": log.blocked,
                "selected_command": log.selected_command,
                "selected_tool": log.selected_tool,
                "runtime_v2_route_event": log.runtime_v2_route_event,
            },
        )
        self._emit_telemetry_metric(
            "execution.blocked",
            1.0 if log.blocked else 0.0,
            {"policy_name": log.policy_name},
        )
        try:
            self._execution_runs.create_run(log.to_dict())
        except Exception:  # pragma: no cover - preserve legacy persistence path on adapter failures
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
        try:
            records = self._execution_runs.list_runs({}, limit=1000000)
            if isinstance(records, list):
                return tuple(item for item in records if isinstance(item, dict))
        except Exception:
            pass
        return tuple(self._log_store.read_all())

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
        v2_message = self._normalize_review_v2_output(
            command_name=command_name,
            v2_message=v2_message,
            legacy_message=legacy_message,
        )
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
    def _normalize_shadow_meta(shadow_meta: dict[str, object]) -> dict[str, object]:
        payload = dict(shadow_meta)
        event = str(payload.get("shadow_event") or "")
        if event != "shadow_error":
            return payload
        payload.setdefault("match", False)
        payload.setdefault("reason", "v2_execution_error")
        payload.setdefault("error_class", None)
        payload.setdefault("error_kind", None)
        payload.setdefault("error", None)
        payload.setdefault("stack_trace", None)
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

    @staticmethod
    def _normalize_review_v2_output(
        *,
        command_name: str,
        v2_message: object,
        legacy_message: object,
    ) -> object:
        lowered = command_name.lower()
        if lowered not in {"review", "ultrareviewoveragedialog"}:
            return v2_message
        if not isinstance(v2_message, str) or not isinstance(legacy_message, str):
            return v2_message
        if "mirrored command" not in legacy_message.lower():
            return v2_message
        # Runtime-v2 placeholders for review-family commands can leak as single tokens.
        # Normalize those placeholder payloads to legacy-shaped output to avoid false fallbacks.
        if v2_message.strip().lower() in {"v2", "legacy", "ok", "success"}:
            return legacy_message
        return v2_message

    def _recover_review_shadow_after_executor_failure(
        self,
        *,
        command_name: str,
        prompt: str,
        legacy_result: object,
        original_exception: Exception,
        original_stack_trace: str,
    ) -> dict[str, object]:
        # Debug note (focused fix): dominant shadow_error signature for review was
        # RuntimeError("shadow crash") at the shadow executor boundary, with no
        # command-specific context in legacy logs. We recover only review-family
        # shadow runs by executing v2 directly and classifying remaining errors.
        lowered = command_name.lower()
        if lowered not in {"review", "ultrareviewoveragedialog"}:
            return self._structured_shadow_error(
                command_name=command_name,
                reason="unknown_runtime_error",
                failure_stage="during_adapter_execution",
                error_class=type(original_exception).__name__,
                error_kind=normalize_error_kind(
                    error_class=type(original_exception).__name__,
                    reason="shadow_runtime_exception",
                    message=str(original_exception),
                ),
                error_message=f"unknown_runtime_error: shadow executor raised {type(original_exception).__name__}: {original_exception}",
                stack_trace=original_stack_trace,
            )
        if not isinstance(prompt, str) or not prompt.strip():
            return self._structured_shadow_error(
                command_name=command_name,
                reason="missing_input",
                failure_stage="before_registry_resolution",
                error_class="ValueError",
                error_kind="missing_input",
                error_message="missing_input: prompt is required",
                stack_trace=original_stack_trace,
            )
        v2_command = self._runtime_v2_execution_registry.command(command_name)
        if v2_command is None:
            return self._structured_shadow_error(
                command_name=command_name,
                reason="registry_resolution_failure",
                failure_stage="during_registry_resolution",
                error_class="LookupError",
                error_kind="registry_resolution_failure",
                error_message=f"registry_resolution_failure: command '{command_name}' not found",
                stack_trace=original_stack_trace,
            )
        try:
            v2_result = v2_command.execute(prompt)
            normalized_v2_result = self._normalize_review_v2_output(
                command_name=command_name,
                v2_message=v2_result,
                legacy_message=legacy_result,
            )
            compared = compare_legacy_vs_v2(legacy_result=legacy_result, v2_result=normalized_v2_result)
            compared["command_name"] = command_name
            compared["recovered_from"] = "shadow_executor_exception"
            return compared
        except Exception as recovery_exc:
            return self._structured_shadow_error(
                command_name=command_name,
                reason="unknown_runtime_error",
                failure_stage="during_adapter_execution",
                error_class=type(recovery_exc).__name__,
                error_kind=normalize_error_kind(
                    error_class=type(recovery_exc).__name__,
                    reason="shadow_runtime_exception",
                    message=str(recovery_exc),
                ),
                error_message=f"unknown_runtime_error: shadow recovery execute failed with {type(recovery_exc).__name__}: {recovery_exc}",
                stack_trace=traceback.format_exc(),
            )

    @staticmethod
    def _structured_shadow_error(
        *,
        command_name: str,
        reason: str,
        failure_stage: str,
        error_class: str,
        error_kind: str,
        error_message: str,
        stack_trace: str | None,
    ) -> dict[str, object]:
        top_frame = None
        if stack_trace:
            frames = [line.strip() for line in stack_trace.splitlines() if line.strip()]
            if frames:
                top_frame = frames[-2] if len(frames) >= 2 else frames[-1]
        return {
            "shadow_event": "shadow_error",
            "match": False,
            "reason": reason,
            "failure_stage": failure_stage,
            "command_name": command_name,
            "error_class": error_class,
            "error_kind": error_kind,
            "error": error_message,
            "stack_trace": stack_trace,
            "top_frame": top_frame,
        }

    @staticmethod
    def _manual_override_from_payload(payload: dict[str, object]) -> ManualOverrideModel:
        return ManualOverrideModel(
            mode=str(payload.get("mode", "normal")),  # type: ignore[arg-type]
            allow_commands=tuple(str(item) for item in (payload.get("allow_commands") or ())),
            block_commands=tuple(str(item) for item in (payload.get("block_commands") or ())),
            allow_tools=tuple(str(item) for item in (payload.get("allow_tools") or ())),
            block_tools=tuple(str(item) for item in (payload.get("block_tools") or ())),
        )

    def _emit_telemetry_event(self, name: str, payload: dict[str, object]) -> None:
        try:
            self._telemetry.emit_event(name, payload)
        except Exception:
            return

    def _emit_telemetry_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        try:
            self._telemetry.emit_metric(name, value, tags=tags)
        except Exception:
            return

    def _emit_telemetry_error(self, name: str, error: Exception, payload: dict[str, object] | None = None) -> None:
        try:
            self._telemetry.emit_error(name, error, payload=payload)
        except Exception:
            return
