"""Immutable draft revisions + explicit human approval (Final Phase II).

Building a revision computes the authorizing binding (recipient/body/finding/evidence/disclosure/
suppression snapshot hashes) from real persisted truth. Approving copies the revision's exact
hashes into a single-use, expiring approval bound to that revision. Editing supersedes the old
revision and invalidates its approval (it never mutates an approved revision in place). Reviewer
identity must not be empty. There is no bulk approval.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from core.scout.comms.repository import CommsError, CommsRepository
from core.scout.comms.snapshots import approval_binding, body_hash, suppression_snapshot
from core.scout.memory.repository import MemoryRepository
from core.scout.outreach.disclosure import build_manifest


class ApprovalError(CommsError):
    pass


def _plus(now: str, hours: int) -> str:
    try:
        return (datetime.fromisoformat(now) + timedelta(hours=hours)).isoformat()
    except (ValueError, TypeError):
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _current_binding(mem: MemoryRepository, *, revision_id: str, company_id: str, contact_id: str,
                     finding_id: str, channel: str, subject: str, body: str, now: str
                     ) -> Dict[str, Any]:
    contact = mem.get_contact(contact_id)
    finding = mem.get_finding(finding_id)
    evidence = mem.evidence_for_finding(finding_id)
    if contact is None or finding is None:
        raise ApprovalError("cannot build a revision from missing contact/finding")
    if finding.get("category") == "security":
        # Responsible disclosure: never build an outreach revision from a security finding.
        raise ApprovalError("responsible-disclosure (security) finding cannot enter outreach")
    ev_ids = [e["evidence_id"] for e in evidence]
    finding_dict = {"finding_id": finding["finding_id"],
                    "verification_state": finding["verification_state"],
                    "lifecycle_state": finding["lifecycle_state"],
                    "is_client_safe": bool(finding["client_safe"]), "evidence_ids": ev_ids}
    safe = ([{"finding_id": finding["finding_id"], "business_impact": finding["title"],
              "evidence_ids": ev_ids}] if finding["client_safe"] else [])
    manifest = build_manifest(company_id, safe, stage="OUTREACH", contact_ref=contact_id,
                              suppression_check_ref="reval-live", revalidation_ref="reval-live",
                              generated_at=now)
    disc = {"ready": manifest.is_ready, "stage": manifest.stage,
            "item_finding_refs": [i.finding_ref for i in manifest.items], "blockers": manifest.blockers}
    no_outreach = mem.is_suppressed(company_id, "NO_OUTREACH")
    supp = suppression_snapshot(company_id, no_outreach=no_outreach,
                                company_suppressed=mem.is_suppressed(company_id, "NO_SCAN"),
                                opted_out=False, do_not_contact=(contact["status"] == "DO_NOT_CONTACT"),
                                hard_bounced=False)
    binding = approval_binding(revision_id=revision_id, recipient=contact, channel=channel,
                               subject=subject, body=body, disclosure=disc, finding=finding_dict,
                               evidence_rows=evidence, contact=contact, suppression=supp)
    binding["evidence_ids"] = ev_ids
    return binding


def build_revision(mem: MemoryRepository, comms: CommsRepository, *, draft_id: str, company_id: str,
                   contact_id: str, finding_id: str, channel: str, subject: str, body: str,
                   now: str, ttl_hours: int = 72, creator: str = "pipeline") -> str:
    number = comms.next_revision_number(draft_id)
    revision_id = f"rev-{draft_id}-{number}"
    binding = _current_binding(mem, revision_id=revision_id, company_id=company_id,
                               contact_id=contact_id, finding_id=finding_id, channel=channel,
                               subject=subject, body=body, now=now)
    comms.create_revision({
        "revision_id": revision_id, "draft_id": draft_id, "revision_number": number,
        "company_id": company_id, "contact_id": contact_id, "channel": channel,
        "finding_id": finding_id, "evidence_ids": binding["evidence_ids"], "subject": subject,
        "body": body, "body_hash": body_hash(subject, body),
        "recipient_hash": binding["recipient_hash"], "disclosure_hash": binding["disclosure_hash"],
        "finding_hash": binding["finding_hash"], "evidence_hash": binding["evidence_hash"],
        "contact_provenance_hash": binding["contact_provenance_hash"],
        "suppression_hash": binding["suppression_hash"], "generated_at": now,
        "expires_at": _plus(now, ttl_hours), "creator": creator})
    return revision_id


def approve_revision(comms: CommsRepository, revision_id: str, *, reviewer: str, now: str,
                     ttl_hours: int = 24, reason: str = "", reviewed_content_hash: str = "") -> str:
    if not reviewer.strip():
        raise ApprovalError("reviewer identity must not be empty")
    rev = comms.get_revision(revision_id)
    if rev is None:
        raise ApprovalError("unknown revision")
    approval_id = f"ap-{revision_id}"
    comms.create_approval({
        "approval_id": approval_id, "revision_id": revision_id, "recipient_hash": rev["recipient_hash"],
        "body_hash": rev["body_hash"], "disclosure_hash": rev["disclosure_hash"],
        "finding_hash": rev["finding_hash"], "evidence_hash": rev["evidence_hash"],
        "contact_provenance_hash": rev["contact_provenance_hash"],
        "suppression_hash": rev["suppression_hash"], "channel": rev["channel"], "reviewer": reviewer,
        "decision": "approve", "reason": reason, "approved_at": now,
        "expires_at": _plus(now, ttl_hours), "reviewed_content_hash": reviewed_content_hash})
    return approval_id


def edit_revision(mem: MemoryRepository, comms: CommsRepository, old_revision_id: str, *,
                  subject: str, body: str, now: str, ttl_hours: int = 72) -> str:
    """Editing creates a NEW immutable revision and invalidates the old revision's approval —
    it never mutates an approved revision in place."""
    old = comms.get_revision(old_revision_id)
    if old is None:
        raise ApprovalError("unknown revision to edit")
    comms.supersede_revision(old_revision_id)
    comms.invalidate_approval(f"ap-{old_revision_id}", "revision edited / superseded", now)
    return build_revision(mem, comms, draft_id=old["draft_id"], company_id=old["company_id"],
                          contact_id=old["contact_id"], finding_id=old["finding_id"],
                          channel=old["channel"], subject=subject, body=body, now=now,
                          ttl_hours=ttl_hours, creator="edit")
