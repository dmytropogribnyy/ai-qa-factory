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
    from core.orchestration.providers import validate_project_id
    return validate_project_id(pid)


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


def run_analyze_job(args) -> int:
    """v3.0.0 — analyze a potential client (Upwork/direct) job: read-only planning + a human-readable
    feasibility verdict. NEVER starts implementation. Exit: 0 ok, 1 invalid, 2 safety block."""
    import sys as _sys

    from core.config import get_settings
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

    from core.orchestration.content_safety import redact_intake_text
    from core.orchestration.providers import ClockProvider, IdProvider, generate_project_id
    generated = args.project_id is None
    project_id = (generate_project_id(redact_intake_text(raw).text, IdProvider())
                  if generated else args.project_id)
    if not _valid_project_id(project_id):
        print("ERROR: invalid project id (use [A-Za-z0-9._-], no separators)", file=_sys.stderr)
        return 2
    try:
        out_dir = Path(get_settings().output_dir).resolve()
        from core.orchestration.client_work import ClientWorkService
        res = ClientWorkService(ClockProvider(), IdProvider(), output_dir=str(out_dir)).analyze(
            raw, project_id=project_id, source_platform=args.source_platform,
            profile_override=args.profile, fresh_only=generated)
    except Exception as exc:
        print(f"BLOCKED/ERROR: {exc}", file=_sys.stderr)
        return 2
    r = res.feasibility
    print(f"=== Feasibility: {r.verdict}  (confidence {r.confidence}, risk {r.risk_level}) ===")
    print(f"Project: {res.project_id}   Profile: {res.profile or '(unresolved)'}")
    print(f"Intent: {r.client_intent}")
    print(f"Technical fit: {r.technical_fit}")
    print(f"Effort: {r.estimated_effort}   Pricing: {r.pricing_guidance}")
    if r.client_questions:
        print("Questions for the client:")
        for q in r.client_questions:
            print(f"  - {q}")
    if r.reasons_to_reject:
        print("Honest reasons this may not fit:")
        for x in r.reasons_to_reject:
            print(f"  - {x}")
    print(f"Workspace: {res.workspace_dir}")
    print("Analysis only - nothing executed. Review FEASIBILITY_SUMMARY.md / PROPOSAL_DRAFT.md, "
          "then approve to proceed.")
    return 0


def _parse_artifacts(spec, kind, is_evidence=False):
    """Parse 'path[:kind_or_desc],...' into ProducedArtifact list."""
    from core.orchestration.operator_executor import ProducedArtifact
    out = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        path, _, extra = item.partition(":")
        path = path.strip()
        if not path:
            continue
        if is_evidence:
            out.append(ProducedArtifact(path, "report", is_evidence=True, evidence_kind="report",
                                        description=extra.strip() or path))
        else:
            out.append(ProducedArtifact(path, (extra.strip() or kind)))
    return out


