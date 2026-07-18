"""Immediate pre-send revalidation (Final Phase II).

Recomputes every send gate from AUTHORITATIVE persisted truth immediately before a provider call
and compares the recomputed snapshot hashes to the approved binding. Any change (body/recipient/
finding/evidence/disclosure/suppression/contact) blocks the send; an approval bound to changed
state is invalidated. It never trusts stored booleans or placeholder references. Produces a
versioned PRE_SEND_REVALIDATION artifact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from core.scout.comms.controls import sending_allowed
from core.scout.comms.provenance import provenance_blockers
from core.scout.comms.records import (
    ensure_suppression_check,
    record_pre_send_revalidation,
    references_resolve,
)
from core.scout.comms.repository import CommsRepository
from core.scout.comms.snapshots import approval_binding, is_placeholder_ref, suppression_snapshot
from core.scout.memory.repository import MemoryRepository
from core.scout.outreach.disclosure import build_manifest

_HASH_KEYS = ("recipient_hash", "body_hash", "disclosure_hash", "finding_hash", "evidence_hash",
              "contact_provenance_hash", "suppression_hash")
_BLOCKING_EVENTS = frozenset({"OPT_OUT", "HARD_BOUNCE", "COMPLAINT"})


@dataclass
class RevalidationResult:
    ok: bool = False
    blockers: List[str] = field(default_factory=list)
    artifact: Dict[str, Any] = field(default_factory=dict)
    recipient_value: str = ""


def _expired(iso: str, now: str) -> bool:
    if not iso.strip():
        return False
    try:
        return datetime.fromisoformat(iso) <= datetime.fromisoformat(now)
    except (ValueError, TypeError):
        return True  # unparseable expiry is treated as expired (fail closed)


def revalidate(mem: MemoryRepository, comms: CommsRepository, revision_id: str, approval_id: str,
               *, campaign_id: str, provider_id: str, channel: str, live: bool, now: str
               ) -> RevalidationResult:
    blockers: List[str] = []
    rev = comms.get_revision(revision_id)
    ap = comms.get_approval(approval_id)
    if rev is None:
        return RevalidationResult(False, ["unknown_revision"], {"ok": False, "at": now})
    if ap is None:
        return RevalidationResult(False, ["unknown_approval"], {"ok": False, "at": now})

    # Approval + revision validity.
    if ap["state"] != "APPROVED":
        blockers.append(f"approval_state_{ap['state'].lower()}")
    if ap["consumed"]:
        blockers.append("approval_already_consumed")
    if ap["revision_id"] != revision_id:
        blockers.append("approval_revision_mismatch")
    if rev["superseded"]:
        blockers.append("revision_superseded")
    if rev["state"] not in ("APPROVED", "RESERVED_FOR_SEND"):
        blockers.append("revision_not_approved")
    if _expired(ap["expires_at"], now):
        blockers.append("approval_expired")
    if _expired(rev["expires_at"], now):
        blockers.append("revision_expired")

    # No placeholder references may authorize a send.
    if is_placeholder_ref(rev["contact_id"]) or is_placeholder_ref(rev["finding_id"]):
        blockers.append("placeholder_reference")

    contact = mem.get_contact(rev["contact_id"])
    finding = mem.get_finding(rev["finding_id"])
    evidence = mem.evidence_for_finding(rev["finding_id"])
    events = comms.contact_event_types(rev["contact_id"])
    provenance = mem.active_provenance(rev["contact_id"])

    # Complete contact provenance is mandatory (missing/synthetic/unpublished/expired -> block).
    blockers.extend(provenance_blockers(provenance, now=now))

    if contact is None:
        blockers.append("contact_missing")
    elif contact["status"] != "VERIFIED":
        blockers.append("contact_not_verified")
    if finding is None:
        blockers.append("finding_missing")
    elif (finding["lifecycle_state"] != "ACTIVE" or finding["verification_state"] != "VERIFIED"
          or not finding["client_safe"]):
        blockers.append("finding_not_sendable")
    # Responsible disclosure: a security finding can never enter normal outreach.
    if finding is not None and finding.get("category") == "security":
        blockers.append("responsible_disclosure_blocked")
    if events & _BLOCKING_EVENTS:
        blockers.append("contact_blocked_by_event")
    for e in evidence:
        if not e["client_safe"]:
            blockers.append("evidence_not_client_safe")
        if _expired(e["retention_deadline"], now):
            blockers.append("evidence_expired")

    no_outreach = mem.is_suppressed(rev["company_id"], "NO_OUTREACH")
    company_suppressed = (mem.is_suppressed(rev["company_id"], "NO_SCAN")
                          or mem.is_suppressed(rev["company_id"], "COOLDOWN"))
    if no_outreach:
        blockers.append("no_outreach_suppression")
    if company_suppressed:
        blockers.append("company_suppressed")

    # Recompute the binding from current truth and compare to the approval.
    if contact is not None and finding is not None:
        ev_ids = [e["evidence_id"] for e in evidence]
        finding_dict = {"finding_id": finding["finding_id"],
                        "verification_state": finding["verification_state"],
                        "lifecycle_state": finding["lifecycle_state"],
                        "is_client_safe": bool(finding["client_safe"]), "evidence_ids": ev_ids}
        safe_findings = ([{"finding_id": finding["finding_id"], "business_impact": finding["title"],
                           "evidence_ids": ev_ids}] if finding["client_safe"] else [])
        # Real, persisted, resolvable gate references (never synthetic "reval-live" labels).
        supp_blockers = ([b for b, on in (("no_outreach", no_outreach),
                          ("company_suppressed", company_suppressed), ("opt_out", "OPT_OUT" in events),
                          ("hard_bounce", "HARD_BOUNCE" in events), ("complaint", "COMPLAINT" in events))
                          if on])
        supp_ref = ensure_suppression_check(comms, company_id=rev["company_id"],
                                            contact_id=rev["contact_id"], blockers=supp_blockers,
                                            now=now)
        reval_ref = record_pre_send_revalidation(comms, company_id=rev["company_id"],
                                                 contact_id=rev["contact_id"], revision_id=revision_id,
                                                 approval_id=approval_id, blockers=sorted(set(blockers)),
                                                 now=now)
        manifest = build_manifest(rev["company_id"], safe_findings, stage="OUTREACH",
                                  contact_ref=rev["contact_id"], suppression_check_ref=supp_ref,
                                  revalidation_ref=reval_ref, approval_ref="", generated_at=now)
        disc = {"ready": manifest.is_ready, "stage": manifest.stage,
                "item_finding_refs": [i.finding_ref for i in manifest.items],
                "blockers": manifest.blockers}
        # The manifest is send-ready only when its suppression reference resolves to a real record.
        _, ref_blockers = references_resolve(comms, suppression_check_ref=supp_ref,
                                             company_id=rev["company_id"],
                                             contact_id=rev["contact_id"], now=now)
        blockers.extend(ref_blockers)
        supp = suppression_snapshot(rev["company_id"], no_outreach=no_outreach,
                                    company_suppressed=company_suppressed,
                                    opted_out="OPT_OUT" in events,
                                    do_not_contact=(contact["status"] == "DO_NOT_CONTACT"),
                                    hard_bounced="HARD_BOUNCE" in events)
        current = approval_binding(revision_id=revision_id, recipient=contact, channel=channel,
                                   subject=rev["subject"], body=rev["body"], disclosure=disc,
                                   finding=finding_dict, evidence_rows=evidence, contact=contact,
                                   suppression=supp, provenance=provenance)
        for key in _HASH_KEYS:
            if current.get(key) != ap.get(key):
                blockers.append(f"changed_{key[:-5]}")  # e.g. changed_body, changed_recipient

    recipient_value = contact["normalized_value"] if contact else ""
    allowed, control_blockers = sending_allowed(
        comms, campaign_id=campaign_id, provider_id=provider_id, channel=channel,
        recipient=recipient_value, live=live)
    blockers.extend(control_blockers)

    blockers = sorted(set(blockers))
    ok = not blockers
    artifact = {"revision_id": revision_id, "approval_id": approval_id, "ok": ok,
                "blockers": blockers, "at": now, "recipient_ref": rev["contact_id"],
                "provider_id": provider_id, "channel": channel, "live": live,
                "finding_id": rev["finding_id"], "company_id": rev["company_id"]}
    return RevalidationResult(ok, blockers, artifact, recipient_value)
