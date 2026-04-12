from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal

from .compat import (
    runtime_v2_partial_command_allowlist,
    runtime_v2_partial_enabled,
    runtime_v2_rollout_percent,
    runtime_v2_shadow_command_allowlist,
    runtime_v2_shadow_enabled,
)
from .runtime_bucket import stable_bucket
from .runtime_guardrail import GuardrailStatus
from .runtime_risk import RuntimeRiskAssessment

DEFAULT_FORCE_LEGACY_ROUTES: set[str] = set()
DEFAULT_SKIP_SHADOW_ROUTES: set[str] = set()
DEFAULT_CONSERVATIVE_ROUTES: set[str] = {"review"}
PROMOTION_STATES: tuple[str, ...] = (
    "legacy_only",
    "shadow_only",
    "sampled_v2",
    "partial_v2",
    "full_v2",
)
PromotionState = Literal["legacy_only", "shadow_only", "sampled_v2", "partial_v2", "full_v2"]
SUPPORTED_ENV_KEYS: tuple[str, ...] = (
    "RUNTIME_V2_ENABLED",
    "RUNTIME_V2_DEFAULT_ROUTE_SPLIT",
    "RUNTIME_V2_ROUTE_SPLIT",
    "RUNTIME_V2_SELECTIVE_SHADOW_ENABLED",
    "RUNTIME_V2_DEFAULT_SHADOW_SPLIT",
    "RUNTIME_V2_SHADOW_ROUTE_SPLIT",
    "RUNTIME_V2_SHADOW_ONLY_HIGH_VALUE",
    "RUNTIME_V2_HIGH_VALUE_ROUTES",
    "RUNTIME_V2_FORCE_LEGACY_ROUTES",
    "RUNTIME_V2_FORCE_V2_ROUTES",
    "RUNTIME_V2_SKIP_SHADOW_ROUTES",
    "RUNTIME_V2_DEFAULT_STATE",
    "RUNTIME_V2_ROUTE_FAMILY_MAP",
    "RUNTIME_V2_FAMILY_STATE",
    "RUNTIME_V2_ROUTE_OVERRIDE",
    "RUNTIME_V2_ROLLBACK_STATE",
    "RUNTIME_V2_ROLLBACK_ACTIVE",
    "RUNTIME_V2_CONSERVATIVE_ROUTES",
    "RUNTIME_V2_CONSERVATIVE_STATE",
    # Backward-compatible legacy keys (still accepted)
    "RUNTIME_V2_PROMOTION_DEFAULT",
    "RUNTIME_V2_ROUTE_FAMILY",
    "RUNTIME_V2_PROMOTION_FAMILY_STATES",
    "RUNTIME_V2_PROMOTION_ROUTE_OVERRIDES",
)


@dataclass(frozen=True)
class PromotionGovernance:
    default_state: PromotionState
    route_family_map: dict[str, str]
    family_states: dict[str, PromotionState]
    route_overrides: dict[str, PromotionState]
    rollback_state: PromotionState | None
    rollback_active: bool
    conservative_routes: set[str]
    conservative_state: PromotionState


@dataclass(frozen=True)
class Phase4RuntimeConfig:
    runtime_v2_enabled: bool
    default_route_split: int
    route_split: dict[str, int]
    shadow_enabled: bool
    default_shadow_split: int
    shadow_route_split: dict[str, int]
    shadow_only_high_value: bool
    force_legacy_routes: set[str]
    force_v2_routes: set[str]
    skip_shadow_routes: set[str]
    high_value_routes: set[str]
    governance: PromotionGovernance


@dataclass(frozen=True)
class RoutingDecision:
    primary_runtime: str
    run_shadow: bool
    reason: str
    route_name: str
    sampled: bool
    forced: bool
    guard_blocked: bool
    guard_reason: str | None
    shadow_reason: str
    route_split_percent: int
    shadow_split_percent: int
    route_bucket: int
    shadow_bucket: int
    promotion_state: PromotionState
    route_family: str
    governance_source: str
    downgraded: bool
    downgrade_reason: str | None
    rollback_state: PromotionState | None


