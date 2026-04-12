from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..siam_core.compat import build_command_catalog_port, build_tool_catalog_port


@dataclass(frozen=True)
class PanelPayload:
    data: Any
    updated_at: str
    error: str | None = None


@dataclass(frozen=True)
class SiamDashboardSnapshot:
    refreshed_at: str
    status: PanelPayload
    route: PanelPayload
    control_state: PanelPayload
    logs: PanelPayload
    session: PanelPayload
    commands: PanelPayload
    tools: PanelPayload
    subsystems: PanelPayload
    command_catalog: PanelPayload
    tool_catalog: PanelPayload


class SiamDashboardAdapter:
    """CLI bridge for machine-readable Siam control-layer contracts."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = workspace_root or Path(__file__).resolve().parents[2]
        self._command_catalog = build_command_catalog_port()
        self._tool_catalog = build_tool_catalog_port()

    def _run_json(self, command: str, *args: str) -> Any:
        result = subprocess.run(
            [sys.executable, "-m", "src.siam_command.main", "--output", "json", command, *args],
            cwd=self._workspace_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _safe_read(self, loader: Any, fallback: Any) -> PanelPayload:
        captured_at = self._now_iso()
        try:
            payload = loader()
            return PanelPayload(data=payload, updated_at=captured_at, error=None)
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.stdout.strip() or f"command failed with code {exc.returncode}"
            return PanelPayload(data=fallback, updated_at=captured_at, error=message)
        except Exception as exc:  # pragma: no cover
            return PanelPayload(data=fallback, updated_at=captured_at, error=str(exc))

    def read_status(self) -> dict[str, Any]:
        return self._run_json("status")

    def read_control_state(self) -> dict[str, Any]:
        return self._run_json("control-state")

    def read_route(self, prompt: str) -> dict[str, Any]:
        payload = self._run_json("route", prompt)
        if isinstance(payload, dict):
            return payload
        return {}

    def read_logs(self) -> dict[str, Any]:
        return self._run_json("logs")

    def read_session(self) -> dict[str, Any]:
        return self._run_json("session")

    def read_commands(self) -> dict[str, Any]:
        return self._run_json("list-commands")

    def read_tools(self) -> dict[str, Any]:
        return self._run_json("list-tools")

    def read_subsystems(self) -> list[dict[str, Any]]:
        payload = self._run_json("list-subsystems")
        if isinstance(payload, list):
            return payload
        return []

    def read_command_catalog(self) -> list[dict[str, str]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "source_path": item.source_path,
                "owner": item.owner,
            }
            for item in self._command_catalog.list_items()
        ]

    def read_tool_catalog(self) -> list[dict[str, str]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "source_path": item.source_path,
                "owner": item.owner,
            }
            for item in self._tool_catalog.list_items()
        ]

    def collect_snapshot(self, route_prompt: str) -> SiamDashboardSnapshot:
        return SiamDashboardSnapshot(
            refreshed_at=self._now_iso(),
            status=self._safe_read(self.read_status, {}),
            route=self._safe_read(lambda: self.read_route(route_prompt), {}),
            control_state=self._safe_read(self.read_control_state, {}),
            logs=self._safe_read(self.read_logs, {"in_memory": [], "persisted": []}),
            session=self._safe_read(self.read_session, {}),
            commands=self._safe_read(self.read_commands, {"count": 0, "items": []}),
            tools=self._safe_read(
                self.read_tools,
                {"available_count": 0, "allowed_count": 0, "available": [], "allowed": []},
            ),
            subsystems=self._safe_read(self.read_subsystems, []),
            command_catalog=self._safe_read(self.read_command_catalog, []),
            tool_catalog=self._safe_read(self.read_tool_catalog, []),
        )
