from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class DocumentationRecord(SchemaMixin):
    """Metadata record for one documentation file tracked by the workbench."""

    id: str = field(default_factory=lambda: str(uuid4()))
    path: str = ""
    title: str = ""
    doc_type: str = "unknown"
    source_of_truth: bool = False
    generated: bool = False
    owner: str = ""
    update_triggers: List[str] = field(default_factory=list)
    related_code_paths: List[str] = field(default_factory=list)
    related_schema_modules: List[str] = field(default_factory=list)
    related_commands: List[str] = field(default_factory=list)
    last_reviewed_at: Optional[str] = None
    status: str = "unknown"
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentationRecord:
        return super().from_dict(data)


@dataclass
class DocumentationManifest(SchemaMixin):
    """Registry of all documentation files tracked for a project or the workbench itself."""

    project_id: str = ""
    docs: List[DocumentationRecord] = field(default_factory=list)
    source_of_truth_docs: List[str] = field(default_factory=list)
    generated_docs: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "docs": [d.to_dict() for d in self.docs],
            "source_of_truth_docs": self.source_of_truth_docs,
            "generated_docs": self.generated_docs,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentationManifest:
        docs = [
            DocumentationRecord.from_dict(d) if isinstance(d, dict) else d
            for d in data.get("docs", [])
        ]
        return cls(
            project_id=data.get("project_id", ""),
            docs=docs,
            source_of_truth_docs=data.get("source_of_truth_docs", []),
            generated_docs=data.get("generated_docs", []),
            notes=data.get("notes", []),
        )


@dataclass
class DocumentationFreshnessCheck(SchemaMixin):
    """One finding from a documentation freshness audit."""

    id: str = field(default_factory=lambda: str(uuid4()))
    doc_path: str = ""
    check_type: str = "unknown"
    passed: bool = True
    severity: str = "info"
    finding: str = ""
    recommended_action: str = ""
    related_file: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentationFreshnessCheck:
        return super().from_dict(data)


@dataclass
class DocumentationFreshnessReport(SchemaMixin):
    """Report produced by a documentation freshness audit run."""

    project_id: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    checks: List[DocumentationFreshnessCheck] = field(default_factory=list)
    docs_current: bool = False
    docs_needing_review: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    summary: str = ""
    recommended_next_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "created_at": self.created_at,
            "checks": [c.to_dict() for c in self.checks],
            "docs_current": self.docs_current,
            "docs_needing_review": self.docs_needing_review,
            "blockers": self.blockers,
            "summary": self.summary,
            "recommended_next_action": self.recommended_next_action,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentationFreshnessReport:
        checks = [
            DocumentationFreshnessCheck.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("checks", [])
        ]
        return cls(
            project_id=data.get("project_id", ""),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            checks=checks,
            docs_current=data.get("docs_current", False),
            docs_needing_review=data.get("docs_needing_review", []),
            blockers=data.get("blockers", []),
            summary=data.get("summary", ""),
            recommended_next_action=data.get("recommended_next_action", ""),
        )
