"""Delivery preview schemas — Phase 4C.

Preview only — no zip/package creation, no approved_for_delivery=True.

SAFETY DEFAULTS:
- package_created = False
- zip_created = False
- approved_for_delivery = False
- safe_to_package = False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

PREVIEW_STATUSES = {"draft", "pending_review", "ready_for_review", "blocked"}
ARTIFACT_TYPES = {
    "client_report", "delivery_note", "evidence_manifest",
    "scaffold_metadata", "strategy_doc", "how_to_run",
}


@dataclass
class DeliveryPreviewItem(SchemaMixin):
    """A single artifact that would be included or excluded from a future delivery package."""
    id: str = ""
    path: str = ""
    title: str = ""
    artifact_type: str = ""
    include_in_preview: bool = True
    client_visible: bool = False
    requires_redaction: bool = True
    approved_for_delivery: bool = False
    reason: str = ""
    notes: List[str] = field(default_factory=list)


@dataclass
class DeliveryPackagePreview(SchemaMixin):
    """Preview manifest of what a future delivery package would contain."""
    project_id: str = ""
    preview_status: str = "draft"
    package_name: str = ""
    package_created: bool = False
    zip_created: bool = False
    approved_for_delivery: bool = False
    items: List[DeliveryPreviewItem] = field(default_factory=list)
    excluded_items: List[DeliveryPreviewItem] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "preview_status": self.preview_status,
            "package_name": self.package_name,
            "package_created": self.package_created,
            "zip_created": self.zip_created,
            "approved_for_delivery": self.approved_for_delivery,
            "items": [i.to_dict() for i in self.items],
            "excluded_items": [i.to_dict() for i in self.excluded_items],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeliveryPackagePreview:
        known = {
            "project_id", "preview_status", "package_name",
            "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["items"] = [
            DeliveryPreviewItem.from_dict(i) if isinstance(i, dict) else i
            for i in data.get("items", [])
        ]
        kwargs["excluded_items"] = [
            DeliveryPreviewItem.from_dict(i) if isinstance(i, dict) else i
            for i in data.get("excluded_items", [])
        ]
        # Safety: package/zip creation and delivery approval cannot be rehydrated.
        kwargs["package_created"] = False
        kwargs["zip_created"] = False
        kwargs["approved_for_delivery"] = False
        return cls(**kwargs)


@dataclass
class DeliverySafetyChecklist(SchemaMixin):
    """Safety checklist that must be completed before any delivery package is created."""
    project_id: str = ""
    no_secrets: bool = False
    redaction_complete: bool = False
    client_approval_present: bool = False
    evidence_reviewed: bool = False
    reports_reviewed: bool = False
    internal_notes_removed: bool = False
    approved_for_delivery: bool = False
    safe_to_package: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeliverySafetyChecklist:
        known = {
            "project_id", "no_secrets", "redaction_complete",
            "client_approval_present", "evidence_reviewed", "reports_reviewed",
            "internal_notes_removed", "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        # Safety: delivery approval cannot be rehydrated from disk.
        kwargs["approved_for_delivery"] = False
        kwargs["safe_to_package"] = False
        return cls(**kwargs)
