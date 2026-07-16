"""Requirement schema — Phase 8.0 (ARK universal work layer).

A Requirement is an atomic, verifiable expectation extracted from a WorkPacket.
It is intentionally separate from WorkRequest: WorkRequest is the raw normalised
intake record, while Requirement is a single decomposed, trackable unit that the
EvidenceVerifier can later mark as satisfied or not.

SAFETY / DESIGN NOTES:
- verification_status defaults to "unverified" and is never rehydrated as verified.
- This schema is planning-only foundation. No runtime behaviour is attached in Phase 8.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin

REQUIREMENT_TYPES = frozenset({
    "functional", "non_functional", "quality", "security", "performance",
    "accessibility", "compliance", "delivery", "constraint", "unknown",
})

VERIFICATION_STATUSES = frozenset({
    "unverified", "in_progress", "satisfied", "not_satisfied",
    "partially_satisfied", "blocked", "not_applicable",
})


@dataclass
class Requirement(SchemaMixin):
    """One atomic, verifiable requirement derived from a work packet."""

    id: str = field(default_factory=lambda: str(uuid4()))
    text: str = ""
    source_ref: str = ""                       # label/artifact reference, not a live URL
    requirement_type: str = "unknown"
    priority: int = 0
    acceptance_criteria: List[str] = field(default_factory=list)
    confidence: float = 0.0
    verification_status: str = "unverified"
    assumptions: List[str] = field(default_factory=list)
    related_deliverables: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Requirement:
        obj = super().from_dict(data)
        # Safety: a requirement can never be rehydrated from disk as already verified.
        if obj.verification_status == "satisfied":
            obj.verification_status = "unverified"
        return obj
