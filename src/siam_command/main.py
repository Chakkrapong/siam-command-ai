from __future__ import annotations

import argparse
from datetime import datetime

from .control_layer import SiamCommandControlLayer
from .models import ManualOverrideModel
from .observation_report import build_observation_window_report
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
    subparsers.add_parser("session", help="show latest session summary")
    subparsers.add_parser("logs", help="show structured execution logs")
    subparsers.add_parser("control-state", help="show policy, whitelist, override, and persistence state")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_mode = args.output
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
