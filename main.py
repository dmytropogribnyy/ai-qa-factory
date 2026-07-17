from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.agent_registry import build_agent_registry
from core.config import get_settings
from core.version import APP_VERSION  # v5.0.8 legacy label preserved below for test compat
from core.initial_analysis_engine import InitialAnalysisEngine
from core.llm_router import LLMRouter
from core.orchestrator import QAFactoryOrchestrator
from core.persistence import get_persistence
from core.quality_gate import QualityGate
from core.workflow_registry import WORKFLOWS
from tools.test_runner import TestRunner
from tools.system_health import SystemHealthChecker


def read_input(path: str | None) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    return file_path.read_text(encoding="utf-8").strip()


_WORK_MAX_INPUT_BYTES = 200_000
_PROJECT_ID_RE = __import__("re").compile(r"[A-Za-z0-9._-]{1,64}")


def _valid_project_id(pid: str) -> bool:
    import os
    return (
        bool(pid)
        and _PROJECT_ID_RE.fullmatch(pid) is not None
        and ".." not in pid
        and "/" not in pid and "\\" not in pid
        and not os.path.isabs(pid)
    )


def run_work(args) -> int:
    """Phase 8.1 planning-only entrypoint. Exit: 0 ok (incl WAITING), 1 invalid, 2 safety block."""
    import sys as _sys
    from core.config import get_settings

    # 1. Resolve input (mutually exclusive; enforced by argparse group)
    try:
        if getattr(args, "stdin", False):
            raw = _sys.stdin.read()
        elif getattr(args, "text", None) is not None:
            raw = args.text
        else:
            raw = read_input(args.input)
    except Exception as exc:
        print(f"ERROR: {exc}", file=_sys.stderr)
        return 1

    raw = (raw or "").strip()
    if not raw:
        print("ERROR: empty input", file=_sys.stderr)
        return 1
    if len(raw.encode("utf-8")) > _WORK_MAX_INPUT_BYTES:
        print(f"ERROR: input exceeds {_WORK_MAX_INPUT_BYTES} bytes", file=_sys.stderr)
        return 1

    # 2. Resolve project id (generate a safe one when omitted; validate either way)
    from core.orchestration.providers import ClockProvider, IdProvider, generate_project_id
    from core.orchestration.content_safety import redact_intake_text
    generated = args.project_id is None
    if generated:
        # Generate the id from REDACTED text so a secret can never reach the path/stdout/logs.
        redacted_seed = redact_intake_text(raw).text
        project_id = generate_project_id(redacted_seed, IdProvider())
    else:
        project_id = args.project_id
    if not _valid_project_id(project_id):
        print("ERROR: invalid project id (use [A-Za-z0-9._-], no separators, not absolute)",
              file=_sys.stderr)
        return 2

    # 3. Run planning-only workflow
    try:
        from core.orchestration.work_workflow import WorkPlanningWorkflow
        from core.orchestration.content_safety import ArtifactPublishError
        from core.orchestration.work_workflow import WorkPlanningError

        settings = get_settings()
        out_dir = Path(settings.output_dir).resolve()
        wf = WorkPlanningWorkflow(ClockProvider(), IdProvider(), output_dir=out_dir)
        # Defensive: resolved target must stay inside the output dir.
        target = (out_dir / project_id / "40_ark_work").resolve()
        if out_dir not in target.parents:
            print("ERROR: resolved output path escapes the output directory", file=_sys.stderr)
            return 2
        result = wf.run(
            raw, project_id=project_id,
            source_platform=args.source_platform, profile_override=args.profile,
            fresh_only=generated,
        )
    except (ArtifactPublishError,) as exc:
        print(f"BLOCKED (safety): {exc}", file=_sys.stderr)
        return 2
    except WorkPlanningError as exc:
        print(f"BLOCKED: {exc}", file=_sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=_sys.stderr)
        return 1

    # 4. Report (redacted summary only)
    if getattr(args, "as_json", False):
        import json as _json
        # Exactly one redacted JSON object on stdout; no banner, no raw brief.
        print(_json.dumps({
            "project_id": result.project_id,
            "project_id_generated": generated,
            "selected_profile": result.profile,
            "state": result.final_status,
            "artifact_directory": result.target_dir,
            "artifact_paths": result.artifacts,
            "missing_information": result.missing_information_count,
            "approvals_required": result.approvals_required_count,
            "secrets_redacted": result.secrets_redacted,
            "planning_only": result.planning_only,
        }, indent=2, ensure_ascii=False))
    else:
        origin = "generated" if generated else "provided"
        print(f"Project id ({origin}): {result.project_id}")
        print(f"Work planned (planning-only): profile={result.profile or '(unresolved)'} "
              f"state={result.final_status}")
        print(f"Missing info: {result.missing_information_count} | "
              f"Approvals: {result.approvals_required_count}")
        print(f"Artifacts ({len(result.artifacts)}) -> {result.target_dir}")
        if result.warnings:
            print("Warnings: " + "; ".join(result.warnings))
    return 0


