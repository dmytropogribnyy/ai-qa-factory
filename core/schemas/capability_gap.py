"""Capability gap detection + MCP recommendation schemas — Phase 8.0.

Lets the Factory (and agents) SEE what is available, DETECT which required
capabilities have no ready tool or no connected server, and RECOMMEND which MCP /
plugin / connector would close the gap — so we use ready tools instead of
reinventing them, and only build new capabilities when nothing suitable exists.

SAFETY / DESIGN NOTES:
- Planning-only foundation. Detecting a gap and recommending a server does NOT add,
  install, or connect anything. Actually adding a server is a manifest edit performed
  under human approval (a write/external action), not an automatic step.
- References only; no secrets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin

GAP_KINDS = frozenset({
    "no_tool_available",        # capability has no ready MCP/backend at all
    "server_not_configured",    # a suitable server exists as a candidate but is not configured
    "server_unreachable",       # configured but failing health
    "requires_auth_setup",      # reachable but needs Factory-side auth
    "requires_approval",        # available but gated by capability class
    "build_required",           # must be implemented in-repo
})

RECOMMENDATION_ACTIONS = frozenset({
    "use_existing",             # a ready server/backend already covers it
    "configure_candidate",      # add a known candidate to the manifest (approval)
    "authenticate",             # complete auth setup for a configured server
    "repair",                   # fix an unreachable configured server
    "build",                    # implement a new capability/runner
})


@dataclass
class MCPRecommendation(SchemaMixin):
    """A proposed way to close a capability gap using a ready or candidate tool."""

    id: str = field(default_factory=lambda: str(uuid4()))
    capability: str = ""                        # atomic capability the gap concerns
    action: str = "use_existing"
    candidate_server: str = ""                  # server alias, if any
    capability_class: str = "read"
    requires_approval: bool = True              # adding/using is approval-gated by class
    rationale: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MCPRecommendation:
        return super().from_dict(data)


@dataclass
class CapabilityGap(SchemaMixin):
    """One required capability that is not currently satisfiable as-is."""

    capability: str = ""
    kind: str = "no_tool_available"
    detail: str = ""
    recommendations: List[MCPRecommendation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "kind": self.kind,
            "detail": self.detail,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CapabilityGap:
        known = {"capability", "kind", "detail"}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["recommendations"] = [
            MCPRecommendation.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("recommendations", [])
        ]
        return cls(**kwargs)


@dataclass
class CapabilityGapReport(SchemaMixin):
    """Full gap analysis for a work packet: what is available vs. what is needed."""

    id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    work_packet_ref: str = ""
    available_servers: List[str] = field(default_factory=list)
    available_capabilities: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    gaps: List[CapabilityGap] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "work_packet_ref": self.work_packet_ref,
            "available_servers": list(self.available_servers),
            "available_capabilities": list(self.available_capabilities),
            "required_capabilities": list(self.required_capabilities),
            "gaps": [g.to_dict() for g in self.gaps],
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CapabilityGapReport:
        known = {
            "id", "project_id", "work_packet_ref", "available_servers",
            "available_capabilities", "required_capabilities", "notes", "created_at",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["gaps"] = [
            CapabilityGap.from_dict(g) if isinstance(g, dict) else g
            for g in data.get("gaps", [])
        ]
        return cls(**kwargs)
