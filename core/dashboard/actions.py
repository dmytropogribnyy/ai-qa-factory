"""Dashboard actions + project detail (v3.1 M1/M5/M6).

AllowedAction is derived from the REAL lifecycle state (never invented in JS). Mutations map to
guarded HTTP endpoints that call WorkExecutionService - the same service the CLI uses. Actions that
would require an arbitrary command/argv (record-execution, validate) are NEVER HTTP mutations: they
are Claude Code handoffs (open VS Code / copy CLI command). The Dashboard prepares work orders and
shows state; Claude Code executes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.dashboard.read_model import health_of, stage_label
from core.orchestration.work_execution import WorkExecutionService

_ARK = "40_ark_work"


@dataclass
class AllowedAction:
    id: str
    label: str
    kind: str            # http_mutation | handoff | navigate
    method: str = ""     # POST for http_mutation
    endpoint: str = ""   # e.g. /api/work/approve
    confirm: bool = False
    primary: bool = False
    fields: List[str] = field(default_factory=list)   # required inputs (reviewer/note/reason)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# The single guarded mutation endpoints (all POST, behind the shared guard; none take a command).
_MUT = "/api/work"


def allowed_actions(status: str) -> List[AllowedAction]:
    s = status
    handoff_execute = AllowedAction("open_vscode", "Open in VS Code", "handoff", primary=True,
                                    note="do the work in VS Code with Claude Code, then record it")
    refresh = AllowedAction("refresh", "Refresh", "navigate", method="GET")
    if s in ("PLANNED", "WAITING_FOR_APPROVAL", "WAITING_FOR_INFORMATION"):
        return [AllowedAction("approve", "Review Plan & Approve", "http_mutation", "POST",
                              f"{_MUT}/approve", primary=True, fields=["reviewer"]), refresh]
    if s == "READY_TO_EXECUTE":
        return [handoff_execute,
                AllowedAction("copy_work_order", "Copy Claude Code Work Order", "handoff"),
                AllowedAction("copy_workspace", "Copy Workspace Path", "handoff"), refresh]
    if s in ("EXECUTING", "EXECUTION_PARTIAL"):
        return [handoff_execute, refresh]
    if s == "VERIFYING":
        return [AllowedAction("open_vscode", "Run Validation in VS Code", "handoff", primary=True,
                              note="validation runs a real command in VS Code, never over HTTP"),
                refresh]
    if s == "REPAIR_REQUIRED":
        return [AllowedAction("open_vscode", "Resolve in VS Code", "handoff", primary=True,
                              note="fix the failures, then re-record execution and validate"), refresh]
    if s == "BLOCKED":
        return [AllowedAction("open_vscode", "Resolve Blocker in VS Code", "handoff", primary=True),
                refresh]
    if s == "READY_FOR_REVIEW":
        return [AllowedAction("review_approve", "Approve Review", "http_mutation", "POST",
                              f"{_MUT}/review", primary=True, fields=["reviewer"]),
                AllowedAction("review_reject", "Reject (send to repair)", "http_mutation", "POST",
                              f"{_MUT}/review-reject", confirm=True, fields=["reviewer"]), refresh]
    if s == "READY_FOR_DELIVERY":
        return [AllowedAction("prepare_delivery", "Prepare Delivery", "http_mutation", "POST",
                              f"{_MUT}/prepare-delivery", primary=True), refresh]
    if s == "DELIVERY_PREPARED":
        return [AllowedAction("mark_delivered", "Mark Delivered (I sent it)", "http_mutation", "POST",
                              f"{_MUT}/mark-delivered", confirm=True, primary=True,
                              note="records your manual send; this sends nothing"),
                AllowedAction("reopen_delivery", "Reopen Delivery", "http_mutation", "POST",
                              f"{_MUT}/reopen-delivery", confirm=True, fields=["reviewer", "reason"]),
                refresh]
    return [refresh]


def primary_action(status: str) -> Optional[Dict[str, Any]]:
    for a in allowed_actions(status):
        if a.primary:
            return a.to_dict()
    return None


class ProjectDetailBuilder:
    """Reads the persisted per-project state (confined) and assembles the detail DTO."""

    def __init__(self, output_dir: str) -> None:
        self._out = output_dir
        self._svc = WorkExecutionService(output_dir=output_dir)

    def _ws(self, pid: str) -> Path:
        return self._svc._ws(pid)          # confined + project-id validated by the service

    def _read(self, pid: str, name: str) -> Dict[str, Any]:
        return self._svc._read_json(self._ws(pid) / name)

    def exists(self, pid: str) -> bool:
        try:
            return (self._ws(pid) / "WORK_RUN_STATE.json").exists()
        except Exception:
            return False

    def detail(self, pid: str) -> Optional[Dict[str, Any]]:
        if not self.exists(pid):
            return None
        state = self._svc._load_state(pid)
        wp = self._read(pid, "WORK_PACKET.json")
        fr = self._read(pid, "FEASIBILITY_REPORT.json")
        ev = self._read(pid, "EVIDENCE_INDEX.json")
        tr = self._read(pid, "TEST_RESULTS.json")
        review = self._read(pid, "REVIEW.json")
        manifest = self._read(pid, "WORK_DELIVERY_MANIFEST.json")
        prog = self._read(pid, "EXECUTION_PROGRESS.json")
        blockers = list(prog.get("outcome", {}).get("blockers", []))
        view = self._svc.status(pid)
        header = {"project_id": pid, "title": wp.get("title") or fr.get("client_intent") or pid,
                  "source": wp.get("source_platform") or "manual", "stage": stage_label(state.status),
                  "status": state.status, "health": ("attention" if blockers else health_of(state.status)),
                  "progress": view.progress}
        summary = {"status": state.status, "stage": stage_label(state.status),
                   "next_action": view.next_action, "progress": view.progress, "blockers": blockers,
                   "acceptance_criteria": fr.get("acceptance_criteria", []),
                   "required_tools": fr.get("selected_tools", []),
                   "tests_run": view.tests_run, "tests_passed": view.tests_passed,
                   "evidence_count": view.evidence_count}
        plan = {"client_intent": fr.get("client_intent", ""), "verdict": fr.get("verdict", ""),
                "requirements": [_req_text(r) for r in wp.get("requirements", [])],
                "proposed_plan": fr.get("proposed_plan", fr.get("plan", [])),
                "client_questions": fr.get("client_questions", []),
                "approval": self._read(pid, "APPROVAL.json")}
        # Evidence with a safe preview href + a Stale flag when the current hash no longer matches
        # the validated snapshot (M7).
        validated = self._read(pid, "VALIDATED_ARTIFACTS.json").get("hashes", {})
        ev_items = []
        for e in ev.get("evidence", []):
            rel = e.get("relative_path", "")
            item = dict(e)
            item["href"] = (f"/work-evidence?project={pid}&path={rel}") if rel else ""
            if rel and rel in validated:
                cur = self._svc._hash_map(pid, [rel]).get(rel)
                item["integrity"] = "verified" if cur == validated[rel] else "stale"
            else:
                item["integrity"] = "unverified"
            ev_items.append(item)
        results = {"validation_passed": bool(tr.get("passed")), "tests_run": tr.get("tests_run", 0),
                   "tests_passed": tr.get("tests_passed", 0), "failures": tr.get("failures", []),
                   "evidence": ev_items,
                   "artifacts": [a.get("filename") for a in prog.get("outcome", {}).get("artifacts", [])]}
        delivery = {"status": state.status,
                    "review_approved": bool(review.get("approved")),
                    "reviewed_by": review.get("reviewer", ""),
                    "manifest_digest": manifest.get("manifest_digest", ""),
                    "included_files": manifest.get("included_files", []),
                    "included": manifest.get("included", {}),
                    "prepared_at": self._read(pid, "DELIVERY_PREPARED.json").get("prepared_at", ""),
                    "client_message_source": manifest.get("client_message_source", ""),
                    "history": self._read(pid, "DELIVERY_HISTORY.json").get("events", [])}
        return {"schema": "dashboard-read-model/v1", "header": header, "summary": summary,
                "plan": plan, "results": results, "delivery": delivery,
                "allowed_actions": [a.to_dict() for a in allowed_actions(state.status)],
                "primary_action": primary_action(state.status),
                "workspace_path": str(self._ws(pid))}

    def work_order(self, pid: str) -> Optional[str]:
        """A structured Claude Code work order built from persisted state (no second prompt store)."""
        d = self.detail(pid)
        if d is None:
            return None
        s, p = d["summary"], d["plan"]

        def _bullets(items: List[Any], empty: str) -> List[str]:
            vals = [f"- {x}" for x in items if str(x).strip()]
            return vals or [empty]

        lines = [f"# Claude Code Work Order - {pid}", "",
                 f"Project: {pid}", f"Workspace: {d['workspace_path']}",
                 f"Current lifecycle state: {s['status']} ({s['stage']})", "",
                 f"## Client intent\n{p['client_intent']}", "",
                 "## Requirements", *_bullets(p["requirements"], "- (none recorded)"), "",
                 "## Acceptance criteria", *_bullets(s["acceptance_criteria"], "- (none recorded)"), "",
                 "## Approved plan", *_bullets(p["proposed_plan"], "- (see FEASIBILITY_SUMMARY.md)"), "",
                 "## Required tools", *_bullets(s["required_tools"], "- (none)"), "",
                 "## Do the work in VS Code, then record it via the CLI:", "",
                 f"    python main.py client-work record-execution --project-id {pid} \\",
                 "        --artifacts <path1,path2> --evidence <path:desc>",
                 f"    python main.py client-work validate --project-id {pid} \\",
                 '        --validation-argv-json \'["python","-m","pytest","-q"]\'',
                 f"    python main.py client-work status --project-id {pid}", "",
                 "The Dashboard shows persisted progress/evidence; it does not run your code."]
        return "\n".join(lines) + "\n"


def _req_text(r: Any) -> str:
    if isinstance(r, dict):
        return str(r.get("text") or r.get("requirement") or r)
    return str(r)


def work_order_text(output_dir: str, pid: str) -> Optional[str]:
    return ProjectDetailBuilder(output_dir).work_order(pid)
