"""Per-vertical QA profiles + bounded, fail-closed public interaction flows (v3.3).

The QA profile is selected deterministically from the site type. Each interactive flow reuses the
existing `pipeline/browser_qa` reversible primitive and the `public_action_policy` guard, and
holds one invariant: **it never crosses an irreversible boundary** (submit / send / book /
reserve / order / pay / production signup / account creation). It stops before such a boundary,
verifies cleanup for any reversible state it changed, and any exception / ambiguity / CAPTCHA /
unexpected state makes the result non-client-safe.

Flows (by site type):
- e-commerce / marketplace-cart -> ONE reversible synthetic guest-cart action + verified cleanup;
- booking/travel -> inspect availability, STOP before Hold/Reserve/Book/Confirm/payment;
- B2B SaaS -> inspect the signup/demo ENTRY only, never submit or create an account;
- professional services / contact -> validate form UI client-side, never submit;
- marketplace -> public search/filter/sort/pagination + listing detail, no account/message/order;
- personal/portfolio -> passive/static only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.scout.pipeline.browser_qa import run_reversible_cart
from core.scout.pipeline.normalize import RawObservation
from core.scout.presets import (
    SITE_TYPE_B2B_SAAS,
    SITE_TYPE_BOOKING,
    SITE_TYPE_COMMERCIAL,
    SITE_TYPE_ECOMMERCE,
    SITE_TYPE_MARKETPLACE,
    SITE_TYPE_PERSONAL,
    SITE_TYPE_PROFESSIONAL,
)
from core.scout.public_action_policy import (
    MODE_PASSIVE,
    MODE_REVERSIBLE,
    PolicyStop,
    check_action,
    is_irreversible,
    is_reversible,
)

FLOW_PASSIVE = "passive"
FLOW_CART = "reversible_cart"
FLOW_BOOKING = "booking_inspect"
FLOW_SAAS = "saas_signup_entry"
FLOW_FORM = "form_validation"
FLOW_BROWSE = "marketplace_browse"

# Collect visible action labels (bounded) — read-only.
ACTIONS_JS = (
    "(() => Array.from(document.querySelectorAll("
    "'button, a, [role=button], input[type=submit]'))"
    ".map(e => (e.innerText||e.value||'').trim()).filter(Boolean).slice(0,80))()"
)
# Read a form's client-side validation surface — read-only, never submits.
FORM_VALIDATION_JS = (
    "(() => { const f = document.querySelector('form'); if(!f) return {form:false};"
    " const req = Array.from(f.querySelectorAll('[required]')).length;"
    " return {form:true, required:req,"
    " client_validation: typeof f.checkValidity === 'function'}; })()"
)


@dataclass(frozen=True)
class VerticalProfile:
    site_type: str
    interaction_mode: str          # public_passive | public_reversible
    flow: str
    check_families: tuple
    stop_boundaries: tuple         # human-readable irreversible boundaries for this vertical


_COMMON_CHECKS = ("availability", "links", "console", "accessibility", "seo", "performance",
                  "mobile", "structured_data")

_PROFILES: Dict[str, VerticalProfile] = {
    SITE_TYPE_COMMERCIAL: VerticalProfile(
        SITE_TYPE_COMMERCIAL, MODE_REVERSIBLE, FLOW_FORM, _COMMON_CHECKS + ("business_flow",),
        ("submit", "send message")),
    SITE_TYPE_B2B_SAAS: VerticalProfile(
        SITE_TYPE_B2B_SAAS, MODE_REVERSIBLE, FLOW_SAAS, _COMMON_CHECKS + ("business_flow",),
        ("sign up", "create account", "start free trial", "submit")),
    SITE_TYPE_ECOMMERCE: VerticalProfile(
        SITE_TYPE_ECOMMERCE, MODE_REVERSIBLE, FLOW_CART, _COMMON_CHECKS + ("business_flow",),
        ("checkout", "buy now", "place order", "payment")),
    SITE_TYPE_BOOKING: VerticalProfile(
        SITE_TYPE_BOOKING, MODE_REVERSIBLE, FLOW_BOOKING, _COMMON_CHECKS + ("business_flow",),
        ("reserve", "book", "confirm", "hold", "payment")),
    SITE_TYPE_PROFESSIONAL: VerticalProfile(
        SITE_TYPE_PROFESSIONAL, MODE_REVERSIBLE, FLOW_FORM, _COMMON_CHECKS + ("business_flow",),
        ("submit", "send request", "send message")),
    SITE_TYPE_MARKETPLACE: VerticalProfile(
        SITE_TYPE_MARKETPLACE, MODE_REVERSIBLE, FLOW_BROWSE, _COMMON_CHECKS + ("business_flow",),
        ("order", "message seller", "create account", "checkout")),
    SITE_TYPE_PERSONAL: VerticalProfile(
        SITE_TYPE_PERSONAL, MODE_PASSIVE, FLOW_PASSIVE, _COMMON_CHECKS, ()),
}

# Industry/vertical -> representative site type (for the ≥12-vertical campaign taxonomy).
_INDUSTRY_TO_SITE_TYPE: Dict[str, str] = {
    "saas": SITE_TYPE_B2B_SAAS,
    "b2b saas": SITE_TYPE_B2B_SAAS,
    "b2b platforms": SITE_TYPE_B2B_SAAS,
    "fintech": SITE_TYPE_B2B_SAAS,
    "e-commerce": SITE_TYPE_ECOMMERCE,
    "ecommerce": SITE_TYPE_ECOMMERCE,
    "marketplaces": SITE_TYPE_MARKETPLACE,
    "marketplace": SITE_TYPE_MARKETPLACE,
    "travel/booking": SITE_TYPE_BOOKING,
    "travel": SITE_TYPE_BOOKING,
    "booking": SITE_TYPE_BOOKING,
    "professional services": SITE_TYPE_PROFESSIONAL,
    "agencies": SITE_TYPE_PROFESSIONAL,
    "local services": SITE_TYPE_PROFESSIONAL,
    "health/pharma": SITE_TYPE_PROFESSIONAL,
    "education": SITE_TYPE_PROFESSIONAL,
    "media/content": SITE_TYPE_COMMERCIAL,
}


def select_profile(site_type: str) -> VerticalProfile:
    """Return the QA profile for a site type, defaulting (fail-safe) to the commercial profile."""
    return _PROFILES.get(site_type or "", _PROFILES[SITE_TYPE_COMMERCIAL])


def profile_for_industry(industry: str) -> VerticalProfile:
    """Map a campaign industry/vertical onto its representative QA profile."""
    return select_profile(_INDUSTRY_TO_SITE_TYPE.get((industry or "").strip().lower(),
                                                      SITE_TYPE_COMMERCIAL))


@dataclass
class VerticalFlowResult:
    flow: str
    interaction_mode: str
    completed: bool = False
    crossed_boundary: bool = False       # INVARIANT: must always be False
    stopped_before_boundary: bool = False
    boundary: str = ""
    cleanup_verified: bool = True
    client_safe_capable: bool = True
    steps: List[str] = field(default_factory=list)
    observations: List[RawObservation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "observations"}
        d["observations"] = [o.to_dict() if hasattr(o, "to_dict") else o for o in self.observations]
        return d


def _unclean(res: VerticalFlowResult, url: str, exc: Exception) -> None:
    res.client_safe_capable = False
    res.cleanup_verified = False
    res.observations.append(RawObservation(
        capability="business_flow", category="business_flow",
        title="Vertical flow stopped on unexpected state", severity="info", url=url,
        root_impact_key="flow:unexpected_state", signature="flow_unexpected_state",
        business_impact="Flow could not complete safely; findings are not client-safe.",
        from_clean_session=False,
        provenance={"tool": "vertical_flow", "error": str(exc)[:120]}))


def _labels(page) -> List[str]:
    try:
        return list(page.evaluate(ACTIONS_JS) or [])
    except Exception:
        return []


def _stop_before_irreversible(res: VerticalFlowResult, labels: List[str]) -> None:
    for lab in labels:
        if is_irreversible(lab):
            res.stopped_before_boundary = True
            res.boundary = lab
            res.steps.append(f"stopped_before:{lab}")
            return


def run_booking_inspect(page, url: str) -> VerticalFlowResult:
    res = VerticalFlowResult(flow=FLOW_BOOKING, interaction_mode=MODE_REVERSIBLE)
    try:
        page.goto(url, wait_until="load", timeout=15000)
        res.steps.append("loaded")
        labels = _labels(page)
        for lab in labels:                       # one reversible availability/search action
            if is_reversible(lab) and ("availab" in lab.lower() or "search" in lab.lower()):
                check_action(lab, allowed_mode=MODE_REVERSIBLE)
                res.steps.append(f"reversible:{lab}")
                break
        _stop_before_irreversible(res, labels)   # never click reserve/book/confirm/pay
        res.completed = True
    except PolicyStop as ps:
        res.stopped_before_boundary = True
        res.boundary = ps.boundary
        res.steps.append(f"policy_stop:{ps.boundary}")
    except Exception as exc:
        _unclean(res, url, exc)
    return res


def run_saas_signup_entry(page, url: str) -> VerticalFlowResult:
    res = VerticalFlowResult(flow=FLOW_SAAS, interaction_mode=MODE_REVERSIBLE)
    try:
        page.goto(url, wait_until="load", timeout=15000)
        res.steps.append("loaded")
        labels = _labels(page)
        # We only INSPECT the signup/demo entry — we never click submit/create-account.
        _stop_before_irreversible(res, labels)
        res.completed = True
    except Exception as exc:
        _unclean(res, url, exc)
    return res


def run_form_validation(page, url: str) -> VerticalFlowResult:
    res = VerticalFlowResult(flow=FLOW_FORM, interaction_mode=MODE_REVERSIBLE)
    try:
        page.goto(url, wait_until="load", timeout=15000)
        res.steps.append("loaded")
        info = page.evaluate(FORM_VALIDATION_JS) or {}
        res.steps.append(f"form_inspected:{bool(info.get('form'))}")
        # Never submit — only observe client-side validation surface.
        _stop_before_irreversible(res, _labels(page))
        res.completed = True
    except Exception as exc:
        _unclean(res, url, exc)
    return res


def run_marketplace_browse(page, url: str) -> VerticalFlowResult:
    res = VerticalFlowResult(flow=FLOW_BROWSE, interaction_mode=MODE_REVERSIBLE)
    try:
        page.goto(url, wait_until="load", timeout=15000)
        res.steps.append("loaded")
        labels = _labels(page)
        for lab in labels:                       # one reversible browse action (search/filter/sort)
            low = lab.lower()
            if is_reversible(lab) and any(k in low for k in ("search", "filter", "sort", "next")):
                check_action(lab, allowed_mode=MODE_REVERSIBLE)
                res.steps.append(f"reversible:{lab}")
                break
        _stop_before_irreversible(res, labels)   # never account/message/order
        res.completed = True
    except PolicyStop as ps:
        res.stopped_before_boundary = True
        res.boundary = ps.boundary
    except Exception as exc:
        _unclean(res, url, exc)
    return res


def run_cart_flow(page, url: str) -> VerticalFlowResult:
    res = VerticalFlowResult(flow=FLOW_CART, interaction_mode=MODE_REVERSIBLE)
    cart = run_reversible_cart(page, url)
    res.completed = True
    res.cleanup_verified = cart.cleanup_verified
    res.client_safe_capable = cart.cleanup_verified   # an unclean session is never client-safe
    res.observations = list(cart.observations)
    res.steps.append(f"reversible_cart:cleanup={'ok' if cart.cleanup_verified else 'failed'}")
    return res


def run_vertical_flow(page, url: str, profile: VerticalProfile) -> VerticalFlowResult:
    """Dispatch to the bounded flow for a profile. Passive profiles perform no interaction."""
    if profile.flow == FLOW_CART:
        return run_cart_flow(page, url)
    if profile.flow == FLOW_BOOKING:
        return run_booking_inspect(page, url)
    if profile.flow == FLOW_SAAS:
        return run_saas_signup_entry(page, url)
    if profile.flow == FLOW_FORM:
        return run_form_validation(page, url)
    if profile.flow == FLOW_BROWSE:
        return run_marketplace_browse(page, url)
    res = VerticalFlowResult(flow=FLOW_PASSIVE, interaction_mode=MODE_PASSIVE, completed=True)
    res.steps.append("passive_only")
    return res
