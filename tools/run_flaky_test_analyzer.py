"""Phase 5O — Flaky test analyzer CLI.

Default mode: static analysis + selector stability + healing proposals (no code changes).
Apply mode: apply proposals to spec files (requires --apply-proposals --approve-code-modification).

Blocked flags (always exit 1): --auto-fix, --skip-human-review, --approve-delivery.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from core.flaky_test_analyzer import FlakyTestAnalyzer  # noqa: E402

_BLOCKED_FLAGS = {
    "--auto-fix": "Automatic code fixes are always blocked (safety invariant).",
    "--skip-human-review": "Human review cannot be skipped (safety invariant).",
    "--approve-delivery": "Delivery approval must be done via human review, not CLI.",
    "--force-apply": "Force-apply is always blocked — use --apply-proposals with explicit approval.",
}


def _blocked_flag_check(args_list: list[str]) -> None:
    for flag, reason in _BLOCKED_FLAGS.items():
        if flag in args_list:
            print(f"[BLOCKED] {flag}: {reason}", file=sys.stderr)
            sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description="AI QA Factory — Phase 5O Flaky Test Analyzer",
    )
    parser.add_argument("--project-id", required=True, help="Project identifier")
    parser.add_argument(
        "--spec-files",
        nargs="*",
        default=[],
        help="Playwright spec file paths to analyze (default: auto-discover *.spec.ts)",
    )
    parser.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root directory for output artifacts (default: outputs)",
    )
    parser.add_argument(
        "--apply-proposals",
        action="store_true",
        default=False,
        help="Apply healing proposals to spec files (requires --approve-code-modification)",
    )
    parser.add_argument(
        "--approve-code-modification",
        action="store_true",
        default=False,
        help="Approve inserting healing TODO comments into spec files",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        default=False,
        help="Dry run — do not write output files",
    )
    args = parser.parse_args(argv)

    analyzer = FlakyTestAnalyzer(
        project_id=args.project_id,
        outputs_root=args.outputs_root,
        spec_files=args.spec_files or None,
    )

    # Always run analysis
    analysis = analyzer.analyze(write_files=not args.no_write)
    selector_report = analyzer.analyze_selectors(write_files=not args.no_write)
    healing_report = analyzer.generate_healing_proposals(write_files=not args.no_write)

    if args.apply_proposals:
        try:
            healing_report = analyzer.apply_proposals(
                healing_report,
                approve_code_modification=args.approve_code_modification,
                write_files=not args.no_write,
            )
        except ValueError as exc:
            print(f"[BLOCKED] {exc}", file=sys.stderr)
            sys.exit(1)

    print(f"[OK] Flaky test analysis — project: {analysis.project_id}")
    print(f"     Files analyzed: {len(analysis.files_analyzed)}")
    print(f"     Flakiness risks: {analysis.total_risks} ({analysis.risks_by_severity})")
    print(f"     Selector score:  {selector_report.stability_score}/100 "
          f"(strong={selector_report.strong_count} weak={selector_report.weak_count})")
    print(f"     Proposals:       {healing_report.total_proposals} generated, "
          f"{healing_report.applied_proposals} applied")
    print(f"     Status:          analysis={analysis.status} | healing={healing_report.status}")
    print(f"     Code modified:   {analysis.code_modification_allowed}")
    print(f"     Human review:    {analysis.human_review_required}")
    if healing_report.total_proposals > 0 and not args.apply_proposals:
        print()
        print("[NOTE] Proposals generated — review Self_Healing_Proposals.md before applying.")


if __name__ == "__main__":
    main()
