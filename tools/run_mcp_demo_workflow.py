"""Phase 6-R — MCP demo workflow runner.

Runs all 7 MCP tool handlers in sequence against demo Playwright spec fixtures.
No mcp package required — uses integrations/mcp/tool_handlers.py directly.

Default mode: safe, planning_only, no network, no browser, no code changes.
Demonstrates the full QA Factory flow: health → analyze → audit → flaky → proposals →
delivery pack → blocked apply (no approval).

Blocked flags (always exit 1):
  --approve-delivery  Delivery approval requires human review, not CLI.
  --skip-review       Human review cannot be skipped (safety invariant).
  --force-apply       Force-apply is always blocked — use explicit approval per-step.
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from integrations.mcp.tool_handlers import (  # noqa: E402
    APP_VERSION,
    dispatch,
)

_BLOCKED_FLAGS = {
    "--approve-delivery": "Delivery approval must be done via human review, not CLI.",
    "--skip-review": "Human review cannot be skipped (safety invariant).",
    "--force-apply": "Force-apply is always blocked — review proposals manually.",
}

_DEMO_SPEC_ROOT = Path(__file__).parent.parent / "fixtures" / "demo_quality_audit" / "playwright_specs"
_FLAKY_SPEC = str(_DEMO_SPEC_ROOT / "flaky_test.spec.ts")
_STABLE_SPEC = str(_DEMO_SPEC_ROOT / "stable_test.spec.ts")

_SEP = "-" * 72


def _blocked_flag_check(args_list: list[str]) -> None:
    for flag, reason in _BLOCKED_FLAGS.items():
        if flag in args_list:
            print(f"[BLOCKED] {flag}: {reason}", file=sys.stderr)
            sys.exit(1)


def _print_step(step_num: int, tool_name: str) -> None:
    print(f"\n{_SEP}")
    print(f"  Step {step_num}: {tool_name}")
    print(_SEP)


def _print_result(result: dict) -> None:
    status = result.get("status", "?")
    marker = {
        "healthy": "[ok]",
        "analysis_only": "[ok]",
        "planning_only": "[ok]",
        "proposal_generated": "[ok]",
        "draft": "[ok]",
        "dry_run": "[ok]",
        "blocked": "[blocked]",
        "failed": "[fail]",
    }.get(status, "[-]")

    print(f"  Status:          {marker} {status}")

    for key in ("version", "safety_mode", "default_execution_mode"):
        if key in result:
            print(f"  {key.replace('_', ' ').capitalize():<20} {result[key]}")

    for key in ("files_analyzed", "found_artifact_dirs"):
        if key in result and result[key]:
            print(f"  {key.replace('_', ' ').capitalize():<20} {result[key]}")

    for key in ("total_risks", "stability_score", "weak_selectors", "total_proposals", "applied_proposals"):
        if key in result:
            print(f"  {key.replace('_', ' ').capitalize():<20} {result[key]}")

    for key in ("module_statuses",):
        if key in result:
            print("  Module statuses:")
            for mod, st in result[key].items():
                print(f"    {mod:<24} {st}")

    for key in ("artifact_paths", "artifacts"):
        if key in result and result[key]:
            print("  Artifacts:")
            for a in result[key]:
                print(f"    - {a}")

    for key in ("delivery_dir", "zip_path"):
        if key in result:
            print(f"  {key.replace('_', ' ').capitalize():<20} {result[key]}")

    for key in ("total_artifacts", "secret_scan_passed"):
        if key in result:
            print(f"  {key.replace('_', ' ').capitalize():<20} {result[key]}")

    for key in ("note", "reason"):
        if key in result:
            wrapped = textwrap.fill(result[key], width=64, subsequent_indent="    ")
            print(f"  Note: {wrapped}")

    if result.get("human_review_required"):
        print("  Human review:        required")
    if result.get("network_used") is False:
        print("  Network used:        no")
    if result.get("approved_for_client_delivery") is False:
        print("  Delivery approved:   no (human sign-off required)")


def run_demo(
    project_id: str,
    outputs_root: str,
    spec_files: list[str],
    write_files: bool,
) -> dict[str, dict]:
    """Run the 7-step MCP demo workflow and return all results."""
    results: dict[str, dict] = {}

    # Step 1: health
    _print_step(1, "qa_factory_health")
    r = dispatch("qa_factory_health", {})
    _print_result(r)
    results["qa_factory_health"] = r

    # Step 2: analyze_project
    _print_step(2, "analyze_project")
    r = dispatch("analyze_project", {
        "project_id": project_id,
        "outputs_root": outputs_root,
    })
    _print_result(r)
    results["analyze_project"] = r

    # Step 3: run_quality_audit (planning_only — no network)
    _print_step(3, "run_quality_audit (planning_only default)")
    r = dispatch("run_quality_audit", {
        "project_id": project_id,
        "target_url": "https://demo.playwright.dev/todomvc",
        "outputs_root": outputs_root,
        "write_files": write_files,
    })
    _print_result(r)
    results["run_quality_audit"] = r

    # Step 4: run_flaky_test_analysis
    _print_step(4, "run_flaky_test_analysis")
    r = dispatch("run_flaky_test_analysis", {
        "project_id": project_id,
        "spec_files": spec_files,
        "outputs_root": outputs_root,
        "write_files": write_files,
    })
    _print_result(r)
    results["run_flaky_test_analysis"] = r

    # Step 5: propose_self_healing_fixes
    _print_step(5, "propose_self_healing_fixes")
    r = dispatch("propose_self_healing_fixes", {
        "project_id": project_id,
        "spec_files": spec_files,
        "outputs_root": outputs_root,
        "write_files": write_files,
    })
    _print_result(r)
    results["propose_self_healing_fixes"] = r

    # Step 6: generate_delivery_pack
    _print_step(6, "generate_delivery_pack")
    r = dispatch("generate_delivery_pack", {
        "project_id": project_id,
        "outputs_root": outputs_root,
        "write_files": write_files,
    })
    _print_result(r)
    results["generate_delivery_pack"] = r

    # Step 7: apply_self_healing_fixes — no approval → should be blocked
    _print_step(7, "apply_self_healing_fixes (no approval — expect blocked)")
    r = dispatch("apply_self_healing_fixes", {
        "project_id": project_id,
        "spec_files": spec_files,
        "outputs_root": outputs_root,
        # approve_code_modification intentionally omitted
    })
    _print_result(r)
    results["apply_self_healing_fixes"] = r

    return results


def _print_summary(results: dict[str, dict]) -> None:
    print(f"\n{_SEP}")
    print("  QA Factory MCP Demo Workflow — Summary")
    print(_SEP)
    for tool, result in results.items():
        status = result.get("status", "?")
        hr = "[y]" if result.get("human_review_required") else "[n]"
        print(f"  {tool:<36} {status:<22} review={hr}")
    print(_SEP)
    print("  Safety mode:      safe_by_default -- no auto-execution, no auto-delivery")
    print("  apply blocked:    [y] (approve_code_modification not provided)")
    print("  Human review:     required for all steps")
    print(_SEP)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description=f"AI QA Factory v{APP_VERSION} — Phase 6-R MCP Demo Workflow",
    )
    parser.add_argument(
        "--project-id",
        default="mcp-demo",
        help="Project identifier (default: mcp-demo)",
    )
    parser.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root directory for output artifacts (default: outputs)",
    )
    parser.add_argument(
        "--spec-files",
        nargs="*",
        default=[_FLAKY_SPEC, _STABLE_SPEC],
        help="Playwright spec files to analyze (default: demo fixtures)",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        default=False,
        help="Dry run — do not write output files",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        default=False,
        help="Emit full JSON results to stdout after summary",
    )
    args = parser.parse_args(argv)

    print(f"\n{'=' * 72}")
    print(f"  AI QA Factory v{APP_VERSION} — MCP Demo Workflow (Phase 6-R)")
    print(f"  Project:  {args.project_id}")
    print(f"  Outputs:  {args.outputs_root}")
    print(f"  Specs:    {len(args.spec_files)} file(s)")
    print(f"  Write:    {'no (dry run)' if args.no_write else 'yes'}")
    print(f"{'=' * 72}")

    results = run_demo(
        project_id=args.project_id,
        outputs_root=args.outputs_root,
        spec_files=args.spec_files,
        write_files=not args.no_write,
    )
    _print_summary(results)

    if args.json_output:
        print("\n--- JSON Output ---")
        print(json.dumps(results, indent=2, default=str))

    print(f"\n[OK] Demo workflow complete — project: {args.project_id}")
    if not args.no_write:
        print(f"     Artifacts in: {args.outputs_root}/{args.project_id}/")


if __name__ == "__main__":
    main()
