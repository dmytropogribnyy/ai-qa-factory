"""WorkDeliveryManifest schema — Phase 8.0 (ARK universal work layer).

ADDITIVE (correction #2):
- The mature `ClientDeliveryManifest` (core/schemas/client_delivery.py) is NOT
  renamed, generalised, or modified. WorkDeliveryManifest is a new universal
  wrapper that carries common work-delivery metadata and REFERENCES a domain
  manifest (e.g. ClientDeliveryManifest for QA projects) by type + artifact path.

SAFETY / DESIGN NOTES:
- approved_for_delivery defaults to False and is never rehydrated as True.
- References only; no secret-bearing content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin

DELIVERY_VERIFICATION_STATES = frozenset({
    "unverified", "partially_verified", "verified", "verification_failed",
})


@dataclass
class WorkDeliveryManifest(SchemaMixin):
    """Universal delivery wrapper referencing a domain-specific manifest."""

    id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    work_packet_ref: str = ""
    deliverables: List[str] = field(default_factory=list)       # artifact paths/labels
    evidence_refs: List[str] = field(default_factory=list)      # EvidenceRecord/Claim ids
    verification_state: str = "unverified"
    # Link to the domain manifest instead of duplicating it.
    domain_manifest_type: str = ""              # e.g. "ClientDeliveryManifest"
    domain_manifest_path: str = ""              # artifact path reference
    approved_for_delivery: bool = False
    notes: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkDeliveryManifest:
        obj = super().from_dict(data)
        # Safety: delivery approval can never be rehydrated from disk as True.
        obj.approved_for_delivery = False
        return obj
