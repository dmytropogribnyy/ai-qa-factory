"""Real persisted gate records + reference resolution (Final Independent Acceptance, v2.0.1).

Replaces synthetic string references (e.g. ``"reval-live"``) with resolvable immutable records:
suppression checks, policy decisions, and pre-send revalidations. Each has an immutable id, a
content hash, generated/expires timestamps, and company/contact/revision references. A disclosure
manifest may be treated as send-ready only when its suppression-check and revalidation references
resolve to real, matching, unexpired records — never to a human-looking placeholder string.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from core.scout.comms.repository import CommsRepository
from core.scout.comms.snapshots import canonical_hash, is_placeholder_ref


def _plus(now: str, hours: int) -> str:
    try:
        return (datetime.fromisoformat(now) + timedelta(hours=hours)).isoformat()
    except (ValueError, TypeError):
        return now


def _expired(iso: str, now: str) -> bool:
    if not (iso or "").strip():
        return False
    try:
        return datetime.fromisoformat(iso) <= datetime.fromisoformat(now)
    except (ValueError, TypeError):
        return True


def ensure_suppression_check(comms: CommsRepository, *, company_id: str, contact_id: str,
                             blockers: List[str], now: str, ttl_hours: int = 24) -> str:
    """Persist a suppression-check record and return its resolvable id."""
    result = "clear" if not blockers else "suppressed"
    content_hash = canonical_hash({"company_id": company_id, "contact_id": contact_id,
                                   "result": result, "blockers": sorted(blockers)})
    check_id = "supck-" + content_hash[7:27]
    comms.record_suppression_check({
        "check_id": check_id, "company_id": company_id, "contact_id": contact_id,
        "result": result, "blockers": sorted(blockers), "content_hash": content_hash,
        "generated_at": now, "expires_at": _plus(now, ttl_hours)})
    return check_id


def ensure_policy_decision(comms: CommsRepository, *, company_id: str, contact_id: str,
                           channel: str, result: str, now: str, country: str = "",
                           ttl_hours: int = 24) -> str:
    content_hash = canonical_hash({"company_id": company_id, "contact_id": contact_id,
                                   "channel": channel, "country": country, "result": result})
    decision_id = "pol-" + content_hash[7:27]
    comms.record_policy_decision({
        "decision_id": decision_id, "company_id": company_id, "contact_id": contact_id,
        "channel": channel, "country": country, "result": result, "content_hash": content_hash,
        "generated_at": now, "expires_at": _plus(now, ttl_hours)})
    return decision_id


def record_pre_send_revalidation(comms: CommsRepository, *, company_id: str, contact_id: str,
                                 revision_id: str, approval_id: str, blockers: List[str],
                                 now: str, ttl_hours: int = 1) -> str:
    result = "ok" if not blockers else "blocked"
    content_hash = canonical_hash({"revision_id": revision_id, "approval_id": approval_id,
                                   "result": result, "blockers": sorted(blockers)})
    revalidation_id = "reval-" + content_hash[7:27]
    comms.record_revalidation({
        "revalidation_id": revalidation_id, "company_id": company_id, "contact_id": contact_id,
        "revision_id": revision_id, "approval_id": approval_id, "result": result,
        "blockers": sorted(blockers), "content_hash": content_hash, "generated_at": now,
        "expires_at": _plus(now, ttl_hours)})
    return revalidation_id


def references_resolve(comms: CommsRepository, *, suppression_check_ref: str, company_id: str,
                       contact_id: str, now: str) -> Tuple[bool, List[str]]:
    """A disclosure manifest is send-ready only when its suppression-check reference resolves to a
    real, matching, unexpired record — never a placeholder/label string."""
    blockers: List[str] = []
    if is_placeholder_ref(suppression_check_ref):
        blockers.append("placeholder_suppression_reference")
        return False, blockers
    row = comms.get_suppression_check(suppression_check_ref)
    if row is None:
        blockers.append("unresolved_suppression_reference")
        return False, blockers
    if row["company_id"] != company_id or (row["contact_id"] and row["contact_id"] != contact_id):
        blockers.append("suppression_reference_mismatch")
    if _expired(row["expires_at"], now):
        blockers.append("suppression_reference_expired")
    if row["result"] != "clear":
        blockers.append("suppression_reference_not_clear")
    return (not blockers), blockers


def resolved_records(comms: CommsRepository, refs: Dict[str, str]) -> Dict[str, Any]:
    """For artifacts: resolve each reference to its record (or a not-resolved marker)."""
    out: Dict[str, Any] = {}
    getters = {"suppression_check_ref": comms.get_suppression_check,
               "revalidation_ref": comms.get_revalidation,
               "policy_decision_ref": comms.get_policy_decision}
    for name, ref in refs.items():
        getter = getters.get(name)
        out[name] = {"ref": ref, "resolved": bool(getter and getter(ref))} if getter else {"ref": ref}
    return out