def require_real_llm_guard(settings, require_real_llm: bool, allow_mock: bool = False) -> None:
    if require_real_llm and settings.is_mock and not allow_mock:
        raise RuntimeError(
            "--require-real-llm was passed, but LLM_MODE=mock. "
            "Configure real LiteLLM model IDs/API keys before client-facing output, "
            "or pass --allow-mock for an intentional dry/training run."
        )


def add_common_workflow_args(cmd) -> None:
    cmd.add_argument("--input", "-i", required=True, help="Path to input file")
    cmd.add_argument("--project-id", help="Optional saved project_id to resume/re-run with --from-step or --only")
    cmd.add_argument("--approve", action="store_true", help="Mark output as approved by user")
    cmd.add_argument("--require-real-llm", action="store_true", help="Fail if LLM_MODE=mock")
    cmd.add_argument("--allow-mock", action="store_true", help="Explicitly allow mock LLM despite --require-real-llm")
    cmd.add_argument("--client-id", help="Optional client memory ID")
    cmd.add_argument("--source-platform", help="Optional source hint, e.g. upwork, fiverr, writing_platform, direct_b2b")
    cmd.add_argument("--auto", action="store_true", help="Run full workflow without pauses (default)")
    cmd.add_argument("--step", action="store_true", help="Pause between agents and allow inline feedback")
    cmd.add_argument("--dry-run", action="store_true", help="Run workflow without writing final outputs")
    cmd.add_argument("--from-step", help="Continue workflow from a specific agent using saved state when available")
    cmd.add_argument("--only", help="Run only one agent using saved state when available")


def resolve_execution_mode(args) -> str:
    if getattr(args, "dry_run", False):
        return "dry-run"
    if getattr(args, "step", False):
        return "step"
    return "auto"


