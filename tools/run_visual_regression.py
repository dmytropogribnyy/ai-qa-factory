"""
Phase 5I — CLI: run visual regression.

Usage:
  # Capture baselines (first run):
  python tools/run_visual_regression.py \\
    --project-id my-project \\
    --target-url https://www.saucedemo.com \\
    --mode capture \\
    --approve-visual-regression

  # Compare against baselines:
  python tools/run_visual_regression.py \\
    --project-id my-project \\
    --target-url https://www.saucedemo.com \\
    --mode compare \\
    --approve-visual-regression

  # Mobile device visual regression:
  python tools/run_visual_regression.py \\
    --project-id my-project \\
    --target-url https://www.amazon.com/dp/B08N5WRWNW \\
    --mode capture \\
    --device "iPhone 14" \\
    --approve-visual-regression

SAFETY:
- No credentials, no auth.
- Raw secret flags never accepted.
- Baselines stored in outputs/<project_id>/18_visual_regression/ (gitignored).
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
                    f"[BLOCKED] Flag '{blocked}' is not allowed.",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5I: Run visual regression (capture / compare / update)."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--target-url", required=True,
                        help="URL to test visually")
    parser.add_argument("--mode", default="compare",
                        choices=["capture", "compare", "update"],
                        help="capture=create baselines, compare=diff, update=overwrite baselines")
    parser.add_argument("--device",
                        help="Optional device name for mobile viewport (e.g. 'iPhone 14')")
    parser.add_argument("--threshold", type=float, default=0.01,
                        help="Max diff ratio (0.01=1%%, default 0.01)")
    parser.add_argument("--approve-visual-regression", action="store_true",
                        help="Confirm approval for visual regression execution")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to outputs/")
    parser.add_argument("--timeout", type=int, default=120)

    args = parser.parse_args()

    from core.visual_regression_runner import VisualRegressionRunner
    runner = VisualRegressionRunner(outputs_root=Path("outputs"))

    report = runner.run(
        project_id=args.project_id,
        target_url=args.target_url,
        mode=args.mode,
        device_name=args.device or "",
        approve_visual_regression=args.approve_visual_regression,
        threshold_ratio=args.threshold,
        timeout=args.timeout,
    )

    print(f"Status:         {report.execution_status}")
    print(f"Mode:           {report.mode}")
    print(f"Target:         {report.target_url}")
    print(f"Tests:          {report.total_tests} total / {report.passed} passed / {report.failed} failed")
    if report.new_baselines:
        print(f"New baselines:  {report.new_baselines}")
    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if not args.no_write and report.execution_status != "blocked":
        paths = runner.render_artifacts(report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(0 if report.execution_status == "complete" and not report.failed else 1)


if __name__ == "__main__":
    main()
