"""
Phase 5I — CLI: run mobile viewport smoke.

Usage:
  python tools/run_mobile_viewport_smoke.py \\
    --project-id my-project \\
    --device "iPhone 14" \\
    --approve-mobile-execution

  # Amazon mobile web readonly:
  python tools/run_mobile_viewport_smoke.py \\
    --project-id amazon-mobile-test \\
    --device "Pixel 7" \\
    --readonly-profile amazon_mobile_readonly \\
    --target-url https://www.amazon.com/dp/B08N5WRWNW \\
    --approve-mobile-execution

SAFETY:
- No credentials, no auth.
- Ecommerce readonly profiles apply the same path-gate and selector-scan as Phase 5H.
- Raw secret flags are never accepted.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = ("--password", "--token", "--secret", "--api-key", "--cookie", "--username")


def _check_blocked_flags(argv: list) -> None:
    for flag in argv:
        flag_lower = flag.lower()
        for blocked in _BLOCKED_FLAGS:
            if flag_lower == blocked or flag_lower.startswith(blocked + "="):
                print(
                    f"[BLOCKED] Flag '{blocked}' is not allowed. "
                    "Mobile viewport runner accepts no secret arguments.",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5I: Run mobile viewport Playwright smoke."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--device", required=True,
                        help="Device name (e.g. 'iPhone 14', 'Pixel 7', 'iPad Pro')")
    parser.add_argument("--command-mode", default="viewport_smoke",
                        choices=["list", "viewport_smoke"])
    parser.add_argument("--target-url",
                        help="Target URL for the smoke (optional; uses scaffold base URL)")
    parser.add_argument("--readonly-profile",
                        help="Mobile ecommerce readonly profile (e.g. amazon_mobile_readonly)")
    parser.add_argument("--approve-mobile-execution", action="store_true",
                        help="Confirm approval for mobile viewport execution")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to outputs/")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Subprocess timeout in seconds (default 120)")

    args = parser.parse_args()

    from core.mobile_viewport_runner import MobileViewportRunner
    runner = MobileViewportRunner(outputs_root=Path("outputs"))

    report = runner.run(
        project_id=args.project_id,
        device_name=args.device,
        command_mode=args.command_mode,
        target_url=args.target_url,
        readonly_profile=args.readonly_profile,
        approve_mobile_execution=args.approve_mobile_execution,
        timeout=args.timeout,
    )

    print(f"Status:         {report.execution_status}")
    print(f"Device:         {report.device_name}")
    print(f"Mode:           {report.command_mode}")
    if report.target_url:
        print(f"Target URL:     {report.target_url}")
    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")
    if report.notes:
        print("\nNotes:")
        for n in report.notes:
            print(f"  - {n}")

    if not args.no_write and report.execution_status != "blocked":
        paths = runner.render_artifacts(report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(0 if report.execution_status == "complete" else 1)


if __name__ == "__main__":
    main()
