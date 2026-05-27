"""Phase 6 — QA Factory MCP Server CLI.

Default mode: start stdio MCP server (requires: pip install mcp).
List mode: --list-tools shows all available tools without starting the server.

Blocked flags (always exit 1):
  --approve-delivery   Delivery approval must come from human review, not CLI.
  --skip-review        Human review cannot be skipped.
  --auto-start-browser Browser execution requires explicit per-request approval flags.
  --credentials        Credentials must never be passed via CLI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from integrations.mcp.tool_handlers import APP_VERSION, TOOL_NAMES  # noqa: E402

_BLOCKED_FLAGS = {
    "--approve-delivery": "Delivery approval must be done via human review, not CLI.",
    "--skip-review": "Human review cannot be skipped (safety invariant).",
    "--auto-start-browser": "Browser execution requires per-request approval flags, not a global CLI flag.",
    "--credentials": "Credentials must never be passed via CLI to MCP tools.",
}


def _blocked_flag_check(args_list: list[str]) -> None:
    for flag, reason in _BLOCKED_FLAGS.items():
        if flag in args_list:
            print(f"[BLOCKED] {flag}: {reason}", file=sys.stderr)
            sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description=f"AI QA Factory v{APP_VERSION} — Phase 6 MCP Server",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        default=False,
        help="List all available MCP tools and exit",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        default=False,
        help="Print version and exit",
    )
    parser.add_argument(
        "--demo-health",
        action="store_true",
        default=False,
        help="Run qa_factory_health tool and print result (no MCP transport needed)",
    )
    args = parser.parse_args(argv)

    if args.version:
        print(f"AI QA Factory MCP Server v{APP_VERSION}")
        return

    if args.list_tools:
        print(f"AI QA Factory MCP Server v{APP_VERSION} — Available tools ({len(TOOL_NAMES)}):")
        for name in TOOL_NAMES:
            print(f"  - {name}")
        print()
        print("Start server: python tools/run_mcp_server.py")
        print("Install:      pip install mcp")
        return

    if args.demo_health:
        from integrations.mcp.tool_handlers import handle_qa_factory_health
        result = handle_qa_factory_health({})
        print(json.dumps(result, indent=2))
        return

    # Default: start MCP server
    try:
        import asyncio
        from integrations.mcp.server import run_server
        asyncio.run(run_server())
    except ImportError as exc:
        print(
            f"[ERROR] {exc}\n"
            "Install the mcp package: pip install mcp\n"
            "Then re-run: python tools/run_mcp_server.py",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