def phase4_runtime_config() -> Phase4RuntimeConfig:
    default_split = _read_int("RUNTIME_V2_DEFAULT_ROUTE_SPLIT", runtime_v2_rollout_percent())
    default_shadow_split = _read_int("RUNTIME_V2_DEFAULT_SHADOW_SPLIT", 100)
    high_value_defaults = {name.lower() for name in runtime_v2_shadow_command_allowlist()}
    high_value_routes = _read_route_set("RUNTIME_V2_HIGH_VALUE_ROUTES", fallback=high_value_defaults)
    force_legacy_routes = _read_csv_set("RUNTIME_V2_FORCE_LEGACY_ROUTES", fallback=DEFAULT_FORCE_LEGACY_ROUTES)
    force_v2_routes = _read_csv_set("RUNTIME_V2_FORCE_V2_ROUTES")
    if force_v2_routes and force_legacy_routes:
        force_v2_routes = {name for name in force_v2_routes if name not in force_legacy_routes}
    default_governance = _read_promotion_state_with_alias(
        keys=("RUNTIME_V2_DEFAULT_STATE", "RUNTIME_V2_PROMOTION_DEFAULT"),
        fallback="legacy_only",
    )
    route_family_map = _read_route_family_map_with_alias(
        keys=("RUNTIME_V2_ROUTE_FAMILY_MAP", "RUNTIME_V2_ROUTE_FAMILY")
    )
    family_states = _read_promotion_state_map_with_alias(
        keys=("RUNTIME_V2_FAMILY_STATE", "RUNTIME_V2_PROMOTION_FAMILY_STATES")
    )
    route_overrides = _read_promotion_state_map_with_alias(
        keys=("RUNTIME_V2_ROUTE_OVERRIDE", "RUNTIME_V2_PROMOTION_ROUTE_OVERRIDES")
    )
    rollback_state = _read_optional_promotion_state("RUNTIME_V2_ROLLBACK_STATE")
    rollback_active = _read_bool("RUNTIME_V2_ROLLBACK_ACTIVE", False)
    conservative_routes = _read_route_set("RUNTIME_V2_CONSERVATIVE_ROUTES", fallback=DEFAULT_CONSERVATIVE_ROUTES)
    # Hard guarantee: review-family commands must always stay conservative unless code changes explicitly.
    conservative_routes = set(DEFAULT_CONSERVATIVE_ROUTES).union(conservative_routes)
    governance = PromotionGovernance(
        default_state=default_governance,
        route_family_map=route_family_map,
        family_states=family_states,
        route_overrides=route_overrides,
        rollback_state=rollback_state,
        rollback_active=rollback_active,
        conservative_routes=conservative_routes,
        conservative_state=_read_promotion_state("RUNTIME_V2_CONSERVATIVE_STATE", "shadow_only"),
    )
    return Phase4RuntimeConfig(
        runtime_v2_enabled=_read_bool("RUNTIME_V2_ENABLED", runtime_v2_partial_enabled()),
        default_route_split=max(0, min(100, default_split)),
        route_split=_read_split_map("RUNTIME_V2_ROUTE_SPLIT"),
        shadow_enabled=_read_bool("RUNTIME_V2_SELECTIVE_SHADOW_ENABLED", runtime_v2_shadow_enabled()),
        default_shadow_split=max(0, min(100, default_shadow_split)),
        shadow_route_split=_read_split_map("RUNTIME_V2_SHADOW_ROUTE_SPLIT"),
        shadow_only_high_value=_read_bool("RUNTIME_V2_SHADOW_ONLY_HIGH_VALUE", True),
        force_legacy_routes=force_legacy_routes,
        force_v2_routes=force_v2_routes,
        skip_shadow_routes=_read_route_set("RUNTIME_V2_SKIP_SHADOW_ROUTES", fallback=DEFAULT_SKIP_SHADOW_ROUTES),
        high_value_routes=high_value_routes,
        governance=governance,
    )


def resolve_route_name(*, selected_command: str | None, selected_tool: str | None) -> str:
    if selected_command:
        return selected_command.strip().lower()
    if selected_tool:
        return selected_tool.strip().lower()
    return "none"


