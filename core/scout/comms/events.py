"""Delivery / reply / bounce / opt-out event processing (Final Independent Acceptance, v2.0.1).

Every inbound event carries a trust class. Only an authenticated provider event (provider matches
the referenced outbound message + verified signature where supported), a clearly marked
deterministic fixture event, or an explicitly approved manual import may mutate durable state. The
contact/company relationship is ALWAYS derived from the referenced outbound message — a supplied
contact_id/company_id can never override it (a forged relationship is quarantined for review and
never suppresses another company). Unverifiable events are quarantined (recorded, review item, no
mutation). Events are deduplicated by key. No public unauthenticated endpoint exists.
"""
from __future__ import annotations

import json
from typing import Any, Dict, NamedTuple, Optional

from core.scout.comms.repository import (
    CommsError,
    CommsRepository,
    M_BOUNCED,
    M_DELIVERED,
    M_OPTED_OUT,
    M_REPLIED,
)
from core.scout.memory.repository import MemoryRepository

NORMALIZED_TYPES = frozenset({
    "ACCEPTED", "DELIVERED", "DELIVERY_DELAYED", "BOUNCED_SOFT", "BOUNCED_HARD",
    "REPLIED_POSITIVE", "REPLIED_NEUTRAL", "REPLIED_NEGATIVE", "OPTED_OUT", "COMPLAINT", "UNKNOWN",
})
_REPLIES = frozenset({"REPLIED_POSITIVE", "REPLIED_NEUTRAL", "REPLIED_NEGATIVE"})

# Trust classes — anything else is untrusted and quarantined.
TRUST_AUTHENTICATED = "authenticated_provider_event"
TRUST_FIXTURE = "deterministic_fixture_event"
TRUST_MANUAL = "explicitly_approved_manual_import"
_TRUSTED = frozenset({TRUST_AUTHENTICATED, TRUST_FIXTURE, TRUST_MANUAL})
_MAX_METADATA_BYTES = 2000


class _Verdict(NamedTuple):
    ok: bool
    reason: str
    contact_id: str
    company_id: str
    message_id: str


def _try_transition(comms: CommsRepository, message_id: str, to_state: str, now: str,
                    error: str = "") -> None:
    """Best-effort message transition for an inbound event (an invalid/out-of-order transition is
    ignored; the durable contact-state effect still applies)."""
    try:
        comms.transition_message(message_id, to_state, now, error=error)
    except CommsError:
        pass


def _verify_event(comms: CommsRepository, event: Dict[str, Any], msg: Optional[Dict[str, Any]]
                  ) -> _Verdict:
    trust = event.get("trust_class")
    if trust not in _TRUSTED:
        return _Verdict(False, "untrusted_class", "", "", "")
    if len(json.dumps(event.get("metadata", {}))) > _MAX_METADATA_BYTES:
        return _Verdict(False, "metadata_too_large", "", "", "")
    if event.get("message_ref") and msg is None:
        return _Verdict(False, "unknown_message", "", "", "")

    if msg is not None:
        # The relationship is authoritative from the message; a supplied id may never override it.
        sup_c, sup_co = event.get("contact_id"), event.get("company_id")
        if sup_c and sup_c != msg["contact_id"]:
            return _Verdict(False, "forged_contact_relationship", "", "", "")
        if sup_co and sup_co != msg["company_id"]:
            return _Verdict(False, "forged_company_relationship", "", "", "")
        if trust == TRUST_AUTHENTICATED:
            if event.get("provider") and event["provider"] != msg["provider_id"]:
                return _Verdict(False, "provider_message_mismatch", "", "", "")
            if event.get("signature_status") != "verified":
                return _Verdict(False, "unverified_signature", "", "", "")
        return _Verdict(True, "", msg["contact_id"], msg["company_id"], msg["message_id"])

    # No message reference: only a controlled fixture / approved manual import may use supplied ids.
    if trust == TRUST_AUTHENTICATED:
        return _Verdict(False, "authenticated_event_requires_message", "", "", "")
    if trust == TRUST_MANUAL and not (event.get("approved_by") or "").strip():
        return _Verdict(False, "manual_import_requires_approver", "", "", "")
    return _Verdict(True, "", event.get("contact_id", ""), event.get("company_id", ""), "")


def process_event(mem: MemoryRepository, comms: CommsRepository, event: Dict[str, Any], *, now: str
                  ) -> str:
    """Process one normalized event. Returns 'duplicate' | 'processed' | 'quarantined' |
    'unknown_type'. Only a verified, trusted event mutates durable state."""
    if event.get("normalized_type") not in NORMALIZED_TYPES:
        return "unknown_type"
    msg = comms.get_message(event["message_ref"]) if event.get("message_ref") else None
    verdict = _verify_event(comms, event, msg)
    result = "processed" if verdict.ok else f"quarantined:{verdict.reason}"
    if not comms.add_provider_event({**event, "processing_result": result}):
        return "duplicate"  # idempotent — a duplicate dedup_key is a no-op
    if not verdict.ok:
        # Quarantine: recorded + routed to human review; NO contact/suppression/follow-up mutation.
        mem.add_review_item(f"quarantine-{event['event_id']}", "event_review",
                            event.get("message_ref", ""), verdict.company_id or None, now)
        return "quarantined"

    t = event["normalized_type"]
    contact_id, company_id, message_id = verdict.contact_id, verdict.company_id, verdict.message_id
    if t == "DELIVERED" and message_id:
        _try_transition(comms, message_id, M_DELIVERED, now)
    elif t == "BOUNCED_HARD":
        if message_id:
            _try_transition(comms, message_id, M_BOUNCED, now, error="hard bounce")
        if contact_id:
            comms.add_contact_event(contact_id, company_id, "HARD_BOUNCE", "hard bounce", now)
            mem.set_contact_status(contact_id, "INVALID")  # invalid for sending
            mem.add_suppression(company_id, "", "NO_OUTREACH", "hard bounce", now)
    elif t == "OPTED_OUT":
        if message_id:
            _try_transition(comms, message_id, M_OPTED_OUT, now)
        if contact_id:
            comms.add_contact_event(contact_id, company_id, "OPT_OUT", "opt-out", now)
            mem.set_contact_status(contact_id, "DO_NOT_CONTACT")
            mem.add_suppression(company_id, "", "NO_OUTREACH", "opt-out", now)  # durable, immediate
    elif t == "COMPLAINT":
        if contact_id:
            comms.add_contact_event(contact_id, company_id, "COMPLAINT", "complaint", now)
            mem.set_contact_status(contact_id, "DO_NOT_CONTACT")
            mem.add_suppression(company_id, "", "NO_OUTREACH", "complaint", now)
    elif t in _REPLIES:
        if message_id:
            _try_transition(comms, message_id, M_REPLIED, now)
        if contact_id:
            comms.add_contact_event(contact_id, company_id, "REPLIED", t, now)  # stops follow-up
        if t == "REPLIED_POSITIVE" and company_id:
            mem.add_review_item(f"reply-{message_id or contact_id}", "commercial_review",
                                contact_id, company_id, now)
            comms.add_commercial_event(company_id, "positive_reply", now, source="fixture")
        elif t == "REPLIED_NEGATIVE" and company_id:
            mem.add_suppression(company_id, "", "NO_OUTREACH", "negative reply", now)
    # DELIVERY_DELAYED / BOUNCED_SOFT / ACCEPTED / UNKNOWN: recorded, no contact-state mutation.
    return "processed"
