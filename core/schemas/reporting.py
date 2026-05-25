"""Report draft schemas — Phase 4C.

SAFETY DEFAULTS:
- status = "draft"
- approved_for_delivery = False
- client_ready = False
- safe_to_deliver = False
- approval_checked = False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

REPORT_TYPES = {"internal_qa_summary", "client_report", "delivery_note", "executive_summary"}
REPORT_STATUSES = {"draft", "pending_review", "reviewed", "approved", "rejected"}
AUDIENCE_TYPES = {"internal", "client", "executive", "technical"}


@dataclass
class ReportSection(SchemaMixin):
    """A single section within a report draft."""
    id: str = ""
    title: str = ""
    content: str = ""
    client_visible: bool = False
    internal_only: bool = True
    requires_review: bool = True
    notes: List[str] = field(default_factory=list)


@dataclass
class ReportDraft(SchemaMixin):
    """A draft report — never approved for delivery by default."""
    project_id: str = ""
    report_type: str = ""
    title: str = ""
    audience: str = "internal"
    status: str = "draft"
    client_visible: bool = False
    approved_for_delivery: bool = False
    sections: List[ReportSection] = field(default_factory=list)
    source_artifacts: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "report_type": self.report_type,
            "title": self.title,
            "audience": self.audience,
            "status": self.status,
            "client_visible": self.client_visible,
            "approved_for_delivery": self.approved_for_delivery,
            "sections": [s.to_dict() for s in self.sections],
            "source_artifacts": list(self.source_artifacts),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReportDraft:
        known = {
            "project_id", "report_type", "title", "audience", "status",
            "client_visible", "source_artifacts", "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["sections"] = [
            ReportSection.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("sections", [])
        ]
        # Safety: delivery approval cannot be rehydrated from disk.
        kwargs["approved_for_delivery"] = False
        return cls(**kwargs)


@dataclass
class ReportQualityChecklist(SchemaMixin):
    """Quality checklist that must pass before any report is considered deliverable."""
    project_id: str = ""
    report_id: str = ""
    technically_correct: bool = False
    specific: bool = False
    actionable: bool = False
    evidence_based: bool = False
    honest_scope: bool = False
    no_overclaiming: bool = False
    client_ready: bool = False
    human_readable: bool = False
    no_internal_notes: bool = False
    approval_checked: bool = False
    safe_to_deliver: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReportQualityChecklist:
        known = {
            "project_id", "report_id",
            "technically_correct", "specific", "actionable", "evidence_based",
            "honest_scope", "no_overclaiming", "human_readable",
            "no_internal_notes", "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        # Safety: delivery flags cannot be rehydrated from disk.
        kwargs["client_ready"] = False
        kwargs["approval_checked"] = False
        kwargs["safe_to_deliver"] = False
        return cls(**kwargs)


@dataclass
class DeliveryNoteDraft(SchemaMixin):
    """Draft delivery note — companion to client report, never approved by default."""
    project_id: str = ""
    title: str = ""
    status: str = "draft"
    approved_for_delivery: bool = False
    client_visible: bool = False
    summary: str = ""
    included_artifacts: List[str] = field(default_factory=list)
    excluded_artifacts: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeliveryNoteDraft:
        known = {
            "project_id", "title", "status", "client_visible", "summary",
            "included_artifacts", "excluded_artifacts", "caveats", "next_steps", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        # Safety: delivery approval cannot be rehydrated from disk.
        kwargs["approved_for_delivery"] = False
        return cls(**kwargs)