def compute_routing_decision(
    *,
    route_name: str,
    request_id: str,
    config: Phase4RuntimeConfig,
    risk_assessment: RuntimeRiskAssessment,
    guardrail_status: GuardrailStatus,
) -> RoutingDecision:
    route_name = _normalize_route(route_name)
    route_family, promotion_state, governance_source = _resolve_promotion_state(route_name=route_name, governance=config.governance)
    route_split = _split_for_route(config.route_split, route_name, config.default_route_split)
    shadow_split = _split_for_route(config.shadow_route_split, route_name, config.default_shadow_split)
    sampled, route_bucket = _sample_route(route_name=route_name, request_id=request_id, split_percent=route_split)
    shadow_sampled, shadow_bucket = _sample_route(
        route_name=f"shadow:{route_name}",
        request_id=request_id,
        split_percent=shadow_split,
    )

    guard_blocked, guard_reason = apply_v2_guard(
        risk_assessment=risk_assessment,
        guardrail_status=guardrail_status,
    )
    downgraded = False
    downgrade_reason: str | None = None
    effective_state = promotion_state
    if promotion_state in {"sampled_v2", "partial_v2", "full_v2"} and guardrail_status.auto_disabled:
        effective_state = "shadow_only"
        downgraded = True
        downgrade_reason = "guardrail_auto_downgrade"
        guard_blocked = True
        guard_reason = "auto_disabled_due_to_guardrail"
    forced = False
    primary_runtime = "legacy"
    reason = "partial_disabled"
    if route_name in config.force_legacy_routes:
        forced = True
        reason = "force_legacy_route"
    elif route_name in config.force_v2_routes:
        forced = True
        if guard_blocked:
            reason = guard_reason or "guard_blocked"
        elif not config.runtime_v2_enabled:
            reason = "partial_disabled"
        else:
            primary_runtime = "v2"
            reason = "force_v2_route"
    elif not config.runtime_v2_enabled:
        reason = "partial_disabled"
    elif effective_state == "legacy_only":
        reason = "promotion_legacy_only"
    elif effective_state == "shadow_only":
        if downgraded and guard_reason:
            reason = guard_reason
        else:
            reason = "promotion_shadow_only"
    elif effective_state == "sampled_v2":
        if guard_blocked:
            reason = guard_reason or "guard_blocked"
        elif sampled:
            primary_runtime = "v2"
            reason = "allowlisted_partial_route"
        else:
            reason = "not_in_rollout_bucket"
    elif effective_state == "partial_v2":
        if guard_blocked:
            reason = guard_reason or "guard_blocked"
        else:
            primary_runtime = "v2"
            reason = "promotion_partial_v2"
            forced = governance_source in {"route_override", "rollback"}
    elif effective_state == "full_v2":
        if guard_blocked:
            reason = guard_reason or "guard_blocked"
        else:
            primary_runtime = "v2"
            reason = "promotion_full_v2"
            forced = True
    else:
        reason = "partial_disabled"

    run_shadow, shadow_reason = apply_shadow_guard(
        route_name=route_name,
        primary_runtime=primary_runtime,
        sampled=shadow_sampled,
        config=config,
        promotion_state=effective_state,
    )
    return RoutingDecision(
        primary_runtime=primary_runtime,
        run_shadow=run_shadow,
        reason=reason,
        route_name=route_name,
        sampled=sampled,
        forced=forced,
        guard_blocked=guard_blocked,
        guard_reason=guard_reason,
        shadow_reason=shadow_reason,
        route_split_percent=route_split,
        shadow_split_percent=shadow_split,
        route_bucket=route_bucket,
        shadow_bucket=shadow_bucket,
        promotion_state=effective_state,
        route_family=route_family,
        governance_source=governance_source,
        downgraded=downgraded,
        downgrade_reason=downgrade_reason,
        rollback_state=config.governance.rollback_state,
    )


def apply_v2_guard(
    *,
    risk_assessment: RuntimeRiskAssessment,
    guardrail_status: GuardrailStatus,
) -> tuple[bool, str | None]:
    if not risk_assessment.eligible_for_v2:
        return True, risk_assessment.risk_reason
    if guardrail_status.auto_disabled:
        return True, "auto_disabled_due_to_guardrail"
    return False, None


def apply_shadow_guard(
    *,
    route_name: str,
    primary_runtime: str,
    sampled: bool,
    config: Phase4RuntimeConfig,
    promotion_state: PromotionState,
) -> tuple[bool, str]:
    if not config.shadow_enabled:
        return False, "disabled"
    if promotion_state == "legacy_only":
        return False, "promotion_legacy_only"
    if primary_runtime == "v2":
        return False, "primary_is_v2"
    if route_name in config.skip_shadow_routes:
        return False, "skip_shadow_route"
    if config.shadow_only_high_value and route_name not in config.high_value_routes:
        return False, "command_not_allowlisted"
    if not sampled:
        return False, "not_in_shadow_bucket"
    return True, "eligible"