def main(argv: list[str] | None = None) -> int:
    # v5.0.8 Model Routing Profiles — previous release label (kept for legacy sync test)
    parser = argparse.ArgumentParser(
        description=f"Guided QA Automation Workbench v{APP_VERSION} — AI-assisted QA delivery platform for real client projects. AI drafts. Senior QA decides.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    for mode in ["prescreen", "filter", "job", "upwork", "audit", "plan", "test-design", "scaffold", "review", "delivery", "mcp-guide", "full"]:
        cmd = subparsers.add_parser(mode, help=f"Run {mode} workflow")
        add_common_workflow_args(cmd)

    run_cmd = subparsers.add_parser("run-tests", help="Safely run tests for an existing project path")
    run_cmd.add_argument("--project-path", required=True, help="Path to project/framework directory")
    run_cmd.add_argument("--kind", choices=["playwright", "pytest"], default="playwright")


    batch_cmd = subparsers.add_parser("batch-filter", help="Filter a directory of opportunity/job files and create a shortlist report")
    batch_cmd.add_argument("--input", "-i", required=True, help="Directory with .txt/.md job files")
    batch_cmd.add_argument("--require-real-llm", action="store_true", help="Fail if LLM_MODE=mock")
    batch_cmd.add_argument("--allow-mock", action="store_true", help="Explicitly allow mock LLM despite --require-real-llm")

    subparsers.add_parser("capabilities", help="Print current capability matrix path and summary")
    subparsers.add_parser("system-health", help="Check local Factory readiness: env, packages, directories, Node/Playwright tools")

    agents_cmd = subparsers.add_parser("agents", help="List available agents or agents relevant to a workflow")
    agents_cmd.add_argument("--workflow", choices=sorted(WORKFLOWS.keys()), help="Optional workflow name")
    agents_cmd.add_argument("--input", "-i", help="Optional input file for future relevance filtering")

    ask_cmd = subparsers.add_parser("ask", help="Ask a question about a saved project")
    ask_cmd.add_argument("--project-id", required=True)
    ask_cmd.add_argument("--question", "-q", help="Question to ask. If omitted in a TTY, starts a small REPL.")

    # Phase 8.1 — ARK universal work entrypoint (planning-only; no MCP calls, no execution)
    work_cmd = subparsers.add_parser(
        "work", help="Plan a unit of work (planning-only): produce WorkPacket + plans + approvals"
    )
    work_src = work_cmd.add_mutually_exclusive_group(required=True)
    work_src.add_argument("--input", "-i", help="Path to a brief file")
    work_src.add_argument("--text", help="Literal brief text")
    work_src.add_argument("--stdin", action="store_true", help="Read the brief from stdin")
    work_cmd.add_argument("--project-id", help="Project id (safe name; no separators). "
                          "Optional: a safe id is generated when omitted; pass it to resume.")
    work_cmd.add_argument("--source-platform", default="unknown",
                          help="Commercial source platform (e.g. upwork, direct). NOT an input type.")
    work_cmd.add_argument("--profile", help="Optional capability-profile override")
    work_cmd.add_argument("--json", action="store_true", dest="as_json",
                          help="Print a redacted machine summary")

    # Phase 8.3 — Prospect QA Scout (bounded, read-only local runtime)
    scout_cmd = subparsers.add_parser(
        "scout", help="Prospect QA Scout v1.0 — bounded read-only local QA over public seeds"
    )
    scout_cmd.add_argument("action", choices=[
        "run", "demo", "dashboard", "control", "smoke",
        "campaign-demo", "campaign-plan", "campaign-run", "providers",
        "presend-demo", "db-status", "db-backup", "db-restore", "review-list", "doctor"])
    scout_cmd.add_argument("--seeds", help="Comma-separated public URLs (run; or dashboard "
                                           "to start an active run)")
    scout_cmd.add_argument("--url", help="Single public URL (smoke)")
    scout_cmd.add_argument("--campaign", default="adhoc")
    scout_cmd.add_argument("--output", default="outputs")
    scout_cmd.add_argument("--browser", choices=["static", "playwright"], default="static")
    scout_cmd.add_argument("--max-sites", type=int, default=10, dest="max_sites")
    scout_cmd.add_argument("--max-pages", type=int, default=5, dest="max_pages")
    scout_cmd.add_argument("--concurrency", type=int, default=1,
                           help="Must be 1 in v1.0.x (parallel execution is deferred)")
    scout_cmd.add_argument("--run-id", dest="run_id", default="")
    scout_cmd.add_argument("--resume", action="store_true")
    scout_cmd.add_argument("--port", type=int, default=8765, help="Dashboard port")
    scout_cmd.add_argument("--signal", choices=["pause", "resume", "cancel", "kill"],
                           help="Control signal (scout control)")
    # Phase 8.4 — discovery / commercial triage options.
    scout_cmd.add_argument("--import", dest="import_file",
                           help="Import file for campaign-run/plan (CSV/JSON/NDJSON/txt)")
    scout_cmd.add_argument("--countries", default="", help="Comma-separated country codes")
    scout_cmd.add_argument("--languages", default="", help="Comma-separated language codes")
    scout_cmd.add_argument("--industries", default="", help="Comma-separated industries")
    scout_cmd.add_argument("--business-types", dest="business_types", default="",
                           help="Comma-separated business types")
    scout_cmd.add_argument("--keywords", default="", help="Comma-separated keywords")
    scout_cmd.add_argument("--campaign-id", dest="campaign_id", default="",
                           help="Explicit campaign id (else a unique one is generated)")
    scout_cmd.add_argument("--min-commercial", dest="min_commercial", type=int, default=40,
                           help="Minimum commercial triage score to be eligible (0..100)")
    scout_cmd.add_argument("--max-promoted", dest="max_promoted", type=int, default=5,
                           help="Max candidates promoted into the Scout QA engine")
    scout_cmd.add_argument("--per-provider-budget", dest="per_provider_budget", type=int,
                           default=50, help="Max results per provider call")
    scout_cmd.add_argument("--matrix-max", dest="matrix_max", type=int, default=500,
                           help="Hard cap on campaign matrix size (fails closed above this)")
    scout_cmd.add_argument("--cost-ceiling", dest="cost_ceiling", type=float, default=0.0,
                           help="Optional monetary ceiling (USD); 0 disables the check")
    scout_cmd.add_argument("--sample", type=int, default=None,
                           help="Deterministically sample an over-limit matrix to this size")
    scout_cmd.add_argument("--approve-live-discovery", dest="approve_live_discovery",
                           action="store_true",
                           help="Explicitly approve configured live providers (never required by tests)")
    # Final Phase I — pre-send pipeline + memory database options.
    scout_cmd.add_argument("--db", help="Memory database path (db-status/backup/restore/review-list)")
    scout_cmd.add_argument("--dest", help="Destination path (db-backup/db-restore)")

    args = parser.parse_args(argv)

    if args.mode == "work":
        return run_work(args)

    if args.mode == "scout":
        from core.scout.cli import run_scout_cli
        return run_scout_cli(args)


    if args.mode == "batch-filter":
        try:
            settings = get_settings()
            require_real_llm_guard(settings, getattr(args, "require_real_llm", False), getattr(args, "allow_mock", False))
            return batch_filter(args.input, settings)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.mode == "run-tests":
        runner = TestRunner()
        result = runner.run_playwright(args.project_path) if args.kind == "playwright" else runner.run_pytest(args.project_path)
        print("=" * 72)
        print(f"Test runner: {args.kind}")
        print(f"Project path: {args.project_path}")
        print(f"Success: {result.success}")
        print(f"Summary: {result.summary}")
        if result.stdout:
            print("\nSTDOUT:\n" + result.stdout[-4000:])
        if result.stderr:
            print("\nSTDERR:\n" + result.stderr[-4000:])
        print("=" * 72)
        return 0 if result.success else 1

    if args.mode == "capabilities":
        path = Path("docs/CAPABILITY_MATRIX.md")
        print(path.read_text(encoding="utf-8") if path.exists() else "Capability matrix missing.")
        return 0

    if args.mode == "system-health":
        settings = get_settings()
        checker = SystemHealthChecker(settings)
        items = checker.run()
        report = checker.render_markdown(items)
        out = settings.output_dir / "system_health_report.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(report)
        print(f"Saved: {out}")
        return 0 if all(i.status in {"pass", "info", "warning"} for i in items) else 1

    if args.mode == "agents":
        settings = get_settings()
        router = LLMRouter(settings)
        registry = build_agent_registry(InitialAnalysisEngine(router), router, QualityGate(), persistence=get_persistence(settings))
        if args.workflow:
            print(f"Agents in workflow `{args.workflow}`:")
            for agent in WORKFLOWS[args.workflow]:
                print(f"- {agent}")
        else:
            print("Available agents:")
            for agent in sorted(registry.keys()):
                print(f"- {agent}")
        return 0

    if args.mode == "ask":
        return ask_project(args.project_id, args.question)

    try:
        raw_input = read_input(args.input)
        settings = get_settings()
        require_real_llm_guard(settings, getattr(args, "require_real_llm", False), getattr(args, "allow_mock", False))
        orchestrator = QAFactoryOrchestrator(settings)
        state = orchestrator.run(
            args.mode,
            raw_input,
            approve=args.approve,
            client_id=args.client_id,
            execution_mode=resolve_execution_mode(args),
            from_step=args.from_step,
            only=args.only,
            project_id_override=getattr(args, "project_id", None),
            source_platform_override=getattr(args, "source_platform", None),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    fallback_count = orchestrator.router.fallback_to_mock_count
    if fallback_count > 0:
        print(f"WARNING: {fallback_count} LLM call(s) fell back to mock output. Check outputs/{state.project_id}/logs/factory.jsonl.", file=sys.stderr)
        if getattr(args, "require_real_llm", False) and not getattr(args, "allow_mock", False):
            return 2

    print("=" * 72)
    print(f"AI QA Factory v5.0.8 completed: {state.project_id}")
    print(f"Mode: {state.mode}")
    print(f"Execution mode: {state.execution_mode}")
    print(f"Source platform: {state.source_platform}")
    print(f"Opportunity type: {state.opportunity_type}")
    print(f"Recommended action: {state.recommended_action}")
    print(f"Project type: {state.project_type}")
    print(f"Stack: {state.stack_choice}")
    print(f"Prompt profile: {state.prompt_profile}")
    print(f"Fit score: {state.fit_score}/100")
    if state.suggested_price:
        print(f"Suggested price: {state.suggested_price}")
    print(f"Approval: {state.approval_status}")
    if state.execution_mode != "dry-run":
        print(f"Outputs: {settings.output_dir / state.project_id}")
    else:
        print("Outputs: dry-run only, final files not written")
    print("=" * 72)
    if state.approval_status == "needs_human_review":
        print("Human review required before client delivery.")
    return 0


def ask_project(project_id: str, question: str | None) -> int:
    settings = get_settings()
    persistence = get_persistence(settings)
    data = persistence.load_project(project_id)
    if not data:
        print(f"ERROR: saved project not found: {project_id}", file=sys.stderr)
        return 1
    router = LLMRouter(settings)
    outputs_dir = settings.output_dir / project_id
    artifact_summaries = []
    for path in sorted(outputs_dir.rglob("*.md"))[:25]:
        try:
            rel = path.relative_to(outputs_dir)
            artifact_summaries.append(f"### {rel}\n{path.read_text(encoding='utf-8', errors='ignore')[:1200]}")
        except Exception:
            continue
    context = "\n\n".join(artifact_summaries) or "No markdown artifacts found."

    def answer(q: str) -> str:
        response = router.complete(
            "analysis",
            "You answer questions about a saved AI QA Factory project. Be practical, concise and honest.",
            f"Project state JSON:\n{data}\n\nArtifacts:\n{context}\n\nQuestion:\n{q}",
            max_tokens=1200,
            context=data,
        )
        return response.text

    if question:
        print(answer(question))
        return 0
    if not sys.stdin.isatty():
        print("ERROR: --question is required in non-interactive mode", file=sys.stderr)
        return 1
    print(f"Loaded project: {project_id}. Type 'exit' to quit.")
    while True:
        q = input("> ").strip()
        if q.lower() in {"exit", "quit"}:
            return 0
        if q:
            print(answer(q))


def batch_filter(input_dir: str, settings) -> int:
    directory = Path(input_dir)
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    files = sorted([p for p in directory.iterdir() if p.suffix.lower() in {".txt", ".md"}])
    if not files:
        raise FileNotFoundError(f"No .txt or .md job files found in: {input_dir}")
    orchestrator = QAFactoryOrchestrator(settings)
    rows = []
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not raw:
            continue
        state = orchestrator.run("filter", raw, execution_mode="auto")
        rows.append({
            "file": path.name,
            "project_id": state.project_id,
            "action": state.recommended_action,
            "fit": state.fit_score,
            "platform": state.source_platform,
            "type": state.opportunity_type,
            "support": state.support_level,
            "commercial": state.commercial_fit,
        })
    report_lines = [
        "# Batch Opportunity Filter Report",
        "",
        "| File | Action | Fit | Platform | Type | Support | Commercial | Project |",
        "|---|---:|---:|---|---|---|---|---|",
    ]
    priority = {"strong_apply": 0, "apply_selectively": 1, "advisory_only": 2, "review_manually": 3, "skip_risky": 8, "skip_low_value": 9, "skip_not_core": 9}
    rows.sort(key=lambda r: (priority.get(r["action"], 5), -int(r["fit"])))
    for r in rows:
        report_lines.append(f"| {r['file']} | `{r['action']}` | {r['fit']} | {r['platform']} | {r['type']} | {r['support']} | {r['commercial']} | `{r['project_id']}` |")
    report_lines += [
        "",
        "## How to use this report",
        "- Start with `strong_apply` opportunities.",
        "- Use `apply_selectively` only with narrow/honest positioning.",
        "- Skip `skip_risky`, `skip_low_value`, and `skip_not_core` unless there is a strategic exception.",
    ]
    out = settings.output_dir / "batch_opportunity_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print("=" * 72)
    print(f"Batch filter completed: {len(rows)} opportunities")
    print(f"Report: {out}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
