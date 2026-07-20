"""Country confidence — honest Verified / Probable / Unverified (v3.3).

Tavily country targeting is relevance-biased, not strict proof. We store an explicit confidence
label backed by bounded public evidence:

- **Verified** — structured metadata (schema.org PostalAddress addressCountry) or a legal/imprint
  page states a country that matches the declared one.
- **Probable** — a ccTLD or the page language aligns with the declared country.
- **Unverified** — no corroborating evidence.

A company is NEVER rejected merely because geography is Unverified; the status is shown clearly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

VERIFIED, PROBABLE, UNVERIFIED = "verified", "probable", "unverified"


def _norm(country: str) -> str:
    return (country or "").strip().lower()


@dataclass
class CountryAssessment:
    country: str
    status: str
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"country": self.country, "status": self.status, "evidence": list(self.evidence)}


def assess_country(declared: str, *, structured_country: str = "", imprint_country: str = "",
                   cctld: str = "", language_hint: str = "") -> CountryAssessment:
    """Assess how confidently the declared country is supported by bounded public evidence."""
    want = _norm(declared)
    structured, imprint = _norm(structured_country), _norm(imprint_country)
    tld, lang = _norm(cctld), _norm(language_hint)
    evidence: List[str] = []

    # Verified — hard, page-sourced evidence that matches the declared country.
    if structured and structured == want:
        evidence.append("structured metadata addressCountry matches")
        return CountryAssessment(want, VERIFIED, evidence)
    if imprint and imprint == want:
        evidence.append("legal/imprint page states country")
        return CountryAssessment(want, VERIFIED, evidence)

    # A conflicting hard signal downgrades confidence rather than claiming Verified.
    if (structured and structured != want) or (imprint and imprint != want):
        evidence.append("structured/imprint country differs from declared")
        return CountryAssessment(want, UNVERIFIED, evidence)

    # Probable — soft, relevance-biased alignment.
    if tld and tld == want:
        evidence.append(f"ccTLD .{tld} aligns")
        return CountryAssessment(want, PROBABLE, evidence)
    if lang and lang == want:
        evidence.append(f"page language {lang} aligns")
        return CountryAssessment(want, PROBABLE, evidence)

    return CountryAssessment(want, UNVERIFIED, ["no corroborating country evidence"])
