from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .adapters import SiamDashboardAdapter
from .render_operational import render_dashboard


def build_dashboard_handler(adapter: SiamDashboardAdapter) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        @staticmethod
        def _default_route_prompt() -> str:
            return "review MCP tool permissions"

        def _render_response(
            self,
            route_prompt: str,
            query_params: dict[str, str] | None = None,
        ) -> None:
            snapshot = adapter.collect_snapshot(route_prompt=route_prompt)
            html = render_dashboard(
                snapshot=snapshot,
                route_prompt=route_prompt,
                query=query_params or {},
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            if parts.path not in ("/", "/index.html"):
                self.send_error(404, "Not Found")
                return
            query = parse_qs(parts.query)
            route_prompt = query.get("route_prompt", [self._default_route_prompt()])[0]
            flat_query = {key: values[0] for key, values in query.items() if values}
            self._render_response(
                route_prompt=route_prompt,
                query_params=flat_query,
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def run_server(
    host: str,
    port: int,
    adapter_factory: Callable[[], SiamDashboardAdapter] = SiamDashboardAdapter,
) -> None:
    adapter = adapter_factory()
    server = ThreadingHTTPServer((host, port), build_dashboard_handler(adapter))
    print(f"Siam dashboard running at http://{host}:{port}")
    print("Use Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
