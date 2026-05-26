"""
Phase 5J — CLI: Run the E2E QA Pipeline.

Orchestrates enabled Phase runners in fixed order:
  task_source → browser → api_smoke → google_auth → github_auth
  → mobile_viewport → visual_regression → db_smoke → qa_report

Usage:
  # Browser + API smoke:
  python tools/run_e2e_pipeline.py \\
    --project-id my-project \\
    --enable-browser \\
    --browser-target-url https://www.saucedemo.com \\
    --browser-category demo_auth \\
    --browser-approve \\
    --enable-api \\
    --api-target-url https://jsonplaceholder.typicode.com \\
    --api-profile jsonplaceholder_no_auth \\
    --api-approve \\
    --approve-pipeline-execution

  # Full pipeline with DB smoke:
  python tools/run_e2e_pipeline.py \\
    --project-id my-project \\
    --enable-browser --browser-target-url https://... --browser-category demo_auth --browser-approve \\
    --enable-db --db-provider postgresql --db-url-env-var STAGING_DATABASE_URL \\
                --db-table users --db-approve \\
    --enable-qa-report \\
    --approve-pipeline-execution

SAFETY:
- Each module's own safety gates remain in effect.
- Raw secrets never accepted via CLI flags.
- --approve-pipeline-execution required for any execution.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key",
    "--cookie", "--pat", "--access-token", "--bearer",
    "--db-url",  # raw DB connection strings blocked
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
        description="Phase 5J: Run the E2E QA Pipeline."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--approve-pipeline-execution", action="store_true",
                        help="Confirm approval for pipeline execution")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--timeout-per-module", type=int, default=300,
                        help="Timeout per module in seconds (default 300)")
    parser.add_argument("--stop-on-failure", action="store_true",
                        help="Stop pipeline after the first failed or blocked module")

    # Module enable flags
    parser.add_argument("--enable-task-source", action="store_true")
    parser.add_argument("--enable-browser", action="store_true")
    parser.add_argument("--enable-api", action="store_true")
    parser.add_argument("--enable-google-auth", action="store_true")
    parser.add_argument("--enable-github-auth", action="store_true")
    parser.add_argument("--enable-mobile", action="store_true")
    parser.add_argument("--enable-visual", action="store_true")
    parser.add_argument("--enable-db", action="store_true")
    parser.add_argument("--enable-qa-report", action="store_true")

    # task_source args
    parser.add_argument("--task-source-provider", default="")
    parser.add_argument("--task-source-token-env-var", default="")
    parser.add_argument("--task-source-project-id", default="")

    # browser args
    parser.add_argument("--browser-target-url", default="")
    parser.add_argument("--browser-category", default="")
    parser.add_argument("--browser-approve", action="store_true")

    # api args
    parser.add_argument("--api-target-url", default="")
    parser.add_argument("--api-profile", default="")
    parser.add_argument("--api-approve", action="store_true")

    # google_auth args
    parser.add_argument("--google-auth-mode", default="storage_state_reuse")
    parser.add_argument("--google-storage-state-path", default="")
    parser.add_argument("--google-approve", action="store_true")
    parser.add_argument("--google-dedicated-test-account-confirmed", action="store_true")

    # github_auth args
    parser.add_argument("--github-auth-mode", default="storage_state_reuse")
    parser.add_argument("--github-storage-state-path", default="")
    parser.add_argument("--github-approve", action="store_true")
    parser.add_argument("--github-dedicated-test-account-confirmed", action="store_true")

    # mobile args
    parser.add_argument("--mobile-device", default="")
    parser.add_argument("--mobile-target-url", default="")
    parser.add_argument("--mobile-readonly-profile", default="")
    parser.add_argument("--mobile-approve", action="store_true")

    # visual args
    parser.add_argument("--visual-target-url", default="")
    parser.add_argument("--visual-mode", default="compare",
                        choices=["capture", "compare", "update"])
    parser.add_argument("--visual-device", default="")
    parser.add_argument("--visual-approve", action="store_true")

    # db args
    parser.add_argument("--db-provider", default="",
                        choices=["", "postgresql", "mysql", "mongodb"])
    parser.add_argument("--db-url-env-var", default="",
                        help="Env var NAME for DB connection string (not the value)")
    parser.add_argument("--db-table", default="")
    parser.add_argument("--db-approve", action="store_true")

    # qa_report args
    parser.add_argument("--qa-report-source-project-id", action="append",
                        dest="qa_source_ids", default=[],
                        help="Source project IDs for QA report (repeatable)")

    args = parser.parse_args()

    # Build enabled modules list
    enabled_modules = []
    if args.enable_task_source:
        enabled_modules.append("task_source")
    if args.enable_browser:
        enabled_modules.append("browser")
    if args.enable_api:
        enabled_modules.append("api_smoke")
    if args.enable_google_auth:
        enabled_modules.append("google_auth")
    if args.enable_github_auth:
        enabled_modules.append("github_auth")
    if args.enable_mobile:
        enabled_modules.append("mobile_viewport")
    if args.enable_visual:
        enabled_modules.append("visual_regression")
    if args.enable_db:
        enabled_modules.append("db_smoke")
    if args.enable_qa_report:
        enabled_modules.append("qa_report")

    from core.e2e_pipeline_runner import E2EPipelineRunner
    from core.schemas.pipeline import PipelineModuleConfig

    cfg = PipelineModuleConfig(
        task_source_provider=args.task_source_provider,
        task_source_token_env_var=args.task_source_token_env_var,
        task_source_project_id=args.task_source_project_id,
        browser_target_url=args.browser_target_url,
        browser_category=args.browser_category,
        browser_approve=args.browser_approve,
        api_target_url=args.api_target_url,
        api_profile=args.api_profile,
        api_approve=args.api_approve,
        google_auth_mode=args.google_auth_mode,
        google_storage_state_path=args.google_storage_state_path,
        google_approve=args.google_approve,
        google_dedicated_test_account_confirmed=args.google_dedicated_test_account_confirmed,
        github_auth_mode=args.github_auth_mode,
        github_storage_state_path=args.github_storage_state_path,
        github_approve=args.github_approve,
        github_dedicated_test_account_confirmed=args.github_dedicated_test_account_confirmed,
        mobile_device=args.mobile_device,
        mobile_target_url=args.mobile_target_url,
        mobile_readonly_profile=args.mobile_readonly_profile,
        mobile_approve=args.mobile_approve,
        visual_target_url=args.visual_target_url,
        visual_mode=args.visual_mode,
        visual_device=args.visual_device,
        visual_approve=args.visual_approve,
        db_provider=args.db_provider,
        db_url_env_var=args.db_url_env_var,
        db_table=args.db_table,
        db_approve=args.db_approve,
        qa_report_source_project_ids=args.qa_source_ids,
    )

    runner = E2EPipelineRunner(outputs_root=Path("outputs"))

    # Always show plan first
    plan = runner.plan(
        project_id=args.project_id,
        enabled_modules=enabled_modules,
        module_config=cfg,
        approve_pipeline_execution=args.approve_pipeline_execution,
    )

    print(f"Pipeline plan for: {args.project_id}")
    print(f"Enabled modules:   {', '.join(plan.execution_order) or 'none'}")
    if plan.blocked_modules:
        print(f"Blocked modules:   {', '.join(plan.blocked_modules)}")
    if plan.blockers:
        print("\nBlockers:")
        for b in plan.blockers:
            print(f"  - {b}")
        sys.exit(1)

    # Run
    report = runner.run(
        project_id=args.project_id,
        enabled_modules=enabled_modules,
        module_config=cfg,
        approve_pipeline_execution=args.approve_pipeline_execution,
        timeout_per_module=args.timeout_per_module,
        stop_on_first_failure=args.stop_on_failure,
    )

    stopped_note = " (stopped early)" if report.stopped_early else ""
    print(f"\nStatus:     {report.overall_status}{stopped_note}")
    print(f"Complete:   {report.modules_complete}")
    print(f"Failed:     {report.modules_failed}")
    print(f"Blocked:    {report.modules_blocked}")
    print(f"Skipped:    {report.modules_skipped}")
    print(f"Duration:   {report.total_duration_seconds}s")

    for mr in report.module_results:
        status_icon = "✓" if mr.status == "complete" else "✗"
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
