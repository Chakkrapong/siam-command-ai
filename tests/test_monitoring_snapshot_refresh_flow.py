from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.siam_command.automation.reporter import run_reporter
from src.siam_command.automation.watcher import run_watcher


def _write_log(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(entry, ensure_ascii=True) for entry in entries), encoding="utf-8")


class MonitoringSnapshotRefreshFlowTests(unittest.TestCase):
    def test_run_watcher_refreshes_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "execution-log.jsonl"
            _write_log(log_path, [{"execution_id": "exec_1"}])

            with patch("src.siam_command.automation.watcher.export_all_snapshots") as mock_export:
                mock_export.return_value = {"ok": True}
                run_watcher(str(log_path))

            mock_export.assert_called_once_with(
                readiness_path=".siam/readiness_snapshot.json",
                alerts_path=".siam/alerts_snapshot.json",
                log_path=str(log_path),
                ports=None,
                settings=None,
            )

    def test_run_reporter_refreshes_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "execution-log.jsonl"
            _write_log(log_path, [{"execution_id": "exec_1"}])

            with patch("src.siam_command.automation.reporter.export_all_snapshots") as mock_export:
                mock_export.return_value = {"ok": True}
                run_reporter(str(log_path), tail=1)

            mock_export.assert_called_once_with(
                readiness_path=".siam/readiness_snapshot.json",
                alerts_path=".siam/alerts_snapshot.json",
                log_path=str(log_path),
                ports=None,
                settings=None,
            )

    def test_run_reporter_missing_file_skips_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_log_path = Path(tmp) / "missing.jsonl"

            with patch("src.siam_command.automation.reporter.export_all_snapshots") as mock_export:
                run_reporter(str(missing_log_path), tail=1)

            mock_export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
