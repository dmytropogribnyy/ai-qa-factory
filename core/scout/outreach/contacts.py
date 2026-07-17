"""Public contact intelligence + contact governance (Final Phase I).

Runtime use of the hardened Phase 8.2 contact contracts. Contacts come only from official/public
sources (or explicit manual public entries); inferred candidates can never become VERIFIED or
send-eligible; named-person contacts always require manual review; and suppression / NO_OUTREACH
permanently block draft readiness (commercial/contactability scores never override suppression).
Nothing here fetches or sends anything — it records observed public contacts.
"""
from __future__ import annotations

from typing import List, Optional

from core.schemas.prospect_contact import ContactProvenance, ContactRecord
from core.schemas.source_reference import SourceReference


def public_contact(company_id: str, domain: str, channel: str, value: str, *, evidence_ref: str,
                   observed_at: str, source_url: str = "", source_category: str = "public_website",
                   published: bool = True, terms: str = "reviewed_ok",
                   data_subject: str = "organization", display_name: str = "", role_title: str = "",
                   verify: bool = False, suppression_check_ref: str = "",
                   manual_review_ref: str = "") -> ContactRecord:
    """Build a public business ContactRecord. `verify=True` promotes to VERIFIED only when the
    provenance genuinely qualifies (public, published-for-contact, evidenced, timestamped)."""
    prov = ContactProvenance(
        source=SourceReference(url=source_url or f"https://{domain}/contact",
                               platform="public_website", retrieved_at=observed_at),
        source_category=source_category, observed_at=observed_at, evidence_ref=evidence_ref,
        extraction_method="published_link", confidence="medium",
        publicly_published_for_contact=published, terms_review_status=terms)
    status = "PUBLIC_OBSERVED"
    last_verified = ""
    if verify and prov.counts_for_verification and data_subject != "named_person":
        status = "VERIFIED"
        last_verified = observed_at
    return ContactRecord(
        company_ref=company_id, domain_ref=domain, channel=channel, value=value,
        display_name=display_name, role_title=role_title, data_subject_category=data_subject,
        status=status, provenance=[prov], first_observed_at=observed_at,
        last_verified_at=last_verified, suppression_check_ref=suppression_check_ref,
        manual_review_ref=manual_review_ref)


def inferred_contact(company_id: str, domain: str, channel: str, value: str, *, observed_at: str
                     ) -> ContactRecord:
    """An inferred/guessed candidate — can never be VERIFIED or an outreach candidate."""
    prov = ContactProvenance(source=SourceReference(url=f"https://{domain}/", platform="inferred"),
                             source_category="inferred_candidate", observed_at=observed_at,
                             extraction_method="inferred_pattern", confidence="low",
                             publicly_published_for_contact=False)
    return ContactRecord(company_ref=company_id, domain_ref=domain, channel=channel, value=value,
                         data_subject_category="unknown", status="UNVERIFIED", provenance=[prov],
                         first_observed_at=observed_at)


def governance_blockers(contact: ContactRecord, *, company_suppressed: bool, no_outreach: bool,
                        do_not_contact: bool = False, opt_out: bool = False,
                        suppression_check_ref: str = "") -> List[str]:
    """Compute the fail-closed blockers preventing a contact from entering draft preparation."""
    blockers: List[str] = []
    if do_not_contact or contact.status == "DO_NOT_CONTACT":
        blockers.append("do_not_contact")
    if opt_out:
        blockers.append("opt_out_history")
    if company_suppressed:
        blockers.append("company_suppressed")
    if no_outreach:
        # NO_OUTREACH permanently blocks draft readiness (never overridden by scores).
        blockers.append("NO_OUTREACH_suppression")
    if contact.is_inferred_only:
        blockers.append("inferred_contact_not_send_eligible")
    if contact.status != "VERIFIED":
        blockers.append("contact_not_verified")
    if contact.data_subject_category == "named_person" and not contact.named_person_review_complete:
        blockers.append("named_person_review_incomplete")
    if not (suppression_check_ref or contact.suppression_check_ref).strip():
        blockers.append("missing_suppression_check_reference")
    return blockers


def is_draft_ready_contact(contact: ContactRecord, *, company_suppressed: bool, no_outreach: bool,
                           suppression_check_ref: str = "", do_not_contact: bool = False,
                           opt_out: bool = False) -> bool:
    """A contact is draft-ready only when it is a real outreach candidate AND passes governance.
    (Draft readiness is never 'sent' — Final Phase I only prepares.)"""
    if not contact.is_outreach_candidate:
        return False
    return not governance_blockers(contact, company_suppressed=company_suppressed,
                                   no_outreach=no_outreach, do_not_contact=do_not_contact,
                                   opt_out=opt_out, suppression_check_ref=suppression_check_ref)


def prefer_generic_over_named(contacts: List[ContactRecord]) -> Optional[ContactRecord]:
    """Prefer a verified generic business contact over an unreviewed named person."""
    generic = [c for c in contacts if c.data_subject_category != "named_person"
               and c.is_outreach_candidate]
    if generic:
        return generic[0]
    named_ready = [c for c in contacts
                   if c.data_subject_category == "named_person" and c.is_outreach_candidate]
    return named_ready[0] if named_ready else None
