"""Canonical snapshot hashing for send authorization (Final Phase II).

An approval binds to the exact authorizing state via canonical hashes; pre-send revalidation
recomputes the same hashes from authoritative persisted truth and blocks (and invalidates the
approval) on any mismatch. Hashing is deterministic (sorted-key JSON) and never includes secrets,
cookies, tokens, or raw provider payloads.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

# References that are placeholders, never authoritative — sending must reject them.
PLACEHOLDER_REFS = frozenset({"", "supp-1", "reval-1", "ev-pending", "ev-none", "ev",
                              "reval-pending", "pending", "c", "c1", "site", "market-policy"})


def canonical_hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def is_placeholder_ref(ref: str) -> bool:
    return (ref or "").strip() in PLACEHOLDER_REFS


def body_hash(subject: str, body: str) -> str:
    return canonical_hash({"subject": subject, "body": body})


def recipient_snapshot(contact: Dict[str, Any]) -> Dict[str, Any]:
    """The exact recipient the approval is bound to (no display of secrets)."""
    return {"contact_id": contact.get("contact_id", ""), "channel": contact.get("channel", ""),
            "normalized_value": contact.get("normalized_value", ""),
            "status": contact.get("status", ""),
            "data_subject_category": contact.get("data_subject_category", ""),
            "manual_review_required": bool(contact.get("manual_review_required")),
            "last_verified_at": contact.get("last_verified_at", "")}


def contact_provenance_snapshot(contact: Dict[str, Any]) -> Dict[str, Any]:
    return {"contact_id": contact.get("contact_id", ""),
            "status": contact.get("status", ""),
            "source_category": contact.get("source_category", ""),
            "manual_review_required": bool(contact.get("manual_review_required")),
            "last_verified_at": contact.get("last_verified_at", "")}


def finding_snapshot(finding: Dict[str, Any]) -> Dict[str, Any]:
    return {"finding_id": finding.get("finding_id", ""),
            "verification_state": finding.get("verification_state", ""),
            "lifecycle_state": finding.get("lifecycle_state", ""),
            "is_client_safe": bool(finding.get("is_client_safe")),
            "evidence_ids": sorted(finding.get("evidence_ids", []))}


def evidence_snapshot(evidence_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"evidence": sorted(
        [{"evidence_id": e.get("evidence_id", ""), "content_hash": e.get("content_hash", ""),
          "client_safe": bool(e.get("client_safe")),
          "retention_deadline": e.get("retention_deadline", "")}
         for e in evidence_rows], key=lambda x: x["evidence_id"])}


def disclosure_snapshot(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {"ready": bool(manifest.get("ready")), "stage": manifest.get("stage", ""),
            "item_finding_refs": sorted(manifest.get("item_finding_refs", [])),
            "blockers": sorted(manifest.get("blockers", []))}


def suppression_snapshot(company_id: str, *, no_outreach: bool, company_suppressed: bool,
                         opted_out: bool, do_not_contact: bool, hard_bounced: bool) -> Dict[str, Any]:
    return {"company_id": company_id, "no_outreach": bool(no_outreach),
            "company_suppressed": bool(company_suppressed), "opted_out": bool(opted_out),
            "do_not_contact": bool(do_not_contact), "hard_bounced": bool(hard_bounced)}


def approval_binding(*, revision_id: str, recipient: Dict[str, Any], channel: str,
                     subject: str, body: str, disclosure: Dict[str, Any], finding: Dict[str, Any],
                     evidence_rows: List[Dict[str, Any]], contact: Dict[str, Any],
                     suppression: Dict[str, Any]) -> Dict[str, str]:
    """The full set of hashes an approval binds to (and revalidation recomputes)."""
    return {
        "revision_id": revision_id,
        "recipient_hash": canonical_hash(recipient_snapshot(recipient)),
        "channel": channel,
        "body_hash": body_hash(subject, body),
        "disclosure_hash": canonical_hash(disclosure_snapshot(disclosure)),
        "finding_hash": canonical_hash(finding_snapshot(finding)),
        "evidence_hash": canonical_hash(evidence_snapshot(evidence_rows)),
        "contact_provenance_hash": canonical_hash(contact_provenance_snapshot(contact)),
        "suppression_hash": canonical_hash(suppression),
    }
