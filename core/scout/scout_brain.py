"""Scout Brain — bounded, explainable adaptive reasoning (v3.3).

The concept's Phase A (understand the target) and Phase E/F (adapt on evidence) as DETERMINISTIC,
explainable decisions — not a free-form prompt. See docs/architecture/SCOUT_BRAIN_CONCEPT.md.

- `understand_target()` infers archetype + business model + primary journeys with a confidence and
  the evidence behind it, and reports its `reasoning_source` (deterministic today; a model hook may
  raise confidence later). It NEVER silently pretends model reasoning happened.
- `replan_on_evidence()` changes the investigation when new evidence appears (deepen a flow, stop a
  weak target, escalate evidence, or block) — always inside the safety policy.
- Commercial / QA / Evidence-confidence / Safety-confidence stay SEPARATE; the combined score
  prioritizes business value and is capped by safety (an unsafe target is never top-ranked).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

# Archetypes.
ARCH_SAAS = "b2b_saas"
ARCH_ECOMMERCE = "ecommerce"
ARCH_BOOKING = "booking_travel"
ARCH_MARKETPLACE = "marketplace"
ARCH_PROFESSIONAL = "professional_services"
ARCH_CORPORATE = "commercial_product_company"
ARCH_PORTFOLIO = "personal_portfolio"
ARCH_UNKNOWN = "unknown"

# Reasoning provenance (honest degradation).
SRC_DETERMINISTIC = "deterministic"
SRC_MODEL = "model"
SRC_FALLBACK = "fallback"

_JOURNEYS = {
    ARCH_ECOMMERCE: ["product discovery", "search/filter", "product variants", "cart (reversible)",
                     "totals/pricing display", "mobile shopping"],
    ARCH_BOOKING: ["date selection", "availability display", "guest count", "pricing/currency",
                   "calendar usability", "mobile booking"],
    ARCH_SAAS: ["landing/pricing", "public demo", "signup/login entry", "form validation",
                "documentation", "responsive/accessibility"],
    ARCH_MARKETPLACE: ["discovery", "filter/sort", "listing detail", "pricing display"],
    ARCH_PROFESSIONAL: ["service discovery", "CTA behaviour", "contact form validation",
                        "phone/email links", "localization", "mobile usability"],
    ARCH_CORPORATE: ["navigation", "primary CTA", "contact form validation", "responsive"],
    ARCH_PORTFOLIO: ["navigation", "responsive", "accessibility"],
    ARCH_UNKNOWN: ["navigation", "responsive"],
}

_BUSINESS_MODEL = {
    ARCH_ECOMMERCE: "transactional product sales",
    ARCH_BOOKING: "reservation / availability sales",
    ARCH_SAAS: "subscription software",
    ARCH_MARKETPLACE: "multi-seller intermediation",
    ARCH_PROFESSIONAL: "service engagement / lead generation",
    ARCH_CORPORATE: "product company / brand presence",
    ARCH_PORTFOLIO: "personal / portfolio",
    ARCH_UNKNOWN: "undetermined",
}


@dataclass
class TargetUnderstanding:
    archetype: str
    business_model: str
    primary_journeys: List[str]
    confidence: int
    evidence: List[str] = field(default_factory=list)
    reasoning_source: str = SRC_DETERMINISTIC

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _text(signals: Dict[str, Any]) -> str:
    parts = [str(signals.get("title", "")), str(signals.get("meta", ""))]
    parts += [str(x) for x in signals.get("headings", [])]
    parts += [str(x) for x in signals.get("links", [])]
    parts += [str(x) for x in signals.get("markers", [])]
    return " ".join(parts).lower()


def understand_target(*, signals: Dict[str, Any]) -> TargetUnderstanding:
    """Deterministically infer archetype / business model / primary journeys + confidence.

    `signals` is a bounded bag of observed page tokens (title, meta, headings, links, markers).
    Strong, specific commercial markers raise confidence; a thin/ambiguous page stays low-confidence
    and archetype UNKNOWN (honest)."""
    hay = _text(signals)
    ev: List[str] = []

    def has(*words: str) -> bool:
        return any(w in hay for w in words)

    archetype = ARCH_UNKNOWN
    if has("add to cart", "checkout", "shopping cart", "shop now", "add to bag"):
        archetype = ARCH_ECOMMERCE
        ev.append("cart/checkout markers")
    elif has("book now", "check availability", "reserve", "reservation", "check-in", "nights"):
        archetype = ARCH_BOOKING
        ev.append("booking/availability markers")
    elif has("marketplace", "browse listings", "sellers", "vendors"):
        archetype = ARCH_MARKETPLACE
        ev.append("marketplace/listing markers")
    elif has("free trial", "start free", "book a demo", "request a demo", "pricing plans") \
            and has("sign up", "signup", "log in", "login", "dashboard", "api"):
        archetype = ARCH_SAAS
        ev.append("saas signup/pricing/demo markers")
    elif has("our services", "consulting", "request a quote", "get a quote", "book a consultation"):
        archetype = ARCH_PROFESSIONAL
        ev.append("professional-services markers")
    elif has("pricing", "plans", "products", "solutions", "contact sales"):
        archetype = ARCH_CORPORATE
        ev.append("generic commercial markers")
    elif has("portfolio", "about me", "my work", "resume", "cv"):
        archetype = ARCH_PORTFOLIO
        ev.append("personal/portfolio markers")

    # Confidence from the number of corroborating signals (bounded, honest).
    strength = len(ev) * 30
    if signals.get("forms"):
        strength += 10
        ev.append("form(s) present")
    if signals.get("structured_data"):
        strength += 10
        ev.append("structured data present")
    confidence = min(strength, 90) if archetype != ARCH_UNKNOWN else min(strength, 20)
    if archetype == ARCH_UNKNOWN:
        ev.append("no decisive archetype markers")

    return TargetUnderstanding(
        archetype=archetype, business_model=_BUSINESS_MODEL[archetype],
        primary_journeys=list(_JOURNEYS[archetype]), confidence=confidence, evidence=ev,
        reasoning_source=SRC_DETERMINISTIC)


# --- adaptive replanning (Phase E/F) -----------------------------------------------------------
ACTION_CONTINUE = "continue"
ACTION_DEEPEN = "deepen_flow"
ACTION_ESCALATE = "escalate_evidence"
ACTION_STOP = "stop_target"
ACTION_BLOCK = "block"


@dataclass
class ReplanDecision:
    action: str
    reason: str
    focus_flow: str = ""
    stop_before: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


# Evidence event -> adaptive action (safety-respecting).
_EVENT_RULES = {
    "failed_network": (ACTION_DEEPEN, "network failure on a user flow — inspect the affected flow"),
    "price_inconsistency": (ACTION_DEEPEN, "price/total inconsistency — inspect variants/totals/currency"),
    "broken_mobile_form": (ACTION_DEEPEN, "broken mobile form — inspect fields/validation/layout"),
    "calendar_inconsistency": (ACTION_DEEPEN, "calendar inconsistency — inspect dates/guests/pricing, "
                               "stop before reservation"),
    "no_defect_high_value": (ACTION_DEEPEN, "valuable target, no obvious defect — bounded deeper exploration"),
    "probable_high_severity": (ACTION_ESCALATE, "probable high-severity defect — one safe confirmation"),
    "minor_only_weak_target": (ACTION_STOP, "weak target, only cosmetic issues — stop spending browser budget"),
    "captcha": (ACTION_BLOCK, "CAPTCHA encountered — stop, never bypass"),
    "auth_ambiguity": (ACTION_BLOCK, "authentication ambiguity — stop rather than guess"),
    "cleanup_failure": (ACTION_STOP, "reversible cleanup unverified — stop, mark non-client-safe"),
    "unexpected_state": (ACTION_STOP, "unexpected/changed state — stop rather than guess"),
}


def replan_on_evidence(*, archetype: str, event: str, remaining_budget_s: int = 1,
                       depth: str = "selective") -> ReplanDecision:
    """Given a new evidence event during investigation, decide the next adaptive action. Blocking
    and stopping always win over deepening; a spent budget forces a stop."""
    action, reason = _EVENT_RULES.get(event, (ACTION_CONTINUE, "no adaptive trigger"))
    if action in (ACTION_BLOCK, ACTION_STOP):
        return ReplanDecision(action=action, reason=reason)
    if remaining_budget_s <= 0:
        return ReplanDecision(action=ACTION_STOP, reason="per-target/campaign budget exhausted")
    # For booking, deepening always keeps the reservation stop-boundary.
    stop_before = "reserve/book/confirm/payment" if archetype == ARCH_BOOKING else ""
    focus = {"price_inconsistency": "cart", "failed_network": "affected_flow",
             "broken_mobile_form": "form", "calendar_inconsistency": "calendar"}.get(event, "")
    return ReplanDecision(action=action, reason=reason, focus_flow=focus, stop_before=stop_before)


# --- separate confidence scores + combined ranking (§5, §4) ------------------------------------
def evidence_confidence(findings: List[Dict[str, Any]]) -> int:
    """0-100: how strong the QA evidence is (evidence refs + reproducibility signals)."""
    if not findings:
        return 0
    backed = sum(1 for f in findings if f.get("evidence_refs") or f.get("evidence_ids"))
    repro = sum(1 for f in findings if f.get("signature"))
    return min(20 + backed * 25 + repro * 10, 100)


def safety_confidence(*, cleanup_verified: bool, crossed_boundary: bool,
                      client_safe_capable: bool) -> int:
    """0-100: how safe/clean the interactive session was. Any crossed boundary is 0."""
    if crossed_boundary:
        return 0
    score = 40
    if cleanup_verified:
        score += 40
    if client_safe_capable:
        score += 20
    return min(score, 100)


def combined_opportunity_score(*, commercial: int, qa_value: int, evidence_conf: int,
                               safety_conf: int) -> int:
    """Rank by business value first, but cap by safety — an unsafe target is never top-ranked.
    Prioritizes value over raw issue count (qa_value already weights severity, not count)."""
    base = round(0.45 * commercial + 0.35 * qa_value + 0.20 * evidence_conf)
    # Safety cap: scale down when the session was not clean/safe.
    capped = round(base * (safety_conf / 100.0)) if safety_conf < 100 else base
    return max(0, min(capped, 100))


def brain_summary(*, understanding: TargetUnderstanding, commercial: int, qa_value: int,
                  evidence_conf: int, safety_conf: int) -> Dict[str, Any]:
    """A compact, auditable decision summary for the Dashboard target-detail view."""
    combined = combined_opportunity_score(commercial=commercial, qa_value=qa_value,
                                          evidence_conf=evidence_conf, safety_conf=safety_conf)
    return {
        "archetype": understanding.archetype,
        "business_model": understanding.business_model,
        "primary_journeys": understanding.primary_journeys,
        "understanding_confidence": understanding.confidence,
        "understanding_evidence": understanding.evidence,
        "reasoning_source": understanding.reasoning_source,
        "scores": {"commercial": commercial, "qa_value": qa_value,
                   "evidence_confidence": evidence_conf, "safety_confidence": safety_conf,
                   "combined_opportunity": combined},
    }


def combined_and_source() -> Tuple[str, str]:  # pragma: no cover - trivial doc anchor
    return (SRC_DETERMINISTIC, SRC_FALLBACK)
