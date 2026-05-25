"""CLI: plan_execution.py — Phase 4A Execution Readiness Planner.

Inspects local artifacts and generates execution approval checklist and readiness report.
No execution, no URL fetching, no credentials, no external calls.

Usage:
    python tools/plan_execution.py --project-id <id>
    python tools/plan_execution.py --project-id <id> --no-write
    python tools/plan_execution.py --project-id <id> --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_readiness_planner import ExecutionReadinessPlanner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4A: Execution Readiness Planner — local artifacts only, no execution."
    )
    parser.add_argument("--project-id", required=True, help="Project ID")
    parser.add_argument("--scaffold-root", default=None, help="Scaffold root path (optional)")
    parser.add_argument("--no-write", action="store_true", help="Do not write artifacts to disk")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    parser.add_argument(
        "--outputs-root", default="outputs", help="Outputs root directory (default: outputs)"
    )
    args = parser.parse_args(argv)

    outputs_root = Path(args.outputs_root)
    planner = ExecutionReadinessPlanner(outputs_root=outputs_root)

    scaffold_root = Path(args.scaffold_root) if args.scaffold_root else None
    checklist, report = planner.plan_readiness(args.project_id, scaffold_root)

    if args.json_out:
        print(json.dumps({
            "checklist": checklist.to_dict(),
            "readiness_report": report.to_dict(),
        }, indent=2))
        return 0

    if not args.no_write:
        paths = planner.render_execution_plan_artifacts(checklist, report, args.project_id)
        print("Execution plan artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nExecution Readiness Report")
    print(f"  project_id:                {report.project_id}")
    print(f"  readiness_status:          {report.readiness_status}")
    print(f"  approved_for_execution:    {report.approved_for_execution}")
    print(f"  evidence_plan_ready:       {report.evidence_plan_ready}")
    print(f"  blockers:                  {len(report.blockers)}")
    print(f"  required_approvals:        {len(report.required_approvals)}")

    print("\nSafety boundary:")
    print("  No execution performed.")
    print("  No URL fetching performed.")
    print("  No credentials used.")
    print("  No external calls performed.")
    print("  approved_for_execution=False.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
