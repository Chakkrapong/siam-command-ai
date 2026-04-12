from __future__ import annotations

import json

from .models import ExecutionLogModel, SessionSummaryModel


class ExecutionLogFormatter:
    @staticmethod
    def to_structured_record(log: ExecutionLogModel) -> dict[str, object]:
        return log.to_dict()

    @staticmethod
    def to_json_line(log: ExecutionLogModel) -> str:
        return json.dumps(log.to_dict(), separators=(",", ":"), ensure_ascii=True)


class SessionSummaryFormatter:
    @staticmethod
    def to_structured_record(summary: SessionSummaryModel) -> dict[str, object]:
        return summary.to_dict()

    @staticmethod
    def to_pretty_json(summary: SessionSummaryModel) -> str:
        return json.dumps(summary.to_dict(), indent=2, ensure_ascii=True)