def run_client_work(args) -> int:
    """v3.0.0/v3.0.1 - operator CLI over the persisted client-work lifecycle. Execution is
    Claude-Code-driven and human-approved; the Factory records/validates/reviews/delivers what was
    produced. A whole client job completes via these commands - no custom Python driver needed."""
    import sys as _sys

    from core.config import get_settings
    from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
    from core.orchestration.work_state_manager import InvalidTransitionError
    if not args.project_id:
        print("ERROR: --project-id is required", file=_sys.stderr)
        return 1
    svc = WorkExecutionService(output_dir=str(Path(get_settings().output_dir)))
    pid = args.project_id
    try:
        if args.action in ("status", "resume"):
            v = svc.resume(pid) if args.action == "resume" else svc.status(pid)
            print(f"Project {pid}: {v.status} ({v.progress}%)  evidence={v.evidence_count}  "
                  f"tests={v.tests_passed}/{v.tests_run}  delivery_ready={v.delivery_ready}")
            if v.blockers:
                print("Blockers: " + ", ".join(v.blockers))
            print(f"Next: {v.next_action}")
        elif args.action == "approve":
            if not (args.reviewer or "").strip():
                print("ERROR: --reviewer is required to approve", file=_sys.stderr)
                return 1
            st = svc.approve(pid, reviewer=args.reviewer, note=args.note or "")
            print(f"Approved {pid}: {st.status}. Do the work in the workspace, then: record-execution "
                  "-> validate -> review -> prepare-delivery.")
        elif args.action == "record-execution":
            from core.orchestration.operator_executor import OperatorWorkspaceExecutor
            produced = (_parse_artifacts(args.artifacts, "artifact")
                        + _parse_artifacts(args.evidence, "report", is_evidence=True))
            if not produced:
                print("ERROR: give --artifacts and/or --evidence (comma-separated relative paths)",
                      file=_sys.stderr)
                return 1
            executor = OperatorWorkspaceExecutor(produced, executor_id="operator:cli")
            state, outcome = svc.execute(pid, executor)
            if outcome.blockers:
                print("BLOCKED: " + "; ".join(outcome.blockers), file=_sys.stderr)
                return 2
            print(f"Recorded execution for {pid}: {len(outcome.artifacts)} artifact(s), "
                  f"{len(outcome.evidence)} evidence item(s). State {state.status}. Now: validate.")
        elif args.action == "validate":
            from core.orchestration.operator_executor import (
                CommandValidationExecutor,
                ValidationCommandError,
            )
            command = None
            if (getattr(args, "validation_argv_json", None) or "").strip():
                import json as _json
                try:
                    command = _json.loads(args.validation_argv_json)
                except ValueError:
                    print("ERROR: --validation-argv-json is not valid JSON", file=_sys.stderr)
                    return 1
                if (not isinstance(command, list) or not command
                        or not all(isinstance(a, str) and a for a in command)):
                    print("ERROR: --validation-argv-json must be a JSON array of non-empty strings, "
                          "e.g. '[\"python\", \"-m\", \"pytest\", \"-q\"]'", file=_sys.stderr)
                    return 1
            elif (args.command or "").strip():
                command = args.command      # compatibility: POSIX-tokenized command string
            else:
                print("ERROR: give --validation-argv-json '[\"python\", \"-m\", \"pytest\", \"-q\"]' "
                      "(preferred; unambiguous on Windows) or --command \"pytest -q\"",
                      file=_sys.stderr)
                return 1
            try:
                executor = CommandValidationExecutor(command)
            except ValidationCommandError as exc:
                print(f"ERROR: invalid validation command: {exc}", file=_sys.stderr)
                return 1
            state, result = svc.validate(pid, executor)
            print(f"Validation for {pid}: {'PASS' if result.passed else 'FAIL'} "
                  f"({result.tests_passed}/{result.tests_run}). State {state.status}. "
                  f"{'Now: review.' if result.passed else 'Fix, then record-execution again.'}")
            return 0 if result.passed else 3
        elif args.action == "review":
            if not (args.reviewer or "").strip():
                print("ERROR: --reviewer is required to review", file=_sys.stderr)
                return 1
            st = svc.review(pid, reviewer=args.reviewer, approved=not args.reject, note=args.note or "")
            print(f"Review {'REJECTED' if args.reject else 'APPROVED'} for {pid}: {st.status}.")
        elif args.action == "prepare-delivery":
            m = svc.prepare_delivery(pid)
            print(f"Delivery package prepared for {pid}: {len(m['included_files'])} file(s), "
                  f"evidence={m['evidence_count']}, validation_passed={m['validation_passed']}, "
                  f"reviewed_by={m.get('reviewed_by') or '(none)'}, digest={m['manifest_digest'][:23]}... "
                  "State DELIVERY_PREPARED. Send the package yourself, then: mark-delivered.")
        elif args.action == "reopen-delivery":
            if not (args.reviewer or "").strip():
                print("ERROR: --reviewer is required to reopen a delivery", file=_sys.stderr)
                return 1
            if not (args.reason or "").strip():
                print("ERROR: --reason is required to reopen a delivery", file=_sys.stderr)
                return 1
            entry = svc.reopen_delivery(pid, reviewer=args.reviewer, reason=args.reason)
            outcome = entry["outcome"]
            if outcome == "REPAIR_REQUIRED":
                print(f"Reopened {pid}: validated content changed ({len(entry['registered_changed'])} "
                      "file(s)) -> REPAIR_REQUIRED. Redo: record-execution -> validate -> review -> "
                      "prepare-delivery.")
            else:
                print(f"Reopened {pid}: drafts/metadata only -> READY_FOR_DELIVERY. "
                      "Re-run prepare-delivery when ready.")
        elif args.action == "mark-delivered":
            st = svc.mark_delivered(pid, note=args.note or "")
            print(f"Marked delivered for {pid}: {st.status}. (This recorded your assertion that you "
                  "sent the prepared package manually; nothing was sent by this command.)")
        elif args.action in ("worker-start", "worker-resume"):
            # Bounded autonomous execution via the real Claude Code worker, built ONLY from the
            # persisted project state. Confined to the workspace; never a prompt/command from a caller.
            # The project id is validated by workspace_dir BEFORE any path op (rejects traversal,
            # separators, absolute paths, Windows reserved names, control chars).
            from core.orchestration.claude_worker import ClaudeWorkerExecutor
            ws = svc.workspace_dir(pid)                       # validates id first (raises for unsafe)
            (ws / "WORKER_CANCEL.json").unlink(missing_ok=True)   # clear any stale cancel marker
            executor = ClaudeWorkerExecutor(resume=(args.action == "worker-resume"),
                                            timeout_s=int(getattr(args, "timeout", 300) or 300))
            state, outcome = svc.execute(pid, executor)      # requires the project to exist + approval
            if outcome.blockers:
                print("Worker BLOCKED: " + "; ".join(outcome.blockers), file=_sys.stderr)
                return 2
            print(f"Worker recorded execution for {pid}: {len(outcome.artifacts)} file(s) changed. "
                  f"State {state.status}. Now: validate (a real command), then review.")
        elif args.action == "worker-status":
            import json as _json
            v = svc.status(pid)                              # validates id + requires the project exists
            ws = svc.workspace_dir(pid)                       # confined workspace (already validated)
            print(f"Project {pid}: {v.status} ({v.progress}%). Next: {v.next_action}")
            sess_path = ws / "EXECUTION_SESSION.json"
            if sess_path.exists():
                s = _json.loads(sess_path.read_text(encoding="utf-8"))
                print(f"Worker session: executor={s.get('executor')} session={s.get('session_id')} "
                      f"stop={s.get('stop_reason')} files_changed={len(s.get('files_changed', []))} "
                      f"cost_usd={s.get('cost_usd')} ok={s.get('ok')}")
                if s.get("blockers"):
                    print("Blockers: " + "; ".join(s["blockers"]))
            else:
                print("No worker session recorded yet.")
        elif args.action == "worker-cancel":
            import json as _json
            from datetime import datetime, timezone
            # Validate the id AND require the project to genuinely exist before writing anything, so a
            # rejected/nonexistent request never creates a workspace, marker, or any other file.
            if not svc.project_exists(pid):
                print(f"ERROR: no such project '{pid}' (nothing to cancel; run analyze-job first)",
                      file=_sys.stderr)
                return 2
            ws = svc.workspace_dir(pid)                       # confined workspace (already validated)
            (ws / "WORKER_CANCEL.json").write_text(
                _json.dumps({"requested_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8")
            print(f"Cancel requested for {pid}: a running worker will stop safely (process tree "
                  "terminated); a not-yet-started worker will not launch.")
        else:
            print("ERROR: unknown action", file=_sys.stderr)
            return 1
    except (WorkExecutionError, InvalidTransitionError) as exc:
        print(f"BLOCKED: {exc}", file=_sys.stderr)
        return 2
    return 0


def run_operator_dashboard(args) -> int:
    """v3.1 - the local operator dashboard (Overview/Work/Scout/Tools) over the existing core.

    Reads persisted state through read-only DTOs and exposes guarded lifecycle actions (approve,
    review, prepare/reopen/mark delivery) that call the SAME services the CLI uses. It never runs an
    arbitrary command, never accepts argv over HTTP, and sends nothing.
    """
    import time as _time

    from core.config import get_settings
    from core.scout.dashboard import remove_ownership_record, start_dashboard
    from core.scout.service import ScoutService
    out = args.output or str(Path(get_settings().output_dir))
    service = ScoutService(out)
    server, url = start_dashboard(service, port=args.port, operator_home=True)
    bound_port = server.server_address[1]
    print(f"AI QA Factory operator dashboard: {url}   (Ctrl+C to stop)")
    print(f"  Overview {url}/  ·  Work {url}/work  ·  Scout {url}/scout  ·  Tools {url}/tools")
    print("  Reads persisted state; lifecycle actions are guarded; nothing is scanned or sent.")
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        print("dashboard stopped")
    finally:
        remove_ownership_record(out, bound_port)
    return 0


def run_projects(args) -> int:
    """v3.0.0 - one read-only index over client-work projects + Scout campaigns (no new database)."""
    from core.config import get_settings
    from core.orchestration.project_index import ProjectIndex
    out_dir = str(Path(get_settings().output_dir))
    index = ProjectIndex(out_dir)
    if getattr(args, "as_json", False):
        import json as _json
        print(_json.dumps(index.snapshot(), indent=2, ensure_ascii=False))
        return 0
    projects = index.list_projects()
    print(f"Projects ({len(projects)}) - client-work + Scout, from existing state:")
    for p in projects:
        print(f"  [{p.type:14}] {p.project_id:28} {p.lifecycle_state:22} {p.progress:3}%  "
              f"blockers={len(p.blockers)} evidence={p.evidence_count}")
        print(f"      next: {p.operator_next_action}")
    return 0


def run_tool_status(args) -> int:
    """v3.0.0 - honest capability/tool readiness (no live MCP or network call; none live-accepted)."""
    from datetime import datetime, timezone

    from core.orchestration.tool_broker import ToolBroker
    broker = ToolBroker(clock=lambda: datetime.now(timezone.utc).isoformat())
    if getattr(args, "as_json", False):
        import json as _json
        print(_json.dumps(broker.snapshot(), indent=2, ensure_ascii=False))
        return 0
    print("Tool readiness (deterministic; no live MCP/network call; none live-accepted):")
    print(f"  {'tool':22} {'level':18} {'domain':26} {'readiness':16} auth / fallback")
    for t in broker.discover():
        print(f"  {t.id:22} {t.ui_level:18} {t.domain:26} {t.readiness:16} "
              f"{t.auth_requirement} / {t.fallback}")
        if t.readiness in ("unavailable", "blocked-by-auth") and t.setup_instruction:
            print(f"      setup: {t.setup_instruction}")
    print("Session-only MCP tools are 'declared' here; connect them in Claude Code (/mcp) to use.")
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

    # v3.0.0 — analyze a potential client job (read-only planning + feasibility verdict; never executes)
    analyze_cmd = subparsers.add_parser(
        "analyze-job",
        help="Analyze a potential Upwork/direct client job: feasibility verdict + questions + proposal "
             "(read-only; nothing is executed)")
    analyze_src = analyze_cmd.add_mutually_exclusive_group(required=True)
    analyze_src.add_argument("--input", "-i", help="Path to the job brief file")
    analyze_src.add_argument("--text", help="Literal job brief text")
    analyze_src.add_argument("--stdin", action="store_true", help="Read the brief from stdin")
    analyze_cmd.add_argument("--project-id", help="Project id (safe name; generated when omitted)")
    analyze_cmd.add_argument("--source-platform", default="unknown",
                             help="Commercial source platform (e.g. upwork, direct)")
    analyze_cmd.add_argument("--profile", help="Optional capability-profile override")

    # v3.0.0 — honest capability/tool readiness broker
    tool_cmd = subparsers.add_parser(
        "tool-status", help="Show honest tool readiness (internal/local/session/external; none live)")
    tool_cmd.add_argument("--json", action="store_true", dest="as_json",
                          help="Print the machine-readable capability snapshot")

    # v3.1 — the local operator dashboard (Overview / Scout / Work / Tools) over the existing core
    dash_cmd = subparsers.add_parser(
        "dashboard", help="Start the local operator dashboard on 127.0.0.1 (Overview, Work, Scout, "
                          "Tools; read-only reads + guarded lifecycle actions; nothing is sent)")
    dash_cmd.add_argument("--port", type=int, default=8765, help="Dashboard port")
    dash_cmd.add_argument("--output", default=None, help="Output workspace (defaults to OUTPUT_DIR)")

    # v3.0.0 — unified project index (client-work + Scout)
    projects_cmd = subparsers.add_parser(
        "projects", help="List client-work projects + Scout campaigns from existing state (read-only)")
    projects_cmd.add_argument("--json", action="store_true", dest="as_json",
                              help="Print the machine-readable project snapshot")

    # v3.0.0 — operator actions over the persisted client-work execution lifecycle
    cw_cmd = subparsers.add_parser(
        "client-work",
        help="Drive the persisted client-work lifecycle end to end: approve, record-execution, "
             "validate, review, prepare-delivery, mark-delivered, status/resume "
             "(execution is Claude-Code-driven and human-approved)")
    cw_cmd.add_argument("action", choices=["status", "resume", "approve", "record-execution",
                                           "validate", "review", "prepare-delivery",
                                           "reopen-delivery", "mark-delivered",
                                           "worker-start", "worker-status", "worker-resume",
                                           "worker-cancel"])
    cw_cmd.add_argument("--project-id", required=True, help="Project id (from analyze-job)")
    cw_cmd.add_argument("--reviewer", help="Reviewer identity (required to approve/review/reopen)")
    cw_cmd.add_argument("--note", default="", help="Optional note (approval/review/delivery)")
    cw_cmd.add_argument("--reason", default="", help="reopen-delivery: why the prepared delivery is "
                                                     "being reopened (required)")
    cw_cmd.add_argument("--artifacts", help="record-execution: comma-separated relative artifact "
                                            "paths, each optionally 'path:kind'")
    cw_cmd.add_argument("--evidence", help="record-execution: comma-separated relative evidence "
                                           "paths, each optionally 'path:description'")
    cw_cmd.add_argument("--validation-argv-json", dest="validation_argv_json",
                        help="validate: the operator's validation command as a JSON array of "
                             "argument strings (preferred; cross-platform), e.g. "
                             "'[\"python\", \"-m\", \"pytest\", \"-q\"]'. Runs in the workspace "
                             "with shell=False and a bounded timeout.")
    cw_cmd.add_argument("--command", help="validate (compatibility): a single command string, "
                                          "tokenized POSIX-style; prefer --validation-argv-json "
                                          "on Windows or for paths with spaces")
    cw_cmd.add_argument("--reject", action="store_true", help="review: reject (send to REPAIR_REQUIRED)")
    cw_cmd.add_argument("--timeout", type=int, default=300,
                        help="worker-start/resume: hard wall-clock bound in seconds (default 300)")

    # Phase 8.3 — Prospect QA Scout (bounded, read-only local runtime)
    scout_cmd = subparsers.add_parser(
        "scout", help="Prospect QA Scout v1.0 — bounded read-only local QA over public seeds"
    )
    scout_cmd.add_argument("action", choices=[
        "run", "demo", "dashboard", "control", "smoke",
        "campaign-demo", "campaign-plan", "campaign-run", "providers",
        "presend-demo", "db-status", "db-backup", "db-restore", "review-list", "doctor",
        "radar-demo", "send", "outreach-control", "comms-status", "mcp-audit",
        "draft-create", "draft-preview", "draft-edit", "draft-approve", "draft-reject",
        "draft-revoke", "draft-status", "gmail-auth", "gmail-status",
        "gmail-revoke-local-token", "provider-status"])
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
    # Final Phase II — approved communication options (sending is disabled by default).
    scout_cmd.add_argument("--draft-revision", dest="draft_revision", help="Draft revision id (send)")
    scout_cmd.add_argument("--approval-id", dest="approval_id", default="",
                           help="Approval id (send; defaults to ap-<revision>)")
    scout_cmd.add_argument("--provider", help="Outbound provider id (send)")
    scout_cmd.add_argument("--approve-send", dest="approve_send", action="store_true",
                           help="Go LIVE (default is dry-run). Requires --reviewer + --confirm-recipient")
    scout_cmd.add_argument("--reviewer", help="Non-empty reviewer identity (send)")
    scout_cmd.add_argument("--confirm-recipient", dest="confirm_recipient",
                           help="Exact normalized recipient confirmation (send)")
    scout_cmd.add_argument("--scope", help="Outreach-control scope (global|campaign:x|provider:x|channel:x)")
    scout_cmd.add_argument("--state", choices=["enable", "disable", "pause", "kill"],
                           help="Outreach-control state")
    # v2.0.1 — human review CLI (one revision at a time; no bulk / approve-all).
    scout_cmd.add_argument("--draft-id", dest="draft_id", help="Draft id (draft-create)")
    scout_cmd.add_argument("--company-id", dest="company_id", help="Company id (draft-create)")
    scout_cmd.add_argument("--contact-id", dest="contact_id", help="Contact id (draft-create)")
    scout_cmd.add_argument("--finding-id", dest="finding_id", help="Finding id (draft-create)")
    scout_cmd.add_argument("--subject", help="Draft subject (draft-create/draft-edit)")
    scout_cmd.add_argument("--body", help="Draft body (prefer --body-file to avoid shell history)")
    scout_cmd.add_argument("--body-file", dest="body_file",
                           help="Read the draft body from a file (never echoed into shell history)")
    scout_cmd.add_argument("--reason", help="Reason (draft-reject/draft-revoke)")
    scout_cmd.add_argument("--reviewed-content-hash", dest="reviewed_content_hash",
                           help="Exact preview hash from draft-preview (draft-approve)")
    scout_cmd.add_argument("--confirm", help="Typed confirmation (draft-approve: APPROVE; "
                                             "gmail-revoke-local-token: REVOKE)")
    # v2.0.1 — Gmail OAuth desktop flow (credentials supplied locally; never committed).
    scout_cmd.add_argument("--client-config", dest="client_config", help="Gmail OAuth client JSON path")
    scout_cmd.add_argument("--token-store", dest="token_store", help="Gmail OAuth token store path")
    scout_cmd.add_argument("--expected-account", dest="expected_account",
                           help="Authorized Gmail account (default dipptrue@gmail.com)")

    args = parser.parse_args(argv)

    if args.mode == "work":
        return run_work(args)

    if args.mode == "analyze-job":
        return run_analyze_job(args)

    if args.mode == "tool-status":
        return run_tool_status(args)

    if args.mode == "projects":
        return run_projects(args)

    if args.mode == "client-work":
        return run_client_work(args)

    if args.mode == "dashboard":
        return run_operator_dashboard(args)

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
