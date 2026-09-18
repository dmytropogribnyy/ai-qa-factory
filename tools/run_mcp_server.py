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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from integrations.mcp.observer_handlers import OBSERVER_TOOL_NAMES  # noqa: E402
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
    args_list = sys.argv[1:] if argv is None else argv
    _blocked_flag_check(args_list)

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
    parser.add_argument("--http", action="store_true", default=False,
                        help="Serve over authenticated streamable-HTTP (needs AIQA_MCP_TOKEN)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (default loopback)")
    # Deliberately NOT the Dashboard's 8765. This endpoint is the one meant to be reachable through
    # a tunnel; the Dashboard authenticates nothing on its read paths. Sharing a default let
    # "point your tunnel at 8765" read as sensible advice while publishing the Dashboard instead.
    parser.add_argument("--port", type=int, default=8770,
                        help="HTTP port (default 8770; never the Dashboard's 8765)")
    # The ONLY way to reach the operator catalog. Deliberately a flag rather than an environment
    # variable: a tunnel child inherits its parent's environment, so an inherited value must never be
    # able to widen the remote catalog. Omitted -> the restricted observer role.
    parser.add_argument("--role", choices=("observer", "operator"), default=None,
                        help="MCP role for THIS process (default: observer, read-only)")
    args = parser.parse_args(argv)

    from integrations.mcp.server import set_role, tool_names
    active_role = set_role(args.role)

    if args.version:
        print(f"AI QA Factory MCP Server v{APP_VERSION}")
        return

    if args.list_tools:
        # Role-scoped, so the listing can never advertise a tool this process would refuse to run.
        exposed = set(tool_names(active_role))
        planning = [n for n in TOOL_NAMES if n in exposed]
        observer = [n for n in OBSERVER_TOOL_NAMES if n in exposed]
        print(f"AI QA Factory MCP Server v{APP_VERSION} — Available tools "
              f"({len(exposed)}, role: {active_role}):")
        print(f" Planning tools ({len(planning)}):")
        for name in planning:
            print(f"  - {name}")
        print(f" Observer tools ({len(observer)}):")
        for name in observer:
            print(f"  - {name}")
        print()
        print("Start server: python tools/run_mcp_server.py")
        print("Install:      pip install mcp")
        print("Output root:  set AIQA_OUTPUT_ROOT (default: outputs)")
        return

    if args.demo_health:
        # Routed through the role-aware dispatch, not the raw handler: calling the handler directly
        # printed all seven planning tools regardless of role, so the default diagnostic advertised
        # tools this process can neither list nor dispatch. Health must have ONE meaning.
        from integrations.mcp.server import _call_handler
        print(_call_handler("qa_factory_health", {}))
        return

    if args.http:
        try:
            from integrations.mcp.server import run_http_server
            print(f"[mcp] serving authenticated streamable-HTTP on http://{args.host}:{args.port}/mcp",
                  file=sys.stderr)
            run_http_server(host=args.host, port=args.port)
            return
        except ImportError as exc:
            print(f"[ERROR] {exc}\nInstall: pip install mcp uvicorn starlette", file=sys.stderr)
            sys.exit(1)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)

    # Default: start MCP server over stdio
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
