"""Dynamic Tool/MCP Broker gap analysis (v3.2 Section 11).

Given a service profile (or a Work Order's required tools), derive the required capabilities, inspect
ACTUAL readiness via the existing ToolBroker + AccessBootstrap, select the smallest relevant toolset,
apply the documented fallback, and produce a Tool Gap Report. It never claims a tool is usable
without real readiness; missing tools carry a fallback and the exact operator/client action.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from core.orchestration.access_bootstrap import AccessBootstrap
from core.orchestration.service_capability import get_service
from core.orchestration.tool_broker import ToolBroker

# ToolBroker/access readiness values that mean "genuinely usable now".
_READY_TOOL = {"fixture-tested", "health-checked", "authenticated", "live-accepted"}
_READY_ACCESS = {"Runtime Verified", "Fixture Verified", "Live Verified", "Authenticated",
                 "Installed", "Connected"}


@dataclass
class ToolNeed:
    tool: str
    ready: bool
    readiness: str
    fallback: str = ""
    action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# A required access prerequisite is "satisfied" ONLY when genuinely usable/verified. Merely
# Installed / Connected / Runtime-Available (e.g. a driver present, a CLI on PATH, an MCP configured)
# is NOT satisfied — capability readiness is per-requirement, not "installed == ready" (P0-C).
_ACCESS_SATISFIED = {"Runtime Verified", "Fixture Verified", "Live Verified", "Authenticated"}


@dataclass
class AccessGap:
    access_id: str
    name: str
    owner: str                 # operator | client | local
    readiness: str
    action: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolGapReport:
    service_id: str
    required_tools: List[str]
    required_access: List[str]
    selected: List[str] = field(default_factory=list)
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    access_gaps: List[Dict[str, Any]] = field(default_factory=list)
    ready: bool = False
    fallback: str = ""
    operator_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def plan_tools(service_id: str, *, broker: ToolBroker = None, access: AccessBootstrap = None
               ) -> ToolGapReport:
    svc = get_service(service_id)
    if svc is None:
        return ToolGapReport(service_id=service_id, required_tools=[], required_access=[],
                             operator_action="unknown service id")
    broker = broker or ToolBroker(clock=lambda: "")
    access = access or AccessBootstrap()
    tool_status = {t.id: t.readiness for t in broker.discover()}
    integrations = {i.id: i for i in access.inspect()}
    access_status = {i: it.readiness for i, it in integrations.items()}

    needs: List[ToolNeed] = []
    for tool in svc.required_tools:
        readiness = tool_status.get(tool) or access_status.get(tool) or "declared"
        ready = (readiness in _READY_TOOL) or (readiness in _READY_ACCESS)
        needs.append(ToolNeed(tool=tool, ready=ready, readiness=readiness,
                              fallback=("" if ready else svc.fallback),
                              action=("" if ready else svc.operator_action_if_blocked)))
    selected = [n.tool for n in needs if n.ready]           # smallest relevant ready toolset
    gaps = [n.to_dict() for n in needs if not n.ready]

    # Typed access/authorization prerequisites resolved through AccessBootstrap: a required access id
    # that is not genuinely satisfied (e.g. a client-owned repo/DB/CI/cloud scope that is Needs Client)
    # makes the service NOT ready and carries the exact owner + action (item 20).
    access_gaps: List[Dict[str, Any]] = []
    for aid in svc.required_access_ids:
        it = integrations.get(aid)
        if it is None:
            access_gaps.append(AccessGap(aid, aid, "unknown", "unknown",
                                         "unknown access id (not resolvable via AccessBootstrap)").to_dict())
            continue
        if it.readiness not in _ACCESS_SATISFIED:
            access_gaps.append(AccessGap(aid, it.name, it.owner, it.readiness,
                                         it.setup_action or svc.operator_action_if_blocked).to_dict())

    all_ready = not gaps and not access_gaps
    # The operator action prioritises a tool gap; else the first (client) access gap's exact action.
    if all_ready:
        operator_action = ""
    elif gaps:
        operator_action = svc.operator_action_if_blocked
    else:
        operator_action = access_gaps[0]["action"]
    return ToolGapReport(
        service_id=service_id, required_tools=list(svc.required_tools),
        required_access=list(svc.required_access), selected=selected, gaps=gaps,
        access_gaps=access_gaps, ready=all_ready,
        fallback=("" if all_ready else svc.fallback), operator_action=operator_action)


def snapshot() -> Dict[str, Any]:
    from core.orchestration.service_capability import SERVICE_CAPABILITIES
    return {"schema": "tool-gap/v1",
            "reports": [plan_tools(s.service_id).to_dict() for s in SERVICE_CAPABILITIES]}
