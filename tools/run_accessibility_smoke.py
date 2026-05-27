"""Phase 5N — Accessibility smoke CLI.

Default mode: generate Playwright + axe-core skeleton spec (no network calls).
Approved execution mode: generate execution-ready spec with approval flags.

Safety: blocked flags (--allow-active-scan, --bypass-auth, --allow-exploit) always exit 1.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from core.accessibility_runner import AccessibilityRunner  # noqa: E402

_BLOCKED_FLAGS = {
    "--allow-active-scan": "Active scanning is always blocked (safety invariant).",
    "--bypass-auth": "Auth bypass is always blocked (safety invariant).",
    "--allow-exploit": "Exploit attempts are always blocked (safety invariant).",
    "--skip-human-review": "Human review cannot be skipped (safety invariant).",
    "--approve-delivery": "Delivery approval must be done via human review, not CLI.",
}


def _blocked_flag_check(args_list: list[str]) -> None:
    for flag, reason in _BLOCKED_FLAGS.items():
        if flag in args_list:
            print(f"[BLOCKED] {flag}: {reason}", file=sys.stderr)
            sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description="AI QA Factory — Phase 5N Accessibility Smoke Generator",
    )
    parser.add_argument("--project-id", required=True, help="Project identifier")
    parser.add_argument("--target-url", required=True, help="URL to plan accessibility checks for")
    parser.add_argument(
        "--wcag-level",
        default="AA",
        choices=["A", "AA", "AAA"],
        help="WCAG compliance level (default: AA)",
    )
    parser.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root directory for output artifacts (default: outputs)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Request approved execution mode (requires approval flags below)",
    )
    parser.add_argument(
        "--approve-public-readonly-execution",
        action="store_true",
        default=False,
        help="Approve public read-only browser execution",
    )
    parser.add_argument(
        "--approve-browser-execution",
        action="store_true",
        default=False,
        help="Approve browser-based accessibility check execution",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        default=False,
        help="Dry run — do not write output files",
    )
    args = parser.parse_args(argv)

    runner = AccessibilityRunner(
        project_id=args.project_id,
        target_url=args.target_url,
        outputs_root=args.outputs_root,
        wcag_level=args.wcag_level,
    )

    if args.execute:
        try:
            report = runner.execute(
                approve_public_readonly=args.approve_public_readonly_execution,
                approve_browser_execution=args.approve_browser_execution,
                write_files=not args.no_write,
            )
        except ValueError as exc:
            print(f"[BLOCKED] {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        report = runner.generate_plan(write_files=not args.no_write)

    print(f"[OK] Accessibility smoke — status: {report.status}")
    print(f"     Project:   {report.project_id}")
    print(f"     Target:    {report.target_url}")
    print(f"     WCAG:      {report.wcag_level}")
    print(f"     Checks:    {len(report.checks_planned)} planned")
    if report.generated_test_file:
        print(f"     Spec:      {report.generated_test_file}")
    print(f"     Read-only: {report.read_only} | Active scan: {report.active_scan_allowed}")
    print(f"     Human review required: {report.human_review_required}")
    print()
    print("[NOTE] Delivery report will show 'Generated checks only' until execution is approved.")


if __name__ == "__main__":
    main()
