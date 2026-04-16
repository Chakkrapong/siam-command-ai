from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from ..siam_command.application.ports import ControlPlanePorts
from ..siam_command.automation.monitoring_api import (
    DEFAULT_ALERTS_SNAPSHOT_PATH,
    DEFAULT_READINESS_SNAPSHOT_PATH,
    get_alerts_snapshot_response,
    get_monitoring_bundle_response,
    get_readiness_snapshot_response,
)
from ..siam_command.infrastructure.bootstrap import build_control_plane_ports
from ..siam_command.infrastructure.settings import SiamInfrastructureSettings
from .adapters import (
    get_automation_summary,
    get_execution_detail,
    get_readiness,
    get_summary,
    list_alerts,
    list_executions,
    list_shadow_errors,
)


def _default_log_path() -> str:
    return str(Path(".siam/execution-log.jsonl"))


def _default_readiness_snapshot_path() -> str:
    return str(Path(DEFAULT_READINESS_SNAPSHOT_PATH))


def _default_alerts_snapshot_path() -> str:
    return str(Path(DEFAULT_ALERTS_SNAPSHOT_PATH))


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=True).encode("utf-8")


def build_api_handler(
    log_path_provider: Callable[[], str],
    readiness_snapshot_path_provider: Callable[[], str] = _default_readiness_snapshot_path,
    alerts_snapshot_path_provider: Callable[[], str] = _default_alerts_snapshot_path,
    monitoring_ports: ControlPlanePorts | None = None,
    monitoring_settings: SiamInfrastructureSettings | None = None,
) -> type[BaseHTTPRequestHandler]:
    class SiamApiHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload: object, status: int = 200) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)

            if parts.path == "/api/monitoring/readiness":
                payload = get_readiness_snapshot_response(
                    readiness_snapshot_path_provider(),
                    ports=monitoring_ports,
                    settings=monitoring_settings,
                )
                self._send_json(payload)
                return

            if parts.path == "/api/monitoring/alerts":
                payload = get_alerts_snapshot_response(
                    alerts_snapshot_path_provider(),
                    ports=monitoring_ports,
                    settings=monitoring_settings,
                )
                self._send_json(payload)
                return

            if parts.path == "/api/monitoring":
                payload = get_monitoring_bundle_response(
                    readiness_path=readiness_snapshot_path_provider(),
                    alerts_path=alerts_snapshot_path_provider(),
                    ports=monitoring_ports,
                    settings=monitoring_settings,
                )
                self._send_json(payload)
                return

            log_path = query.get("log_path", [log_path_provider()])[0]

            if parts.path == "/api/summary":
                payload = get_summary(log_path, minutes=int(query.get("minutes", ["60"])[0]))
                self._send_json(payload)
                return

            if parts.path == "/api/executions":
                payload = list_executions(log_path, limit=int(query.get("limit", ["50"])[0]))
                self._send_json(payload)
                return

            if parts.path.startswith("/api/executions/"):
                execution_id = parts.path.rsplit("/", 1)[-1].strip()
                payload = get_execution_detail(log_path, execution_id)
                if payload is None:
                    self._send_json({"error": "execution not found"}, status=404)
                    return
                self._send_json(payload)
                return

            if parts.path == "/api/automation":
                payload = get_automation_summary(log_path, minutes=int(query.get("minutes", ["60"])[0]))
                self._send_json(payload)
                return

            if parts.path == "/api/alerts":
                payload = list_alerts(
                    log_path,
                    minutes=int(query.get("minutes", ["60"])[0]),
                    limit=int(query.get("limit", ["50"])[0]),
                )
                self._send_json(payload)
                return

            if parts.path == "/api/readiness":
                payload = get_readiness(
                    log_path,
                    window=int(query.get("window", ["50"])[0]),
                )
                self._send_json(payload)
                return

            if parts.path == "/api/debug/shadow-errors":
                payload = list_shadow_errors(
                    log_path,
                    limit=int(query.get("limit", ["20"])[0]),
                    recent_window=int(query.get("recent_window", ["50"])[0]),
                )
                self._send_json(payload)
                return

            self._send_json({"error": "not found"}, status=404)

        def log_message(self, format: str, *args: object) -> None:
            return

    return SiamApiHandler


def run_server(host: str = "127.0.0.1", port: int = 8780, log_path: str | None = None) -> None:
    resolved_log_path = log_path or _default_log_path()
    monitoring_settings = SiamInfrastructureSettings.from_env()
    monitoring_ports: ControlPlanePorts | None = None
    if (
        monitoring_settings.readiness_provider.strip().lower() != "local"
        or monitoring_settings.alert_provider.strip().lower() != "local"
    ):
        try:
            monitoring_ports = build_control_plane_ports(monitoring_settings)
        except Exception:
            monitoring_ports = None
    handler = build_api_handler(
        lambda: resolved_log_path,
        monitoring_ports=monitoring_ports,
        monitoring_settings=monitoring_settings,
    )
    server = ThreadingHTTPServer((host, int(port)), handler)
    print(f"Siam API running at http://{host}:{port} (log_path={resolved_log_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
