from __future__ import annotations

import argparse

from .server import run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Siam read-only mini dashboard")
    parser.add_argument("command", choices=("serve",), nargs="?", default="serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        run_server(args.host, args.port)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

