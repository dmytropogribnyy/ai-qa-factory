"""Phase 6.1 -- One-command client audit CLI.

Runs a full client QA audit workflow using existing AI QA Factory modules.
Safe by default: all modules run in planning_only mode unless explicit approvals
are provided.

Usage examples:

  # Safe audit (planning mode, no network, no browser)
  python tools/run_client_audit.py --project-id my-demo --mode safe_audit

  # With spec file (API contract import + planning)
  python tools/run_client_audit.py \\
    --project-id client-x --spec-file openapi.json --mode safe_audit

  # Dry run (no files written)
  python tools/run_client_audit.py --project-id demo --no-write

  # API-only mode
  python tools/run_client_audit.py \\
    --project-id api-audit --spec-file openapi.json --mode api_only

  # Delivery-only mode (collect existing outputs)
  python tools/run_client_audit.py --project-id existing --mode delivery_only

Blocked flags (always exit 1):
  --auto-approve-all       Blanket approval is not supported -- use explicit flags.
  --skip-human-review      Human review cannot be skipped (safety invariant).
  --force-deliver          Force-deliver is always blocked -- review first.
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from core.client_audit_workflow import ClientAuditWorkflow  # noqa: E402
from core.schemas.client_audit import ClientAuditInputs, ClientAuditMode  # noqa: E402

_APP_VERSION = "6.4.0"

_BLOCKED_FLAGS = {
    "--auto-approve-all": (
        "Blanket approval is not supported. "
        "Use --approve-public-readonly-execution or --approve-browser-execution individually."
    ),
    "--skip-human-review": "Human review cannot be skipped (safety invariant).",
    "--force-deliver": "Force-deliver is always blocked -- review delivery pack manually.",
}

_SEP = "-" * 72
_WIDE_SEP = "=" * 72


def _blocked_flag_check(args_list: list[str]) -> None:
    for flag, reason in _BLOCKED_FLAGS.items():
        if flag in args_list:
            print(f"[BLOCKED] {flag}: {reason}", file=sys.stderr)
            sys.exit(1)


def _print_preflight(inputs: ClientAuditInputs, plan_dict: dict) -> None:
    print(f"\n{_SEP}")
    print("  Preflight Plan")
    print(_SEP)
    print(f"  Mode:     {inputs.mode.value}")
    print(f"  Project:  {inputs.project_id}")
    print(f"  Write:    {'yes' if inputs.write_files else 'no (dry run)'}")
    print("")
    print("  Detected inputs:")
    for k, v in plan_dict.get("detected_inputs", {}).items():
        print(f"    {k:<36} {v}")
    print("")
    enabled = plan_dict.get("enabled_modules", [])
    if enabled:
        print("  Enabled modules:")
        for m in enabled:
            print(f"    - {m}")
    skipped = plan_dict.get("skipped_modules", [])
    if skipped:
        print("")
        print("  Skipped modules:")
        for s in skipped:
            reason = s.get("reason", "")
            wrapped = textwrap.fill(reason, width=52, subsequent_indent=" " * 38)
            print(f"    - {s.get('module', ''):<30} {wrapped}")
    blocked = plan_dict.get("blocked_risky_actions", [])
    if blocked:
        print("")
        print("  Blocked / risky actions:")
        for b in blocked:
            print(f"    - {b}")
    approval = plan_dict.get("approval_required_steps", [])
    if approval:
        print("")
        print("  Approval required for full execution:")
        for a in approval:
            print(f"    - {a}")


def _print_module_result(name: str, status: str, note: str) -> None:
    marker = {
        "executed": "[ok]",
        "analysis_only": "[ok]",
        "planning_only": "[plan]",
        "draft": "[ok]",
        "failed": "[fail]",
        "skipped": "[-]",
        "blocked": "[blocked]",
    }.get(status, "[-]")
    print(f"  {name:<36} {marker} {status}")
    if note:
        wrapped = textwrap.fill(note, width=60, subsequent_indent=" " * 4)
        print(f"    {wrapped}")


def _print_summary(result_dict: dict) -> None:
    print(f"\n{_SEP}")
    print("  AI QA Factory Client Audit Summary")
    print(_SEP)
    print(f"  Status:                {result_dict['status']}")
    print(f"  Modules executed:      {result_dict['modules_executed']}")
    print(f"  Modules planning-only: {result_dict['modules_planning_only']}")
    print(f"  Blocked risky actions: {result_dict['blocked_risky_actions']}")
    print(f"  Findings:              {result_dict['findings']}")
    print(f"  Artifacts:             {result_dict['artifacts_root']}")
    print(f"  Delivery pack:         {result_dict['delivery_dir']}")
    print("")
    print("  Human review required:        yes")
    print("  Approved for client delivery: no (human sign-off required)")
    print("")
    print("  Safety invariants:")
    print(f"    raw_secrets_allowed:          {result_dict['raw_secrets_allowed']}")
    print(f"    destructive_actions_allowed:  {result_dict['destructive_actions_allowed']}")
    print(f"    production_write_allowed:     {result_dict['production_write_allowed']}")
    print(f"    auto_send_allowed:            {result_dict['auto_send_allowed']}")
    print(f"    client_delivery_auto_approved:{result_dict['client_delivery_auto_approved']}")
    print(_SEP)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description=f"AI QA Factory v{_APP_VERSION} -- One-Command Client Audit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", default="client-audit-demo",
                        help="Project identifier (default: client-audit-demo)")
    parser.add_argument("--target-url", default="",
                        help="Target URL for frontend/security modules")
    parser.add_argument("--spec-file", default="",
                        help="OpenAPI or Swagger spec file path")
    parser.add_argument("--postman-collection", default="",
                        help="Postman collection JSON path")
    parser.add_argument("--task-source-report-path", default="",
                        help="Path to task source report (Linear, Jira, etc.)")
    parser.add_argument("--scaffold-root", default="",
                        help="Playwright scaffold root directory")
    parser.add_argument("--outputs-root", default="outputs",
                        help="Root directory for output artifacts (default: outputs)")
    parser.add_argument(
        "--mode",
        choices=["safe_audit", "api_only", "frontend_readonly", "delivery_only"],
        default="safe_audit",
        help="Audit workflow mode (default: safe_audit)",
    )
    parser.add_argument("--no-write", action="store_true", default=False,
                        help="Dry run -- do not write output files")
    parser.add_argument("--approve-public-readonly-execution",
                        action="store_true", default=False,
                        help="Approve passive HEAD request for security check")
    parser.add_argument("--approve-browser-execution",
                        action="store_true", default=False,
                        help="Approve browser-based accessibility/performance checks")
    parser.add_argument("--json-output", action="store_true", default=False,
                        help="Emit full JSON results to stdout after summary")
    args = parser.parse_args(argv)

    print(f"\n{_WIDE_SEP}")
    print(f"  AI QA Factory v{_APP_VERSION} -- Client Audit Workflow")
    print(f"  Project: {args.project_id}")
    print(f"  Mode:    {args.mode}")
    print(f"  Outputs: {args.outputs_root}")
    print(f"  Write:   {'no (dry run)' if args.no_write else 'yes'}")
    print(f"{_WIDE_SEP}")

    inputs = ClientAuditInputs(
        project_id=args.project_id,
        mode=ClientAuditMode(args.mode),
        target_url=args.target_url,
        spec_file=args.spec_file,
        postman_collection=args.postman_collection,
        task_source_report_path=args.task_source_report_path,
        scaffold_root=args.scaffold_root,
        outputs_root=args.outputs_root,
        write_files=not args.no_write,
        approve_public_readonly_execution=args.approve_public_readonly_execution,
        approve_browser_execution=args.approve_browser_execution,
    )

    workflow = ClientAuditWorkflow(inputs)
    plan = workflow.build_plan()
    plan_dict = {
        "detected_inputs": plan.detected_inputs,
        "enabled_modules": plan.enabled_modules,
        "skipped_modules": [
            {"module": s.name, "reason": s.reason} for s in plan.skipped_modules
        ],
        "blocked_risky_actions": plan.blocked_risky_actions,
        "approval_required_steps": plan.approval_required_steps,
    }
    _print_preflight(inputs, plan_dict)

    print(f"\n{_SEP}")
    print("  Running modules...")
    print(_SEP)

    result = workflow.run()

    for mr in result.module_results:
        _print_module_result(mr.name, mr.status, mr.note)

    result_dict = {
        "status": result.status,
        "modules_executed": result.modules_executed,
        "modules_planning_only": result.modules_planning_only,
        "blocked_risky_actions": result.blocked_risky_actions,
        "findings": result.findings,
        "artifacts_root": result.artifacts_root,
        "delivery_dir": result.delivery_dir,
        "raw_secrets_allowed": result.raw_secrets_allowed,
        "destructive_actions_allowed": result.destructive_actions_allowed,
        "production_write_allowed": result.production_write_allowed,
        "auto_send_allowed": result.auto_send_allowed,
        "client_delivery_auto_approved": result.client_delivery_auto_approved,
        "module_results": [
            {"name": mr.name, "status": mr.status, "note": mr.note}
            for mr in result.module_results
        ],
    }

    _print_summary(result_dict)

    if args.json_output:
        print("\n--- JSON Output ---")
        print(json.dumps(result_dict, indent=2, default=str))

    print(f"\n[OK] Client audit complete -- project: {args.project_id}")
    if not args.no_write:
        print(f"     Artifacts in: {args.outputs_root}/{args.project_id}/")
        print(f"     Audit plan:   {args.outputs_root}/{args.project_id}/33_client_audit/")


if __name__ == "__main__":
    main()
