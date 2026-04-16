from __future__ import annotations

import argparse
from datetime import datetime

from .models import ManualOverrideModel
from .observation_report import build_observation_window_report
from .safe_primitives import (
    build_monitoring_snapshot_view,
    build_operator_report,
    build_review_surface,
    compute_state_check,
)
from .serializers import SiamOutputSerializer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Siam command control layer wrapper")
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="output mode (default: text)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show control-layer health/status")
    subparsers.add_parser("list-commands", help="list available claw commands")
    subparsers.add_parser("list-tools", help="list available and allowed tools")
    subparsers.add_parser("list-subsystems", help="list subsystem catalog")
    route_parser = subparsers.add_parser("route", help="apply route policy only")
    route_parser.add_argument("prompt")
    execute_parser = subparsers.add_parser("execute", help="apply policy then execute")
    execute_parser.add_argument("prompt")
    execute_parser.add_argument("--payload", default="")
    override_parser = subparsers.add_parser("override", help="set manual override mode")
    override_parser.add_argument(
        "mode",
        choices=("normal", "block_all_tools", "allow_only"),
    )
    observation_parser = subparsers.add_parser(
        "observation-window-report",
        help="build rollout observation report for a clean window",
    )
    observation_parser.add_argument(
        "--window-open-timestamp",
        required=True,
        help="ISO8601 timestamp marking the start of the observation window",
    )
    observation_parser.add_argument(
        "--log-path",
        default="",
        help="optional path to execution jsonl log file (defaults to configured observability path)",
    )
    safe_state_check = subparsers.add_parser("safe-state-check", help="read-only safe state snapshot")
    safe_state_check.add_argument("--log-path", default=".siam/execution-log.jsonl")
    safe_state_check.add_argument("--window", type=int, default=50)
    safe_review_surface = subparsers.add_parser("safe-review-surface", help="read-only safe review surface")
    safe_review_surface.add_argument("--log-path", default=".siam/execution-log.jsonl")
    safe_review_surface.add_argument("--tail", type=int, default=5)
    safe_operator_report = subparsers.add_parser("safe-operator-report", help="read-only safe operator report")
    safe_operator_report.add_argument("--log-path", default=".siam/execution-log.jsonl")
    safe_operator_report.add_argument("--tail", type=int, default=5)
    safe_monitoring_view = subparsers.add_parser("safe-monitoring-view", help="read-only safe monitoring view")
    safe_monitoring_view.add_argument("--log-path", default=".siam/execution-log.jsonl")
    safe_monitoring_view.add_argument("--readiness-path", default=".siam/readiness_snapshot.json")
    safe_monitoring_view.add_argument("--alerts-path", default=".siam/alerts_snapshot.json")
    subparsers.add_parser("session", help="show latest session summary")
    subparsers.add_parser("logs", help="show structured execution logs")
    subparsers.add_parser("control-state", help="show policy, whitelist, override, and persistence state")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_mode = args.output
    if args.command == "safe-state-check":
        payload = compute_state_check(args.log_path, window=max(1, int(args.window)))
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "safe-review-surface":
        payload = build_review_surface(args.log_path, tail=max(0, int(args.tail)))
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "safe-operator-report":
        payload = build_operator_report(args.log_path, tail=max(0, int(args.tail)))
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "safe-monitoring-view":
        payload = build_monitoring_snapshot_view(
            readiness_path=args.readiness_path,
            alerts_path=args.alerts_path,
            automation_log_path=args.log_path,
        )
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    from .control_layer import SiamCommandControlLayer

    layer = SiamCommandControlLayer.from_defaults()
    if args.command == "status":
        payload = SiamOutputSerializer.status_model(layer.health_status())
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "list-commands":
        commands = layer.list_available_commands()
        if output_mode == "json":
            print(SiamOutputSerializer.emit(SiamOutputSerializer.command_inventory(commands), output_mode))
        else:
            for name in commands:
                print(name)
        return 0
    if args.command == "list-tools":
        available = layer.list_available_tools()
        allowed = layer.list_allowed_tools()
        if output_mode == "json":
            payload = SiamOutputSerializer.tool_inventory(available, allowed)
            print(SiamOutputSerializer.emit(payload, output_mode))
        else:
            print("available:")
            for name in available:
                print(f"- {name}")
            print("allowed:")
            for name in allowed:
                print(f"- {name}")
        return 0
    if args.command == "list-subsystems":
        subsystems = tuple(layer.list_subsystems())
        if output_mode == "json":
            payload = SiamOutputSerializer.subsystem_list(subsystems)
            print(SiamOutputSerializer.emit(payload, output_mode))
        else:
            for item in subsystems:
                print(f"{item.name}\t{item.owner}\t{item.role}\t{item.status}")
        return 0
    if args.command == "route":
        decision = layer.apply_route_policy(args.prompt)
        payload = SiamOutputSerializer.route_model(decision)
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "execute":
        log_model = layer.execute_with_control(args.prompt, args.payload)
        payload = SiamOutputSerializer.execution_log_model(log_model)
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "override":
        layer.set_manual_override(ManualOverrideModel(mode=args.mode))
        if output_mode == "json":
            payload = {
                "override": SiamOutputSerializer.manual_override(layer.manual_override_state()),
                "status": SiamOutputSerializer.status_model(layer.health_status()),
            }
            print(SiamOutputSerializer.emit(payload, output_mode))
        else:
            print(layer.health_status().to_dict())
        return 0
    if args.command == "session":
        summary = layer.latest_session_summary()
        payload = SiamOutputSerializer.session_model(summary)
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "logs":
        if output_mode == "json":
            payload = {
                "in_memory": SiamOutputSerializer.execution_log_list(layer.execution_logs()),
                "persisted": list(layer.persisted_execution_logs()),
            }
            print(SiamOutputSerializer.emit(payload, output_mode))
        else:
            for line in layer.format_execution_logs():
                print(line)
            for record in layer.persisted_execution_logs():
                print(record)
        return 0
    if args.command == "control-state":
        payload = SiamOutputSerializer.control_state(
            policy_name=layer.policy_name(),
            whitelist_tools=layer.whitelist_state(),
            override=layer.manual_override_state(),
            log_persistence_enabled=bool(layer.log_persistence_state()["enabled"]),
            log_path=str(layer.log_persistence_state()["path"]),
        )
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    if args.command == "observation-window-report":
        try:
            datetime.fromisoformat(args.window_open_timestamp)
        except ValueError:
            parser.error("invalid --window-open-timestamp: expected ISO8601 format")
            return 2
        log_path = args.log_path.strip() or str(layer.log_persistence_state()["path"])
        payload = build_observation_window_report(
            window_open_timestamp=args.window_open_timestamp,
            log_path=log_path,
        )
        print(SiamOutputSerializer.emit(payload, output_mode))
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