def compact_execution_report(
    *,
    decision: RoutingDecision,
    shadow_event: str | None,
    shadow_meta: dict[str, object] | None,
    runtime_guardrail: dict[str, object],
    runtime_execution: dict[str, object],
) -> dict[str, object]:
    shadow_payload = shadow_meta or {}
    return {
        "route": decision.route_name,
        "primary_runtime": runtime_execution.get("served_runtime", decision.primary_runtime),
        "routing_reason": decision.reason,
        "shadow": {
            "run": decision.run_shadow,
            "event": shadow_event,
            "reason": decision.shadow_reason if shadow_event == "shadow_skipped" else shadow_payload.get("reason"),
            "match": shadow_payload.get("match"),
            "error_kind": shadow_payload.get("error_kind") or shadow_payload.get("v2_error_kind"),
            "error_kind_match": shadow_payload.get("error_kind_match"),
        },
        "guard": {
            "blocked": decision.guard_blocked,
            "reason": decision.guard_reason,
            "status": runtime_guardrail.get("reason"),
        },
        "governance": {
            "promotion_state": decision.promotion_state,
            "route_family": decision.route_family,
            "state_source": decision.governance_source,
            "downgraded": decision.downgraded,
            "downgrade_reason": decision.downgrade_reason,
            "rollback_state": decision.rollback_state,
        },
    }


def _sample_route(*, route_name: str, request_id: str, split_percent: int) -> tuple[bool, int]:
    bounded = max(0, min(100, split_percent))
    bucket = stable_bucket(f"{route_name}:{request_id}")
    if bounded <= 0:
        return False, bucket
    if bounded >= 100:
        return True, bucket
    return bucket < bounded, bucket


def _split_for_route(route_split: dict[str, int], route_name: str, default_split: int) -> int:
    value = route_split.get(route_name, default_split)
    return max(0, min(100, int(value)))


