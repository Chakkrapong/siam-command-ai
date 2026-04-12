from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from typing import Any

from .adapters import PanelPayload, SiamDashboardSnapshot


def _pretty_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)


def _panel_error(error: str | None) -> str:
    if not error:
        return ""
    return (
        "<div class='panel-error'>"
        "<strong>Panel error:</strong> "
        f"{escape(error)}"
        "</div>"
    )


def _safe_dict(panel: PanelPayload) -> dict[str, Any]:
    return panel.data if isinstance(panel.data, dict) else {}


def _safe_list(panel: PanelPayload) -> list[Any]:
    return panel.data if isinstance(panel.data, list) else []


def _badge(label: str, kind: str) -> str:
    return f"<span class='badge badge-{escape(kind)}'>{escape(label)}</span>"


def _render_key_values(payload: dict[str, Any]) -> str:
    if not payload:
        return "<p class='muted'>No structured fields returned.</p>"
    rows = "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td><code>{escape(str(value))}</code></td>"
        "</tr>"
        for key, value in payload.items()
    )
    return f"<table><tbody>{rows}</tbody></table>"


def _dedupe_by_name(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = str(row.get("name", "")).strip()
        key = name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _filter_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not query.strip():
        return rows
    needle = query.lower()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        blob = " ".join(
            str(row.get(key, ""))
            for key in ("name", "owner", "description", "source_path", "role", "path", "status")
        ).lower()
        if needle in blob:
            filtered.append(row)
    return filtered


def _render_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "<p class='muted'>No rows for current filter.</p>"
    head = "".join(f"<th>{escape(col)}</th>" for col in columns)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(row.get(col.lower(), '')))}</td>" for col in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _route_state(route: dict[str, Any], route_error: str | None) -> tuple[str, str]:
    if route_error:
        return ("error", "error")
    selected_command = route.get("selected_command")
    selected_tool = route.get("selected_tool")
    if selected_command or selected_tool:
        return ("success", "success")
    return ("blocked", "blocked")


def _render_route(route_panel: PanelPayload) -> str:
    route = _safe_dict(route_panel)
    label, kind = _route_state(route, route_panel.error)
    details = _pretty_json(route)
    return (
        f"<p>{_badge('route: ' + label, kind)}</p>"
        "<details open>"
        "<summary>Route JSON</summary>"
        f"<pre>{escape(details)}</pre>"
        "</details>"
    )


def _render_logs(logs_panel: PanelPayload) -> str:
    payload = _safe_dict(logs_panel)
    in_memory = payload.get("in_memory", [])
    persisted = payload.get("persisted", [])
    in_memory_logs = in_memory if isinstance(in_memory, list) else []
    persisted_logs = persisted if isinstance(persisted, list) else []
    all_logs = in_memory_logs + persisted_logs
    blocked = sum(1 for row in all_logs if isinstance(row, dict) and bool(row.get("blocked")))
    success = len(all_logs) - blocked
    state_kind = "error" if logs_panel.error else ("blocked" if blocked > 0 else "success")
    summary = (
        f"total={len(all_logs)} "
        f"in_memory={len(in_memory_logs)} "
        f"persisted={len(persisted_logs)} "
        f"success={max(success, 0)} blocked={blocked}"
    )
    return (
        f"<p>{_badge('logs: ' + state_kind, state_kind)} <code>{escape(summary)}</code></p>"
        "<div class='split'>"
        "<details open><summary>In-memory logs</summary>"
        f"<pre>{escape(_pretty_json(in_memory_logs[-20:]))}</pre>"
        "</details>"
        "<details open><summary>Persisted logs</summary>"
        f"<pre>{escape(_pretty_json(persisted_logs[-20:]))}</pre>"
        "</details>"
        "</div>"
    )


def _render_inventory_form(route_prompt: str, commands_q: str, tools_q: str, subsystems_q: str) -> str:
    return (
        "<form method='get' class='filters'>"
        f"<input type='hidden' name='route_prompt' value='{escape(route_prompt)}' />"
        "<label>Commands filter</label>"
        f"<input name='commands_q' value='{escape(commands_q)}' />"
        "<label>Tools filter</label>"
        f"<input name='tools_q' value='{escape(tools_q)}' />"
        "<label>Subsystems filter</label>"
        f"<input name='subsystems_q' value='{escape(subsystems_q)}' />"
        "<button type='submit'>Apply Filters</button>"
        "</form>"
    )


