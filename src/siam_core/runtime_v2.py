from __future__ import annotations

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


@dataclass(frozen=True)
class RuntimeV2RoutePort(RuntimeRoutePort):
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
class RuntimeV2CommandCatalogPort(CommandCatalogPort):
    def list_items(self) -> tuple[CatalogItem, ...]:
        return tuple(
            CatalogItem(
                name=item.name,
                description=item.responsibility,
                source_path=item.source_hint,
                owner="Siam Runtime V2",
            )
            for item in get_commands()
        )

    def list_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.list_items())


@dataclass(frozen=True)
class RuntimeV2ToolCatalogPort(ToolCatalogPort):
    def list_items(self) -> tuple[CatalogItem, ...]:
        from ..tools import get_tools

        return tuple(
            CatalogItem(
                name=item.name,
                description=item.responsibility,
                source_path=item.source_hint,
                owner="Siam Runtime V2",
            )
            for item in get_tools()
        )

    def list_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.list_items())

    def list_allowed_names(self, whitelist: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {name.lower() for name in whitelist}
        return tuple(name for name in self.list_names() if name.lower() in allowed)


class RuntimeV2SessionPort(SessionPort):
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


class RuntimeV2ExecutionRegistryPort(ExecutionRegistryPort):
    def __init__(self) -> None:
        self._registry = build_execution_registry()

    def command(self, name: str):
        return self._registry.command(name)

    def tool(self, name: str):
        return self._registry.tool(name)


@dataclass(frozen=True)
class RuntimeV2SubsystemCatalogPort(SubsystemCatalogPort):
    def list_subsystems(self) -> tuple[dict[str, str], ...]:
        manifest = build_port_manifest()
        return tuple(
            {
                "name": item.name,
                "owner": "Siam Runtime V2",
                "role": item.notes,
                "path": item.path,
                "status": "active",
            }
            for item in manifest.top_level_modules
        )


def build_runtime_v2_port() -> RuntimeRoutePort:
    return RuntimeV2RoutePort(runtime=PortRuntime())


def build_runtime_v2_command_catalog_port() -> CommandCatalogPort:
    return RuntimeV2CommandCatalogPort()


def build_runtime_v2_tool_catalog_port() -> ToolCatalogPort:
    return RuntimeV2ToolCatalogPort()


def build_runtime_v2_session_port() -> SessionPort:
    return RuntimeV2SessionPort()


def build_runtime_v2_execution_registry_port() -> ExecutionRegistryPort:
    return RuntimeV2ExecutionRegistryPort()


def build_runtime_v2_subsystem_catalog_port() -> SubsystemCatalogPort:
    return RuntimeV2SubsystemCatalogPort()

