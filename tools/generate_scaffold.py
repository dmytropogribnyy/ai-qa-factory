"""generate_scaffold.py — generate a Playwright TypeScript scaffold for a project.

Phase 3A scaffold generation only:
- No URL fetching.
- No browser execution.
- No npm/npx execution.
- No TypeScript compilation.
- No credential use.
- No external calls.
- No test execution.
- Generated scaffold requires human review before any local validation.

Usage:
    python tools/generate_scaffold.py --project-id demo --input "Need Playwright tests for SaaS"
    python tools/generate_scaffold.py --from-output outputs/myproject --project-id myproject
    python tools/generate_scaffold.py --project-id demo --input "..." --no-write
    python tools/generate_scaffold.py --project-id demo --input "..." --json

Exit codes:
    0 = scaffold generated successfully
    1 = error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_OUTPUTS_ROOT = _PROJECT_ROOT / "outputs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_blueprint_from_output(output_dir: Path):
    """Load ProjectBlueprint from an existing output directory."""
    from core.schemas.project_blueprint import ProjectBlueprint
    bp_path = output_dir / "00_project" / "PROJECT_BLUEPRINT.json"
    if not bp_path.exists():
        raise FileNotFoundError(f"PROJECT_BLUEPRINT.json not found at {bp_path}")
    data = json.loads(bp_path.read_text(encoding="utf-8"))
    return ProjectBlueprint.from_dict(data)


def _load_strategy_from_output(output_dir: Path):
    """Load QAStrategy from an existing output directory. Returns None if missing."""
    from core.schemas.qa_strategy import QAStrategy
    st_path = output_dir / "02_strategy" / "QA_STRATEGY.json"
    if not st_path.exists():
        return None
    data = json.loads(st_path.read_text(encoding="utf-8"))
    return QAStrategy.from_dict(data)


def _run_full_pipeline(raw_text: str, project_id: str, write: bool):
    """Run Phase 2A + 2B + 2C + 3A pipeline from raw input text."""
    from core.workbench_controller import WorkbenchController
    ctrl = WorkbenchController(outputs_root=_OUTPUTS_ROOT if write else Path("outputs_dry"))
    result = ctrl.build_context_with_scaffold(
        raw_inputs=[raw_text],
        raw_text=raw_text,
        project_id=project_id,
    )
    return result


def _run_scaffold_only(blueprint, strategy, project_id: str, write: bool):
    """Run Phase 3A only — scaffold generation from existing blueprint + strategy."""
    from core.framework_scaffold_generator import FrameworkScaffoldGenerator
    if write:
        out_dir = _OUTPUTS_ROOT / project_id / "03_framework" / "playwright"
    else:
        out_dir = Path("outputs_dry") / project_id / "03_framework" / "playwright"
    return FrameworkScaffoldGenerator().generate_scaffold(blueprint, strategy, out_dir)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(result: dict, write: bool) -> int:
    scaffold = result.get("scaffold") if isinstance(result, dict) else result
    project_id = scaffold.project_id

    width = 72
    print()
    print("=" * width)
    print("  Phase 3A — Framework Scaffold Generator")
    print("=" * width)
    print(f"  Project ID:      {project_id}")
    print(f"  Framework type:  {scaffold.framework_type}")
    print(f"  Language:        {scaffold.language}")
    print(f"  Files generated: {len(scaffold.files)}")
    print(f"  Scaffold status: {scaffold.scaffold_status}")
    print(f"  Execution allowed: {scaffold.execution_allowed}")
    print(f"  Client visible:  {scaffold.client_visible}")
    print(f"  Requires review: {scaffold.requires_review}")
    print()
    print("  Files:")
    for f in scaffold.files:
        print(f"    {f.path}")
    print()

    if not write:
        print("  [dry-run] Files not written to disk (--no-write).")
    else:
        print(f"  Output: outputs/{project_id}/03_framework/playwright/")
        print()
        print("  Recommended next action:")
        print("    Review docs/SCAFFOLD_REVIEW_CHECKLIST.md before any local validation.")
        print("    execution_allowed=False — explicit approval required before running.")

    print()
    print("  Result: [OK]")
    print("=" * width)
    print()
    return 0


def _print_json(scaffold) -> int:
    print(json.dumps(scaffold.to_dict(), indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate a Playwright TypeScript scaffold (Phase 3A — no execution).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input",
        dest="input_text",
        metavar="TEXT",
        default="",
        help="Raw input text describing the project (runs full 2A+2B+2C+3A pipeline).",
    )
    p.add_argument(
        "--from-output",
        dest="from_output",
        metavar="DIR",
        default="",
        help="Load existing blueprint/strategy from this output directory (3A only).",
    )
    p.add_argument(
        "--project-id",
        dest="project_id",
        metavar="ID",
        default="",
        help="Project ID to use (required with --from-output; optional with --input).",
    )
    p.add_argument(
        "--no-write",
        dest="no_write",
        action="store_true",
        help="Print results only; do not write files to disk.",
    )
    p.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print JSON scaffold to stdout (implies --no-write).",
    )
    return p


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    write = not args.no_write and not args.output_json

    try:
        if args.from_output:
            # Scaffold-only from existing output
            out_path = Path(args.from_output)
            if not out_path.exists():
                out_path = _PROJECT_ROOT / args.from_output
            blueprint = _load_blueprint_from_output(out_path)
            strategy = _load_strategy_from_output(out_path)
            project_id = args.project_id or blueprint.project_id
            scaffold = _run_scaffold_only(blueprint, strategy, project_id, write)

            if args.output_json:
                return _print_json(scaffold)
            return _print_report(scaffold, write)

        elif args.input_text:
            from uuid import uuid4
            project_id = args.project_id or f"scaffold-{str(uuid4())[:8]}"
            result = _run_full_pipeline(args.input_text, project_id, write)

            if args.output_json:
                return _print_json(result["scaffold"])
            return _print_report(result, write)

        else:
            print("Error: provide --input TEXT or --from-output DIR", file=sys.stderr)
            parser.print_help()
            return 1

    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
