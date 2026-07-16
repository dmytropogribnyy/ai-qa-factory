"""Evidence collection schemas — Phase 4B.

SAFETY DEFAULTS:
- client_visible = False
- internal_only = True
- requires_redaction = True
- ready_for_client_review = False
- approved_for_client_view = False
- client_visible_blocked = True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

EVIDENCE_TYPES = {
    "validation_report", "command_log", "scaffold_metadata",
    "strategy_artifact", "blueprint_artifact", "project_artifact",
    "internal_summary", "quality_gate",
}


@dataclass
class EvidenceRecord(SchemaMixin):
    """A single piece of evidence registered in the evidence collection."""
    id: str = ""
    evidence_type: str = ""
    path: str = ""
    title: str = ""
    description: str = ""
    source_phase: str = ""
    client_visible: bool = False
    internal_only: bool = True
    requires_redaction: bool = True
    redacted: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: List[str] = field(default_factory=list)


@dataclass
class EvidenceCollection(SchemaMixin):
    """Full evidence collection for a project."""
    project_id: str = ""
    evidence_root: str = ""
    records: List[EvidenceRecord] = field(default_factory=list)
    client_visible_count: int = 0
    internal_only_count: int = 0
    redaction_required_count: int = 0
    ready_for_client_review: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "evidence_root": self.evidence_root,
            "records": [r.to_dict() for r in self.records],
            "client_visible_count": self.client_visible_count,
            "internal_only_count": self.internal_only_count,
            "redaction_required_count": self.redaction_required_count,
            "ready_for_client_review": self.ready_for_client_review,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceCollection:
        known = {
            "project_id", "evidence_root",
            "client_visible_count", "internal_only_count",
            "redaction_required_count", "ready_for_client_review", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["records"] = [
            EvidenceRecord.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("records", [])
        ]
        # Safety: client review flag cannot be rehydrated as True.
        kwargs["ready_for_client_review"] = False
        return cls(**kwargs)


@dataclass
class EvidenceQualityGate(SchemaMixin):
    """Quality gate checklist before evidence can be reviewed or delivered."""
    project_id: str = ""
    has_command_logs: bool = False
    has_test_results: bool = False
    has_screenshots: bool = False
    has_traces: bool = False
    has_internal_summary: bool = False
    has_client_summary: bool = False
    redaction_complete: bool = False
    approved_for_client_view: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceQualityGate:
        known = {
            "project_id", "has_command_logs", "has_test_results",
            "has_screenshots", "has_traces", "has_internal_summary",
            "has_client_summary", "redaction_complete",
            "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        # Safety: client approval cannot be rehydrated from disk.
        kwargs["approved_for_client_view"] = False
        return cls(**kwargs)


@dataclass
class EvidenceRedactionReport(SchemaMixin):
    """Report on secret scanning and redaction status of evidence files."""
    project_id: str = ""
    scanned_files: List[str] = field(default_factory=list)
    redactions_needed: int = 0
    redactions_completed: int = 0
    secrets_found: List[str] = field(default_factory=list)
    unsafe_paths: List[str] = field(default_factory=list)
    client_visible_blocked: bool = True
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# EvidenceClaim — Phase 8.0 (ARK universal work layer)
#
# ADDITIVE: extends the evidence family for capability-agnostic verification.
# EvidenceRecord = a stored artifact; EvidenceClaim = an assertion ("requirement X
# is satisfied") backed by evidence records, carrying an independent verification
# status set by the EvidenceVerifier (never the implementer).
# ---------------------------------------------------------------------------

EVIDENCE_CLAIM_STATUSES = frozenset({
    "unverified", "verified", "refuted", "insufficient_evidence", "not_applicable",
})


@dataclass
class EvidenceClaim(SchemaMixin):
    """An assertion backed by evidence, independently verifiable."""
    id: str = ""
    claim_text: str = ""
    capability: str = ""                        # atomic capability this claim relates to
    requirement_ref: str = ""                   # Requirement.id, if any
    evidence_refs: List[str] = field(default_factory=list)   # EvidenceRecord ids/paths
    verification_status: str = "unverified"
    verified_by: str = ""                       # must differ from the implementer
    confidence: float = 0.0
    notes: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceClaim:
        obj = super().from_dict(data)
        # Safety: a claim can never be rehydrated from disk as already verified.
        if obj.verification_status == "verified":
            obj.verification_status = "unverified"
        return obj
