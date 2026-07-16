"""WorkPacket schema — Phase 8.0 (ARK universal work layer).

A WorkPacket is the single normalised container for any inbound work — an Upwork
brief, a client message, a task URL, or a repo reference. It wraps (by reference)
the existing `WorkRequest` intake record and adds decomposed requirements, the
chosen capability profile, and pointers to plan/state artifacts.

REUSE DECISION:
- WorkRequest (core/schemas/work_request.py) is preserved unchanged and referenced,
  not duplicated. WorkPacket is the assembly layer above it.

SAFETY / DESIGN NOTES:
- References only (labels / artifact paths / env-var names), never secrets or live URLs.
- Planning-only foundation. No fetching or execution in Phase 8.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin
from core.schemas.requirement import Requirement


@dataclass
class WorkPacket(SchemaMixin):
    """Normalised container for one unit of inbound work."""

    id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    title: str = ""
    summary: str = ""
    source_platform: str = "unknown"            # upwork | direct | url | repo | ...
    source_ref: str = ""                        # label / artifact path, not a live URL
    work_request_ref: str = ""                  # WorkRequest.id this packet wraps
    requirements: List[Requirement] = field(default_factory=list)
    capability_profile: str = ""                # chosen CapabilityProfile name
    detected_capabilities: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    # Artifact pointers (filled as later phases produce them)
    capability_plan_ref: str = ""
    toolchain_plan_ref: str = ""
    run_state_ref: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "summary": self.summary,
            "source_platform": self.source_platform,
            "source_ref": self.source_ref,
            "work_request_ref": self.work_request_ref,
            "requirements": [r.to_dict() for r in self.requirements],
            "capability_profile": self.capability_profile,
            "detected_capabilities": list(self.detected_capabilities),
            "constraints": list(self.constraints),
            "assumptions": list(self.assumptions),
            "missing_information": list(self.missing_information),
            "capability_plan_ref": self.capability_plan_ref,
            "toolchain_plan_ref": self.toolchain_plan_ref,
            "run_state_ref": self.run_state_ref,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkPacket:
        known = {
            "id", "project_id", "title", "summary", "source_platform", "source_ref",
            "work_request_ref", "capability_profile", "detected_capabilities",
            "constraints", "assumptions", "missing_information",
            "capability_plan_ref", "toolchain_plan_ref", "run_state_ref", "created_at",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["requirements"] = [
            Requirement.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("requirements", [])
        ]
        return cls(**kwargs)
