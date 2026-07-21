"""Dashboard read model (v3.1 M1) - deterministic DTOs over the existing core services.

Bounded, paginated, filterable, sortable. Stable status labels + next action. No business logic is
duplicated here that belongs to the core; this only READS persisted state (with lightweight polling
and a manual Refresh on the UI side) and shapes it for rendering. Untrusted text is escaped by the
renderer, not here; these DTOs carry raw values.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.orchestration.project_index import ProjectIndex
from core.orchestration.tool_broker import ToolBroker
from core.orchestration.work_execution import WorkExecutionService
from core.schemas.work_run_state import WorkRunState

SCHEMA_VERSION = "dashboard-read-model/v1"

# Friendly, stable stage labels (never leak raw enum churn into the UI).
_STAGE = {
    "RECEIVED": "Intake", "INTAKE_COMPLETE": "Intake", "PLANNED": "Plan proposed",
    "WAITING_FOR_INFORMATION": "Awaiting info", "WAITING_FOR_APPROVAL": "Awaiting approval",
    "READY_TO_EXECUTE": "Ready to execute", "EXECUTING": "In progress",
    "EXECUTION_PARTIAL": "In progress", "VERIFYING": "Validating",
    "REPAIR_REQUIRED": "Needs repair", "READY_FOR_REVIEW": "Ready for review",
    "READY_FOR_DELIVERY": "Ready for delivery", "DELIVERY_PREPARED": "Delivery prepared",
    "BLOCKED": "Blocked", "FAILED": "Failed", "CANCELLED": "Cancelled", "COMPLETED": "Completed",
}
# Health buckets: ok | attention | blocked | done.
_HEALTH = {
    "BLOCKED": "blocked", "FAILED": "blocked", "REPAIR_REQUIRED": "attention",
    "PLANNED": "attention", "WAITING_FOR_APPROVAL": "attention",
    "WAITING_FOR_INFORMATION": "attention", "READY_FOR_REVIEW": "attention",
    "READY_FOR_DELIVERY": "attention", "DELIVERY_PREPARED": "attention",
    "COMPLETED": "done", "CANCELLED": "done",
}
# Attention titles per lifecycle state (Overview inbox).
_ATTENTION = {
    "PLANNED": "Plan needs approval", "WAITING_FOR_APPROVAL": "Plan needs approval",
    "WAITING_FOR_INFORMATION": "Waiting for client information", "BLOCKED": "Work blocked",
    "REPAIR_REQUIRED": "Validation failed - needs repair", "READY_FOR_REVIEW": "Ready for review",
    "READY_FOR_DELIVERY": "Delivery needs preparation",
    "DELIVERY_PREPARED": "Prepared package waiting to be sent",
}
_ACTIVE_WORK = {"EXECUTING", "EXECUTION_PARTIAL", "VERIFYING", "READY_TO_EXECUTE"}


def stage_label(status: str) -> str:
    return _STAGE.get(status, status or "Unknown")


def health_of(status: str) -> str:
    return _HEALTH.get(status, "ok")


@dataclass
class AttentionItem:
    kind: str
    title: str
    project_id: str
    project_type: str
    status: str
    reason: str
    next_action: str
    href: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectListItem:
    project_id: str
    title: str
    type: str
    stage: str
    status: str
    health: str
    next_action: str
    updated: str
    created: str
    source: str
    progress: int
    evidence_count: int
    blockers: int
    required_tools: List[str]
    href: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScoutCampaignListItem:
    campaign_id: str
    title: str
    status: str
    progress: int
    evidence_count: int
    next_action: str
    href: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolReadinessItem:
    id: str
    name: str
    capability: str
    ui_level: str
    readiness: str
    reason: str
    setup_action: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OverviewSnapshot:
    schema: str = SCHEMA_VERSION
    generated_at: str = ""
    attention: List[Dict[str, Any]] = field(default_factory=list)
    active_work: List[Dict[str, Any]] = field(default_factory=list)
    active_campaigns: List[Dict[str, Any]] = field(default_factory=list)
    recent_results: List[Dict[str, Any]] = field(default_factory=list)
    alert: Optional[str] = None
    counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DashboardReadModel:
    """Composes ProjectIndex + WorkExecutionService + ToolBroker into UI DTOs."""

    def __init__(self, output_dir: str, clock=None) -> None:
        self._out = output_dir
        self._index = ProjectIndex(output_dir)
        self._work = WorkExecutionService(output_dir=output_dir)
        self._clock = clock or (lambda: "")

    # --- projects -------------------------------------------------------------------------------
    def _client_entries(self, include_diagnostics: bool = False):
        return [p for p in self._index.list_projects(include_diagnostics)
                if p.type == "client_work"]

    def _scout_entries(self, include_diagnostics: bool = False):
        return [p for p in self._index.list_projects(include_diagnostics)
                if p.type == "scout_campaign"]

    def project_list(self, *, view: str = "all", limit: int = 200,
                     offset: int = 0, include_diagnostics: bool = False) -> Dict[str, Any]:
        items = [self._to_list_item(p) for p in self._client_entries(include_diagnostics)]
        items = [i for i in items if _matches_view(i, view)]
        total = len(items)
        page = items[offset:offset + max(1, limit)]
        return {"schema": SCHEMA_VERSION, "generated_at": self._clock(), "view": view,
                "total": total, "offset": offset, "limit": limit,
                "projects": [i.to_dict() for i in page]}

    def _to_list_item(self, p) -> ProjectListItem:
        return ProjectListItem(
            project_id=p.project_id, title=p.title or p.project_id, type=p.type,
            stage=stage_label(p.lifecycle_state), status=p.lifecycle_state,
            health=("attention" if p.blockers else health_of(p.lifecycle_state)),
            next_action=p.operator_next_action, updated=p.updated_at, created=p.created_at,
            source=p.source, progress=p.progress, evidence_count=p.evidence_count,
            blockers=len(p.blockers), required_tools=list(p.selected_tools),
            href=f"/work/{p.project_id}")

    # --- overview -------------------------------------------------------------------------------
    def overview(self, include_diagnostics: bool = False) -> OverviewSnapshot:
        clients = self._client_entries(include_diagnostics)
        scouts = self._scout_entries(include_diagnostics)
        attention: List[AttentionItem] = []
        for p in clients:
            title = _ATTENTION.get(p.lifecycle_state)
            if not title:
                continue
            attention.append(AttentionItem(
                kind="work", title=title, project_id=p.project_id, project_type="client_work",
                status=p.lifecycle_state,
                reason=(p.blockers[0] if p.blockers else p.operator_next_action),
                next_action=p.operator_next_action, href=f"/work/{p.project_id}"))
        for c in scouts:
            if str(c.lifecycle_state).upper() in ("FAILED", "ERROR"):
                attention.append(AttentionItem(
                    kind="scout", title="Scout campaign failed", project_id=c.project_id,
                    project_type="scout_campaign", status=c.lifecycle_state,
                    reason="the campaign ended in a failed state", next_action=c.operator_next_action,
                    href="/scout/campaigns"))
        active_work = [self._to_list_item(p).to_dict() for p in clients
                       if p.lifecycle_state in _ACTIVE_WORK]
        active_campaigns = [self._to_scout_item(c).to_dict() for c in scouts
                            if str(c.lifecycle_state).upper() in ("RUNNING", "ACTIVE", "EXECUTING")]
        recent = [self._to_scout_item(c).to_dict() for c in scouts
                  if str(c.lifecycle_state).upper() in ("COMPLETED", "DONE")][:5]
        # How many diagnostic items are hidden from this (production) view — so the UI can offer an
        # honest "Show diagnostics" without mixing them into the production counts.
        diagnostics_hidden = 0
        if not include_diagnostics:
            diagnostics_hidden = sum(1 for p in self._index.list_projects(include_diagnostics=True)
                                     if p.diagnostic)
        return OverviewSnapshot(
            generated_at=self._clock(),
            attention=[a.to_dict() for a in attention], active_work=active_work,
            active_campaigns=active_campaigns, recent_results=recent, alert=None,
            counts={"attention": len(attention), "active_work": len(active_work),
                    "active_campaigns": len(active_campaigns),
                    "projects": len(clients), "campaigns": len(scouts),
                    "diagnostics_hidden": diagnostics_hidden})

    def _to_scout_item(self, c) -> ScoutCampaignListItem:
        return ScoutCampaignListItem(
            campaign_id=c.project_id, title=c.title or c.project_id, status=c.lifecycle_state,
            progress=c.progress, evidence_count=c.evidence_count,
            next_action=c.operator_next_action, href="/scout/campaigns")

    # --- tools ----------------------------------------------------------------------------------
    def tools(self) -> Dict[str, Any]:
        broker = ToolBroker(clock=self._clock)
        items: List[ToolReadinessItem] = []
        for t in broker.discover():
            items.append(ToolReadinessItem(
                id=t.id, name=t.name, capability=", ".join(t.capabilities), ui_level=t.ui_level,
                readiness=t.readiness, reason=t.check_result, setup_action=t.setup_instruction))
        return {"schema": SCHEMA_VERSION, "generated_at": self._clock(),
                "any_live_accepted": False, "tools": [i.to_dict() for i in items]}

    # --- raw state (for detail views) -----------------------------------------------------------
    def work_state(self, project_id: str) -> Optional[WorkRunState]:
        try:
            return self._work._load_state(project_id)   # confined + validated by the service
        except Exception:
            return None


def _matches_view(item: ProjectListItem, view: str) -> bool:
    v = (view or "all").lower()
    if v in ("all", ""):
        return True
    if v == "needs_attention":
        return item.health in ("attention", "blocked") or item.blockers > 0
    if v == "ready_to_execute":
        return item.status == "READY_TO_EXECUTE"
    if v == "in_progress":
        return item.status in ("EXECUTING", "EXECUTION_PARTIAL", "VERIFYING")
    if v == "blocked":
        return item.status in ("BLOCKED", "FAILED", "REPAIR_REQUIRED")
    if v == "ready_for_review":
        return item.status == "READY_FOR_REVIEW"
    if v == "ready_for_delivery":
        return item.status == "READY_FOR_DELIVERY"
    if v == "delivery_prepared":
        return item.status == "DELIVERY_PREPARED"
    if v == "completed":
        return item.status == "COMPLETED"
    return True
