"""CapabilityPlan schema — Phase 8.0 (ARK universal work layer).

Given a WorkPacket, the CapabilityPlanner produces a CapabilityPlan: which atomic
capabilities are required, which are available, which are missing or blocked, and
which approvals a later execution phase would need.

SAFETY / DESIGN NOTES:
- This is a plan, not an execution. Nothing runs in Phase 8.0.
- approvals_required is descriptive; the ToolPolicyEngine remains authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin

CAPABILITY_AVAILABILITY = frozenset({
    "available",            # a verified in-repo backend can realise it now
    "candidate",            # a manifest MCP server *might* realise it (unverified)
    "requires_discovery",   # needs Phase 8.3 live discovery before it can be used
    "missing",              # no backend or candidate exists
    "blocked",              # blocked by policy
    "requires_approval",
    "requires_auth_setup",
})


@dataclass
class PlannedCapability(SchemaMixin):
    """One capability entry inside a capability plan."""

    capability: str = ""                        # atomic capability name
    availability: str = "missing"
    capability_class: str = "read"
    candidate_backend: str = ""
    candidate_mcp_server: str = ""
    requires_approval: bool = True
    requires_discovery: bool = False            # True if only an unverified MCP candidate exists
    reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlannedCapability:
        return super().from_dict(data)


@dataclass
class CapabilityPlan(SchemaMixin):
    """Planned capabilities for a work packet."""

    id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    work_packet_ref: str = ""
    profile: str = ""                           # capability profile name
    required_capabilities: List[str] = field(default_factory=list)
    planned: List[PlannedCapability] = field(default_factory=list)
    missing_capabilities: List[str] = field(default_factory=list)
    blocked_capabilities: List[str] = field(default_factory=list)
    approvals_required: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "work_packet_ref": self.work_packet_ref,
            "profile": self.profile,
            "required_capabilities": list(self.required_capabilities),
            "planned": [p.to_dict() for p in self.planned],
            "missing_capabilities": list(self.missing_capabilities),
            "blocked_capabilities": list(self.blocked_capabilities),
            "approvals_required": list(self.approvals_required),
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CapabilityPlan:
        known = {
            "id", "project_id", "work_packet_ref", "profile",
            "required_capabilities", "missing_capabilities",
            "blocked_capabilities", "approvals_required", "notes", "created_at",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["planned"] = [
            PlannedCapability.from_dict(p) if isinstance(p, dict) else p
            for p in data.get("planned", [])
        ]
        return cls(**kwargs)
