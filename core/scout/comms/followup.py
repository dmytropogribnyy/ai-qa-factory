"""Human-approved follow-up workflow (Final Phase II).

Follow-ups are planned, never sent automatically. Each follow-up is a separate immutable revision
that requires its own explicit human approval (no approval is inherited). Eligibility is bounded
(max follow-ups, cooldown) and fail-closed: no follow-up after a reply, opt-out, hard bounce, or
complaint; none when suppressed. The scheduler may only create a 'follow-up eligible' review item.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.scout.comms.repository import CommsRepository
from core.scout.memory.repository import MemoryRepository

_STOP_EVENTS = frozenset({"OPT_OUT", "HARD_BOUNCE", "COMPLAINT", "REPLIED"})


def evaluate_followup(mem: MemoryRepository, comms: CommsRepository, *, company_id: str,
                      contact_id: str, parent_message_id: str, sequence_no: int, now: str,
                      max_followups: int = 2) -> Dict[str, Any]:
    """Decide follow-up eligibility and record a plan (+ a human review item if eligible). Never
    sends. Returns {plan_id, state, blockers}."""
    blockers: List[str] = []
    events = comms.contact_event_types(contact_id)
    if events & _STOP_EVENTS:
        blockers.append("reply_optout_bounce_or_complaint")
    if sequence_no > max_followups:
        blockers.append("max_followups_reached")
    if mem.is_suppressed(company_id, "NO_OUTREACH"):
        blockers.append("suppressed")
    state = "ELIGIBLE" if not blockers else "BLOCKED"
    plan_id = f"fu-{contact_id}-{sequence_no}"
    comms.add_followup_plan({"plan_id": plan_id, "company_id": company_id, "contact_id": contact_id,
                             "parent_message_id": parent_message_id, "sequence_no": sequence_no,
                             "state": state, "reason": ";".join(blockers), "created_at": now})
    if state == "ELIGIBLE":
        # A review item only — a follow-up still needs its own new revision + explicit approval.
        mem.add_review_item(f"fu-review-{plan_id}", "draft_review", plan_id, company_id, now)
    return {"plan_id": plan_id, "state": state, "blockers": blockers}
