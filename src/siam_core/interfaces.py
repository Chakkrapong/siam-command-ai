from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import PermissionDenial


@dataclass(frozen=True)
class CatalogItem:
    name: str
    description: str
    source_path: str
    owner: str


@dataclass(frozen=True)
class RouteCandidate:
    kind: str
    name: str
    score: int
    source_hint: str


@dataclass(frozen=True)
class SessionTurnReceipt:
    stop_reason: str


class RuntimeRoutePort(Protocol):
    def route_prompt(self, prompt: str, limit: int = 5) -> tuple[RouteCandidate, ...]:
        ...


class CommandCatalogPort(Protocol):
    def list_items(self) -> tuple[CatalogItem, ...]:
        ...

    def list_names(self) -> tuple[str, ...]:
        ...


class ToolCatalogPort(Protocol):
    def list_items(self) -> tuple[CatalogItem, ...]:
        ...

    def list_names(self) -> tuple[str, ...]:
        ...

    def list_allowed_names(self, whitelist: tuple[str, ...]) -> tuple[str, ...]:
        ...


class SessionPort(Protocol):
    @property
    def session_id(self) -> str:
        ...

    def submit_message(
        self,
        prompt: str,
        matched_commands: tuple[str, ...] = (),
        matched_tools: tuple[str, ...] = (),
        denied_tools: tuple[PermissionDenial, ...] = (),
    ) -> SessionTurnReceipt:
        ...

    def turn_count(self) -> int:
        ...

    def usage_totals(self) -> tuple[int, int]:
        ...


class ExecutablePort(Protocol):
    def execute(self, payload: str) -> str:
        ...


class ExecutionRegistryPort(Protocol):
    def command(self, name: str) -> ExecutablePort | None:
        ...

    def tool(self, name: str) -> ExecutablePort | None:
        ...


class SubsystemCatalogPort(Protocol):
    def list_subsystems(self) -> tuple[dict[str, str], ...]:
        ...
