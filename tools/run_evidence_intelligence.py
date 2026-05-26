"""
Phase 5K — CLI: Run Evidence Intelligence.

Read-only static analysis of existing evidence artifacts for a project.
No approval flag required — this tool never executes tests or makes network calls.

Usage:
  python tools/run_evidence_intelligence.py --project-id my-project

  python tools/run_evidence_intelligence.py \\
    --project-id my-project \\
    --areas auth api database

SAFETY:
- Read-only file analysis only — no subprocess, no network calls.
- No credentials accepted via CLI.
- safe_to_deliver=False always.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key",
    "--cookie", "--pat", "--access-token", "--bearer",
)


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
        description="Phase 5K: Evidence Intelligence — analyze artifact coverage gaps."
    )
    parser.add_argument("--project-id", required=True,
                        help="Project identifier to analyze")
    parser.add_argument("--areas", nargs="+", default=None,
                        help="Specific coverage areas to check (default: all)")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to disk")

    args = parser.parse_args()

    from core.evidence_intelligence import EvidenceIntelligence

    ei = EvidenceIntelligence(outputs_root=Path("outputs"))
    report = ei.analyze(
        project_id=args.project_id,
        areas_to_check=args.areas,
    )

    print(f"Evidence Intelligence — project: {args.project_id}")
    print(f"Coverage score:    {report.overall_coverage_score:.1%}")
    print(f"High-severity gaps: {report.high_severity_gap_count}")
    print(f"Total gaps:        {len(report.gaps)}")
    print()

    if report.coverage_items:
        print("Coverage:")
        for item in report.coverage_items:
            status = "YES" if item.present else " NO"
            print(f"  [{status}] {item.area} ({item.artifact_count} artifacts)")

    if report.gaps:
        print("\nGaps:")
        for gap in report.gaps:
            print(f"  [{gap.severity.upper()}] {gap.area}: {gap.description}")

    if report.recommendations:
        print("\nRecommendations:")
        for r in report.recommendations:
            print(f"  - {r}")

    if report.notes:
        for n in report.notes:
            print(f"  Note: {n}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if not args.no_write:
        paths = ei.render_artifacts(report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(1 if report.blockers else 0)


if __name__ == "__main__":
    main()
