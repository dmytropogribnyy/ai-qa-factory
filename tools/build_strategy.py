"""build_strategy.py — standalone Phase 2C script: build QA strategy from inputs or existing blueprint.

Usage:
    python tools/build_strategy.py --input "Need Playwright tests for a SaaS dashboard with login"
    python tools/build_strategy.py --project-id demo --input "..."
    python tools/build_strategy.py --from-output outputs/demo/00_project
    python tools/build_strategy.py --input "..." --no-write

Phase 2C — planning only:
- No URL fetching.
- No browser execution.
- No credential use.
- No external calls.
- No Playwright scaffold.
- No executable test generation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.workbench_controller import WorkbenchController  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build QA strategy (Phase 2C) from inputs or existing Phase 2B output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input", "-i",
        dest="inputs",
        action="append",
        default=[],
        metavar="TEXT_OR_URL",
        help="Raw input (text brief, URL, file path). Repeat for multiple inputs.",
    )
    p.add_argument(
        "--from-output",
        dest="from_output",
        metavar="DIR",
        help="Load existing Phase 2B artifacts from DIR (e.g. outputs/demo/00_project). "
             "Reads PROJECT_BLUEPRINT.json.",
    )
    p.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        help="Project ID (auto-generated if omitted).",
    )
    p.add_argument(
        "--source-platform",
        dest="source_platform",
        default="unknown",
        help="Source platform (upwork, linear, notion, unknown, ...).",
    )
    p.add_argument(
        "--no-write",
        dest="no_write",
        action="store_true",
        help="Print results only; do not write output files.",
    )
    p.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print full JSON result to stdout (implies --no-write).",
    )
    return p


def _load_blueprint_from_output(from_output: str):
    """Load ProjectBlueprint from an existing outputs/<id>/00_project/ directory."""
    from core.schemas.project_blueprint import ProjectBlueprint

    out_dir = Path(from_output)
    blueprint_json = out_dir / "PROJECT_BLUEPRINT.json"
    if not blueprint_json.exists():
        print(f"[ERROR] PROJECT_BLUEPRINT.json not found in: {out_dir}", file=sys.stderr)
        print("[ERROR] Run Phase 2B first: python tools/classify_inputs.py --with-blueprint", file=sys.stderr)
        return None
    try:
        data = json.loads(blueprint_json.read_text(encoding="utf-8"))
        return ProjectBlueprint.from_dict(data)
    except Exception as exc:
        print(f"[ERROR] Failed to load PROJECT_BLUEPRINT.json: {exc}", file=sys.stderr)
        return None


def _print_summary(result: dict) -> None:
    pid = result["project_id"]
    strategy = result.get("strategy")
    has_blueprint = "blueprint" in result

    print()
    print("=" * 68)
    print("  BUILD STRATEGY — Phase 2C")
    print("=" * 68)
    print(f"  Project ID    : {pid}")
    if has_blueprint:
        bp = result["blueprint"]
        print(f"  Project type  : {bp.project_type}")
        print(f"  Environment   : {bp.environment}")
        print(f"  BP confidence : {bp.confidence_level}")
    if strategy:
        n_areas = len(strategy.strategy_areas)
        n_blocked_areas = sum(1 for a in strategy.strategy_areas if a.blocked)
        n_recommended = sum(1 for t in strategy.test_layers if t.recommended)
        n_risk = len(strategy.risk_matrix)
        n_tactical = len(strategy.tactical_plan_outline)
        n_blocked_risk = sum(1 for r in strategy.risk_matrix if r.blocked)
        print(f"  Strategy areas: {n_areas} ({n_blocked_areas} blocked)")
        print(f"  Risk items    : {n_risk} ({n_blocked_risk} blocked/approval-req)")
        print(f"  Test layers   : {len(strategy.test_layers)} ({n_recommended} recommended)")
        print(f"  Tactical items: {n_tactical}")
        print(f"  Confidence    : {strategy.confidence_level}")
        print(f"  Client ready  : {strategy.client_ready}")
    print("-" * 68)
    print("  Safety:")
    print("    No URL fetched.  No credentials used.  No execution performed.")
    print("    client_ready=False — human review required before delivery.")
    print("=" * 68)
    print()

    if "strategy_artifact_paths" in result:
        print("  Strategy artifacts written:")
        for key, path in result["strategy_artifact_paths"].items():
            rel = Path(path).relative_to(_PROJECT_ROOT) if Path(path).is_absolute() else path
            print(f"    {key}: {rel}")
        print()
    elif "artifact_paths" in result:
        print("  Artifacts written (02_strategy/):")
        for key, path in result["artifact_paths"].items():
            if "strategy" in key or "02_strategy" in str(path):
                rel = Path(path).relative_to(_PROJECT_ROOT) if Path(path).is_absolute() else path
                print(f"    {key}: {rel}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    controller = WorkbenchController()

    # --- Mode A: --from-output (load existing blueprint) ---
    if args.from_output:
        blueprint = _load_blueprint_from_output(args.from_output)
        if blueprint is None:
            return 1

        project_id = args.project_id or blueprint.project_id

        strategy = controller.build_qa_strategy(blueprint)
        strategy_status = controller.update_project_status_for_strategy(project_id, strategy)

        result = {
            "project_id": project_id,
            "blueprint": blueprint,
            "strategy": strategy,
            "strategy_status": strategy_status,
        }

        if not args.no_write and not args.output_json:
            strategy_paths = controller.render_strategy_artifacts(strategy, project_id, strategy_status)
            result["strategy_artifact_paths"] = strategy_paths

        if args.output_json:
            print(json.dumps({
                "project_id": project_id,
                "blueprint": blueprint.to_dict(),
                "strategy": strategy.to_dict(),
                "strategy_status": strategy_status.to_dict(),
            }, indent=2, ensure_ascii=False))
            return 0

        _print_summary(result)
        return 0

    # --- Mode B: --input (full 2A + 2B + 2C) ---
    raw_inputs = list(args.inputs)
    if not raw_inputs:
        parser.print_help()
        print("\n[ERROR] Provide --input or --from-output.", file=sys.stderr)
        return 1

    raw_text = " ".join(raw_inputs)

    if args.no_write or args.output_json:
        result_base = controller.analyze_inputs(
            raw_inputs=raw_inputs,
            raw_text=raw_text,
            source_platform=args.source_platform,
            project_id=args.project_id,
        )
        bp = controller.build_project_blueprint(
            result_base["input_map"],
            result_base["work_request"],
            result_base["task_classification"],
        )
        strategy = controller.build_qa_strategy(
            bp,
            result_base["input_map"],
            result_base["work_request"],
            result_base["task_classification"],
        )
        strategy_status = controller.update_project_status_for_strategy(result_base["project_id"], strategy)
        result_base["blueprint"] = bp
        result_base["strategy"] = strategy
        result_base["strategy_status"] = strategy_status

        if args.output_json:
            print(json.dumps({
                "project_id": result_base["project_id"],
                "blueprint": bp.to_dict(),
                "strategy": strategy.to_dict(),
                "strategy_status": strategy_status.to_dict(),
            }, indent=2, ensure_ascii=False))
            return 0

        _print_summary(result_base)
        return 0

    result = controller.build_context_with_strategy(
        raw_inputs=raw_inputs,
        raw_text=raw_text,
        source_platform=args.source_platform,
        project_id=args.project_id,
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
