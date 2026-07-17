"""Outreach draft generation (Final Phase I).

Generates a concise draft from approved STRUCTURED FACTS only (no free-form invention, no LLM):
one factual observation, its concise business impact, a limited teaser, the relevant audit offer,
and a non-pressure CTA. It never invents facts, exaggerates loss, manufactures urgency, includes
exploit/root-cause detail, guesses a recipient name, or embeds confidential data. `sent` is always
False and there is no send path — a draft only enters a human review queue.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Words a draft must never contain (fake urgency / pressure / unsupported claims).
_FORBIDDEN = ("urgent", "act now", "immediately", "limited time", "you will lose",
              "guaranteed", "hurry", "final notice", "last chance")


@dataclass
class OutreachDraft:
    draft_id: str = ""
    company_id: str = ""
    company_name: str = ""
    contact_ref: str = ""
    channel: str = "email"
    subject: str = ""
    body: str = ""
    offer_type: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)
    policy_refs: List[str] = field(default_factory=list)
    generated_at: str = ""
    expires_at: str = ""
    content_hash: str = ""
    review_state: str = "PENDING_REVIEW"
    sent: bool = False                       # always False — no send exists in Final Phase I

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def generate_draft(company_id: str, company_name: str, contact: Dict[str, Any],
                   finding: Dict[str, Any], offer: Dict[str, Any], *, evidence_ref: str,
                   source_refs: List[str], policy_refs: List[str], generated_at: str,
                   expires_at: str, channel: str = "email",
                   reviewed_name: Optional[str] = None) -> OutreachDraft:
    # Greeting: only use a name that has passed named-person review; else a generic greeting.
    greeting = f"Hello {reviewed_name}," if reviewed_name else "Hello,"
    observation = _one_line(finding.get("title", "a QA issue"))
    impact = _one_line(finding.get("business_impact", "It may affect the visitor experience."))
    offer_type = offer.get("offer_type", "QA_Discovery_Session")
    body = (
        f"{greeting}\n\n"
        f"While reviewing {company_name}'s public site we noticed one issue: {observation}. "
        f"{impact}\n\n"
        f"We put together a short, sanitized summary (one finding, evidence attached by reference). "
        f"If it is useful, we could share a focused {offer_type.replace('_', ' ')} — "
        f"no obligation.\n\n"
        f"Happy to send the short summary if you'd like it.\n\n"
        f"Best regards,\nQA review team"
    )
    _assert_safe(body)
    subject = f"A quick QA note about {company_name}"
    content_hash = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    return OutreachDraft(
        draft_id=f"draft-{company_id}", company_id=company_id, company_name=company_name,
        contact_ref=contact.get("contact_id", ""), channel=channel, subject=subject, body=body,
        offer_type=offer_type, evidence_refs=[evidence_ref] if evidence_ref else [],
        source_refs=list(source_refs), policy_refs=list(policy_refs), generated_at=generated_at,
        expires_at=expires_at, content_hash=content_hash)


def _one_line(text: str) -> str:
    return " ".join(str(text).split())[:240]


def _assert_safe(body: str) -> None:
    low = body.lower()
    for term in _FORBIDDEN:
        if term in low:
            raise ValueError(f"draft contains a forbidden pressure/urgency term: {term!r}")


def render_drafts_md(drafts: List[OutreachDraft]) -> str:
    lines = ["# Outreach Drafts (PENDING HUMAN REVIEW — nothing has been sent)\n"]
    if not drafts:
        lines.append("_No drafts prepared._\n")
    for d in drafts:
        lines.append(f"## Draft `{d.draft_id}` — {d.company_name} ({d.channel})")
        lines.append(f"- Offer: {d.offer_type} · Review state: **{d.review_state}** · Sent: {d.sent}")
        lines.append(f"- Contact: `{d.contact_ref}` · Expires: {d.expires_at}")
        lines.append(f"- Subject: {d.subject}\n")
        lines.append("```\n" + d.body + "\n```\n")
    return "\n".join(lines) + "\n"
