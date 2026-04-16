"""Minimal execution log watcher for Siam Command.

This module is intentionally read-only and synchronous.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

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


def detect_events(entry: Dict[str, Any]) -> List[Dict[str, str]]:
    """Detect watcher signals for one execution log entry."""
    signals: List[Dict[str, str]] = []
    execution_id = str(entry.get("execution_id", ""))

    if entry.get("shadow_event") == "shadow_error":
        signals.append(
            {
                "type": "shadow_error_detected",
                "execution_id": execution_id,
                "severity": "high",
            }
        )

    shadow_meta = entry.get("shadow_meta")
    if isinstance(shadow_meta, dict) and shadow_meta.get("error_kind") == "runtime_exception":
        signals.append(
            {
                "type": "runtime_exception_detected",
                "execution_id": execution_id,
                "severity": "medium",
            }
        )

    return signals


def _print_signal(signal: Dict[str, str]) -> None:
    severity = str(signal.get("severity", "low")).upper()
    signal_type = str(signal.get("type", "unknown"))
    execution_id = str(signal.get("execution_id", ""))
    print(f"[{severity}] {signal_type} ({execution_id})")


def _read_log_lines_from_offset(
    path: str, start_offset: int
) -> tuple[List[Dict[str, Any]], int, bool]:
    """Read valid JSONL entries from a byte offset and return (entries, offset, file_exists)."""
    entries: List[Dict[str, Any]] = []
    try:
        # Use binary mode so tell/seek are stable byte offsets across polling cycles.
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            if file_size < start_offset:
                # Log rotated/truncated: safely restart from the beginning.
                start_offset = 0
            handle.seek(start_offset)
            for raw_line in handle:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
            return entries, handle.tell(), True
    except OSError:
        return [], start_offset, False


def _process_entries(entries: Iterable[Dict[str, Any]]) -> tuple[int, int]:
    """Process entries and print detected signals. Returns (entry_count, signal_count)."""
    total_entries = 0
    total_signals = 0
    for entry in entries:
        total_entries += 1
        signals = detect_events(entry)
        total_signals += len(signals)
        for signal in signals:
            _print_signal(signal)
    return total_entries, total_signals


def _refresh_monitoring_snapshots(
    log_path: str,
    *,
    ports: Any = None,
    settings: Any = None,
) -> None:
    """Best-effort snapshot export hook; never blocks watcher flow."""
    result = export_all_snapshots(
        readiness_path=DEFAULT_READINESS_SNAPSHOT_PATH,
        alerts_path=DEFAULT_ALERTS_SNAPSHOT_PATH,
        log_path=log_path,
        ports=ports,
        settings=settings,
    )
    if result.get("ok"):
        readiness_path = Path(DEFAULT_READINESS_SNAPSHOT_PATH)
        alerts_path = Path(DEFAULT_ALERTS_SNAPSHOT_PATH)
        print(f"[snapshot] refreshed {readiness_path} and {alerts_path}")
    else:
        print("[snapshot] refresh failed")


def run_watcher(
    path: str,
    *,
    ports: Any = None,
    settings: Any = None,
) -> None:
    """Run the watcher over the full log file and print results."""
    total_entries, total_signals = _process_entries(read_log_lines(path))
    _refresh_monitoring_snapshots(path, ports=ports, settings=settings)

    print("")
    print("Summary:")
    print(f"- total_entries: {total_entries}")
    print(f"- total_signals: {total_signals}")


def run_watcher_loop(
    path: str,
    interval_seconds: float = 10,
    *,
    ports: Any = None,
    settings: Any = None,
) -> None:
    """Continuously poll log file and process only newly appended entries."""
    offset = 0
    missing_announced = False
    total_entries = 0
    total_signals = 0

    print(
        f"Watcher loop started (path={path}, interval={interval_seconds}s). "
        "Press Ctrl+C to stop."
    )

    try:
        while True:
            entries, new_offset, file_exists = _read_log_lines_from_offset(path, offset)
            if not file_exists:
                if not missing_announced:
                    print(f"Waiting for log file: {path}")
                    missing_announced = True
            else:
                if missing_announced:
                    print("Log file detected. Watching for new entries...")
                    missing_announced = False
                new_entries, new_signals = _process_entries(entries)
                if new_entries > 0:
                    total_entries += new_entries
                    total_signals += new_signals
                    _refresh_monitoring_snapshots(path, ports=ports, settings=settings)
                    print(
                        f"[cycle] new_entries: {new_entries} | new_signals: {new_signals} | "
                        f"total_entries: {total_entries} | total_signals: {total_signals}"
                    )
                offset = new_offset
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("")
        print("Watcher stopped by user.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Siam Command execution log watcher")
    parser.add_argument(
        "--path",
        default=".siam/execution-log.jsonl",
        help="Path to execution log JSONL file",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously in polling loop mode",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10,
        help="Polling interval in seconds (loop mode only)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.loop:
        if args.interval <= 0:
            raise SystemExit("--interval must be greater than 0")
        run_watcher_loop(path=args.path, interval_seconds=args.interval)
    else:
        run_watcher(path=args.path)
