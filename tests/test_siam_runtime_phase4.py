from __future__ import annotations

import unittest
from unittest.mock import patch

from src.siam_core.runtime_guardrail import GuardrailStatus
from src.siam_core.runtime_phase4 import (
    Phase4RuntimeConfig,
    PromotionGovernance,
    compact_execution_report,
    compute_routing_decision,
    dashboard_instance_validation,
    governance_validator_output,
    phase4_runtime_config,
)
from src.siam_core.runtime_risk import RuntimeRiskAssessment


def _governance(*, default_state: str = "sampled_v2") -> PromotionGovernance:
    return PromotionGovernance(
        default_state=default_state,  # type: ignore[arg-type]
        route_family_map={},
        family_states={},
        route_overrides={},
        rollback_state=None,
        rollback_active=False,
        conservative_routes={"review"},
        conservative_state="shadow_only",
    )


def _config(*, enabled: bool, split: int, shadow_enabled: bool = True) -> Phase4RuntimeConfig:
    return Phase4RuntimeConfig(
        runtime_v2_enabled=enabled,
        default_route_split=split,
        route_split={},
        shadow_enabled=shadow_enabled,
        default_shadow_split=100,
        shadow_route_split={},
        shadow_only_high_value=True,
        force_legacy_routes=set(),
        force_v2_routes=set(),
        skip_shadow_routes=set(),
        high_value_routes={"review"},
        governance=_governance(default_state="sampled_v2" if enabled else "legacy_only"),
    )


def _low_risk() -> RuntimeRiskAssessment:
    return RuntimeRiskAssessment("low", "risk_low_allowlisted_readonly", True)


def _high_risk() -> RuntimeRiskAssessment:
    return RuntimeRiskAssessment("high", "risk_blocked_streaming_not_supported", False)


def _guardrail_healthy() -> GuardrailStatus:
    return GuardrailStatus(False, "healthy", 100, 0.0, 0.0, 0.0)


