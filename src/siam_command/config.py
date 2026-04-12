from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .models import ManualOverrideModel, SubsystemModel


@dataclass(frozen=True)
class ToolWhitelistConfig:
    allowed_tools: tuple[str, ...]


@dataclass(frozen=True)
class RouteKeywordRule:
    contains: tuple[str, ...]
    prefer_commands: tuple[str, ...]
    prefer_tools: tuple[str, ...]


@dataclass(frozen=True)
class RoutePolicyConfig:
    policy_name: str
    max_candidates: int
    kind_priority: tuple[str, ...]
    default_command_fallback: str
    keyword_rules: tuple[RouteKeywordRule, ...]
    default_override: ManualOverrideModel


@dataclass(frozen=True)
class SubsystemsConfig:
    items: tuple[SubsystemModel, ...]


@dataclass(frozen=True)
class SiamConfigBundle:
    tool_whitelist: ToolWhitelistConfig
    route_policy: RoutePolicyConfig
    subsystems: SubsystemsConfig
    observability: "ObservabilityConfig"


@dataclass(frozen=True)
class ObservabilityConfig:
    persist_execution_logs: bool
    execution_log_jsonl_path: str


def default_config_root() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "siam"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_tool_whitelist(path: Path) -> ToolWhitelistConfig:
    payload = _read_json(path)
    allowed_tools = tuple(str(name) for name in payload.get("allowed_tools", []))
    return ToolWhitelistConfig(allowed_tools=allowed_tools)


def load_route_policy(path: Path) -> RoutePolicyConfig:
    payload = _read_json(path)
    keyword_rules = tuple(
        RouteKeywordRule(
            contains=tuple(str(token) for token in rule.get("contains", [])),
            prefer_commands=tuple(str(name) for name in rule.get("prefer_commands", [])),
            prefer_tools=tuple(str(name) for name in rule.get("prefer_tools", [])),
        )
        for rule in payload.get("keyword_rules", [])
    )
    raw_override = payload.get("manual_override_defaults", {})
    return RoutePolicyConfig(
        policy_name=str(payload.get("policy_name", "techin-default-v1")),
        max_candidates=int(payload.get("max_candidates", 5)),
        kind_priority=tuple(str(kind) for kind in payload.get("kind_priority", ["command", "tool"])),
        default_command_fallback=str(payload.get("default_command_fallback", "good-claw")),
        keyword_rules=keyword_rules,
        default_override=ManualOverrideModel(
            mode=str(raw_override.get("mode", "normal")),  # type: ignore[arg-type]
            allow_commands=tuple(str(name) for name in raw_override.get("allow_commands", [])),
            block_commands=tuple(str(name) for name in raw_override.get("block_commands", [])),
            allow_tools=tuple(str(name) for name in raw_override.get("allow_tools", [])),
            block_tools=tuple(str(name) for name in raw_override.get("block_tools", [])),
        ),
    )


def load_subsystems(path: Path) -> SubsystemsConfig:
    payload = _read_json(path)
    items = tuple(
        SubsystemModel(
            name=str(item["name"]),
            owner=str(item["owner"]),
            role=str(item["role"]),
            path=str(item["path"]),
            status=str(item.get("status", "planned")),
        )
        for item in payload.get("subsystems", [])
    )
    return SubsystemsConfig(items=items)


def load_siam_config_bundle(config_root: Path | None = None) -> SiamConfigBundle:
    root = config_root or default_config_root()
    return SiamConfigBundle(
        tool_whitelist=load_tool_whitelist(root / "tool-whitelist.json"),
        route_policy=load_route_policy(root / "route-policy.json"),
        subsystems=load_subsystems(root / "subsystems.json"),
        observability=load_observability(root / "observability.json"),
    )


def load_observability(path: Path) -> ObservabilityConfig:
    payload = _read_json(path)
    persist_raw = os.environ.get("SIAM_PERSIST_EXECUTION_LOGS")
    if persist_raw is None:
        persist_execution_logs = bool(payload.get("persist_execution_logs", False))
    else:
        persist_execution_logs = persist_raw.strip().lower() in {"1", "true", "yes", "on"}
    execution_log_path = os.environ.get("SIAM_EXECUTION_LOG_JSONL_PATH")
    if execution_log_path is None or not execution_log_path.strip():
        execution_log_path = str(payload.get("execution_log_jsonl_path", ".siam/execution-log.jsonl"))
    return ObservabilityConfig(
        persist_execution_logs=persist_execution_logs,
        execution_log_jsonl_path=execution_log_path,
    )
