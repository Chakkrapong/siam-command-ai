"""Minimal execution log reporter for Siam Command."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Tuple

try:
    from .snapshot_exporter import export_all_snapshots
except ImportError:  # pragma: no cover - direct script execution fallback
    def export_all_snapshots(**_: Any) -> Dict[str, Any]:
        return {"ok": False}


DEFAULT_READINESS_SNAPSHOT_PATH = ".siam/readiness_snapshot.json"
DEFAULT_ALERTS_SNAPSHOT_PATH = ".siam/alerts_snapshot.json"


def read_log_lines(path: str) -> Iterable[Dict[str, Any]]:
    """Read JSONL entries line-by-line, skipping invalid lines safely."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    yield entry
    except OSError:
        return


def _detect_flags(entry: Dict[str, Any]) -> Tuple[bool, bool]:
    shadow_error = entry.get("shadow_event") == "shadow_error"
    shadow_meta = entry.get("shadow_meta")
    runtime_exception = isinstance(shadow_meta, dict) and shadow_meta.get("error_kind") == "runtime_exception"
    return shadow_error, runtime_exception


def summarize_entries(entries: Iterable[Dict[str, Any]], tail: int = 5) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    total_entries = 0
    total_shadow_errors = 0
    total_runtime_exceptions = 0
    execution_ids = set()
    recent: Deque[Dict[str, str]] = deque(maxlen=max(tail, 0))

    for entry in entries:
        total_entries += 1
        execution_id = str(entry.get("execution_id", "")).strip()
        if execution_id:
            execution_ids.add(execution_id)

        shadow_error, runtime_exception = _detect_flags(entry)
        if shadow_error:
            total_shadow_errors += 1
        if runtime_exception:
            total_runtime_exceptions += 1

        if tail > 0:
            recent.append(
                {
                    "execution_id": execution_id or "-",
                    "shadow_error": "yes" if shadow_error else "no",
                    "runtime_exception": "yes" if runtime_exception else "no",
                }
            )

    total_signals = total_shadow_errors + total_runtime_exceptions
    if total_entries > 0:
        shadow_error_rate = total_shadow_errors / total_entries
        runtime_exception_rate = total_runtime_exceptions / total_entries
    else:
        shadow_error_rate = 0.0
        runtime_exception_rate = 0.0

    summary = {
        "total_entries": total_entries,
        "unique_execution_ids": len(execution_ids),
        "total_shadow_errors": total_shadow_errors,
        "total_runtime_exceptions": total_runtime_exceptions,
        "total_signals": total_signals,
        "shadow_error_rate": shadow_error_rate,
        "runtime_exception_rate": runtime_exception_rate,
    }
    return summary, list(recent)


def print_report(summary: Dict[str, Any], recent_entries: List[Dict[str, str]]) -> None:
    print("Reporter Summary")
    print("")
    print(f"- total_entries: {summary['total_entries']}")
    print(f"- unique_execution_ids: {summary['unique_execution_ids']}")
    print(f"- total_shadow_errors: {summary['total_shadow_errors']}")
    print(f"- total_runtime_exceptions: {summary['total_runtime_exceptions']}")
    print(f"- total_signals: {summary['total_signals']}")
    print(f"- shadow_error_rate: {summary['shadow_error_rate']:.4f}")
    print(f"- runtime_exception_rate: {summary['runtime_exception_rate']:.4f}")

    if recent_entries:
        print("")
        print("Recent Entries")
        print("")
        for item in recent_entries:
            print(
                f"- {item['execution_id']} | "
                f"shadow_error={item['shadow_error']} | "
                f"runtime_exception={item['runtime_exception']}"
            )


def run_reporter(
    path: str,
    tail: int = 5,
    *,
    ports: Any = None,
    settings: Any = None,
) -> None:
    try:
        with open(path, "r", encoding="utf-8"):
            pass
    except OSError:
        print(f"Log file not found or unreadable: {path}")
        return

    summary, recent = summarize_entries(read_log_lines(path), tail=tail)
    result = export_all_snapshots(
        readiness_path=DEFAULT_READINESS_SNAPSHOT_PATH,
        alerts_path=DEFAULT_ALERTS_SNAPSHOT_PATH,
        log_path=path,
        ports=ports,
        settings=settings,
    )
    if result.get("ok"):
        readiness_path = Path(DEFAULT_READINESS_SNAPSHOT_PATH)
        alerts_path = Path(DEFAULT_ALERTS_SNAPSHOT_PATH)
        print(f"[snapshot] refreshed {readiness_path} and {alerts_path}")
    else:
        print("[snapshot] refresh failed")
    print_report(summary, recent)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Siam Command execution log reporter")
    parser.add_argument(
        "--path",
        default=".siam/execution-log.jsonl",
        help="Path to execution log JSONL file",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=5,
        help="Number of recent valid entries to include in report",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.tail < 0:
        raise SystemExit("--tail must be 0 or greater")
    run_reporter(path=args.path, tail=args.tail)
