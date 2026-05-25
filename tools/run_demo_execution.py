"""CLI: run_demo_execution.py — Phase 4D Controlled Browser Execution Runner.

Runs approval-gated Playwright commands against safe demo/local/public-readonly targets.

No general production execution.
No real credentials.
No payment/checkout/destructive actions.
No scraping/crawling/load/security testing.
No client delivery.

Usage (no execution — blocked preview):
    python tools/run_demo_execution.py --project-id demo

Approved local list execution:
    python tools/run_demo_execution.py --project-id demo --approve-demo-execution --target-category local --command-mode list

Approved SauceDemo list execution:
    python tools/run_demo_execution.py --project-id demo --approve-demo-execution --demo-profile saucedemo_public_demo --command-mode list

Approved SauceDemo smoke execution:
    python tools/run_demo_execution.py --project-id demo --approve-demo-execution --demo-profile saucedemo_public_demo --command-mode smoke

Approved Playwright.dev read-only list execution:
    python tools/run_demo_execution.py --project-id demo --approve-public-readonly-execution --readonly-profile playwright_docs_readonly --command-mode list

Approved Playwright.dev read-only smoke execution:
    python tools/run_demo_execution.py --project-id demo --approve-public-readonly-execution --readonly-profile playwright_docs_readonly --command-mode readonly_smoke

Blocked Alza example:
    python tools/run_demo_execution.py --project-id demo --approve-public-readonly-execution --target-category real_public_readonly --base-url https://www.alza.sk

Blocked Amazon example:
    python tools/run_demo_execution.py --project-id demo --approve-public-readonly-execution --target-category high_risk_marketplace_readonly --base-url https://www.amazon.com

Blocked Linear example:
    python tools/run_demo_execution.py --project-id demo --approve-demo-execution --target-category task_source --base-url https://linear.app/acme/issue/QA-123/example

Direct scaffold root:
    python tools/run_demo_execution.py --scaffold-root outputs/demo/03_framework/playwright --approve-demo-execution --target-category local --command-mode list

JSON output:
    python tools/run_demo_execution.py --project-id demo --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.browser_execution_runner import BrowserExecutionRunner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4D: Controlled Browser Execution — approval-gated demo/local/public-readonly only."
    )
    parser.add_argument("--project-id", default=None, help="Project ID")
    parser.add_argument("--scaffold-root", default=None, help="Direct scaffold root path")
    parser.add_argument("--from-output", action="store_true", help="Resolve scaffold from outputs/<project_id>/")
    parser.add_argument(
        "--approve-demo-execution", action="store_true",
        help="Approve local/localhost/public_demo_target execution only",
    )
    parser.add_argument(
        "--approve-public-readonly-execution", action="store_true",
        help="Approve playwright_docs_readonly read-only smoke only",
    )
    parser.add_argument(
        "--target-category", default=None,
        choices=["local", "localhost", "public_demo_target", "real_public_readonly",
                 "high_risk_marketplace_readonly", "production", "task_source", "unknown"],
        help="Explicit target category",
    )
    parser.add_argument("--base-url", default=None, help="Base URL for target")
    parser.add_argument(
        "--demo-profile", default=None,
        choices=["saucedemo_public_demo", "the_internet_public_demo", "local"],
        help="Demo profile (sets base URL and category automatically)",
    )
    parser.add_argument(
        "--readonly-profile", default=None,
        choices=["playwright_docs_readonly"],
        help="Read-only profile (only playwright_docs_readonly allowed)",
    )
    parser.add_argument(
        "--command-mode", default="list",
        choices=["list", "smoke", "readonly_smoke"],
        help="Command mode: list (--list only), smoke (tests/smoke), readonly_smoke (tests/smoke read-only)",
    )
    parser.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="Do not write artifacts to disk")
    parser.add_argument("--timeout", type=int, default=120, help="Subprocess timeout in seconds (default: 120)")
    parser.add_argument(
        "--outputs-root", default="outputs", help="Outputs root directory (default: outputs)"
    )
    args = parser.parse_args(argv)

    # Require at least one of --project-id or --scaffold-root
    if not args.project_id and not args.scaffold_root:
        print("Error: --project-id or --scaffold-root is required.", file=sys.stderr)
        return 2

    outputs_root = Path(args.outputs_root)
    runner = BrowserExecutionRunner(outputs_root=outputs_root)

    project_id = args.project_id or "scaffold_root_run"
    scaffold_root = Path(args.scaffold_root) if args.scaffold_root else None

    report = runner.run_browser_execution(
        project_id=project_id,
        scaffold_root=scaffold_root,
        approve_demo=args.approve_demo_execution,
        approve_public_readonly=args.approve_public_readonly_execution,
        target_category=args.target_category,
        base_url=args.base_url,
        demo_profile=args.demo_profile,
        readonly_profile=args.readonly_profile,
        command_mode=args.command_mode,
        timeout=args.timeout,
    )

    approval = runner.build_approval(
        project_id=project_id,
        approve_demo=args.approve_demo_execution,
        approve_public_readonly=args.approve_public_readonly_execution,
        target_category=report.target_category,
        base_url=report.target_url,
        demo_profile=args.demo_profile,
        readonly_profile=args.readonly_profile,
        command_mode=args.command_mode,
    )

    if args.json_out:
        print(json.dumps({
            "approval": approval.to_dict(),
            "report": report.to_dict(),
        }, indent=2))
        return 0

    if not args.no_write:
        paths = runner.render_execution_artifacts(approval, report, project_id)
        print("Browser execution artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nBrowser Execution Report")
    print(f"  project_id:                          {report.project_id}")
    print(f"  execution_status:                    {report.execution_status}")
    print(f"  approved:                            {report.approved}")
    print(f"  target_category:                     {report.target_category}")
    print(f"  command_mode:                        {report.command_mode}")
    if report.demo_profile:
        print(f"  demo_profile:                        {report.demo_profile}")
    if report.readonly_profile:
        print(f"  readonly_profile:                    {report.readonly_profile}")
    print(f"  browser_execution_performed:         {report.browser_execution_performed}")
    print(f"  playwright_test_execution_performed: {report.playwright_test_execution_performed}")
    print(f"  public_readonly_target_used:         {report.public_readonly_target_used}")
    print(f"  credentials_used:                    {report.credentials_used}")
    print(f"  safe_to_deliver:                     {report.safe_to_deliver}")
    print(f"  approved_for_client_delivery:        {report.approved_for_client_delivery}")
    print(f"  blockers:                            {len(report.blockers)}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if report.commands:
        print("\nCommands:")
        for cmd in report.commands:
            print(f"  [{cmd.status.upper()}] {cmd.command}")
            if cmd.skipped_reason:
                print(f"    Reason: {cmd.skipped_reason}")
            if cmd.executed and cmd.exit_code is not None:
                print(f"    Exit code: {cmd.exit_code}")

    print("\nSafety boundary:")
    print("  Approved demo/local/public-readonly execution only.")
    print("  No general production target used.")
    print("  No credentials used.")
    print("  No client delivery created.")
    print("  safe_to_deliver=False.")
    print("  approved_for_client_delivery=False.")
    print("  Evidence internal-only.")

    # Exit code: 1 if blocked (not an error, just non-approval state)
    if report.execution_status == "blocked":
        return 1
    if report.execution_status == "error":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
