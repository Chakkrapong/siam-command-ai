from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from ..siam_command.automation.monitoring_api import (
    DEFAULT_ALERTS_SNAPSHOT_PATH,
    DEFAULT_READINESS_SNAPSHOT_PATH,
    get_alerts_snapshot_response,
    get_monitoring_bundle_response,
    get_readiness_snapshot_response,
)
from ..siam_command.safe_primitives import (
    build_monitoring_snapshot_view,
    build_operator_report,
    build_review_surface,
    compute_state_check,
)


def _default_log_path() -> str:
    return str(Path('.siam/execution-log.jsonl'))


def _default_readiness_snapshot_path() -> str:
    return str(Path(DEFAULT_READINESS_SNAPSHOT_PATH))


def _default_alerts_snapshot_path() -> str:
    return str(Path(DEFAULT_ALERTS_SNAPSHOT_PATH))


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=True).encode('utf-8')


def _parse_int_query(query: dict[str, list[str]], key: str, default: int, *, minimum: int) -> int:
    try:
        value = int(query.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), value)


def build_api_handler(
    log_path_provider: Callable[[], str],
    readiness_snapshot_path_provider: Callable[[], str] = _default_readiness_snapshot_path,
    alerts_snapshot_path_provider: Callable[[], str] = _default_alerts_snapshot_path,
) -> type[BaseHTTPRequestHandler]:
    class SiamApiHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload: object, status: int = 200) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)

            if parts.path == '/api/monitoring/readiness':
                payload = get_readiness_snapshot_response(readiness_snapshot_path_provider())
                self._send_json(payload)
                return

            if parts.path == '/api/monitoring/alerts':
                payload = get_alerts_snapshot_response(alerts_snapshot_path_provider())
                self._send_json(payload)
                return

            if parts.path == '/api/monitoring':
                payload = get_monitoring_bundle_response(
                    readiness_path=readiness_snapshot_path_provider(),
                    alerts_path=alerts_snapshot_path_provider(),
                )
                self._send_json(payload)
                return

            log_path = query.get('log_path', [log_path_provider()])[0]

            if parts.path == '/api/safe/state-check':
                payload = compute_state_check(
                    log_path,
                    window=_parse_int_query(query, 'window', 50, minimum=1),
                )
                self._send_json(payload)
                return

            if parts.path == '/api/safe/review-surface':
                payload = build_review_surface(
                    log_path,
                    tail=_parse_int_query(query, 'tail', 5, minimum=0),
                )
                self._send_json(payload)
                return

            if parts.path == '/api/safe/operator-report':
                payload = build_operator_report(
                    log_path,
                    tail=_parse_int_query(query, 'tail', 5, minimum=0),
                )
                self._send_json(payload)
                return

            if parts.path == '/api/safe/monitoring-view':
                payload = build_monitoring_snapshot_view(
                    readiness_path=query.get('readiness_path', [readiness_snapshot_path_provider()])[0],
                    alerts_path=query.get('alerts_path', [alerts_snapshot_path_provider()])[0],
                    automation_log_path=log_path,
                )
                self._send_json(payload)
                return

            self._send_json({'error': 'not found'}, status=404)

        def log_message(self, format: str, *args: object) -> None:
            return

    return SiamApiHandler


def run_server(host: str = '127.0.0.1', port: int = 8780, log_path: str | None = None) -> None:
    resolved_log_path = log_path or _default_log_path()
    handler = build_api_handler(lambda: resolved_log_path)
    server = ThreadingHTTPServer((host, int(port)), handler)
    print(f'Siam API running at http://{host}:{port} (log_path={resolved_log_path})')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    run_server()
