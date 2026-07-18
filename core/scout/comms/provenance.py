"""Complete contact provenance (Final Independent Acceptance, v2.0.1).

Contact provenance is a normalized, immutable entity (schema v3). Pre-send blocks unless an ACTIVE
provenance record proves the contact is publicly published for outreach, terms-reviewed where
required, fresh, named-person-reviewed where applicable, and not synthetic/defaulted. Fixture
provenance is permitted ONLY when explicitly marked ``source_category='deterministic_fixture'`` and
is never treated as a real prospect contact. The approval binds to the full provenance snapshot.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from core.scout.comms.snapshots import canonical_hash

FIXTURE_SOURCE_CATEGORY = "deterministic_fixture"
# Source categories that indicate a synthetic/defaulted (non-real) provenance when NOT the marker.
_SYNTHETIC_CATEGORIES = frozenset({"", "unknown", "default", "synthetic", "inferred", "guessed",
                                   "placeholder", "none"})
# Terms-review statuses acceptable for outreach.
_ALLOWED_TERMS = frozenset({"reviewed_ok", "not_applicable_public_org"})
_NAMED_PERSON_OK = frozenset({"approved", "cleared"})


def _expired(iso: str, now: str) -> bool:
    if not (iso or "").strip():
        return False
    try:
        return datetime.fromisoformat(iso) <= datetime.fromisoformat(now)
    except (ValueError, TypeError):
        return True  # unparseable freshness deadline is treated as expired (fail closed)


def normalized_source_hash(*, source_category: str, source_url: str, source_evidence_ref: str,
                           extraction_method: str) -> str:
    return canonical_hash({"source_category": source_category, "source_url": source_url,
                           "source_evidence_ref": source_evidence_ref,
                           "extraction_method": extraction_method})


def fixture_provenance(contact_id: str, company_id: str, now: str, *,
                       domain: str = "example") -> Dict[str, Any]:
    """A clearly-marked deterministic-fixture provenance that passes the send gates for tests and
    demos ONLY. It is never a real prospect contact (source_category = deterministic_fixture)."""
    src_url = f"https://{domain}/contact"
    ev = f"prov-ev-{contact_id}"
    nsh = normalized_source_hash(source_category=FIXTURE_SOURCE_CATEGORY, source_url=src_url,
                                 source_evidence_ref=ev, extraction_method="fixture")
    return {
        # A provenance id is unique per source: superseding a contact's provenance never collides.
        "provenance_id": f"prov-{contact_id}-{nsh[7:23]}", "contact_id": contact_id,
        "company_id": company_id, "source_category": FIXTURE_SOURCE_CATEGORY, "source_url": src_url,
        "source_evidence_ref": ev, "extraction_method": "fixture", "observed_at": now,
        "last_verified_at": now, "freshness_deadline": "2099-01-01T00:00:00+00:00",
        "publicly_published_for_contact": True, "terms_review_status": "reviewed_ok",
        "source_version": "fixture-1", "confidence": "high", "data_subject_category": "organization",
        "person_class": "generic", "manual_review_required": False, "manual_review_ref": "",
        "named_person_review_result": "", "suppression_check_ref": "", "normalized_source_hash": nsh,
        "state": "ACTIVE", "created_at": now,
    }


def provenance_blockers(provenance: Optional[Dict[str, Any]], *, now: str) -> List[str]:
    """Return the reasons an ACTIVE provenance record forbids outreach (empty == clear)."""
    if provenance is None:
        return ["provenance_missing"]
    b: List[str] = []
    if provenance.get("state") != "ACTIVE":
        b.append("provenance_not_active")
    cat = (provenance.get("source_category") or "").strip()
    if cat != FIXTURE_SOURCE_CATEGORY and cat in _SYNTHETIC_CATEGORIES:
        b.append("provenance_synthetic_or_defaulted")
    if not provenance.get("publicly_published_for_contact"):
        b.append("contact_not_publicly_published")
    if (provenance.get("terms_review_status") or "") not in _ALLOWED_TERMS:
        b.append("provenance_terms_blocked")
    if not (provenance.get("source_url") or provenance.get("source_evidence_ref")):
        b.append("provenance_source_unresolved")
    if _expired(provenance.get("freshness_deadline", ""), now):
        b.append("provenance_expired")
    if (provenance.get("person_class") == "named_person"
            and (provenance.get("named_person_review_result") or "") not in _NAMED_PERSON_OK):
        b.append("named_person_review_incomplete")
    if provenance.get("manual_review_required") and not (provenance.get("manual_review_ref") or ""):
        b.append("provenance_manual_review_incomplete")
    return b


def is_fixture(provenance: Optional[Dict[str, Any]]) -> bool:
    return bool(provenance) and provenance.get("source_category") == FIXTURE_SOURCE_CATEGORY
