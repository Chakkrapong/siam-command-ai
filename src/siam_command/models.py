from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol


OverrideMode = Literal["normal", "block_all_tools", "allow_only"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SubsystemModel:
    name: str
    owner: str
    role: str
    path: str
    status: str


@dataclass(frozen=True)
class RouteDecisionModel:
    prompt: str
    selected_command: str | None
    selected_tool: str | None
    candidate_commands: tuple[str, ...]
    candidate_tools: tuple[str, ...]
    blocked_commands: tuple[str, ...]
    blocked_tools: tuple[str, ...]
    reason: str
    policy_name: str
    decided_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionLogModel:
    execution_id: str
    timestamp: str
    prompt: str
    selected_command: str | None
    selected_tool: str | None
    command_message: str | None
    tool_message: str | None
    stop_reason: str
    blocked: bool
    policy_name: str
    session_id: str
    runtime_v2_route_event: str | None = None
    runtime_v2_route_meta: dict[str, object] | None = None
    shadow_event: str | None = None
    shadow_meta: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SessionSummaryModel:
    session_id: str
    turn_count: int
    total_input_tokens: int
    total_output_tokens: int
    last_stop_reason: str | None
    latest_route: RouteDecisionModel | None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if self.latest_route is not None:
            payload["latest_route"] = self.latest_route.to_dict()
        return payload


@dataclass(frozen=True)
class HealthStatusModel:
    mode: str
    policy_name: str
    command_count: int
    tool_count: int
    allowed_tool_count: int
    subsystem_count: int
    override_mode: OverrideMode
    last_execution_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ManualOverrideModel:
    mode: OverrideMode = "normal"
    allow_commands: tuple[str, ...] = ()
    block_commands: tuple[str, ...] = ()
    allow_tools: tuple[str, ...] = ()
    block_tools: tuple[str, ...] = ()

    def allows_command(self, command_name: str) -> bool:
        lowered = command_name.lower()
        allow_set = {name.lower() for name in self.allow_commands}
        block_set = {name.lower() for name in self.block_commands}
        if self.mode == "allow_only" and lowered not in allow_set:
            return False
        return lowered not in block_set

    def allows_tool(self, tool_name: str) -> bool:
        lowered = tool_name.lower()
        allow_set = {name.lower() for name in self.allow_tools}
        block_set = {name.lower() for name in self.block_tools}
        if self.mode == "block_all_tools":
            return lowered in allow_set
        if self.mode == "allow_only" and lowered not in allow_set:
            return False
        return lowered not in block_set


class MusicGenAdapterContract(Protocol):
    adapter_name: str
    tool_name: str

    def describe_tool(self) -> str:
        ...

    def mount_subsystem(self) -> SubsystemModel:
        ...
