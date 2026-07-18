"""Delivery / reply / bounce / opt-out event processing (Final Phase II).

Normalizes provider/inbound events, deduplicates them (idempotent by dedup key), and applies
fail-closed effects: a hard bounce invalidates the contact for sending; opt-out and complaint
create durable suppression immediately and disable follow-up; any reply stops automatic follow-up;
a positive reply opens a commercial-review item; unknown events never silently mutate contact
state. Local mode imports events deterministically; a signed provider webhook is optional and
never a public unauthenticated endpoint.
"""
from __future__ import annotations

from typing import Any, Dict

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


def _try_transition(comms: CommsRepository, message_id: str, to_state: str, now: str,
                    error: str = "") -> None:
    """Best-effort message transition for an inbound event: an out-of-order/invalid transition is
    ignored (the durable contact-state effect still applies), never a crash."""
    try:
        comms.transition_message(message_id, to_state, now, error=error)
    except CommsError:
        pass


def process_event(mem: MemoryRepository, comms: CommsRepository, event: Dict[str, Any], *, now: str
                  ) -> str:
    """Process one normalized event. Returns 'duplicate' | 'processed' | 'unknown_type'."""
    if event.get("normalized_type") not in NORMALIZED_TYPES:
        return "unknown_type"
    if not comms.add_provider_event(event):
        return "duplicate"  # idempotent — a duplicate dedup_key is a no-op

    t = event["normalized_type"]
    msg = comms.get_message(event.get("message_ref", "")) if event.get("message_ref") else None
    contact_id = (msg or {}).get("contact_id") or event.get("contact_id", "")
    company_id = (msg or {}).get("company_id") or event.get("company_id", "")
    message_id = (msg or {}).get("message_id", "")

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
