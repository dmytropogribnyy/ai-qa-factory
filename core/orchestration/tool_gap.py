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


@dataclass
class ToolGapReport:
    service_id: str
    required_tools: List[str]
    required_access: List[str]
    selected: List[str] = field(default_factory=list)
    gaps: List[Dict[str, Any]] = field(default_factory=list)
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
    access_status = {i.id: i.readiness for i in access.inspect()}

    needs: List[ToolNeed] = []
    for tool in svc.required_tools:
        readiness = tool_status.get(tool) or access_status.get(tool) or "declared"
        ready = (readiness in _READY_TOOL) or (readiness in _READY_ACCESS)
        needs.append(ToolNeed(tool=tool, ready=ready, readiness=readiness,
                              fallback=("" if ready else svc.fallback),
                              action=("" if ready else svc.operator_action_if_blocked)))
    selected = [n.tool for n in needs if n.ready]           # smallest relevant ready toolset
    gaps = [n.to_dict() for n in needs if not n.ready]
    # Client-owned access is a gap only in the sense of "needs client"; report it distinctly.
    access_gaps = [a for a in svc.required_access]
    all_ready = not gaps
    return ToolGapReport(
        service_id=service_id, required_tools=list(svc.required_tools),
        required_access=access_gaps, selected=selected, gaps=gaps, ready=all_ready,
        fallback=("" if all_ready else svc.fallback),
        operator_action=("" if all_ready else svc.operator_action_if_blocked))


def snapshot() -> Dict[str, Any]:
    from core.orchestration.service_capability import SERVICE_CAPABILITIES
    return {"schema": "tool-gap/v1",
            "reports": [plan_tools(s.service_id).to_dict() for s in SERVICE_CAPABILITIES]}
