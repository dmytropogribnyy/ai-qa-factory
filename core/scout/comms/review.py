"""Canonical review preview + proof-of-reviewed-content (Final Independent Acceptance, v2.0.1).

A human reviewer previews the EXACT content of one immutable revision; the preview emits a canonical
``reviewed_content_hash`` over the revision's immutable authorizing fields. Approval requires that
exact hash: an empty or arbitrary hash, a hash for another revision, or a stale preview (the
underlying contact/finding/evidence/provenance/suppression changed since the revision was built) is
rejected. The preview never displays secrets.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.scout.comms.repository import CommsRepository
from core.scout.comms.snapshots import canonical_hash
from core.scout.memory.repository import MemoryRepository

# Stable schema version for the review-preview hash (bump only on a field change).
REVIEW_PREVIEW_VERSION = "1"
_PREVIEW_HASH_FIELDS = ("revision_id", "revision_number", "company_id", "contact_id", "channel",
                        "subject", "body", "recipient_hash", "body_hash", "disclosure_hash",
                        "finding_hash", "evidence_hash", "contact_provenance_hash",
                        "suppression_hash", "expires_at")


def preview_hash(revision: Dict[str, Any]) -> str:
    """Deterministic hash over one immutable revision's exact authorizing content."""
    payload: Dict[str, Any] = {"version": REVIEW_PREVIEW_VERSION}
    for f in _PREVIEW_HASH_FIELDS:
        payload[f] = revision.get(f, "")
    return canonical_hash(payload)


def preview_hash_for(comms: CommsRepository, revision_id: str) -> str:
    rev = comms.get_revision(revision_id)
    if rev is None:
        raise KeyError(f"unknown revision: {revision_id!r}")
    return preview_hash(rev)


def review_preview(mem: MemoryRepository, comms: CommsRepository, revision_id: str) -> Dict[str, Any]:
    """The exact content a reviewer sees for one revision, plus the canonical preview hash. The
    recipient is shown from the authoritative contact; nothing here is a secret."""
    rev = comms.get_revision(revision_id)
    if rev is None:
        raise KeyError(f"unknown revision: {revision_id!r}")
    contact: Optional[Dict[str, Any]] = mem.get_contact(rev["contact_id"])
    provenance = mem.active_provenance(rev["contact_id"])
    finding = mem.get_finding(rev["finding_id"])
    return {
        "revision_id": rev["revision_id"], "revision_number": rev["revision_number"],
        "company_id": rev["company_id"], "contact_id": rev["contact_id"], "channel": rev["channel"],
        "recipient": (contact or {}).get("normalized_value", ""),
        "subject": rev["subject"], "body": rev["body"], "finding_id": rev["finding_id"],
        "finding_title": (finding or {}).get("title", ""), "state": rev["state"],
        "superseded": bool(rev["superseded"]), "expires_at": rev["expires_at"],
        "evidence_ids": rev["evidence_ids"],
        "contact_provenance": {
            "source_category": (provenance or {}).get("source_category", ""),
            "source_url": (provenance or {}).get("source_url", ""),
            "publicly_published_for_contact": bool((provenance or {}).get(
                "publicly_published_for_contact")),
            "terms_review_status": (provenance or {}).get("terms_review_status", ""),
            "person_class": (provenance or {}).get("person_class", "")},
        "reviewed_content_hash": preview_hash(rev),
    }
