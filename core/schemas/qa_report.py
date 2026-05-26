"""
Phase 5F — QA Evidence Report schemas.

Safety invariants (hardcoded in __post_init__ + from_dict):
- execution_performed=False
- network_calls_performed=False
- raw_credentials_in_report=False
- raw_tokens_in_report=False
- storage_state_content_read=False
- safe_to_deliver=False
- approved_for_client_delivery=False
- client_ready=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.schemas.base import SchemaMixin


@dataclass
class QAEvidenceItem(SchemaMixin):
    """Single evidence item from one execution lane of one source project."""
    lane: str = ""                 # "browser_auth" | "api_auth"
    target: str = ""               # URL or target name
    target_category: str = ""
    source_project_id: str = ""
    artifact_path: str = ""        # relative path — never storageState content
    status: str = "missing"        # "passed" | "failed" | "missing" | "error"
    commands_executed: int = 0
    duration_seconds: float = 0.0
    notes: List[str] = field(default_factory=list)


@dataclass
class QAEvidenceSource(SchemaMixin):
    """Evidence collected from a single source project."""
    source_project_id: str = ""
    artifacts_found: List[str] = field(default_factory=list)
    artifacts_missing: List[str] = field(default_factory=list)
    evidence_items: List[QAEvidenceItem] = field(default_factory=list)


@dataclass
class QACoverageSummary(SchemaMixin):
    """Coverage across all aggregated source projects."""
    total_evidence_items: int = 0
    passed: int = 0
    failed: int = 0
    missing: int = 0
    covered_lanes: List[str] = field(default_factory=list)
    covered_targets: List[str] = field(default_factory=list)
    not_covered: List[str] = field(default_factory=list)


@dataclass
class QASecretScanResult(SchemaMixin):
    """Result of scanning generated report content for raw secrets/tokens."""
    scan_performed: bool = True
    raw_secret_found: bool = False
    raw_token_found: bool = False
    checked_env_var_names: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)   # descriptions only, never values
    verdict: str = "clean"                               # "clean" | "warn" | "fail"


@dataclass
class QAEvidenceReport(SchemaMixin):
    """
    Consolidated QA Evidence Report — Phase 5F.
    Internal only. Human review required before any client delivery.
    """
    project_id: str = ""
    report_type: str = "qa_evidence_report"
    source_project_ids: List[str] = field(default_factory=list)
    generated_at: str = ""

    # Safety invariants — all hardcoded False / True, cannot be bypassed
    execution_performed: bool = False
    network_calls_performed: bool = False
    raw_credentials_in_report: bool = False
    raw_tokens_in_report: bool = False
    storage_state_content_read: bool = False
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    client_ready: bool = False
    human_review_required: bool = True

    sources: List[QAEvidenceSource] = field(default_factory=list)
    coverage: Optional[QACoverageSummary] = None
    secret_scan: Optional[QASecretScanResult] = None
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.execution_performed = False
        self.network_calls_performed = False
        self.raw_credentials_in_report = False
        self.raw_tokens_in_report = False
        self.storage_state_content_read = False
        self.safe_to_deliver = False
        self.approved_for_client_delivery = False
        self.client_ready = False
        self.human_review_required = True

    @classmethod
    def from_dict(cls, data: dict) -> "QAEvidenceReport":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.execution_performed = False
        obj.network_calls_performed = False
        obj.raw_credentials_in_report = False
        obj.raw_tokens_in_report = False
        obj.storage_state_content_read = False
        obj.safe_to_deliver = False
        obj.approved_for_client_delivery = False
        obj.client_ready = False
        obj.human_review_required = True
        return obj
