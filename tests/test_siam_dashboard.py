from __future__ import annotations

import unittest

from src.siam_dashboard.adapters import PanelPayload, SiamDashboardAdapter, SiamDashboardSnapshot
from src.siam_dashboard.render_operational import render_dashboard


class SiamDashboardTests(unittest.TestCase):
    def test_adapter_collects_contract_snapshot(self) -> None:
        snapshot = SiamDashboardAdapter().collect_snapshot(route_prompt="review MCP tool permissions")
        self.assertIn("policy_name", snapshot.status.data)
        self.assertIn("prompt", snapshot.route.data)
        self.assertIn("manual_override", snapshot.control_state.data)
        self.assertIn("in_memory", snapshot.logs.data)
        self.assertIn("session_id", snapshot.session.data)
        self.assertIn("items", snapshot.commands.data)
        self.assertIn("available", snapshot.tools.data)
        self.assertIsInstance(snapshot.subsystems.data, list)

    def test_dashboard_renders_required_sections(self) -> None:
        snapshot = SiamDashboardAdapter().collect_snapshot(route_prompt="review MCP tool permissions")
        html = render_dashboard(
            snapshot,
            route_prompt="review MCP tool permissions",
            query={
                "commands_q": "review",
                "tools_q": "mcp",
                "subsystems_q": "siam",
                "commands_sort": "name",
                "commands_order": "asc",
                "commands_page": "1",
                "commands_limit": "10",
                "logs_state": "all",
                "logs_source": "all",
                "logs_type": "all",
                "logs_limit": "10",
            },
        )
        self.assertIn("Overview", html)
        self.assertIn("System Status", html)
        self.assertIn("Route / Control State", html)
        self.assertIn("Execution Logs", html)
        self.assertIn("Recent Session History", html)
        self.assertIn("Commands", html)
        self.assertIn("Tools", html)
        self.assertIn("Subsystems", html)
        self.assertIn("Filters / Sort / Paging", html)
        self.assertIn("Recent filtered logs", html)
        self.assertIn("dedupe=on", html)
        self.assertIn("active filters:", html)

    def test_dashboard_renders_panel_errors_without_crash(self) -> None:
        snapshot = SiamDashboardSnapshot(
            refreshed_at="2026-04-11T00:00:00+00:00",
            status=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00", error="status failed"),
            route=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00", error="route failed"),
            control_state=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00", error="control failed"),
            logs=PanelPayload(data={"in_memory": [], "persisted": []}, updated_at="2026-04-11T00:00:01+00:00", error="logs failed"),
            session=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00", error="session failed"),
            commands=PanelPayload(data={"count": 0, "items": []}, updated_at="2026-04-11T00:00:01+00:00", error="commands failed"),
            tools=PanelPayload(data={"available_count": 0, "allowed_count": 0, "available": [], "allowed": []}, updated_at="2026-04-11T00:00:01+00:00", error="tools failed"),
            subsystems=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00", error="subsystems failed"),
            command_catalog=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00", error="command catalog failed"),
            tool_catalog=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00", error="tool catalog failed"),
        )
        html = render_dashboard(snapshot, route_prompt="review MCP tool permissions")
        self.assertIn("Panel error:", html)
        self.assertIn("status failed", html)
        self.assertIn("route failed", html)
        self.assertIn("command catalog failed", html)

    def test_logs_filter_summary_and_redaction_render(self) -> None:
        long_text = "x" * 260
        snapshot = SiamDashboardSnapshot(
            refreshed_at="2026-04-11T00:00:00+00:00",
            status=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00"),
            route=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00"),
            control_state=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00"),
            logs=PanelPayload(
                data={
                    "in_memory": [
                        {"session_id": "s1", "timestamp": "t1", "blocked": False, "selected_command": "review", "prompt": long_text}
                    ],
                    "persisted": [
                        {"session_id": "s2", "timestamp": "t2", "blocked": True, "selected_tool": "MCPTool", "prompt": long_text}
                    ],
                },
                updated_at="2026-04-11T00:00:01+00:00",
            ),
            session=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00"),
            commands=PanelPayload(data={"count": 0, "items": []}, updated_at="2026-04-11T00:00:01+00:00"),
            tools=PanelPayload(data={"available_count": 0, "allowed_count": 0, "available": [], "allowed": []}, updated_at="2026-04-11T00:00:01+00:00"),
            subsystems=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00"),
            command_catalog=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00"),
            tool_catalog=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00"),
        )
        html = render_dashboard(
            snapshot,
            route_prompt="review MCP tool permissions",
            query={"logs_state": "blocked", "logs_source": "persisted", "logs_type": "tool", "logs_limit": "5"},
        )
        self.assertIn("summary: success=", html)
        self.assertIn("showing_recent=", html)
        self.assertIn("... [truncated".replace(" ", ""), html.replace(" ", ""))

    def test_session_refresh_and_empty_states_render(self) -> None:
        snapshot = SiamDashboardSnapshot(
            refreshed_at="2026-04-11T00:00:00+00:00",
            status=PanelPayload(data={"mode": "isolated"}, updated_at="2026-04-11T00:00:01+00:00"),
            route=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00"),
            control_state=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00"),
            logs=PanelPayload(data={"in_memory": [], "persisted": []}, updated_at="2026-04-11T00:00:01+00:00"),
            session=PanelPayload(data={}, updated_at="2026-04-11T00:00:01+00:00"),
            commands=PanelPayload(data={"count": 0, "items": []}, updated_at="2026-04-11T00:00:01+00:00"),
            tools=PanelPayload(data={"available_count": 0, "allowed_count": 0, "available": [], "allowed": []}, updated_at="2026-04-11T00:00:01+00:00"),
            subsystems=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00"),
            command_catalog=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00"),
            tool_catalog=PanelPayload(data=[], updated_at="2026-04-11T00:00:01+00:00"),
        )
        html = render_dashboard(snapshot, route_prompt="review MCP tool permissions", query={"commands_q": "review"})
        self.assertIn("last refresh", html)
        self.assertIn("updated:", html)
        self.assertIn("active filters:", html)
        self.assertIn("No structured fields returned yet.", html)
        self.assertIn("No recent session history available yet.", html)


if __name__ == "__main__":
    unittest.main()