class SiamRuntimePhase4Tests(unittest.TestCase):
    def test_default_config_keeps_review_conservative(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            cfg = phase4_runtime_config()
        self.assertIn("review", cfg.governance.conservative_routes)
        self.assertEqual(cfg.governance.conservative_state, "shadow_only")

    def test_review_conservative_route_is_hard_guaranteed_even_when_env_is_empty(self) -> None:
        with patch.dict("os.environ", {"RUNTIME_V2_CONSERVATIVE_ROUTES": ""}, clear=True):
            cfg = phase4_runtime_config()
        self.assertIn("review", cfg.governance.conservative_routes)

    def test_route_name_is_normalized_lowercase(self) -> None:
        decision = compute_routing_decision(
            route_name="UltrareviewOverageDialog",
            request_id="req-casing",
            config=_config(enabled=True, split=0),
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        self.assertEqual(decision.route_name, "ultrareviewoveragedialog")

    def test_sampling_is_deterministic_by_request_id(self) -> None:
        config = _config(enabled=True, split=10)
        config = Phase4RuntimeConfig(**{**config.__dict__, "governance": _governance(default_state="sampled_v2")})
        first = compute_routing_decision(
            route_name="admin",
            request_id="same-request",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        second = compute_routing_decision(
            route_name="admin",
            request_id="same-request",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        self.assertEqual(first.sampled, second.sampled)
        self.assertEqual(first.primary_runtime, second.primary_runtime)
        self.assertEqual(first.route_bucket, second.route_bucket)

    def test_default_family_route_override_precedence(self) -> None:
        config = _config(enabled=True, split=100)
        config = Phase4RuntimeConfig(
            **{
                **config.__dict__,
                "governance": PromotionGovernance(
                    default_state="legacy_only",
                    route_family_map={"review": "review", "admin": "admin"},
                    family_states={"review": "shadow_only", "admin": "sampled_v2", "default": "legacy_only"},
                    route_overrides={"review": "shadow_only"},
                    rollback_state="legacy_only",
                    rollback_active=False,
                    conservative_routes={"review"},
                    conservative_state="shadow_only",
                ),
                "route_split": {"admin": 5},
            }
        )

        review = compute_routing_decision(
            route_name="review",
            request_id="prec-review",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        admin = compute_routing_decision(
            route_name="admin",
            request_id="prec-admin",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        default = compute_routing_decision(
            route_name="unknown",
            request_id="prec-default",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )

        self.assertEqual(review.promotion_state, "shadow_only")
        self.assertIn(review.governance_source, {"route_override", "conservative_default"})
        self.assertEqual(admin.promotion_state, "sampled_v2")
        self.assertEqual(admin.governance_source, "family_policy")
        self.assertEqual(admin.route_split_percent, 5)
        self.assertEqual(default.promotion_state, "legacy_only")
        self.assertEqual(default.governance_source, "family_policy")

    def test_rollback_state_available_but_inactive_by_default(self) -> None:
        config = _config(enabled=True, split=100)
        config = Phase4RuntimeConfig(
            **{
                **config.__dict__,
                "governance": PromotionGovernance(
                    default_state="sampled_v2",
                    route_family_map={"admin": "admin"},
                    family_states={"admin": "sampled_v2"},
                    route_overrides={},
                    rollback_state="legacy_only",
                    rollback_active=False,
                    conservative_routes=set(),
                    conservative_state="shadow_only",
                ),
            }
        )
        decision = compute_routing_decision(
            route_name="admin",
            request_id="rb-inactive",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        self.assertEqual(decision.promotion_state, "sampled_v2")
        self.assertNotEqual(decision.governance_source, "rollback")

    def test_explicit_rollback_activation_only(self) -> None:
        config = _config(enabled=True, split=100)
        config = Phase4RuntimeConfig(
            **{
                **config.__dict__,
                "governance": PromotionGovernance(
                    default_state="full_v2",
                    route_family_map={"admin": "admin"},
                    family_states={"admin": "full_v2"},
                    route_overrides={"admin": "full_v2"},
                    rollback_state="legacy_only",
                    rollback_active=True,
                    conservative_routes=set(),
                    conservative_state="shadow_only",
                ),
            }
        )
        decision = compute_routing_decision(
            route_name="admin",
            request_id="rb-active",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        self.assertEqual(decision.promotion_state, "legacy_only")
        self.assertEqual(decision.governance_source, "rollback")

    def test_guardrail_downgrade(self) -> None:
        config = _config(enabled=True, split=100)
        config = Phase4RuntimeConfig(
            **{
                **config.__dict__,
                "governance": PromotionGovernance(
                    default_state="full_v2",
                    route_family_map={},
                    family_states={},
                    route_overrides={},
                    rollback_state=None,
                    rollback_active=False,
                    conservative_routes=set(),
                    conservative_state="shadow_only",
                ),
            }
        )
        unhealthy = GuardrailStatus(True, "fallback_rate_exceeded", 100, 0.2, 0.0, 0.0)
        decision = compute_routing_decision(
            route_name="admin",
            request_id="downgrade-1",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=unhealthy,
        )
        self.assertEqual(decision.promotion_state, "shadow_only")
        self.assertTrue(decision.downgraded)
        self.assertEqual(decision.primary_runtime, "legacy")

    def test_conservative_routes_json_array_parsing(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RUNTIME_V2_DEFAULT_STATE": "legacy_only",
                "RUNTIME_V2_CONSERVATIVE_ROUTES": '["review"]',
                "RUNTIME_V2_CONSERVATIVE_STATE": "shadow_only",
            },
            clear=True,
        ):
            cfg = phase4_runtime_config()
        self.assertEqual(cfg.governance.conservative_routes, {"review"})

    def test_target_effective_governance_from_operator_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RUNTIME_V2_ENABLED": "true",
                "RUNTIME_V2_DEFAULT_STATE": "legacy_only",
                "RUNTIME_V2_ROUTE_FAMILY_MAP": '{"review":"review","ultrareviewoveragedialog":"review","logout":"auth","admin":"admin"}',
                "RUNTIME_V2_FAMILY_STATE": '{"review":"shadow_only","admin":"sampled_v2","auth":"legacy_only","default":"legacy_only"}',
                "RUNTIME_V2_ROUTE_OVERRIDE": '{"review":"shadow_only"}',
                "RUNTIME_V2_CONSERVATIVE_ROUTES": '["review"]',
                "RUNTIME_V2_ROUTE_SPLIT": '{"admin":0.05}',
                "RUNTIME_V2_ROLLBACK_STATE": "legacy_only",
                "RUNTIME_V2_ROLLBACK_ACTIVE": "false",
            },
            clear=True,
        ):
            cfg = phase4_runtime_config()
            healthy = _guardrail_healthy()
            risk = _low_risk()
            review = compute_routing_decision(route_name="review", request_id="target-review", config=cfg, risk_assessment=risk, guardrail_status=healthy)
            admin = compute_routing_decision(route_name="admin", request_id="target-admin", config=cfg, risk_assessment=risk, guardrail_status=healthy)
            default = compute_routing_decision(route_name="unknownroute", request_id="target-default", config=cfg, risk_assessment=risk, guardrail_status=healthy)

        self.assertEqual(review.promotion_state, "shadow_only")
        self.assertEqual(admin.promotion_state, "sampled_v2")
        self.assertEqual(admin.route_split_percent, 5)
        self.assertEqual(default.promotion_state, "legacy_only")

    def test_validator_output_contains_expected_fields(self) -> None:
        config = _config(enabled=True, split=100)
        out = governance_validator_output(
            config=config,
            routes=("review", "admin", "unknownroute"),
            request_id="validator-1",
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        self.assertIn("parsed_env_keys_used", out)
        self.assertIn("effective_governance", out)
        self.assertIn("rollback", out)

    def test_dashboard_instance_validation_fails_on_multiple(self) -> None:
        self.assertFalse(dashboard_instance_validation(2)["ok"])
        self.assertEqual(
            dashboard_instance_validation(2)["reason"],
            "multiple_dashboard_instances_detected",
        )

    def test_compact_report_contains_governance(self) -> None:
        config = _config(enabled=True, split=100)
        config = Phase4RuntimeConfig(**{**config.__dict__, "governance": _governance(default_state="sampled_v2")})
        decision = compute_routing_decision(
            route_name="admin",
            request_id="req-4",
            config=config,
            risk_assessment=_low_risk(),
            guardrail_status=_guardrail_healthy(),
        )
        report = compact_execution_report(
            decision=decision,
            shadow_event="shadow_match",
            shadow_meta={"match": True, "reason": "eligible"},
            runtime_guardrail={"reason": "healthy"},
            runtime_execution={"served_runtime": decision.primary_runtime},
        )
        self.assertIn("governance", report)


if __name__ == "__main__":
    unittest.main()
