"""WorkExecutionService (v3.0.0 Milestone 7) - the persisted client-work execution lifecycle.

Factory drives and PERSISTS: approval -> execution started -> progress/blockers -> produced
artifacts -> evidence registration -> validation -> delivery package -> resume after restart. The
Executor is pluggable: real work is Claude-Code-driven and human-approved (Factory records what was
produced); deterministic acceptance FIXTURE executors drive the same contract in CI. This is NOT a
second Claude Code and never claims an autonomous agent ran. No LLM/network is used here; state and
artifacts live on disk in the existing project workspace, so a later Claude session resumes cleanly.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.orchestration.content_safety import ContentSecretScanner
from core.orchestration.providers import ClockProvider, IdProvider
from core.orchestration.work_state_manager import WorkStateManager
from core.schemas.work_execution import ExecutionContext, ExecutionOutcome, ValidationOutcome
from core.schemas.work_run_state import WorkRunState

_ARK = "40_ark_work"
_PROGRESS = {"READY_TO_EXECUTE": 60, "EXECUTING": 75, "EXECUTION_PARTIAL": 75, "VERIFYING": 85,
             "REPAIR_REQUIRED": 70, "READY_FOR_REVIEW": 90, "READY_FOR_DELIVERY": 95,
             "COMPLETED": 100, "BLOCKED": 60, "FAILED": 100, "CANCELLED": 100}


class WorkExecutionError(Exception):
    pass


@dataclass
class LifecycleView:
    project_id: str
    status: str
    progress: int
    evidence_count: int
    tests_run: int
    tests_passed: int
    blockers: List[str]
    next_action: str
    delivery_ready: bool

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class WorkExecutionService:
    def __init__(self, clock: Optional[ClockProvider] = None, ids: Optional[IdProvider] = None,
                 output_dir: str = "outputs") -> None:
        self._clock = clock or ClockProvider()
        self._ids = ids or IdProvider()
        self._out = Path(output_dir)
        self._sm = WorkStateManager(self._clock)
        self._scanner = ContentSecretScanner()

    # --- workspace + safe persistence ------------------------------------------------------------
    def _ws(self, pid: str) -> Path:
        return self._out / pid / _ARK

    def _read_json(self, path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, path: Path, text: str) -> None:
        """Atomic per-file write with a secret scan (never wipes the workspace)."""
        if self._scanner.scan_text(path.name, text):
            raise WorkExecutionError(f"refusing to persist {path.name}: secret-like content detected")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _load_state(self, pid: str) -> WorkRunState:
        p = self._ws(pid) / "WORK_RUN_STATE.json"
        if not p.exists():
            raise WorkExecutionError(f"no work run state for '{pid}' (run analyze-job first)")
        return WorkRunState.from_dict(self._read_json(p))

    def _save_state(self, pid: str, state: WorkRunState) -> None:
        self._write(self._ws(pid) / "WORK_RUN_STATE.json",
                    json.dumps(state.to_dict(), indent=2, sort_keys=True))

    def _context(self, pid: str) -> ExecutionContext:
        wp = self._read_json(self._ws(pid) / "WORK_PACKET.json")
        reqs = [self._req(r) for r in wp.get("requirements", [])]
        return ExecutionContext(project_id=pid, profile=wp.get("capability_profile", ""),
                                workspace_dir=str(self._ws(pid)), requirements=reqs,
                                now=self._clock.now_iso())

    @staticmethod
    def _req(r: Any) -> str:
        return str(r.get("text") or r.get("requirement") or r) if isinstance(r, dict) else str(r)

    # --- lifecycle ------------------------------------------------------------------------------
    def approve(self, pid: str, reviewer: str, note: str = "") -> WorkRunState:
        if not reviewer.strip():
            raise WorkExecutionError("reviewer identity is required to approve")
        state = self._load_state(pid)
        if state.status == "WAITING_FOR_INFORMATION":
            # The operator has resolved the questions and chosen to proceed.
            state = self._sm.transition(state, "PLANNED", "operator resolved missing information",
                                        reviewer)
        if state.status not in ("PLANNED", "WAITING_FOR_APPROVAL"):
            raise WorkExecutionError(f"cannot approve from state {state.status}")
        state = self._sm.transition(state, "READY_TO_EXECUTE", f"approved by {reviewer}: {note}"[:200],
                                    reviewer)
        self._write(self._ws(pid) / "APPROVAL.json",
                    json.dumps({"reviewer": reviewer, "note": note, "approved": True,
                                "at": self._clock.now_iso()}, indent=2, sort_keys=True))
        self._save_state(pid, state)
        return state

    def execute(self, pid: str, executor: Any) -> Tuple[WorkRunState, ExecutionOutcome]:
        state = self._load_state(pid)
        if state.status == "REPAIR_REQUIRED":
            state = self._sm.transition(state, "READY_TO_EXECUTE", "repair requested", "cli")
        if state.status != "READY_TO_EXECUTE":
            raise WorkExecutionError(f"cannot start execution from state {state.status} (approve first)")
        eid = getattr(executor, "executor_id", "executor")
        state = self._sm.transition(state, "EXECUTING", "execution started", eid)
        self._save_state(pid, state)                      # persist BEFORE running the executor
        outcome = executor.execute(self._context(pid))
        self._write(self._ws(pid) / "EXECUTION_PROGRESS.json", json.dumps({
            "executor": eid, "is_acceptance_fixture": bool(getattr(executor, "is_acceptance_fixture",
                                                                   False)),
            "at": self._clock.now_iso(), "outcome": outcome.to_dict()}, indent=2, sort_keys=True))
        self._write(self._ws(pid) / "EVIDENCE_INDEX.json", json.dumps({
            "evidence": [e.to_dict() for e in outcome.evidence],
            "count": len(outcome.evidence)}, indent=2, sort_keys=True))
        to = "BLOCKED" if outcome.blockers else "VERIFYING"
        state = self._sm.transition(state, to, "execution produced artifacts", eid)
        self._save_state(pid, state)
        return state, outcome

    def validate(self, pid: str, executor: Any) -> Tuple[WorkRunState, ValidationOutcome]:
        state = self._load_state(pid)
        if state.status != "VERIFYING":
            raise WorkExecutionError(f"cannot validate from state {state.status}")
        eid = getattr(executor, "executor_id", "executor")
        result = executor.validate(self._context(pid))
        self._write(self._ws(pid) / "TEST_RESULTS.json",
                    json.dumps(result.to_dict(), indent=2, sort_keys=True))
        if result.passed:
            state = self._sm.transition(state, "READY_FOR_REVIEW", "validation passed", eid)
            state = self._sm.transition(state, "READY_FOR_DELIVERY", "review complete", "cli")
        else:
            state = self._sm.transition(state, "REPAIR_REQUIRED",
                                        f"validation failed: {len(result.failures)} failure(s)", eid)
        self._save_state(pid, state)
        return state, result

    def prepare_delivery(self, pid: str) -> Dict[str, Any]:
        state = self._load_state(pid)
        if state.status != "READY_FOR_DELIVERY":
            raise WorkExecutionError(f"delivery package needs state READY_FOR_DELIVERY (is {state.status})")
        ev = self._read_json(self._ws(pid) / "EVIDENCE_INDEX.json")
        tr = self._read_json(self._ws(pid) / "TEST_RESULTS.json")
        fr = self._read_json(self._ws(pid) / "FEASIBILITY_REPORT.json")
        prog = self._read_json(self._ws(pid) / "EXECUTION_PROGRESS.json")
        artifacts = [a.get("filename") for a in prog.get("outcome", {}).get("artifacts", [])]
        manifest = {"project_id": pid, "generated_at": self._clock.now_iso(),
                    "deliverables": fr.get("expected_deliverables", []),
                    "produced_artifacts": artifacts, "evidence_count": ev.get("count", 0),
                    "validation_passed": bool(tr.get("passed")), "tests_run": tr.get("tests_run", 0),
                    "approved_for_delivery": True,
                    "note": "validation passed; delivery package prepared (not yet sent to client)"}
        self._write(self._ws(pid) / "WORK_DELIVERY_MANIFEST.json",
                    json.dumps(manifest, indent=2, sort_keys=True))
        self._write(self._ws(pid) / "DELIVERY_REPORT.md", self._delivery_md(pid, fr, tr, artifacts,
                                                                            ev.get("count", 0)))
        self._write(self._ws(pid) / "CLIENT_MESSAGE.md", self._client_message_md(pid, fr))
        return manifest

    def mark_delivered(self, pid: str, note: str = "") -> WorkRunState:
        state = self._load_state(pid)
        state = self._sm.transition(state, "COMPLETED", f"delivered to client: {note}"[:200], "cli")
        self._save_state(pid, state)
        return state

    def status(self, pid: str) -> LifecycleView:
        state = self._load_state(pid)
        ev = self._read_json(self._ws(pid) / "EVIDENCE_INDEX.json")
        tr = self._read_json(self._ws(pid) / "TEST_RESULTS.json")
        prog = self._read_json(self._ws(pid) / "EXECUTION_PROGRESS.json")
        blockers = list(prog.get("outcome", {}).get("blockers", []))
        return LifecycleView(
            project_id=pid, status=state.status, progress=_PROGRESS.get(state.status, 40),
            evidence_count=ev.get("count", 0), tests_run=tr.get("tests_run", 0),
            tests_passed=tr.get("tests_passed", 0), blockers=blockers,
            next_action=self._next_action(state.status, blockers),
            delivery_ready=state.status in ("READY_FOR_DELIVERY", "COMPLETED"))

    def resume(self, pid: str) -> LifecycleView:
        """Reload the persisted state from disk (proves resume after restart / a new Claude session)."""
        return self.status(pid)

    @staticmethod
    def _next_action(status: str, blockers: List[str]) -> str:
        if blockers:
            return "resolve execution blockers, then re-run execution"
        return {"PLANNED": "review the feasibility summary, then approve",
                "WAITING_FOR_APPROVAL": "approve the plan to proceed",
                "READY_TO_EXECUTE": "start execution (Claude-Code-driven or a fixture executor)",
                "EXECUTING": "execution in progress",
                "VERIFYING": "run validation on the produced artifacts",
                "REPAIR_REQUIRED": "fix the failures and re-run execution",
                "READY_FOR_REVIEW": "review, then advance to delivery",
                "READY_FOR_DELIVERY": "prepare the delivery package, then send and mark delivered",
                "COMPLETED": "delivered"}.get(status, "review the project state")

    @staticmethod
    def _delivery_md(pid: str, fr: Dict[str, Any], tr: Dict[str, Any], artifacts: List[str],
                     evidence: int) -> str:
        lines = [f"# Delivery Report - {pid}", "",
                 f"**Scope.** {fr.get('client_intent', '')}", "",
                 "## Deliverables produced", *[f"- {a}" for a in artifacts], "",
                 f"## Validation\n- tests run: {tr.get('tests_run', 0)} · passed: "
                 f"{tr.get('tests_passed', 0)} · result: {'PASS' if tr.get('passed') else 'FAIL'}",
                 f"- evidence items: {evidence}", "",
                 "## Known limitations", "- as noted during execution", "",
                 "_Validation passed before this package was prepared. Nothing was sent to the client "
                 "automatically._"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _client_message_md(pid: str, fr: Dict[str, Any]) -> str:
        return (f"# Client Message (draft) - {pid}\n\nHi,\n\nThe work is complete and validated. The "
                "delivery package includes the implementation, test results, evidence, and setup "
                "instructions. Please review; happy to walk through anything.\n\n"
                "_Draft for you to edit before sending._\n")
