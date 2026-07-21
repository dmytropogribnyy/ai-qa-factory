"""Shared project index (v3.0.0 Milestone 5).

One read-only view over BOTH client-work projects (outputs/<id>/40_ark_work/) and Scout campaigns
(outputs/scout/<id>/), reading the EXISTING artifacts/state as the source of truth. It creates no
new database and duplicates no business entity - it is an adapter that unifies what already exists.
Malformed/partial state is reported, never crashed on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# Coarse progress from the client-work lifecycle state.
_CLIENT_PROGRESS = {
    "RECEIVED": 10, "INTAKE_COMPLETE": 25, "PLANNED": 40, "WAITING_FOR_INFORMATION": 40,
    "WAITING_FOR_APPROVAL": 55, "READY_TO_EXECUTE": 60, "EXECUTING": 75, "EXECUTION_PARTIAL": 75,
    "VERIFYING": 85, "READY_FOR_REVIEW": 90, "READY_FOR_DELIVERY": 95, "DELIVERY_PREPARED": 98,
    "COMPLETED": 100, "BLOCKED": 40, "FAILED": 100, "CANCELLED": 100,
}


@dataclass
class ProjectEntry:
    project_id: str
    type: str                     # client_work | scout_campaign
    title: str = ""
    source: str = ""
    created_at: str = ""
    updated_at: str = ""
    lifecycle_state: str = ""
    progress: int = 0
    blockers: List[str] = field(default_factory=list)
    workspace_path: str = ""
    evidence_count: int = 0
    deliverables: List[str] = field(default_factory=list)
    selected_capabilities: List[str] = field(default_factory=list)
    selected_tools: List[str] = field(default_factory=list)
    operator_next_action: str = ""
    diagnostic: bool = False       # True for smoke/acceptance/replay/promo/demo artifacts

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class ProjectIndex:
    def __init__(self, output_dir: str = "outputs") -> None:
        self._out = Path(output_dir)

    def list_projects(self, include_diagnostics: bool = False) -> List[ProjectEntry]:
        """Production projects by default. ``include_diagnostics=True`` also surfaces diagnostic
        Scout runs (smoke/acceptance/replay/promo/demo) for an explicit "Show diagnostics" view."""
        projects = self._client_projects(include_diagnostics) + self._scout_campaigns(include_diagnostics)
        return sorted(projects, key=lambda e: (e.updated_at or "", e.project_id), reverse=True)

    def snapshot(self) -> Dict[str, Any]:
        items = self.list_projects()
        return {"project_count": len(items),
                "by_type": {t: sum(1 for p in items if p.type == t)
                            for t in {p.type for p in items}},
                "projects": [p.to_dict() for p in items]}

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _client_projects(self, include_diagnostics: bool = False) -> List[ProjectEntry]:
        from core.scout.canonical_runs import is_diagnostic_run
        out: List[ProjectEntry] = []
        for ark in sorted(self._out.glob("*/40_ark_work")):
            if "scout" in ark.parts:
                continue
            project_id = ark.parent.name
            # smoke-a and other diagnostic/test project ids are hidden from production by default.
            diagnostic = is_diagnostic_run(project_id)
            if diagnostic and not include_diagnostics:
                continue
            wp = self._read_json(ark / "WORK_PACKET.json")
            rs = self._read_json(ark / "WORK_RUN_STATE.json")
            fr = self._read_json(ark / "FEASIBILITY_REPORT.json")
            if not wp and not rs:
                continue
            status = rs.get("status") or "RECEIVED"
            blockers = list(wp.get("missing_information", []))
            evidence = len(list((ark / "evidence").glob("*"))) if (ark / "evidence").is_dir() else 0
            out.append(ProjectEntry(
                project_id=ark.parent.name, type="client_work",
                title=(wp.get("title") or fr.get("client_intent") or ark.parent.name),
                source=wp.get("source_platform") or "unknown",
                created_at=wp.get("created_at", ""),
                updated_at=(rs.get("updated_at") or wp.get("created_at", "")),
                lifecycle_state=status, progress=_CLIENT_PROGRESS.get(status, 0), blockers=blockers,
                workspace_path=str(ark), evidence_count=evidence,
                deliverables=list(fr.get("expected_deliverables", [])),
                selected_capabilities=list(wp.get("detected_capabilities", [])),
                selected_tools=list(fr.get("selected_tools", [])),
                operator_next_action=self._client_next_action(fr, status, blockers),
                diagnostic=diagnostic))
        return out

    def _scout_campaigns(self, include_diagnostics: bool = False) -> List[ProjectEntry]:
        """Canonical Scout campaigns come from the orchestration source (scout/_runcontrol/), the
        SAME source Observer/CampaignService use — NOT a folder scan. Production excludes diagnostic
        ids (smoke/acceptance/replay/promo/demo). Under ``include_diagnostics`` we additionally
        surface legacy folder artifacts (demo/acceptance runs that predate or bypass run-control),
        always classified diagnostic — never counted as production."""
        from core.scout.canonical_runs import canonical_campaigns
        out: List[ProjectEntry] = []
        seen: set = set()
        for row in canonical_campaigns(str(self._out), include_diagnostics=include_diagnostics):
            cid = row["campaign_id"]
            seen.add(cid)
            out.append(self._scout_entry(cid, diagnostic=row["diagnostic"]))
        if include_diagnostics:
            root = self._out / "scout"
            if root.is_dir():
                for base in sorted(p for p in root.iterdir() if p.is_dir()):
                    name = base.name
                    if name in seen or name.startswith("_"):
                        continue
                    st = self._read_json(base / "state.json")
                    if not st and not (base / "report").is_dir():
                        continue
                    seen.add(name)
                    out.append(self._scout_entry(name, diagnostic=True))
        return out

    def _scout_entry(self, cid: str, *, diagnostic: bool) -> ProjectEntry:
        base = self._out / "scout" / cid
        st = self._read_json(base / "state.json")
        report = base / "report"
        evidence = len(list(report.glob("*.json"))) if report.is_dir() else 0
        counts = st.get("counts", {}) if isinstance(st.get("counts"), dict) else {}
        status = st.get("status") or ("COMPLETED" if report.is_dir() else "UNKNOWN")
        return ProjectEntry(
            project_id=(st.get("campaign_id") or cid), type="scout_campaign",
            title=(st.get("campaign_id") or cid), source="scout",
            created_at=st.get("started_at", ""),
            updated_at=st.get("updated_at", st.get("started_at", "")),
            lifecycle_state=status,
            progress=(100 if status in ("COMPLETED", "DONE") else 50 if status else 0),
            blockers=[], workspace_path=str(base), evidence_count=evidence,
            deliverables=[], selected_capabilities=[], selected_tools=[],
            operator_next_action=self._scout_next_action(status, counts), diagnostic=diagnostic)

    @staticmethod
    def _client_next_action(fr: Dict[str, Any], status: str, blockers: List[str]) -> str:
        if status == "DELIVERY_PREPARED":
            return "send the prepared package manually, then mark it delivered"
        if status in ("COMPLETED", "READY_FOR_DELIVERY"):
            return "review the delivery package"
        if blockers:
            return "answer the client questions (blocking information missing)"
        verdict = fr.get("verdict", "")
        if verdict == "NOT_RECOMMENDED":
            return "review honest reasons to reject / offer a smaller in-scope slice"
        if verdict in ("TAKE_AFTER_CLARIFICATION", "TAKE_AFTER_ACCESS_OR_TOOL_SETUP"):
            return "clarify / set up access, then approve the plan"
        return "review the feasibility summary, then approve the plan to proceed"

    @staticmethod
    def _scout_next_action(status: str, counts: Dict[str, Any]) -> str:
        if status in ("COMPLETED", "DONE"):
            return "review companies, findings, evidence, and drafts in the dashboard"
        if status in ("RUNNING", "ACTIVE", "EXECUTING"):
            return "watch progress; pause/resume/stop from the dashboard"
        return "open the campaign in the dashboard"
