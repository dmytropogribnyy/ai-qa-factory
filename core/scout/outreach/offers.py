"""Audit offer engine (Final Phase I).

Maps a prospect's verified client-safe findings to a focused audit offer with an explainable
rationale and scope. Effort/price bands are placeholders that reference a configured policy — a
precise price or effort is never fabricated. Remediation potential never reduces the independent
value of the audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

OFFER_TYPES = frozenset({
    "QA_Discovery_Session", "Focused_Funnel_Audit", "Booking_Audit", "Ecommerce_Checkout_Audit",
    "Mobile_Responsive_Audit", "Accessibility_Audit", "Technical_SEO_Audit", "Performance_Audit",
    "API_Integration_Audit", "Comprehensive_QA_Assessment", "Combined_QA_SEO_Audit",
})

_EFFORT_BANDS = ("discovery", "focused", "standard", "comprehensive")


@dataclass
class AuditOffer:
    offer_id: str = ""
    company_id: str = ""
    offer_type: str = "QA_Discovery_Session"
    rationale: List[str] = field(default_factory=list)
    scope: List[str] = field(default_factory=list)
    included_directions: List[str] = field(default_factory=list)
    excluded_directions: List[str] = field(default_factory=list)
    effort_band: str = "discovery"                 # a band, never a precise number
    deliverables: List[str] = field(default_factory=list)
    price_band_ref: str = "config:pricing_policy"  # reference only; no fabricated price
    required_access: List[str] = field(default_factory=list)
    remediation_fit: str = ""
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def map_offer(company_id: str, findings: List[Dict[str, Any]], profile: str) -> AuditOffer:
    """Choose a focused offer from the client-safe findings and the site profile."""
    by_cap: Dict[str, int] = {}
    high = 0
    evidence: List[str] = []
    for f in findings:
        by_cap[f.get("capability", "")] = by_cap.get(f.get("capability", ""), 0) + 1
        if f.get("severity") in ("high",):
            high += 1
        evidence.extend(f.get("evidence_ids", []))
    caps = {k for k, v in by_cap.items() if v}

    offer_type, rationale = _select(caps, profile, by_cap)
    included, excluded, deliverables, access = _scope(offer_type)
    band = "comprehensive" if offer_type == "Comprehensive_QA_Assessment" else (
        "standard" if high or len(caps) >= 3 else "focused" if caps else "discovery")

    return AuditOffer(
        offer_id=f"offer-{company_id}", company_id=company_id, offer_type=offer_type,
        rationale=rationale, scope=sorted(caps) or ["general_qa_discovery"],
        included_directions=included, excluded_directions=excluded, effort_band=band,
        deliverables=deliverables, required_access=access,
        remediation_fit=("Findings are remediable; the audit's diagnostic value is independent "
                         "of remediation scope."),
        evidence_refs=sorted(set(evidence)))


def _select(caps, profile, by_cap):
    if not caps:
        return "QA_Discovery_Session", ["No verified defect yet; a discovery session is proposed."]
    if profile == "ecommerce" and "business_flow" in caps:
        return "Ecommerce_Checkout_Audit", ["Ecommerce checkout defects observed."]
    if profile == "booking" and "business_flow" in caps:
        return "Booking_Audit", ["Booking-flow defects observed."]
    if len(caps) >= 3:
        return "Comprehensive_QA_Assessment", [f"Defects across {len(caps)} QA dimensions."]
    if "accessibility" in caps and "seo" in caps:
        return "Combined_QA_SEO_Audit", ["Accessibility and technical-SEO defects observed."]
    dominant = max(by_cap, key=by_cap.get)
    single = {
        "accessibility": "Accessibility_Audit", "performance": "Performance_Audit",
        "seo": "Technical_SEO_Audit", "mobile": "Mobile_Responsive_Audit",
        "business_flow": "Focused_Funnel_Audit",
    }.get(dominant, "QA_Discovery_Session")
    return single, [f"{dominant} defects dominate the verified findings."]


def _scope(offer_type: str):
    base_deliv = ["Prioritized findings report", "Reproduction steps", "Sanitized evidence pack"]
    included = {"Accessibility_Audit": ["WCAG-oriented accessibility review"],
                "Performance_Audit": ["Rendered performance observation"],
                "Technical_SEO_Audit": ["Crawl/indexability + on-page technical SEO"],
                "Ecommerce_Checkout_Audit": ["Checkout funnel review (read-only)"],
                "Booking_Audit": ["Booking funnel review (read-only)"],
                "Comprehensive_QA_Assessment": ["Cross-dimension QA assessment"],
                "Combined_QA_SEO_Audit": ["QA + technical SEO review"],
                }.get(offer_type, ["Focused QA discovery"])
    excluded = ["Penetration testing", "Load testing", "Any change to the live site",
                "Any account/order/payment action"]
    access = ["Public URLs only"]
    return included, excluded, base_deliv, access
