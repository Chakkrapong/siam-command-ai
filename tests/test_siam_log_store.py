from __future__ import annotations

import unittest
from unittest.mock import patch

from src.siam_command.log_store import ExecutionLogStore
from src.siam_command.models import ExecutionLogModel


class SiamLogStoreHardeningTests(unittest.TestCase):
    def test_append_handles_permission_error_without_raising(self) -> None:
        store = ExecutionLogStore(path=".siam/execution-log.jsonl", enabled=True)
        log = ExecutionLogModel(
            execution_id="id",
            timestamp="2026-04-11T00:00:00+00:00",
            prompt="p",
            selected_command=None,
            selected_tool=None,
            command_message=None,
            tool_message=None,
            stop_reason="completed",
            blocked=False,
            policy_name="techin-default-v1",
            session_id="s",
        )
        with patch("pathlib.Path.open", side_effect=PermissionError("denied")):
            store.append(log)
        self.assertIsNotNone(store.last_io_error)

    def test_read_all_handles_permission_error_without_raising(self) -> None:
        store = ExecutionLogStore(path=".siam/execution-log.jsonl", enabled=True)
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
            records = store.read_all()
        self.assertEqual(records, ())
        self.assertIsNotNone(store.last_io_error)


if __name__ == "__main__":
    unittest.main()