def _read_bool(key: str, fallback: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return bool(fallback)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(key: str, fallback: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return int(fallback)
    try:
        return int(raw.strip())
    except ValueError:
        return int(fallback)


def _read_csv_set(key: str, *, fallback: set[str] | None = None) -> set[str]:
    raw = os.environ.get(key)
    if raw is None:
        return set(fallback or ())
    values = [item.strip().lower() for item in raw.split(",")]
    return {item for item in values if item}


def _read_split_map(key: str) -> dict[str, int]:
    raw = os.environ.get(key)
    if not raw:
        return {}
    stripped = raw.strip()
    parsed: dict[str, int] = {}
    try:
        loaded = json.loads(stripped)
        if isinstance(loaded, dict):
            for route_name, value in loaded.items():
                parsed[_normalize_route(route_name)] = _safe_percent(value)
            return parsed
    except json.JSONDecodeError:
        pass
    for segment in stripped.split(","):
        if ":" not in segment:
            continue
        route_name, percent = segment.split(":", 1)
        parsed[_normalize_route(route_name)] = _safe_percent(percent)
    return parsed


def _normalize_route(route_name: object) -> str:
    return str(route_name).strip().lower()


def _safe_percent(raw: object) -> int:
    try:
        text = str(raw).strip()
        if "." in text:
            numeric = float(text)
            if 0.0 <= numeric <= 1.0:
                value = int(round(numeric * 100))
            else:
                value = int(round(numeric))
        else:
            value = int(text)
    except ValueError:
        value = 0
    return max(0, min(100, value))


def _read_promotion_state(key: str, fallback: str) -> PromotionState:
    raw = os.environ.get(key)
    if raw is None:
        return _normalize_promotion_state(fallback)
    return _normalize_promotion_state(raw)


def _read_promotion_state_with_alias(*, keys: tuple[str, ...], fallback: str) -> PromotionState:
    for key in keys:
        raw = os.environ.get(key)
        if raw is not None and raw.strip():
            return _normalize_promotion_state(raw)
    return _normalize_promotion_state(fallback)


def _read_optional_promotion_state(key: str) -> PromotionState | None:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return None
    return _normalize_promotion_state(raw)


def _read_promotion_state_map(key: str) -> dict[str, PromotionState]:
    parsed = _read_map_raw(key)
    out: dict[str, PromotionState] = {}
    for item_key, value in parsed.items():
        out[_normalize_route(item_key)] = _normalize_promotion_state(str(value))
    return out


def _read_promotion_state_map_with_alias(*, keys: tuple[str, ...]) -> dict[str, PromotionState]:
    for key in keys:
        raw = os.environ.get(key)
        if raw and raw.strip():
            return _read_promotion_state_map(key)
    return {}


def _read_route_family_map(key: str) -> dict[str, str]:
    parsed = _read_map_raw(key)
    out: dict[str, str] = {}
    for route_name, family_name in parsed.items():
        out[_normalize_route(route_name)] = _normalize_route(family_name)
    return out


def _read_route_family_map_with_alias(*, keys: tuple[str, ...]) -> dict[str, str]:
    for key in keys:
        raw = os.environ.get(key)
        if raw and raw.strip():
            return _read_route_family_map(key)
    return {}


def _read_map_raw(key: str) -> dict[str, object]:
    raw = os.environ.get(key)
    if not raw:
        return {}
    stripped = raw.strip()
    try:
        loaded = json.loads(stripped)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass
    parsed: dict[str, object] = {}
    for segment in stripped.split(","):
        if ":" not in segment:
            continue
        map_key, map_value = segment.split(":", 1)
        parsed[map_key.strip()] = map_value.strip()
    return parsed


def _read_route_set(key: str, *, fallback: set[str] | None = None) -> set[str]:
    raw = os.environ.get(key)
    if raw is None:
        return set(fallback or ())
    stripped = raw.strip()
    if not stripped:
        return set()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        values = [_normalize_route(item) for item in parsed]
        return {item for item in values if item}
    if isinstance(parsed, str):
        normalized = _normalize_route(parsed)
        return {normalized} if normalized else set()
    if isinstance(parsed, dict):
        values = [_normalize_route(item) for item in parsed.keys()]
        return {item for item in values if item}
    values = [_normalize_route(item) for item in stripped.split(",")]
    return {item for item in values if item}


def _normalize_promotion_state(raw: str) -> PromotionState:
    lowered = str(raw).strip().lower()
    if lowered in PROMOTION_STATES:
        return lowered  # type: ignore[return-value]
    return "legacy_only"


def _resolve_promotion_state(*, route_name: str, governance: PromotionGovernance) -> tuple[str, PromotionState, str]:
    route_family = governance.route_family_map.get(route_name, "default")
    if governance.rollback_active and governance.rollback_state is not None:
        return route_family, governance.rollback_state, "rollback"
    if route_name in governance.route_overrides:
        return route_family, governance.route_overrides[route_name], "route_override"
    if route_name in governance.conservative_routes:
        return route_family, governance.conservative_state, "conservative_default"
    if route_family in governance.family_states:
        return route_family, governance.family_states[route_family], "family_policy"
    return route_family, governance.default_state, "default_policy"


def governance_validator_output(
    *,
    config: Phase4RuntimeConfig,
    routes: tuple[str, ...],
    request_id: str,
    risk_assessment: RuntimeRiskAssessment,
    guardrail_status: GuardrailStatus,
) -> dict[str, object]:
    effective: dict[str, object] = {}
    for route in routes:
        decision = compute_routing_decision(
            route_name=route,
            request_id=request_id,
            config=config,
            risk_assessment=risk_assessment,
            guardrail_status=guardrail_status,
        )
        effective[_normalize_route(route)] = {
            "promotion_state": decision.promotion_state,
            "route_family": decision.route_family,
            "governance_source": decision.governance_source,
            "primary_runtime": decision.primary_runtime,
            "sampled": decision.sampled,
            "route_split_percent": decision.route_split_percent,
        }
    return {
        "parsed_env_keys_used": [key for key in SUPPORTED_ENV_KEYS if os.environ.get(key) is not None],
        "rollback": {
            "available_state": config.governance.rollback_state,
            "active": config.governance.rollback_active and config.governance.rollback_state is not None,
        },
        "effective_governance": effective,
    }


def dashboard_instance_validation(process_count: int) -> dict[str, object]:
    count = max(0, int(process_count))
    if count == 1:
        reason = "ok"
    elif count == 0:
        reason = "no_dashboard_instance_detected"
    else:
        reason = "multiple_dashboard_instances_detected"
    return {
        "dashboard_process_count": count,
        "single_instance_required": True,
        "ok": count == 1,
        "reason": reason,
    }
