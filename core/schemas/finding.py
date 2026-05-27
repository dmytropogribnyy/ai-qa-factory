"""Phase 6.2 -- Structured Finding schema for the AI QA Factory.

A Finding is a typed, machine-readable audit result produced by any module
and aggregated by the client audit workflow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(str, Enum):
    FUNCTIONAL = "functional"
    API = "api"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"
    UX = "ux"
    RELIABILITY = "reliability"
    MAINTAINABILITY = "maintainability"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


class FindingStatus(str, Enum):
    OPEN = "open"
    ACCEPTED_RISK = "accepted_risk"
    FALSE_POSITIVE = "false_positive"
    FIXED = "fixed"
    NEEDS_REVIEW = "needs_review"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Finding:
    """A typed, machine-readable audit finding.

    Findings are produced by module adapters when real evidence exists.
    Empty findings lists (no evidence) are always preferred over fake findings.
    """

    id: str
    title: str
    description: str
    severity: Severity
    category: FindingCategory
    source_module: str
    affected_area: str = ""
    evidence: str = ""
    recommendation: str = ""
    client_impact: str = ""
    confidence: Confidence = Confidence.MEDIUM
    status: FindingStatus = FindingStatus.OPEN
    tags: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "category": self.category.value,
            "source_module": self.source_module,
            "affected_area": self.affected_area,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "client_impact": self.client_impact,
            "confidence": self.confidence.value,
            "status": self.status.value,
            "tags": self.tags,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            severity=Severity(data.get("severity", "info")),
            category=FindingCategory(data.get("category", "unknown")),
            source_module=data.get("source_module", ""),
            affected_area=data.get("affected_area", ""),
            evidence=data.get("evidence", ""),
            recommendation=data.get("recommendation", ""),
            client_impact=data.get("client_impact", ""),
            confidence=Confidence(data.get("confidence", "medium")),
            status=FindingStatus(data.get("status", "open")),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
        )
