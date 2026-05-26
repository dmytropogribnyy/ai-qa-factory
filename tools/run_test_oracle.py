"""
Phase 5K — CLI: Run Test Oracle.

Generates prioritized test scenarios from an IntakeReport or a classification.

Usage:
  # From a previously generated intake report:
  python tools/run_test_oracle.py \\
    --project-id my-project \\
    --intake-report-path outputs/my-project/22_intake/INTAKE_REPORT.json

  # From a classification string directly:
  python tools/run_test_oracle.py \\
    --project-id my-project \\
    --classification api_testing

SAFETY:
- Read-only: no execution, no network calls, no subprocess.
- No credentials accepted via CLI.
- Generated scenarios are planning artifacts only (executable_without_approval=False).
"""
from __future__ import annotations

import argparse
import json
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
        description="Phase 5K: Test Oracle — generate prioritized test scenarios."
    )
    parser.add_argument("--project-id", required=True,
                        help="Output project identifier")
    parser.add_argument("--intake-report-path", default="",
                        help="Path to a previously generated INTAKE_REPORT.json")
    parser.add_argument("--classification", default="",
                        help="Classification string (e.g. api_testing) — alternative to --intake-report-path")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to disk")

    args = parser.parse_args()

    if not args.intake_report_path and not args.classification:
        print(
            "[ERROR] Provide --intake-report-path or --classification.",
            file=sys.stderr,
        )
        sys.exit(2)

    from core.test_oracle import TestOracle
    from core.schemas.intake import IntakeReport, INTAKE_CLASSIFICATIONS

    oracle = TestOracle(outputs_root=Path("outputs"))

    if args.intake_report_path:
        p = Path(args.intake_report_path)
        if not p.exists():
            print(f"[ERROR] Intake report not found: {p}", file=sys.stderr)
            sys.exit(2)
        data = json.loads(p.read_text(encoding="utf-8"))
        intake_report = IntakeReport.from_dict(data)
        report = oracle.generate(intake_report=intake_report, project_id=args.project_id)
    else:
        if args.classification not in INTAKE_CLASSIFICATIONS:
            print(
                f"[ERROR] Unknown classification '{args.classification}'. "
                f"Valid: {', '.join(INTAKE_CLASSIFICATIONS)}",
                file=sys.stderr,
            )
            sys.exit(2)
        report = oracle.generate_from_classification(
            classification=args.classification,
            project_id=args.project_id,
        )

    print(f"Test Oracle — project: {args.project_id}")
    print(f"Classification: {report.source_classification}")
    print(f"Scenarios:      {report.total_scenarios}")
    print(f"Deferred:       {len(report.deferred_scenarios)}")
    print()
    for i, s in enumerate(report.scenarios, 1):
        print(f"  P{s.priority} [{s.risk_score:.0%}] {s.name}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if not args.no_write:
        paths = oracle.render_artifacts(report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(1 if report.blockers else 0)


if __name__ == "__main__":
    main()
