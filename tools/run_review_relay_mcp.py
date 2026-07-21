"""Run the role-separated AI QA Factory Review Relay MCP server."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from integrations.mcp.review_relay_server import relay_role, run_http_server, run_server, tool_names  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AI QA Factory Review Relay MCP")
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8775)
    args = parser.parse_args(argv)
    try:
        role = relay_role()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if args.list_tools:
        print(f"Review Relay role={role}; tools ({len(tool_names(role))}):")
        for name in tool_names(role):
            print(f"  - {name}")
        return
    os.environ.setdefault("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    if args.http:
        run_http_server(host=args.host, port=args.port)
    else:
        asyncio.run(run_server())


if __name__ == "__main__":
    main()
