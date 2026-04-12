from __future__ import annotations

import os
from dataclasses import dataclass

from ..commands import get_commands
from ..execution_registry import build_execution_registry
from ..models import PermissionDenial
from ..port_manifest import build_port_manifest
from ..query_engine import QueryEnginePort
from ..runtime import PortRuntime
from .interfaces import (
    CatalogItem,
    CommandCatalogPort,
    ExecutionRegistryPort,
    RouteCandidate,
    RuntimeRoutePort,
    SessionPort,
    SessionTurnReceipt,
    SubsystemCatalogPort,
    ToolCatalogPort,
)
from .runtime_v2 import (
    build_runtime_v2_command_catalog_port,
    build_runtime_v2_execution_registry_port,
    build_runtime_v2_port,
    build_runtime_v2_session_port,
    build_runtime_v2_subsystem_catalog_port,
    build_runtime_v2_tool_catalog_port,
)

USE_RUNTIME_V2_SHADOW = False
USE_RUNTIME_V2_PARTIAL = False
RUNTIME_V2_ROLLOUT_PERCENT = 0
RUNTIME_V2_GUARDRAIL_MIN_SAMPLE_SIZE = 50
RUNTIME_V2_GUARDRAIL_MAX_FALLBACK_RATE = 0.05
RUNTIME_V2_GUARDRAIL_MAX_VALIDATION_FAIL_RATE = 0.02
RUNTIME_V2_GUARDRAIL_MAX_EXCEPTION_RATE = 0.02
RUNTIME_V2_SHADOW_COMMAND_ALLOWLIST: tuple[str, ...] = (
    "review",
    "ultrareviewoveragedialog",
)
RUNTIME_V2_PARTIAL_COMMAND_ALLOWLIST: tuple[str, ...] = (
    "review",
    "ultrareviewoveragedialog",
)


@dataclass(frozen=True)
class ClawCompatRuntimePort(RuntimeRoutePort):
    runtime: PortRuntime

    def route_prompt(self, prompt: str, limit: int = 5) -> tuple[RouteCandidate, ...]:
        return tuple(
            RouteCandidate(
                kind=match.kind,
                name=match.name,
                score=match.score,
                source_hint=match.source_hint,
            )
            for match in self.runtime.route_prompt(prompt, limit=limit)
        )


@dataclass(frozen=True)
class ClawCompatCommandCatalogPort(CommandCatalogPort):
    def list_items(self) -> tuple[CatalogItem, ...]:
        return tuple(
            CatalogItem(
                name=item.name,
                description=item.responsibility,
                source_path=item.source_hint,
                owner="Claw Core",
            )
            for item in get_commands()
        )

    def list_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.list_items())


