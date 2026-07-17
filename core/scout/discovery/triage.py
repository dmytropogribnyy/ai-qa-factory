"""Cheap technical eligibility + explainable commercial triage (Phase 8.4).

Stage 1 (technical) uses the existing static HTTP profiler and Scout URL safety — never
Playwright — to check a candidate is a live, public, parseable, non-parked business site in a
supported market. Stage 2 (commercial) builds an explainable Phase 8.2 `LeadScorecard` from
cheap page signals. The commercial score NEVER authorizes contact or outreach
(`outreach_eligible` stays False); it only ranks candidates for bounded QA promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.schemas.prospect_scoring import LeadScorecard, ScoreDimension
from core.scout.backends import PageObservation
from core.scout.discovery.candidate import (
    COMM_ELIGIBLE,
    COMM_REJECT,
    COMM_WEAK,
    TECH_OK,
    TECH_REJECT,
    CandidateRecord,
)

_PARKED_MARKERS = (
    "domain for sale", "buy this domain", "this domain is for sale", "parked",
    "domain parking", "sedo", "godaddy", "hugedomains", "under construction",
    "coming soon", "site not configured", "default web page",
)
_LOW_VALUE_MARKERS = (
    "personal blog", "my hobby", "hobby project", "student project", "class project",
    "fan page", "just for fun", "personal portfolio of a student",
)
_COMMERCIAL_MARKERS = (
    "pricing", "plans", "subscribe", "subscription", "checkout", "cart", "add to cart",
    "buy now", "book", "booking", "reserve", "appointment", "demo", "get started",
    "free trial", "sign up", "contact sales", "request a quote", "shop", "order",
)
_CONVERSION_LINK_HINTS = ("pricing", "signup", "sign-up", "checkout", "cart", "book", "demo",
                          "contact", "order", "subscribe", "quote", "start", "buy")


@dataclass
class TriageContext:
    languages: List[str]
    countries: List[str]
    min_commercial_threshold: int


def _haystack(obs: PageObservation) -> str:
    parts: List[str] = [obs.title, obs.meta_description]
    parts += [h.get("text", "") for h in obs.headings]
    parts += list(obs.links)
    for form in obs.forms:
        parts += form.submit_labels + form.field_names + [form.action]
    return " ".join(parts).lower()


def assess_technical(rec: CandidateRecord, obs: PageObservation, ctx: TriageContext) -> None:
    """Stage 1: technical eligibility. Mutates the record with status + explainable reasons."""
    reasons: List[str] = []
    if not rec.normalized_url:
        rec.eligibility_status = TECH_REJECT
        return  # already flagged invalid/private during normalization
    if obs.fetch_error:
        reasons.append(f"unreachable:{obs.fetch_error[:80]}")
    if not obs.ok:
        reasons.append(f"bad_status:{obs.status}")
    parseable = bool(obs.title or obs.headings or obs.forms or obs.links)
    if not parseable:
        reasons.append("unparseable_or_empty")
    low = (obs.title + " " + obs.meta_description).lower()
    if any(m in low for m in _PARKED_MARKERS):
        reasons.append("parked_or_placeholder")
    # Explicit unsupported-market rejection when a hint contradicts the campaign scope.
    if ctx.countries and rec.country_hint and rec.country_hint not in ctx.countries:
        reasons.append(f"unsupported_market:{rec.country_hint}")
    if ctx.languages and rec.language_hint and rec.language_hint not in ctx.languages:
        reasons.append(f"unsupported_language:{rec.language_hint}")
    rec.technical_reasons.extend(reasons)
    if reasons:
        rec.eligibility_status = TECH_REJECT
        for r in reasons:
            rec.add_reason(r.split(":")[0])
    else:
        rec.eligibility_status = TECH_OK
        rec.add_reason("technical_ok")


def assess_commercial(rec: CandidateRecord, obs: PageObservation, ctx: TriageContext) -> None:
    """Stage 2: explainable commercial triage. Never authorizes outreach."""
    hay = _haystack(obs)
    dims: List[ScoreDimension] = []

    # business_impact — visible conversion actions (forms / conversion links).
    conv_links = [link for link in obs.links if any(h in link.lower() for h in _CONVERSION_LINK_HINTS)]
    bi_reasons, bi = [], 0
    if obs.forms:
        bi += 45
        bi_reasons.append(f"{len(obs.forms)} form(s) present")
    if conv_links:
        bi += 35
        bi_reasons.append(f"{len(conv_links)} conversion link(s)")
    if not obs.forms and not conv_links:
        bi_reasons.append("no visible conversion action")
    dims.append(ScoreDimension(name="business_impact", value=min(bi, 100), reasons=bi_reasons))

    # commercial_capacity — pricing / catalog / booking / subscription signals.
    hits = sorted({m for m in _COMMERCIAL_MARKERS if m in hay})
    cc = min(len(hits) * 22, 100)
    cc_reasons = [f"commercial signal: {h}" for h in hits] or ["no explicit commercial signal"]
    dims.append(ScoreDimension(name="commercial_capacity", value=cc, reasons=cc_reasons))

    # market_fit — language / country alignment with the campaign.
    mf, mf_reasons = 50, ["no explicit market hint"]
    if ctx.languages and rec.language_hint:
        mf = 90 if rec.language_hint in ctx.languages else 10
        mf_reasons = [f"language {rec.language_hint} "
                      f"{'in' if mf > 50 else 'not in'} campaign scope"]
    dims.append(ScoreDimension(name="market_fit", value=mf, reasons=mf_reasons))

    # website_criticality — richness / structured data / business identity.
    wc, wc_reasons = 20, []
    if obs.structured_data:
        wc += 25
        wc_reasons.append("structured data present")
    if rec.business_name:
        wc += 15
        wc_reasons.append("identifiable business name")
    if len(obs.links) >= 5:
        wc += 20
        wc_reasons.append("multi-section site")
    if obs.has_viewport_meta:
        wc += 10
        wc_reasons.append("responsive viewport")
    dims.append(ScoreDimension(name="website_criticality", value=min(wc, 100),
                               reasons=wc_reasons or ["thin site"]))

    # audit_opportunity — QA-relevant surface area (a realistic audit fit).
    ao = min((len(obs.forms) * 20) + (min(len(obs.images), 5) * 6)
             + (min(len(obs.headings), 5) * 6), 100)
    dims.append(ScoreDimension(name="audit_opportunity", value=ao,
                               reasons=[f"{len(obs.forms)} form(s), {len(obs.images)} image(s), "
                                        f"{len(obs.headings)} heading(s)"]))

    # access_complexity — independent axis; a public page is simple to audit (low complexity).
    dims.append(ScoreDimension(name="access_complexity", value=15,
                               reasons=["public page; no authentication observed"]))

    # Low-value / hobby content caps the commercial outcome regardless of surface area.
    low_value = any(m in hay for m in _LOW_VALUE_MARKERS)
    commercial_axes = ("business_impact", "commercial_capacity", "market_fit",
                       "website_criticality")
    by_name = {d.name: d.value for d in dims}
    score = round(sum(by_name[a] for a in commercial_axes) / len(commercial_axes))
    if low_value:
        score = min(score, 20)

    if score >= 75:
        priority = "A"
    elif score >= 60:
        priority = "B"
    elif score >= ctx.min_commercial_threshold:
        priority = "C"
    else:
        priority = "D"

    scorecard = LeadScorecard(prospect_id=rec.candidate_id, dimensions=dims, priority=priority,
                              outreach_eligible=False,  # commercial score never authorizes outreach
                              rationale=[f"commercial_score={score}",
                                         *( ["low_value_content"] if low_value else [] )])
    rec.commercial_score = score
    rec.commercial_scorecard = scorecard.to_dict()

    if low_value:
        rec.commercial_status = COMM_REJECT
        rec.commercial_reasons.append("low_value_or_hobby_content")
        rec.add_reason("low_value_content")
    elif score >= ctx.min_commercial_threshold:
        rec.commercial_status = COMM_ELIGIBLE
        rec.commercial_reasons.append(f"score {score} >= threshold {ctx.min_commercial_threshold}")
    elif score >= ctx.min_commercial_threshold - 15:
        rec.commercial_status = COMM_WEAK
        rec.commercial_reasons.append(f"score {score} below threshold {ctx.min_commercial_threshold}")
    else:
        rec.commercial_status = COMM_REJECT
        rec.commercial_reasons.append(f"score {score} well below threshold "
                                      f"{ctx.min_commercial_threshold}")
