"""Adaptive deep-QA planner (Final Phase I).

Selects the *relevant* QA capabilities for each promoted candidate from its profile (resource
type, business type, primary/secondary flows, tech/market hints, mobile/SEO importance, access
state, commercial capacity, and budget) rather than running everything against every target.
Produces the Phase 8.2 SITE_PROFILE / BUSINESS_CONTEXT / INTERACTION_BOUNDARY / COVERAGE_MAP
artifacts plus a CAPABILITY_PLAN. Reversible-session writes are planned only for an ecommerce
cart profile and only when the campaign explicitly enables them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.prospect_business import BusinessContext, SiteProfile
from core.schemas.prospect_coverage import CoverageArea, CoverageMap
from core.schemas.prospect_interaction import InteractionActionClass, InteractionBoundary

# QA capability identifiers this pipeline can plan/run.
CAP_A11Y = "accessibility"
CAP_PERF = "performance"
CAP_SEO = "seo"
CAP_STRUCTURED = "structured_data"
CAP_MOBILE = "mobile"
CAP_FLOW = "business_flow"
CAP_REVERSIBLE = "reversible_session"

# profile -> (resource_type, business_type, base capabilities)
_PROFILE_MAP: Dict[str, tuple] = {
    "saas": ("saas_marketing_site", "saas_company",
             [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_STRUCTURED, CAP_MOBILE, CAP_FLOW]),
    "ecommerce": ("ecommerce_site", "ecommerce_business",
                  [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_STRUCTURED, CAP_MOBILE, CAP_FLOW]),
    "booking": ("booking_site", "booking",
                [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_STRUCTURED, CAP_MOBILE, CAP_FLOW]),
    "agency": ("corporate_site", "agency", [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_MOBILE, CAP_FLOW]),
    "personal_brand": ("premium_landing", "personal_brand",
                       [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_MOBILE]),
    "local_service": ("corporate_site", "local_service",
                      [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_MOBILE, CAP_FLOW]),
    "content_media": ("content_media", "content_media",
                      [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_STRUCTURED]),
    "startup_mvp": ("web_application", "startup_mvp",
                    [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_MOBILE, CAP_FLOW]),
    "unknown": ("unknown", "unknown", [CAP_A11Y, CAP_PERF, CAP_SEO, CAP_MOBILE]),
}

_BT_ALIAS = {
    "ecommerce": "ecommerce", "ecommerce_business": "ecommerce",
    "saas": "saas", "saas_company": "saas",
    "booking": "booking", "hotel": "booking", "clinic": "booking", "restaurant": "booking",
    "agency": "agency", "professional_services": "agency",
    "personal_brand": "personal_brand", "premium_landing": "personal_brand",
    "local_service": "local_service",
    "content_media": "content_media", "content": "content_media",
    "startup_mvp": "startup_mvp", "startup": "startup_mvp",
}


@dataclass
class CapabilityPlan:
    campaign_id: str = ""
    company_id: str = ""
    url: str = ""
    profile: str = "unknown"
    capabilities: List[str] = field(default_factory=list)
    reversible_session_enabled: bool = False
    max_pages: int = 4
    time_budget_s: float = 60.0
    rationale: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class PlanBundle:
    capability_plan: CapabilityPlan
    site_profile: SiteProfile
    business_context: BusinessContext
    interaction_boundary: InteractionBoundary
    coverage_map: CoverageMap

    def artifacts(self) -> Dict[str, Any]:
        return {
            "CAPABILITY_PLAN.json": self.capability_plan.to_dict(),
            "SITE_PROFILE.json": self.site_profile.to_dict(),
            "BUSINESS_CONTEXT.json": self.business_context.to_dict(),
            "INTERACTION_BOUNDARY.json": self.interaction_boundary.to_dict(),
            "COVERAGE_MAP.json": self.coverage_map.to_dict(),
        }


def classify_profile(hints: Dict[str, Any], observation) -> str:
    bt = str(hints.get("business_type_hint") or "").lower().strip()
    if bt in _BT_ALIAS:
        return _BT_ALIAS[bt]
    hay = (getattr(observation, "title", "") + " "
           + " ".join(getattr(observation, "links", []))).lower()
    if any(k in hay for k in ("cart", "checkout", "shop", "/product", "add to cart")):
        return "ecommerce"
    if any(k in hay for k in ("book", "appointment", "reserve", "booking")):
        return "booking"
    if any(k in hay for k in ("pricing", "plans", "free trial", "sign up", "signup")):
        return "saas"
    if any(k in hay for k in ("blog", "article", "news", "magazine")):
        return "content_media"
    return "unknown"


def plan_capabilities(hints: Dict[str, Any], observation, *, campaign_id: str, company_id: str,
                      reversible_enabled: bool = False, max_pages: int = 4,
                      time_budget_s: float = 60.0) -> PlanBundle:
    url = getattr(observation, "final_url", "") or getattr(observation, "url", "") or hints.get("url", "")
    profile = classify_profile(hints, observation)
    resource_type, business_type, base_caps = _PROFILE_MAP[profile]
    caps = list(base_caps)
    rationale = [f"profile={profile}"]

    # Reversible session write is planned only for ecommerce carts, only when explicitly enabled.
    if reversible_enabled and profile == "ecommerce":
        caps.append(CAP_REVERSIBLE)
        rationale.append("reversible cart action enabled for this ecommerce campaign")
    elif reversible_enabled:
        rationale.append("reversible enabled but profile is not ecommerce; not planned")

    # Drop structured_data when the page has none observed (relevance-based selection).
    if CAP_STRUCTURED in caps and not getattr(observation, "structured_data", None):
        caps.remove(CAP_STRUCTURED)
        rationale.append("no structured data observed; structured_data check skipped")

    plan = CapabilityPlan(campaign_id=campaign_id, company_id=company_id, url=url, profile=profile,
                          capabilities=caps, reversible_session_enabled=(CAP_REVERSIBLE in caps),
                          max_pages=max_pages, time_budget_s=time_budget_s, rationale=rationale)

    site_profile = SiteProfile(
        domain_ref=company_id, resource_type=resource_type,
        mobile_importance="high" if CAP_MOBILE in caps else "medium",
        seo_importance="high" if CAP_SEO in caps else "medium",
        access_classification="public_open", classification_confidence="low")

    business_context = BusinessContext(
        business_type=business_type,
        countries=[hints["country_hint"]] if hints.get("country_hint") else [],
        languages=[hints["language_hint"]] if hints.get("language_hint") else [],
        primary_flows=_flows_for(profile), confidence="low")

    permitted = [InteractionActionClass.READ_ONLY.value]
    if CAP_REVERSIBLE in caps:
        permitted.append(InteractionActionClass.REVERSIBLE_SESSION_WRITE.value)
    interaction_boundary = InteractionBoundary(permitted_action_classes=permitted,
                                               public_access_only=True)

    coverage_map = CoverageMap(subject_ref=company_id,
                               areas=[CoverageArea(area=c, status="PLANNED") for c in caps])
    return PlanBundle(plan, site_profile, business_context, interaction_boundary, coverage_map)


def _flows_for(profile: str) -> List[str]:
    return {
        "ecommerce": ["checkout"], "saas": ["signup"], "booking": ["booking"],
        "agency": ["contact"], "local_service": ["contact"], "startup_mvp": ["signup"],
    }.get(profile, [])
