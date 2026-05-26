"""CLI: Build Scenario Execution Matrix — Phase 4G.

No execution. No credentials. No external calls.
Builds the canonical scenario execution matrix, permission routing table,
and dedicated test-account plan.

Usage:
  python tools/build_execution_matrix.py --project-id demo
  python tools/build_execution_matrix.py --project-id demo --json
  python tools/build_execution_matrix.py --project-id demo --no-write
  python tools/build_execution_matrix.py --project-id demo --include-test-account-plan
  python tools/build_execution_matrix.py --project-id demo \\
      --decide-url https://www.saucedemo.com --scenario-type no_auth_smoke
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4G: Scenario Execution Matrix — routing/policy/planning only. No execution."
    )
    parser.add_argument("--project-id", help="Project ID")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Print matrix JSON to stdout")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to outputs/")
    parser.add_argument("--include-test-account-plan", action="store_true",
                        help="Include dedicated test-account plan in matrix (default: included)")
    parser.add_argument("--decide-url", default=None,
                        help="Classify this URL into an execution lane")
    parser.add_argument("--scenario-type", default=None,
                        help="Scenario type hint for decision (e.g. no_auth_smoke, demo_auth, readonly_smoke)")
    parser.add_argument("--target-category", default=None,
                        help="Target category override for decision")
    parser.add_argument("--profile", default=None,
                        help="Profile hint for decision")
    parser.add_argument("--outputs-root", default=None,
                        help="Override outputs root directory")

    args = parser.parse_args(argv)

    if not args.project_id:
        print("Error: --project-id is required.", file=sys.stderr)
        return 2

    from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder

    outputs_root = Path(args.outputs_root) if args.outputs_root else None
    builder = ScenarioExecutionMatrixBuilder(outputs_root=outputs_root)

    include_plan = True  # always include by default, flag just makes it explicit

    report = builder.build_matrix(
        project_id=args.project_id,
        include_test_account_plan=include_plan,
        decision_url=args.decide_url,
        scenario_type=args.scenario_type,
        target_category=args.target_category,
        profile=args.profile,
    )

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return 0

    # Human-readable summary
    print("\nScenario Execution Matrix — Phase 4G")
    print(f"  project_id:        {report.project_id}")
    print(f"  matrix_version:    {report.matrix_version}")
    print(f"  lanes_total:       {len(report.lanes)}")
    print(f"  allowed_now:       {report.allowed_now_count}")
    print(f"  planned:           {report.planned_count}")
    print(f"  blocked:           {report.blocked_count}")

    if report.decisions:
        d = report.decisions[0]
        print("\nExecution Decision")
        print(f"  input:             {d.input_label}")
        print(f"  target_url:        {d.target_url}")
        print(f"  execution_lane:    {d.execution_lane}")
        print(f"  allowed_now:       {d.allowed_now}")
        print(f"  implemented_now:   {d.implemented_now}")
        if d.required_approval_flags:
            print(f"  approval_flags:    {', '.join(d.required_approval_flags)}")
        if d.selected_tool:
            print(f"  selected_tool:     {d.selected_tool}")
        if d.blockers:
            print(f"  blockers:          {len(d.blockers)}")
            for b in d.blockers:
                print(f"    - {b}")
        if d.safe_next_steps:
            print("  safe_next_steps:")
            for s in d.safe_next_steps:
                print(f"    - {s}")

    if report.dedicated_test_account_plan:
        plan = report.dedicated_test_account_plan
        print("\nDedicated Test Account Plan")
        print(f"  allowed_now:             {plan.allowed_now}")
        print(f"  safe_for_execution_now:  {plan.safe_for_execution_now}")
        print(f"  requirements:            {len(plan.requirements)}")
        print(f"  provisioning_routes:     {len(plan.provisioning_routes)}")

    if not args.no_write:
        paths = builder.render_matrix_artifacts(report, args.project_id)
        print("\nMatrix artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nSafety boundary:")
    print("  No execution performed.")
    print("  No credentials used.")
    print("  No external calls made.")
    print("  Routing/policy/planning only.")
    print("  personal_account_allowed=False.")
    print("  production_account_allowed=False.")
    print("  repo_storage_allowed=False.")
    print("  safe_for_execution_now=False.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
