"""
Phase 5K — CLI: Run Intake Agent.

Classifies a work request (requirements text) into a test type, risk level,
and recommended pipeline modules. Raw text is never stored in artifacts.

Usage:
  python tools/run_intake_agent.py \\
    --project-id my-project \\
    --input-file path/to/requirements.txt

  python tools/run_intake_agent.py \\
    --project-id my-project \\
    --input-text "We need to test the login API and session management"

SAFETY:
- Raw text is never stored in any artifact.
- No credentials, tokens, or secrets accepted via CLI.
- Heuristic mode only in Phase 5K (no LLM calls).
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
                    f"[BLOCKED] Flag '{blocked}' is not allowed. "
                    "Pass secrets via env var only.",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5K: Intake Agent — classify a work request."
    )
    parser.add_argument("--project-id", required=True,
                        help="Output project identifier")
    parser.add_argument("--input-file", default="",
                        help="Path to a text file containing the requirements")
    parser.add_argument("--input-text", default="",
                        help="Short requirements text (use --input-file for longer text)")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to disk")

    args = parser.parse_args()

    if not args.input_file and not args.input_text:
        print(
            "[ERROR] Provide --input-file <path> or --input-text <text>",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.input_file and args.input_text:
        print(
            "[ERROR] Provide only one of --input-file or --input-text, not both.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Read input
    raw_input = ""
    if args.input_file:
        input_path = Path(args.input_file)
        if not input_path.exists():
            print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
            sys.exit(2)
        raw_input = input_path.read_text(encoding="utf-8")
    else:
        raw_input = args.input_text

    from core.intake_agent import IntakeAgent

    agent = IntakeAgent(outputs_root=Path("outputs"))
    report = agent.analyze(raw_input=raw_input, project_id=args.project_id)

    c = report.classification
    print(f"Intake analysis — project: {args.project_id}")
    print(f"Classification:  {c.classification}")
    print(f"Confidence:      {c.confidence:.1%}")
    print(f"Risk level:      {c.risk_level}")
    if c.recommended_modules:
        print(f"Recommended:     {', '.join(c.recommended_modules)}")
    if c.secondary_classifications:
        print(f"Secondary:       {', '.join(c.secondary_classifications)}")
    if c.evidence_keywords:
        print(f"Evidence:        {', '.join(c.evidence_keywords[:5])}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if not args.no_write:
        paths = agent.render_artifacts(report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(1 if report.blockers else 0)


if __name__ == "__main__":
    main()