@dataclass(frozen=True)
class ClawCompatToolCatalogPort(ToolCatalogPort):
    def list_items(self) -> tuple[CatalogItem, ...]:
        from ..tools import get_tools

        return tuple(
            CatalogItem(
                name=item.name,
                description=item.responsibility,
                source_path=item.source_hint,
                owner="Claw Core",
            )
            for item in get_tools()
        )

    def list_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.list_items())

    def list_allowed_names(self, whitelist: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {name.lower() for name in whitelist}
        return tuple(name for name in self.list_names() if name.lower() in allowed)


class ClawCompatSessionPort(SessionPort):
    def __init__(self) -> None:
        self._engine = QueryEnginePort.from_workspace()

    @property
    def session_id(self) -> str:
        return self._engine.session_id

    def submit_message(
        self,
        prompt: str,
        matched_commands: tuple[str, ...] = (),
        matched_tools: tuple[str, ...] = (),
        denied_tools: tuple[PermissionDenial, ...] = (),
    ) -> SessionTurnReceipt:
        result = self._engine.submit_message(
            prompt=prompt,
            matched_commands=matched_commands,
            matched_tools=matched_tools,
            denied_tools=denied_tools,
        )
        return SessionTurnReceipt(stop_reason=result.stop_reason)

    def turn_count(self) -> int:
        return len(self._engine.mutable_messages)

    def usage_totals(self) -> tuple[int, int]:
        return (self._engine.total_usage.input_tokens, self._engine.total_usage.output_tokens)


class ClawCompatExecutionRegistryPort(ExecutionRegistryPort):
    def __init__(self) -> None:
        self._registry = build_execution_registry()

    def command(self, name: str):
        return self._registry.command(name)

    def tool(self, name: str):
        return self._registry.tool(name)


@dataclass(frozen=True)
class ClawCompatSubsystemCatalogPort(SubsystemCatalogPort):
    def list_subsystems(self) -> tuple[dict[str, str], ...]:
        manifest = build_port_manifest()
        return tuple(
            {
                "name": item.name,
                "owner": "Claw Core",
                "role": item.notes,
                "path": item.path,
                "status": "active",
            }
            for item in manifest.top_level_modules
        )


def build_runtime_port() -> RuntimeRoutePort:
    if runtime_v2_enabled():
        return build_runtime_v2_port()
    return ClawCompatRuntimePort(runtime=PortRuntime())


def build_command_catalog_port() -> CommandCatalogPort:
    if runtime_v2_enabled():
        return build_runtime_v2_command_catalog_port()
    return ClawCompatCommandCatalogPort()


def build_tool_catalog_port() -> ToolCatalogPort:
    if runtime_v2_enabled():
        return build_runtime_v2_tool_catalog_port()
    return ClawCompatToolCatalogPort()


def build_session_port() -> SessionPort:
    if runtime_v2_enabled():
        return build_runtime_v2_session_port()
    return ClawCompatSessionPort()


def build_execution_registry_port() -> ExecutionRegistryPort:
    if runtime_v2_enabled():
        return build_runtime_v2_execution_registry_port()
    return ClawCompatExecutionRegistryPort()


def build_subsystem_catalog_port() -> SubsystemCatalogPort:
    if runtime_v2_enabled():
        return build_runtime_v2_subsystem_catalog_port()
    return ClawCompatSubsystemCatalogPort()


def runtime_v2_enabled() -> bool:
    raw = os.environ.get("USE_RUNTIME_V2", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def runtime_v2_shadow_enabled() -> bool:
    raw = os.environ.get("USE_RUNTIME_V2_SHADOW", str(USE_RUNTIME_V2_SHADOW))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def runtime_v2_shadow_command_allowlist() -> tuple[str, ...]:
    return RUNTIME_V2_SHADOW_COMMAND_ALLOWLIST


def runtime_v2_partial_enabled() -> bool:
    raw = os.environ.get("USE_RUNTIME_V2_PARTIAL", str(USE_RUNTIME_V2_PARTIAL))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def runtime_v2_partial_command_allowlist() -> tuple[str, ...]:
    return RUNTIME_V2_PARTIAL_COMMAND_ALLOWLIST


def runtime_v2_rollout_percent() -> int:
    raw = os.environ.get("RUNTIME_V2_ROLLOUT_PERCENT", str(RUNTIME_V2_ROLLOUT_PERCENT))
    try:
        value = int(raw.strip())
    except ValueError:
        value = RUNTIME_V2_ROLLOUT_PERCENT
    return max(0, min(100, value))


def runtime_v2_guardrail_min_sample_size() -> int:
    raw = os.environ.get("RUNTIME_V2_GUARDRAIL_MIN_SAMPLE_SIZE", str(RUNTIME_V2_GUARDRAIL_MIN_SAMPLE_SIZE))
    try:
        value = int(raw.strip())
    except ValueError:
        value = RUNTIME_V2_GUARDRAIL_MIN_SAMPLE_SIZE
    return max(1, value)


def runtime_v2_guardrail_max_fallback_rate() -> float:
    raw = os.environ.get("RUNTIME_V2_GUARDRAIL_MAX_FALLBACK_RATE", str(RUNTIME_V2_GUARDRAIL_MAX_FALLBACK_RATE))
    try:
        value = float(raw.strip())
    except ValueError:
        value = RUNTIME_V2_GUARDRAIL_MAX_FALLBACK_RATE
    return max(0.0, min(1.0, value))


def runtime_v2_guardrail_max_validation_fail_rate() -> float:
    raw = os.environ.get(
        "RUNTIME_V2_GUARDRAIL_MAX_VALIDATION_FAIL_RATE",
        str(RUNTIME_V2_GUARDRAIL_MAX_VALIDATION_FAIL_RATE),
    )
    try:
        value = float(raw.strip())
    except ValueError:
        value = RUNTIME_V2_GUARDRAIL_MAX_VALIDATION_FAIL_RATE
    return max(0.0, min(1.0, value))


def runtime_v2_guardrail_max_exception_rate() -> float:
    raw = os.environ.get(
        "RUNTIME_V2_GUARDRAIL_MAX_EXCEPTION_RATE",
        str(RUNTIME_V2_GUARDRAIL_MAX_EXCEPTION_RATE),
    )
    try:
        value = float(raw.strip())
    except ValueError:
        value = RUNTIME_V2_GUARDRAIL_MAX_EXCEPTION_RATE
    return max(0.0, min(1.0, value))
