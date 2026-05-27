"""Phase 5P — Client Delivery Pack schemas.

Safety invariants (hardcoded in __post_init__):
- approved_for_client_delivery=False
- human_review_required=True
- auto_send_to_client=False
- secret_scan_before_delivery=True
- raw_secrets_included=False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

DELIVERY_ARTIFACT_TYPES = (
    "qa_report_md", "qa_report_html", "bug_report", "test_cases_csv",
    "risk_matrix", "recommendations", "evidence_index", "delivery_checklist",
    "manifest", "zip_package",
)


@dataclass
class DeliveryArtifact(SchemaMixin):
    """A single artifact in the delivery package."""
    filename: str = ""
    artifact_type: str = ""
    relative_path: str = ""
    size_bytes: int = 0
    included_in_zip: bool = True
    secret_clean: bool = True


@dataclass
class SecretScanResult(SchemaMixin):
    """Result of the pre-delivery secret scan."""
    scanned_files: int = 0
    blocked_files: List[str] = field(default_factory=list)
    issues_found: int = 0
    scan_passed: bool = False

    def __post_init__(self) -> None:
        self.issues_found = len(self.blocked_files)
        self.scan_passed = self.issues_found == 0


@dataclass
class ClientDeliveryManifest(SchemaMixin):
    """Manifest for the client delivery package.

    All safety invariants are hardcoded in __post_init__ and cannot be
    overridden via from_dict() or direct field assignment after construction.
    """
    project_id: str = ""
    generated_at: str = ""
    total_artifacts: int = 0
    artifacts: List[DeliveryArtifact] = field(default_factory=list)
    secret_scan: SecretScanResult = field(default_factory=SecretScanResult)
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    approved_for_client_delivery: bool = False
    human_review_required: bool = True
    auto_send_to_client: bool = False
    secret_scan_before_delivery: bool = True
    raw_secrets_included: bool = False

    def __post_init__(self) -> None:
        self.approved_for_client_delivery = False
        self.human_review_required = True
        self.auto_send_to_client = False
        self.secret_scan_before_delivery = True
        self.raw_secrets_included = False
