from __future__ import annotations

import json

from .models import (
    ExecutionLogModel,
    HealthStatusModel,
    ManualOverrideModel,
    RouteDecisionModel,
    SessionSummaryModel,
    SubsystemModel,
)


class SiamOutputSerializer:
    @staticmethod
    def emit(payload: object, output_mode: str) -> str:
        if output_mode == "json":
            return json.dumps(payload, indent=2, ensure_ascii=True)
        if isinstance(payload, str):
            return payload
        return str(payload)

    @staticmethod
    def status_model(model: HealthStatusModel) -> dict[str, object]:
        return model.to_dict()

    @staticmethod
    def route_model(model: RouteDecisionModel) -> dict[str, object]:
        return model.to_dict()

    @staticmethod
    def execution_log_model(model: ExecutionLogModel) -> dict[str, object]:
        return model.to_dict()

    @staticmethod
    def execution_log_list(models: tuple[ExecutionLogModel, ...]) -> list[dict[str, object]]:
        return [item.to_dict() for item in models]

    @staticmethod
    def session_model(model: SessionSummaryModel) -> dict[str, object]:
        return model.to_dict()

    @staticmethod
    def subsystem_list(models: tuple[SubsystemModel, ...]) -> list[dict[str, object]]:
        return [
            {
                "name": item.name,
                "owner": item.owner,
                "role": item.role,
                "path": item.path,
                "status": item.status,
            }
            for item in models
        ]

    @staticmethod
    def command_inventory(command_names: tuple[str, ...]) -> dict[str, object]:
        return {
            "count": len(command_names),
            "items": list(command_names),
        }

    @staticmethod
    def tool_inventory(available: tuple[str, ...], allowed: tuple[str, ...]) -> dict[str, object]:
        return {
            "available_count": len(available),
            "allowed_count": len(allowed),
            "available": list(available),
            "allowed": list(allowed),
        }

    @staticmethod
    def manual_override(model: ManualOverrideModel) -> dict[str, object]:
        return {
            "mode": model.mode,
            "allow_commands": list(model.allow_commands),
            "block_commands": list(model.block_commands),
            "allow_tools": list(model.allow_tools),
            "block_tools": list(model.block_tools),
        }

    @staticmethod
    def control_state(
        policy_name: str,
        whitelist_tools: tuple[str, ...],
        override: ManualOverrideModel,
        log_persistence_enabled: bool,
        log_path: str,
    ) -> dict[str, object]:
        return {
            "policy_name": policy_name,
            "whitelist_tools": list(whitelist_tools),
            "manual_override": SiamOutputSerializer.manual_override(override),
            "log_persistence": {
                "enabled": log_persistence_enabled,
                "path": log_path,
            },
        }

