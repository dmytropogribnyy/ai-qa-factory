"""
Phase 4D/5H — CLI: Run Browser Execution.

Executes approved Playwright commands against narrowly allowlisted targets.
No credentials are accepted via CLI — use env vars only.

Usage (desktop read-only smoke):
  python tools/run_browser_execution.py \\
    --project-id my-project \\
    --readonly-profile amazon_public_readonly \\
    --target-url https://www.amazon.com \\
    --command-mode readonly_smoke \\
    --approve-public-readonly-execution

  python tools/run_browser_execution.py \\
    --project-id my-project \\
    --readonly-profile alza_public_readonly \\
    --target-url https://www.alza.cz \\
    --command-mode readonly_smoke \\
    --approve-public-readonly-execution

Usage (demo profiles):
  python tools/run_browser_execution.py \\
    --project-id my-project \\
    --demo-profile saucedemo_public_demo \\
    --command-mode smoke \\
    --approve-demo-execution

SAFETY:
- No credentials accepted via CLI.
- subprocess only for allowlisted Playwright commands.
- Amazon/Alza: read-only path gates enforced even with approval.
- auth/checkout/cart/payment paths always blocked.
- safe_to_deliver=False always.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key",
    "--cookie", "--pat", "--access-token", "--bearer",
    "--db-url", "--connection-string", "--dsn",
)


def _check_blocked_flags(argv: list) -> None:
    for flag in argv:
        flag_lower = flag.lower()
        for blocked in _BLOCKED_FLAGS:
            if flag_lower == blocked or flag_lower.startswith(blocked + "="):
                print(
                    f"[BLOCKED] Flag '{blocked}' is not allowed. "
                    "Pass secrets via env var only.",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 4D/5H: Browser Execution — controlled Playwright desktop smoke."
    )
    parser.add_argument("--project-id", required=True,
                        help="Output project identifier")
    parser.add_argument("--demo-profile", default="",
                        help="Demo profile name (e.g. saucedemo_public_demo)")
    parser.add_argument("--readonly-profile", default="",
                        help="Readonly profile name (e.g. amazon_public_readonly, alza_public_readonly)")
    parser.add_argument("--target-url", default="",
                        help="Override base URL for readonly profiles")
    parser.add_argument(
        "--command-mode",
        default="list",
        choices=["list", "smoke", "readonly_smoke"],
        help="Execution mode: list (dry run), smoke, or readonly_smoke",
    )
    parser.add_argument("--approve-demo-execution", action="store_true",
                        help="Approve execution of demo profile commands")
    parser.add_argument("--approve-public-readonly-execution", action="store_true",
                        help="Approve public read-only execution (Amazon, Alza, playwright.dev)")
    parser.add_argument("--scaffold-root", default="",
                        help="Override scaffold path (default: outputs/<project-id>/03_framework/playwright)")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to disk")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Subprocess timeout in seconds (default 120)")

    args = parser.parse_args()

    if not args.demo_profile and not args.readonly_profile:
        print(
            "[ERROR] Provide --demo-profile or --readonly-profile.",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.demo_profile and args.readonly_profile:
        print(
            "[ERROR] Provide only one of --demo-profile or --readonly-profile.",
            file=sys.stderr,
        )
        sys.exit(2)

    from core.browser_execution_runner import BrowserExecutionRunner

    runner = BrowserExecutionRunner(outputs_root=Path("outputs"))

    scaffold_root = Path(args.scaffold_root) if args.scaffold_root else None
    target_url = args.target_url or None

    report = runner.run_browser_execution(
        project_id=args.project_id,
        scaffold_root=scaffold_root,
        approve_demo=args.approve_demo_execution,
        approve_public_readonly=args.approve_public_readonly_execution,
        demo_profile=args.demo_profile or None,
        readonly_profile=args.readonly_profile or None,
        base_url=target_url,
        command_mode=args.command_mode,
        timeout=args.timeout,
    )

    profile_label = args.demo_profile or args.readonly_profile
    print(f"Browser Execution — project: {args.project_id}")
    print(f"Profile:     {profile_label}")
    print(f"Mode:        {args.command_mode}")
    print(f"Target URL:  {report.target_url or '(profile default)'}")
    print(f"Status:      {report.execution_status}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if report.notes:
        print("\nNotes:")
        for n in report.notes:
            print(f"  - {n}")

    if report.commands:
        print(f"\nCommands run: {len(report.commands)}")
        for cmd in report.commands:
            mark = "OK" if cmd.status == "pass" else "FAIL"
            print(f"  [{mark}] {cmd.status}  {cmd.command[:80]}")

    if not args.no_write:
        approval = runner.build_approval(
            project_id=args.project_id,
            approve_demo=args.approve_demo_execution,
            approve_public_readonly=args.approve_public_readonly_execution,
            target_category=report.target_category,
            base_url=report.target_url,
            demo_profile=args.demo_profile or None,
            readonly_profile=args.readonly_profile or None,
            command_mode=args.command_mode,
        )
        paths = runner.render_execution_artifacts(approval, report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(1 if report.blockers or report.execution_status in ("blocked", "error") else 0)


if __name__ == "__main__":
    main()
