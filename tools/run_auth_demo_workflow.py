"""
Phase 7R — Auth Demo Workflow CLI.

Runs the complete auth workbench demo: 7A→7B→7C→7D→client_report.

Usage:
  python tools/run_auth_demo_workflow.py
  python tools/run_auth_demo_workflow.py --project-id demo-auth-workflow
  python tools/run_auth_demo_workflow.py --outputs-root outputs --json

Safety:
  - Raw secrets NEVER accepted via CLI flags.
  - All scenarios run in planning-only or blocked mode.
  - approved_for_client_delivery is always False.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Blocked-flag guard — must run BEFORE argparse
# ---------------------------------------------------------------------------
_BLOCKED_FLAGS = (
    "--username",
    "--password",
    "--secret",
    "--token",
    "--cookie",
    "--access-token",
    "--bearer",
    "--client-secret",
)

for _arg in sys.argv[1:]:
    for _blocked in _BLOCKED_FLAGS:
        if _arg == _blocked or _arg.startswith(_blocked + "="):
            print(
                f"[7R] BLOCKED: '{_blocked}' is not accepted. "
                "Set credentials as OS-level env vars only — never via CLI flags.",
                file=sys.stderr,
            )
            sys.exit(1)

# ---------------------------------------------------------------------------
# Imports (after guard)
# ---------------------------------------------------------------------------
from core.auth_demo_workflow import DEMO_PROJECT_ID, AuthDemoWorkflow  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 7R — Auth Demo Workflow (7A→7B→7C→7D→client_report)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/run_auth_demo_workflow.py
  python tools/run_auth_demo_workflow.py --project-id my-project
  python tools/run_auth_demo_workflow.py --json

All scenarios run in planning-only or blocked mode.
No real credentials or storageState required for the demo.
        """,
    )
    p.add_argument(
        "--project-id",
        default=DEMO_PROJECT_ID,
        help=f"Project identifier (default: {DEMO_PROJECT_ID})",
    )
    p.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root directory for output artifacts (default: outputs)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print result as JSON instead of human-readable summary",
    )
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    workflow = AuthDemoWorkflow(outputs_root=Path(args.outputs_root))
    result = workflow.run(project_id=args.project_id)

    if args.output_json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"\n[7R] Auth Demo Workflow — {args.project_id}")
        print(f"  Scenarios: {len(result.scenarios)}")

        by_category: dict[str, list] = {}
        for s in result.scenarios:
            by_category.setdefault(s.category, []).append(s)

        for category in ("executed", "planned", "skipped", "blocked"):
            items = by_category.get(category, [])
            if items:
                print(f"\n  {category.upper()} ({len(items)}):")
                for s in items:
                    print(f"    [{s.phase}] {s.name}: {s.status}")

        print("\n  Artifacts:")
        if result.capability_plan_path:
            print(f"    7A capability plan : {result.capability_plan_path}")
        if result.strategy_decision_path:
            print(f"    7B strategy        : {result.strategy_decision_path}")
        if result.google_oauth_report_path:
            print(f"    7C google oauth    : {result.google_oauth_report_path}")
        if result.email_password_report_path:
            print(f"    7D email/password  : {result.email_password_report_path}")
        if result.client_report_path:
            print(f"    client report      : {result.client_report_path}")

        print(
            "\n  Safety: approved_for_client_delivery=False, "
            "human_review_required=True"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
