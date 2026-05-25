"""CLI: static scaffold validation (Phase 3B).

Usage:
  python tools/validate_scaffold.py --project-id <id>
  python tools/validate_scaffold.py --scaffold-root <path>
  python tools/validate_scaffold.py --project-id <id> --json
  python tools/validate_scaffold.py --project-id <id> --no-write

SAFETY: No npm, no npx, no TypeScript compilation, no Playwright execution,
no browser launch, no URL fetching, no credentials, no external calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scaffold_validator import ScaffoldValidator


def _resolve_root(project_id: str | None, scaffold_root: str | None) -> Path:
    if scaffold_root:
        return Path(scaffold_root)
    if project_id:
        candidate = Path("outputs") / project_id / "03_framework" / "playwright"
        return candidate
    print("ERROR: provide --project-id or --scaffold-root", file=sys.stderr)
    sys.exit(1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Statically validate a generated Playwright scaffold (Phase 3B).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "No npm, npx, TypeScript, Playwright, browser, URL fetching, "
            "or credentials are used.\n"
            "All checks are static file inspection only."
        ),
    )
    parser.add_argument("--project-id", metavar="ID", help="Project ID (looks up outputs/<id>/03_framework/playwright/)")
    parser.add_argument("--scaffold-root", metavar="PATH", help="Direct path to scaffold root directory")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output validation report as JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="Skip writing artifact files (dry run)")
    args = parser.parse_args(argv)

    root = _resolve_root(args.project_id, args.scaffold_root)
    project_id = args.project_id or root.name

    if not root.exists():
        print(f"ERROR: Scaffold root not found: {root}", file=sys.stderr)
        sys.exit(1)

    validator = ScaffoldValidator()
    report = validator.validate_scaffold(root, project_id)
    plan = validator.build_toolchain_validation_plan(root, project_id)

    if args.json_output:
        out = {"report": report.to_dict(), "plan": plan.to_dict()}
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        status_icon = {"pass": "[PASS]", "fail": "[FAIL]", "warning": "[WARN]", "unknown": "[???]"}
        icon = status_icon.get(report.validation_status, report.validation_status.upper())
        print(f"\nStatic Scaffold Validation {icon}")
        print(f"  Project:    {report.project_id}")
        print(f"  Root:       {report.scaffold_root}")
        print(f"  Checks run: {len(report.checks)}")
        print(f"  Blockers:   {len(report.blockers)}")
        print(f"  Warnings:   {len(report.warnings)}")
        print(f"  Safe to proceed: {report.safe_to_proceed_to_toolchain_validation}")
        print()

        if report.blockers:
            print("BLOCKERS:")
            for b in report.blockers:
                print(f"  - {b}")
            print()

        if report.warnings:
            print("WARNINGS:")
            for w in report.warnings:
                print(f"  - {w}")
            print()

        print("Safety invariants (all must be False):")
        print(f"  execution_performed:      {report.execution_performed}")
        print(f"  npm_performed:            {report.npm_performed}")
        print(f"  npx_performed:            {report.npx_performed}")
        print(f"  browser_performed:        {report.browser_performed}")
        print(f"  external_calls_performed: {report.external_calls_performed}")
        print(f"  safe_to_execute_tests:    {report.safe_to_execute_tests}")
        print()

    if not args.no_write:
        paths = validator.render_validation_artifacts(report, plan, root)
        if not args.json_output:
            print("Artifacts written:")
            for key, path in paths.items():
                print(f"  {key}: {path}")
            print()

    if report.validation_status == "fail":
        if not args.json_output:
            print("Validation FAILED — resolve blockers before toolchain validation.")
        return 1

    if not args.json_output:
        print("Validation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
