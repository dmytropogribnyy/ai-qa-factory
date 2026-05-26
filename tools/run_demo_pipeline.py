"""
Phase 5J-R — Demo Pipeline Runner.

Pre-configured pipeline for known safe public demo targets.
Delegates to E2EPipelineRunner with preset module configs.

Demo targets:
  api     — Restful Booker + JSONPlaceholder API smoke + qa_report
  browser — SauceDemo browser smoke + qa_report
  full    — api + browser + qa_report (default)

Usage:
  # Show plan (no execution):
  python tools/run_demo_pipeline.py --project-id demo-run

  # Run API demo:
  python tools/run_demo_pipeline.py \\
    --project-id demo-run \\
    --demo-target api \\
    --approve-pipeline-execution \\
    --approve-api-smoke

  # Run full demo:
  python tools/run_demo_pipeline.py \\
    --project-id demo-run \\
    --demo-target full \\
    --approve-pipeline-execution \\
    --approve-api-smoke \\
    --approve-browser-execution

SAFETY:
- Same blocked flags as run_e2e_pipeline.py.
- --approve-pipeline-execution required for any execution.
- Each module's own safety gates remain in effect.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key",
    "--cookie", "--pat", "--access-token", "--bearer",
    "--db-url",
)

# Demo presets: module → (target_url, profile/category/device)
_DEMO_API_MODULES = [
    ("api_smoke", "https://restful-booker.herokuapp.com", "restful_booker"),
]
_DEMO_BROWSER_MODULES = [
    ("browser", "https://www.saucedemo.com", "saucedemo"),
]

DEMO_TARGETS = ("api", "browser", "full")


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


def _build_demo_config(demo_target: str, approve_api: bool, approve_browser: bool):
    """Return (enabled_modules, PipelineModuleConfig) for the given demo target."""
    from core.schemas.pipeline import PipelineModuleConfig

    enabled_modules = []
    cfg_kwargs = dict(
        api_target_url="https://restful-booker.herokuapp.com",
        api_profile="restful_booker",
        api_approve=approve_api,
        browser_target_url="https://www.saucedemo.com",
        browser_category="saucedemo",
        browser_approve=approve_browser,
    )

    if demo_target in ("api", "full"):
        enabled_modules.append("api_smoke")
    if demo_target in ("browser", "full"):
        enabled_modules.append("browser")
    enabled_modules.append("qa_report")

    cfg = PipelineModuleConfig(**cfg_kwargs)
    return enabled_modules, cfg


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5J-R: Pre-configured demo pipeline for known safe public targets."
    )
    parser.add_argument("--project-id", required=True,
                        help="Output project identifier")
    parser.add_argument("--demo-target", default="full",
                        choices=list(DEMO_TARGETS),
                        help="Demo target preset: api | browser | full (default: full)")
    parser.add_argument("--approve-pipeline-execution", action="store_true",
                        help="Confirm approval for pipeline execution")
    parser.add_argument("--approve-api-smoke", action="store_true",
                        help="Approve API smoke module")
    parser.add_argument("--approve-browser-execution", action="store_true",
                        help="Approve browser execution module")
    parser.add_argument("--stop-on-failure", action="store_true",
                        help="Stop pipeline after first failed or blocked module")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to disk")
    parser.add_argument("--timeout-per-module", type=int, default=300,
                        help="Timeout per module in seconds (default 300)")

    args = parser.parse_args()

    from core.e2e_pipeline_runner import E2EPipelineRunner

    enabled_modules, cfg = _build_demo_config(
        demo_target=args.demo_target,
        approve_api=args.approve_api_smoke,
        approve_browser=args.approve_browser_execution,
    )

    runner = E2EPipelineRunner(outputs_root=Path("outputs"))

    # Always show plan first
    plan = runner.plan(
        project_id=args.project_id,
        enabled_modules=enabled_modules,
        module_config=cfg,
        approve_pipeline_execution=args.approve_pipeline_execution,
    )

    print(f"Demo pipeline plan — target: {args.demo_target}, project: {args.project_id}")
    print(f"Enabled modules: {', '.join(plan.execution_order) or 'none'}")
    if plan.blocked_modules:
        print(f"Blocked modules: {', '.join(plan.blocked_modules)}")
    if plan.notes:
        print("Notes:")
        for note in plan.notes:
            print(f"  - {note}")
    if plan.blockers:
        print("\nBlockers (execution prevented):")
        for b in plan.blockers:
            print(f"  - {b}")

    if not args.approve_pipeline_execution:
        print("\n[PLAN ONLY] Add --approve-pipeline-execution to run.")
        sys.exit(0)

    if plan.blockers:
        sys.exit(1)

    report = runner.run(
        project_id=args.project_id,
        enabled_modules=enabled_modules,
        module_config=cfg,
        approve_pipeline_execution=args.approve_pipeline_execution,
        timeout_per_module=args.timeout_per_module,
        stop_on_first_failure=args.stop_on_failure,
    )

    stopped_note = " (stopped early)" if report.stopped_early else ""
    print(f"\nStatus:   {report.overall_status}{stopped_note}")
    print(f"Complete: {report.modules_complete}")
    print(f"Failed:   {report.modules_failed}")
    print(f"Blocked:  {report.modules_blocked}")
    print(f"Skipped:  {report.modules_skipped}")
    print(f"Duration: {report.total_duration_seconds}s")

    for mr in report.module_results:
        status_icon = "+" if mr.status == "complete" else "-"
        print(f"  [{status_icon}] {mr.module_name}: {mr.status}")
        for b in mr.blockers:
            print(f"       - {b}")

    if not args.no_write:
        paths = runner.render_artifacts(report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(0 if report.overall_status in ("complete", "partial") else 1)


if __name__ == "__main__":
    main()