def render_dashboard(
    snapshot: SiamDashboardSnapshot,
    route_prompt: str,
    commands_q: str = "",
    tools_q: str = "",
    subsystems_q: str = "",
) -> str:
    generated_at = snapshot.refreshed_at or datetime.now(timezone.utc).isoformat()
    status = _safe_dict(snapshot.status)
    control_state = _safe_dict(snapshot.control_state)
    session = _safe_dict(snapshot.session)
    commands_payload = _safe_dict(snapshot.commands)
    tools_payload = _safe_dict(snapshot.tools)

    command_names = [str(item) for item in commands_payload.get("items", []) if str(item).strip()]
    command_meta_raw = _safe_list(snapshot.command_catalog)
    command_meta_map = {str(row.get("name", "")).lower(): row for row in command_meta_raw if isinstance(row, dict)}
    command_rows = [
        {
            "name": name,
            "owner": str(command_meta_map.get(name.lower(), {}).get("owner", "SiamCommandRegistry")),
            "description": str(command_meta_map.get(name.lower(), {}).get("description", "")),
            "source_path": str(command_meta_map.get(name.lower(), {}).get("source_path", "")),
        }
        for name in command_names
    ]
    command_rows = _filter_rows(_dedupe_by_name(command_rows), commands_q)

    tool_meta_raw = _safe_list(snapshot.tool_catalog)
    tool_meta_map = {str(row.get("name", "")).lower(): row for row in tool_meta_raw if isinstance(row, dict)}
    available = [str(item) for item in tools_payload.get("available", []) if str(item).strip()]
    tool_rows = [
        {
            "name": name,
            "owner": str(tool_meta_map.get(name.lower(), {}).get("owner", "SiamToolRegistry")),
            "description": str(tool_meta_map.get(name.lower(), {}).get("description", "")),
            "source_path": str(tool_meta_map.get(name.lower(), {}).get("source_path", "")),
        }
        for name in available
    ]
    tool_rows = _filter_rows(_dedupe_by_name(tool_rows), tools_q)

    subsystem_rows_raw = []
    for item in _safe_list(snapshot.subsystems):
        if isinstance(item, dict):
            subsystem_rows_raw.append(
                {
                    "name": str(item.get("name", "")),
                    "owner": str(item.get("owner", "")),
                    "description": str(item.get("role", "")),
                    "source_path": str(item.get("path", "")),
                }
            )
    subsystem_rows = _filter_rows(_dedupe_by_name(subsystem_rows_raw), subsystems_q)

    command_count = int(commands_payload.get("count", len(command_rows)))
    tool_count = int(tools_payload.get("available_count", len(tool_rows)))
    subsystem_count = len(_safe_list(snapshot.subsystems))
    persistence = _safe_dict(snapshot.control_state).get("log_persistence", {})
    persistence_enabled = bool(persistence.get("enabled")) if isinstance(persistence, dict) else False

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Siam Command Mini Dashboard</title>
  <style>
    :root {{
      --bg: #f4f5f7;
      --card: #ffffff;
      --border: #dde1e6;
      --text: #1c1f24;
      --muted: #5a6270;
      --accent: #0057b8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, #f7f9fc 0%, #edf1f7 100%);
    }}
    header {{
      background: var(--card);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      position: sticky;
      top: 0;
    }}
    main {{ padding: 20px 24px 40px; display: grid; gap: 18px; }}
    .row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      box-shadow: 0 1px 4px rgba(15, 26, 46, 0.05);
    }}
    h1, h2, h3 {{ margin: 0 0 10px; }}
    h1 {{ font-size: 20px; }}
    h2 {{ font-size: 17px; color: var(--accent); }}
    h3 {{ font-size: 14px; }}
    nav a {{ margin-right: 14px; color: var(--accent); text-decoration: none; font-weight: 600; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    pre {{
      margin: 0;
      background: #0f1a2e;
      color: #f5f7ff;
      border-radius: 8px;
      padding: 10px;
      max-height: 260px;
      overflow: auto;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .muted {{ color: var(--muted); }}
    .split {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
    .toolbar {{ display: flex; gap: 10px; align-items: center; }}
    .summary-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
    .summary-card {{ padding: 10px; border: 1px solid var(--border); border-radius: 10px; background: #fafcff; }}
    .filters {{ display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 10px 0; align-items: end; }}
    .filters input {{ width: 100%; }}
    .panel-error {{ border: 1px solid #d53f3f; background: #fff5f5; color: #7c1f1f; border-radius: 8px; padding: 8px; margin-bottom: 8px; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 3px 8px; font-size: 11px; font-weight: 700; text-transform: uppercase; }}
    .badge-success {{ background: #e6f7ec; color: #1f6d3f; }}
    .badge-blocked {{ background: #fff3d6; color: #8a5a00; }}
    .badge-error {{ background: #ffe7e7; color: #8f2020; }}
    details {{ border: 1px solid var(--border); border-radius: 8px; padding: 8px; background: #fbfdff; }}
    details summary {{ cursor: pointer; font-weight: 600; margin-bottom: 6px; }}
    button {{
      border: 1px solid var(--accent);
      color: white;
      background: var(--accent);
      border-radius: 8px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Siam Command Mini Dashboard</h1>
    <div class="toolbar">
      <span class="muted">Last refresh: {escape(generated_at)}</span>
      <button onclick="window.location.reload()">Refresh</button>
    </div>
    <nav>
      <a href="#commands">Commands</a>
      <a href="#tools">Tools</a>
      <a href="#subsystems">Subsystems</a>
    </nav>
  </header>
  <main>
    <section class="card">
      <h2>Overview</h2>
      <div class="summary-grid">
        <div class="summary-card"><div class="muted">Commands</div><strong>{command_count}</strong></div>
        <div class="summary-card"><div class="muted">Tools</div><strong>{tool_count}</strong></div>
        <div class="summary-card"><div class="muted">Subsystems</div><strong>{subsystem_count}</strong></div>
        <div class="summary-card"><div class="muted">Persistence</div><strong>{'enabled' if persistence_enabled else 'disabled'}</strong></div>
      </div>
    </section>

    <section class="card">
      <h2>System Status</h2>
      {_panel_error(snapshot.status.error)}
      {_render_key_values(status)}
    </section>

    <section class="card">
      <h2>Route / Control State</h2>
      <form method="get" style="margin-bottom: 10px;">
        <input type="hidden" name="commands_q" value="{escape(commands_q)}" />
        <input type="hidden" name="tools_q" value="{escape(tools_q)}" />
        <input type="hidden" name="subsystems_q" value="{escape(subsystems_q)}" />
        <label for="route_prompt">Route prompt inspect:</label>
        <input id="route_prompt" name="route_prompt" value="{escape(route_prompt)}" style="width: 60%; max-width: 680px; margin: 0 8px;" />
        <button type="submit">Route Inspect</button>
      </form>
      <div class="row">
        <div>
          <h3>Control State</h3>
          {_panel_error(snapshot.control_state.error)}
          {_render_key_values(control_state)}
        </div>
        <div>
          <h3>Route Result</h3>
          {_panel_error(snapshot.route.error)}
          {_render_route(snapshot.route)}
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Execution Logs</h2>
      {_panel_error(snapshot.logs.error)}
      {_render_logs(snapshot.logs)}
    </section>

    <section class="card">
      <h2>Session Summary</h2>
      {_panel_error(snapshot.session.error)}
      {_render_key_values(session)}
    </section>

    <section id="commands" class="card">
      <h2>Commands</h2>
      {_panel_error(snapshot.commands.error)}
      {_panel_error(snapshot.command_catalog.error)}
      {_render_inventory_form(route_prompt, commands_q, tools_q, subsystems_q)}
      <p class="muted">Count: {command_count} | Showing: {len(command_rows)} | Dedupe by name: on</p>
      {_render_table(command_rows, ["Name", "Owner", "Description", "Source_Path"])}
    </section>

    <section id="tools" class="card">
      <h2>Tools</h2>
      {_panel_error(snapshot.tools.error)}
      {_panel_error(snapshot.tool_catalog.error)}
      <p class="muted">Available: {escape(str(tools_payload.get("available_count", 0)))} | Allowed: {escape(str(tools_payload.get("allowed_count", 0)))} | Showing: {len(tool_rows)} | Dedupe by name: on</p>
      {_render_table(tool_rows, ["Name", "Owner", "Description", "Source_Path"])}
    </section>

    <section id="subsystems" class="card">
      <h2>Subsystems</h2>
      {_panel_error(snapshot.subsystems.error)}
      <p class="muted">Count: {subsystem_count} | Showing: {len(subsystem_rows)} | Dedupe by name: on</p>
      {_render_table(subsystem_rows, ["Name", "Owner", "Description", "Source_Path"])}
    </section>
  </main>
</body>
</html>"""
