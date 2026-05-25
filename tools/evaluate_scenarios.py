"""CLI: evaluate_scenarios.py — Phase 4ABC Scenario Batch Evaluator.

Reads local fixture files from fixtures/client_scenarios/ and evaluates
safety expectations, category rules, and structural checks.
No URL fetching, no execution, no external calls.

Usage:
    python tools/evaluate_scenarios.py --project-id <id>
    python tools/evaluate_scenarios.py --project-id <id> --no-write
    python tools/evaluate_scenarios.py --project-id <id> --json
    python tools/evaluate_scenarios.py --project-id <id> --fixtures-root fixtures/client_scenarios
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scenario_batch_evaluator import ScenarioBatchEvaluator


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4ABC: Scenario Batch Evaluator — local fixtures only, no execution."
    )
    parser.add_argument("--project-id", required=True, help="Project ID")
    parser.add_argument(
        "--fixtures-root",
        default=None,
        help="Path to fixtures root (default: fixtures/client_scenarios)",
    )
    parser.add_argument("--no-write", action="store_true", help="Do not write artifacts to disk")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    parser.add_argument(
        "--outputs-root", default="outputs", help="Outputs root directory (default: outputs)"
    )
    args = parser.parse_args(argv)

    outputs_root = Path(args.outputs_root)
    fixtures_root = Path(args.fixtures_root) if args.fixtures_root else None
    evaluator = ScenarioBatchEvaluator(fixtures_root=fixtures_root, outputs_root=outputs_root)

    report = evaluator.evaluate_scenarios(args.project_id)

    if args.json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    if not args.no_write:
        paths = evaluator.render_scenario_evaluation_artifacts(report, args.project_id)
        print("Scenario evaluation artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nScenario Batch Evaluation")
    print(f"  project_id:                           {report.project_id}")
    print(f"  total_scenarios:                      {report.total_scenarios}")
    print(f"  passed:                               {report.passed_scenarios}")
    print(f"  warnings:                             {report.warning_scenarios}")
    print(f"  blocked:                              {report.blocked_scenarios}")
    print(f"  evaluation_performed_without_execution: {report.evaluation_performed_without_execution}")
    print(f"  external_calls_performed:             {report.external_calls_performed}")

    exit_code = 0
    if report.blocked_scenarios > 0:
        print(f"\n{report.blocked_scenarios} scenario(s) blocked — review SCENARIO_BATCH_EVALUATION.md")
        exit_code = 1

    print("\nSafety boundary:")
    print("  Local fixture files read only.")
    print("  No URL fetching performed.")
    print("  No execution performed.")
    print("  No external calls performed.")
    print("  external_calls_performed=False.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
