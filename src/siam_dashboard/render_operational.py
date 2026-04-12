from __future__ import annotations

import json
from html import escape
from typing import Any

from .adapters import PanelPayload, SiamDashboardSnapshot


def _d(panel: PanelPayload) -> dict[str, Any]:
    return panel.data if isinstance(panel.data, dict) else {}


def _l(panel: PanelPayload) -> list[Any]:
    return panel.data if isinstance(panel.data, list) else []


def _err(panel: PanelPayload) -> str:
    return f"<div class='err'>Panel error: {escape(panel.error)}</div>" if panel.error else ""


def _updated(panel: PanelPayload) -> str:
    return f"<div class='muted tiny'>updated: {escape(panel.updated_at)}</div>"


def _json(payload: Any) -> str:
    return escape(json.dumps(payload, indent=2, ensure_ascii=True))


def _kv(payload: dict[str, Any]) -> str:
    if not payload:
        return "<p class='empty'>No structured fields returned yet.</p>"
    rows = "".join(
        "<tr>"
        f"<th>{escape(str(k))}</th>"
        f"<td><code>{escape(str(v))}</code></td>"
        "</tr>"
        for k, v in payload.items()
    )
    return f"<table><tbody>{rows}</tbody></table>"


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("name", "")).lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _filter(rows: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    if not q:
        return rows
    n = q.lower()
    return [r for r in rows if n in " ".join(str(r.get(k, "")) for k in ("name", "owner", "description", "source_path")).lower()]


def _sort(rows: list[dict[str, Any]], by: str, order: str) -> list[dict[str, Any]]:
    key = by if by in {"name", "owner", "description", "source_path"} else "name"
    return sorted(rows, key=lambda r: str(r.get(key, "")).lower(), reverse=order == "desc")


def _paginate(rows: list[dict[str, Any]], page_raw: str, limit_raw: str) -> tuple[list[dict[str, Any]], int, int, int]:
    try:
        page = max(1, int(page_raw))
    except Exception:
        page = 1
    try:
        limit = min(200, max(5, int(limit_raw)))
    except Exception:
        limit = 25
    total = len(rows)
    max_page = max(1, (total + limit - 1) // limit)
    page = min(page, max_page)
    start = (page - 1) * limit
    return rows[start : start + limit], total, page, limit


def _table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='empty'>No rows for current state.</p>"
    head = "<tr><th>Name</th><th>Owner</th><th>Description</th><th>Source Path</th></tr>"
    body = "".join(
        "<tr>"
        f"<td>{escape(str(r.get('name', '')))}</td>"
        f"<td>{escape(str(r.get('owner', '')))}</td>"
        f"<td>{escape(str(r.get('description', '')))}</td>"
        f"<td>{escape(str(r.get('source_path', '')))}</td>"
        "</tr>"
        for r in rows
    )
    return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"


def _route_badge(route: dict[str, Any], err: str | None) -> str:
    if err:
        return "<span class='badge b-error'>error</span>"
    if route.get("selected_command") or route.get("selected_tool"):
        return "<span class='badge b-success'>success</span>"
    return "<span class='badge b-blocked'>blocked</span>"


def _log_rows(logs: PanelPayload) -> list[dict[str, Any]]:
    data = _d(logs)
    rows: list[dict[str, Any]] = []
    for source in ("in_memory", "persisted"):
        for item in data.get(source, []) if isinstance(data.get(source, []), list) else []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["source"] = source
            row["state"] = "error" if row.get("error") else ("blocked" if row.get("blocked") else "success")
            if row.get("selected_tool"):
                row["type"] = "tool"
            elif row.get("selected_command"):
                row["type"] = "command"
            elif row.get("blocked"):
                row["type"] = "blocked"
            else:
                row["type"] = "other"
            for k in ("prompt", "command_message", "tool_message"):
                v = row.get(k)
                if isinstance(v, str) and len(v) > 180:
                    row[k] = v[:180] + f"...[truncated {len(v)-180}]"
            rows.append(row)
    return rows


def _render_filters(route_prompt: str, q: dict[str, str]) -> str:
    def i(name: str, default: str = "") -> str:
        return f"<input name='{name}' value='{escape(q.get(name, default))}' />"

    return (
        "<form method='get' class='filters'>"
        f"<label>route_prompt</label>{i('route_prompt', route_prompt)}"
        f"<label>commands_q</label>{i('commands_q')}"
        f"<label>commands_sort</label>{i('commands_sort', 'name')}"
        f"<label>commands_order</label>{i('commands_order', 'asc')}"
        f"<label>commands_page</label>{i('commands_page', '1')}"
        f"<label>commands_limit</label>{i('commands_limit', '25')}"
        f"<label>tools_q</label>{i('tools_q')}"
        f"<label>tools_sort</label>{i('tools_sort', 'name')}"
        f"<label>tools_order</label>{i('tools_order', 'asc')}"
        f"<label>tools_page</label>{i('tools_page', '1')}"
        f"<label>tools_limit</label>{i('tools_limit', '25')}"
        f"<label>subsystems_q</label>{i('subsystems_q')}"
        f"<label>subsystems_sort</label>{i('subsystems_sort', 'name')}"
        f"<label>subsystems_order</label>{i('subsystems_order', 'asc')}"
        f"<label>subsystems_page</label>{i('subsystems_page', '1')}"
        f"<label>subsystems_limit</label>{i('subsystems_limit', '25')}"
        f"<label>logs_state</label>{i('logs_state', 'all')}"
        f"<label>logs_source</label>{i('logs_source', 'all')}"
        f"<label>logs_type</label>{i('logs_type', 'all')}"
        f"<label>logs_limit</label>{i('logs_limit', '30')}"
        "<button type='submit'>Apply</button>"
        "</form>"
    )


def render_dashboard(snapshot: SiamDashboardSnapshot, route_prompt: str, query: dict[str, str] | None = None) -> str:
    q = query or {}
    commands_raw = [{"name": str(n), "owner": "SiamCommandRegistry", "description": "", "source_path": ""} for n in _d(snapshot.commands).get("items", [])]
    for r in _l(snapshot.command_catalog):
        if isinstance(r, dict):
            for x in commands_raw:
                if x["name"].lower() == str(r.get("name", "")).lower():
                    x["description"] = str(r.get("description", ""))
                    x["source_path"] = str(r.get("source_path", ""))
    commands = _sort(_filter(_dedupe(commands_raw), q.get("commands_q", "")), q.get("commands_sort", "name"), q.get("commands_order", "asc"))
    commands_page, commands_total_filtered, commands_page_idx, commands_limit = _paginate(commands, q.get("commands_page", "1"), q.get("commands_limit", "25"))

    tools_raw = [{"name": str(n), "owner": "SiamToolRegistry", "description": "", "source_path": ""} for n in _d(snapshot.tools).get("available", [])]
    for r in _l(snapshot.tool_catalog):
        if isinstance(r, dict):
            for x in tools_raw:
                if x["name"].lower() == str(r.get("name", "")).lower():
                    x["description"] = str(r.get("description", ""))
                    x["source_path"] = str(r.get("source_path", ""))
    tools = _sort(_filter(_dedupe(tools_raw), q.get("tools_q", "")), q.get("tools_sort", "name"), q.get("tools_order", "asc"))
    tools_page, tools_total_filtered, tools_page_idx, tools_limit = _paginate(tools, q.get("tools_page", "1"), q.get("tools_limit", "25"))

    subs_raw = [
        {"name": str(r.get("name", "")), "owner": str(r.get("owner", "")), "description": str(r.get("role", "")), "source_path": str(r.get("path", ""))}
        for r in _l(snapshot.subsystems)
        if isinstance(r, dict)
    ]
    subs = _sort(_filter(_dedupe(subs_raw), q.get("subsystems_q", "")), q.get("subsystems_sort", "name"), q.get("subsystems_order", "asc"))
    subs_page, subs_total_filtered, subs_page_idx, subs_limit = _paginate(subs, q.get("subsystems_page", "1"), q.get("subsystems_limit", "25"))

    logs = _log_rows(snapshot.logs)
    state = q.get("logs_state", "all")
    source = q.get("logs_source", "all")
    typ = q.get("logs_type", "all")
    if state in {"success", "blocked", "error"}:
        logs = [r for r in logs if r.get("state") == state]
    if source in {"in_memory", "persisted"}:
        logs = [r for r in logs if r.get("source") == source]
    if typ in {"command", "tool", "blocked", "other"}:
        logs = [r for r in logs if r.get("type") == typ]
    logs_limit = max(5, min(200, int(q.get("logs_limit", "30")) if q.get("logs_limit", "30").isdigit() else 30))
    logs_recent = logs[-logs_limit:]
    log_all = _log_rows(snapshot.logs)
    log_summary = {
        "success": sum(1 for r in log_all if r.get("state") == "success"),
        "blocked": sum(1 for r in log_all if r.get("state") == "blocked"),
        "error": sum(1 for r in log_all if r.get("state") == "error"),
    }

    route = _d(snapshot.route)
    session = _d(snapshot.session)
    status = _d(snapshot.status)
    control = _d(snapshot.control_state)
    persistence = bool(_d(snapshot.control_state).get("log_persistence", {}).get("enabled")) if isinstance(_d(snapshot.control_state).get("log_persistence", {}), dict) else False

    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Siam Dashboard</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f7fb;color:#1b2430}}main{{padding:18px;display:grid;gap:14px}}.card{{background:#fff;border:1px solid #dce2ea;border-radius:10px;padding:12px}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #e6ebf2;padding:6px;text-align:left;vertical-align:top;word-break:break-word}}pre{{background:#0f1a2e;color:#f5f8ff;padding:8px;border-radius:8px;max-height:280px;overflow:auto;white-space:pre-wrap}}.row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}}.muted{{color:#5f6c80}}.tiny{{font-size:12px}}.err{{border:1px solid #d14343;background:#fff3f3;color:#7d2020;border-radius:6px;padding:6px;margin:6px 0}}.empty{{border:1px dashed #cfd7e3;background:#f9fbff;padding:8px;border-radius:8px}}.filters{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px;align-items:end}}.filters input{{width:100%}}.badge{{padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase}}.b-success{{background:#e6f7ec;color:#1f6d3f}}.b-blocked{{background:#fff3d6;color:#8a5a00}}.b-error{{background:#ffe7e7;color:#8f2020}}
</style></head><body><main>
<section class='card'><h2>Overview</h2><div class='row'>
<div><div class='muted'>commands</div><strong>{int(_d(snapshot.commands).get("count", 0))}</strong></div>
<div><div class='muted'>tools</div><strong>{int(_d(snapshot.tools).get("available_count", 0))}</strong></div>
<div><div class='muted'>subsystems</div><strong>{len(_l(snapshot.subsystems))}</strong></div>
<div><div class='muted'>persistence</div><strong>{'enabled' if persistence else 'disabled'}</strong></div>
<div><div class='muted'>last refresh</div><strong>{escape(snapshot.refreshed_at)}</strong></div>
</div><div class='muted tiny'>active filters: {escape(str({k:v for k,v in q.items() if v}))}</div></section>
<section class='card'><h2>Filters / Sort / Paging</h2>{_render_filters(route_prompt, q)}</section>
<section class='card'><h2>System Status</h2>{_updated(snapshot.status)}{_err(snapshot.status)}<pre>{_json(status)}</pre></section>
<section class='card'><h2>Route / Control State</h2>{_updated(snapshot.route)}{_err(snapshot.route)}<p>{_route_badge(route, snapshot.route.error)}</p><details open><summary>Route JSON</summary><pre>{_json(route)}</pre></details><div class='row'><div><h3>Control State</h3>{_updated(snapshot.control_state)}{_err(snapshot.control_state)}<pre>{_json(control)}</pre></div><div><h3>Session Summary</h3>{_updated(snapshot.session)}{_err(snapshot.session)}{_kv(session)}</div></div></section>
<section class='card'><h2>Execution Logs</h2>{_updated(snapshot.logs)}{_err(snapshot.logs)}<p class='muted'>summary: success={log_summary['success']} blocked={log_summary['blocked']} error={log_summary['error']} filtered={len(logs)} showing_recent={len(logs_recent)}</p><details open><summary>Recent filtered logs (redacted)</summary><pre>{_json(logs_recent)}</pre></details></section>
<section class='card'><h2>Recent Session History (read-only)</h2><p class='muted tiny'>derived from available log sources; if no historical source, this section stays in placeholder mode.</p>{("<p class='empty'>No recent session history available yet.</p>" if not logs_recent else "<pre>" + _json([{'session_id': r.get('session_id'), 'timestamp': r.get('timestamp'), 'state': r.get('state'), 'source': r.get('source')} for r in logs_recent]) + "</pre>")}</section>
<section class='card' id='commands'><h2>Commands</h2>{_updated(snapshot.commands)}{_err(snapshot.commands)}{_err(snapshot.command_catalog)}<p class='muted'>total={int(_d(snapshot.commands).get("count", 0))} filtered={commands_total_filtered} page={commands_page_idx} limit={commands_limit} showing={len(commands_page)} dedupe=on</p>{_table(commands_page)}</section>
<section class='card' id='tools'><h2>Tools</h2>{_updated(snapshot.tools)}{_err(snapshot.tools)}{_err(snapshot.tool_catalog)}<p class='muted'>total={int(_d(snapshot.tools).get("available_count", 0))} filtered={tools_total_filtered} page={tools_page_idx} limit={tools_limit} showing={len(tools_page)} dedupe=on</p>{_table(tools_page)}</section>
<section class='card' id='subsystems'><h2>Subsystems</h2>{_updated(snapshot.subsystems)}{_err(snapshot.subsystems)}<p class='muted'>total={len(_l(snapshot.subsystems))} filtered={subs_total_filtered} page={subs_page_idx} limit={subs_limit} showing={len(subs_page)} dedupe=on</p>{_table(subs_page)}</section>
</main></body></html>"""
