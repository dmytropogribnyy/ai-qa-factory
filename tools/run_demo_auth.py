"""CLI: run_demo_auth.py — Phase 4F Approved Demo Auth Execution.

Runs approval-gated demo auth smoke against the SauceDemo public demo target only.
No real credentials. No personal/production accounts. No Alza/Amazon/Google/Linear auth.

Usage:
    # Preview only (no execution, no credentials):
    python tools/run_demo_auth.py --project-id demo

    # Approved SauceDemo auth smoke:
    python tools/run_demo_auth.py --project-id demo --approve-demo-auth-execution --auth-profile saucedemo_demo_auth --command-mode auth_smoke

    # Approved SauceDemo auth setup (storageState):
    python tools/run_demo_auth.py --project-id demo --approve-demo-auth-execution --auth-profile saucedemo_demo_auth --command-mode auth_setup

    # Direct scaffold root:
    python tools/run_demo_auth.py --scaffold-root outputs/demo/03_framework/playwright --approve-demo-auth-execution --auth-profile saucedemo_demo_auth --command-mode auth_smoke

    # JSON output:
    python tools/run_demo_auth.py --project-id demo --json
    python tools/run_demo_auth.py --project-id demo --approve-demo-auth-execution --auth-profile saucedemo_demo_auth --command-mode auth_smoke --json

This phase does NOT authorize:
    - Alza.sk auth
    - Amazon.com auth
    - Google/OAuth personal login
    - Linear/LinkedIn/Upwork auth
    - Any personal or production account
    - Payment/checkout/order creation
    - Scraping/crawling/load/security testing
    - Client delivery
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.demo_auth_runner import DemoAuthRunner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 4F: Approved Demo Auth Execution — SauceDemo public demo only.\n"
            "No real credentials. No personal/production accounts.\n"
            "No Alza/Amazon/Google/Linear auth."
        )
    )
    parser.add_argument("--project-id", default=None, help="Project ID")
    parser.add_argument(
        "--scaffold-root", default=None,
        help="Path to scaffold root (default: outputs/<project_id>/03_framework/playwright)"
    )
    parser.add_argument(
        "--from-output", default=None,
        help="Path to outputs/<project_id> directory"
    )
    parser.add_argument(
        "--approve-demo-auth-execution", action="store_true",
        help="Explicit approval flag for demo auth execution (required for any execution)"
    )
    parser.add_argument(
        "--auth-profile", default=None,
        help="Auth profile to use (only saucedemo_demo_auth allowed in Phase 4F)"
    )
    parser.add_argument(
        "--command-mode", default="auth_smoke",
        choices=["auth_smoke", "auth_setup"],
        help="Command mode: auth_smoke (run tests) or auth_setup (generate storageState)"
    )
    parser.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="Do not write artifacts to disk")
    parser.add_argument("--timeout", type=int, default=120, help="Subprocess timeout in seconds")
    parser.add_argument(
        "--outputs-root", default="outputs",
        help="Outputs root directory (default: outputs)"
    )
    args = parser.parse_args(argv)

    if not args.project_id and not args.from_output and not args.scaffold_root:
        print("Error: --project-id, --from-output, or --scaffold-root is required.", file=sys.stderr)
        return 2

    outputs_root = Path(args.outputs_root)
    runner = DemoAuthRunner(outputs_root=outputs_root)

    project_id = args.project_id
    if not project_id and args.from_output:
        project_id = Path(args.from_output).name
    if not project_id and args.scaffold_root:
        project_id = "unknown"

    scaffold_root = Path(args.scaffold_root) if args.scaffold_root else None

    report = runner.run_demo_auth_execution(
        project_id=project_id,
        scaffold_root=scaffold_root,
        approve_demo_auth=args.approve_demo_auth_execution,
        auth_profile=args.auth_profile,
        command_mode=args.command_mode,
        timeout=args.timeout,
    )

    if args.json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.execution_status not in ("blocked",) else 1

    if not args.no_write and project_id != "unknown":
        paths = runner.render_auth_artifacts(report, project_id)
        print("Auth artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nAuth Execution Report")
    print(f"  project_id:                  {report.project_id}")
    print(f"  execution_status:            {report.execution_status}")
    print(f"  approved:                    {report.approved}")
    print(f"  demo_profile:                {report.demo_profile}")
    print(f"  auth_execution_performed:    {report.auth_execution_performed}")
    print(f"  browser_execution_performed: {report.browser_execution_performed}")
    print(f"  storage_state_created:       {report.storage_state_created}")
    print(f"  credentials_used:            {report.credentials_used}")
    print(f"  real_credentials_used:       {report.real_credentials_used}")
    print(f"  personal_account_used:       {report.personal_account_used}")
    print(f"  production_account_used:     {report.production_account_used}")
    print(f"  safe_to_deliver:             {report.safe_to_deliver}")
    print(f"  approved_for_client_delivery:{report.approved_for_client_delivery}")
    print(f"  blockers:                    {len(report.blockers)}")
    print(f"  warnings:                    {len(report.warnings)}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  - {w}")

    print("\nSafety boundary:")
    print("  No real credentials used.")
    print("  No personal/production account used.")
    print("  No Alza/Amazon/Google/Linear auth.")
    print("  No payment/checkout/order.")
    print("  safe_to_deliver=False.")
    print("  approved_for_client_delivery=False.")

    if report.execution_status == "blocked":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
