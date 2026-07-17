"""Static-mode deep-QA capabilities (Final Phase I).

Runs the *selected* capabilities (from the adaptive plan) in a deterministic, offline
static-heuristic mode, reusing the existing Scout check registry (no second QA engine) and
adding deep technical-SEO signals (robots.txt / sitemap.xml presence, canonical host conflict,
broken internal links via bounded same-host probing). Every observation is explicitly labelled
`static_heuristic` so it can never be confused with a real axe / rendered-performance run.
"""
from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urljoin, urlsplit

from core.scout.checks import CheckContext, run_checks
from core.scout.pipeline.normalize import RawObservation
from core.scout.pipeline.planner import (
    CAP_A11Y,
    CAP_FLOW,
    CAP_MOBILE,
    CAP_PERF,
    CAP_SEO,
    CAP_STRUCTURED,
    CapabilityPlan,
)

# plan capability -> Scout check family.
_CAP_TO_FAMILY = {
    CAP_A11Y: "accessibility", CAP_PERF: "performance", CAP_SEO: "seo",
    CAP_STRUCTURED: "structured_data", CAP_MOBILE: "mobile", CAP_FLOW: "business_flow",
}
_MODE = "static_heuristic"


def _raw_from_finding(f, capability: str) -> RawObservation:
    return RawObservation(
        capability=capability, category=f.category, title=f.title, severity=f.severity,
        confidence=f.confidence, url=f.url,
        root_impact_key=f"{capability}:{f.signature}", signature=f.signature,
        reproduction_steps=list(f.reproduction_steps), expected=f.expected, actual=f.actual,
        business_impact=f.business_impact,
        provenance={"tool": _MODE, "capability": capability, "backend": "static"})


def run_static_capabilities(plan: CapabilityPlan, observation, backend, *, clock_iso: str,
                            max_links: int = 6) -> List[RawObservation]:
    families = [_CAP_TO_FAMILY[c] for c in plan.capabilities if c in _CAP_TO_FAMILY]
    link_status = _probe_links(observation, backend, max_links) if (
        "seo" in families or "business_flow" in families) else {}
    if link_status:
        families = list(dict.fromkeys(families + ["links"]))
    flow_result = _explore_flow(observation, backend) if "business_flow" in families else None

    ctx = CheckContext(run_id=plan.company_id, prospect_ref=plan.company_id, backend="static",
                       link_status=link_status, flow_result=flow_result)
    findings = run_checks(observation, ctx, families)
    out = [_raw_from_finding(f, _family_to_cap(f.check_family)) for f in findings]
    if "seo" in families:
        out.extend(_deep_seo(observation, backend, clock_iso))
    return out


def _family_to_cap(family: str) -> str:
    inv = {v: k for k, v in _CAP_TO_FAMILY.items()}
    return inv.get(family, family)


def _probe_links(observation, backend, max_links: int) -> Dict[str, int]:
    host = urlsplit(observation.final_url or observation.url).hostname
    seen: Dict[str, int] = {}
    for link in observation.links:
        if len(seen) >= max_links:
            break
        if urlsplit(link).hostname != host or link in seen:
            continue
        probe = backend.observe(link, 10.0, 200_000)
        seen[link] = probe.status if not probe.fetch_error else 0
    return seen


def _explore_flow(observation, backend):
    host = urlsplit(observation.final_url or observation.url).hostname
    hints = ("book", "buy", "cart", "checkout", "signup", "sign-up", "contact", "start", "demo")
    entry = next((link for link in observation.links
                  if urlsplit(link).hostname == host and any(h in link.lower() for h in hints)), None)
    if not entry:
        return None
    nxt = backend.observe(entry, 10.0, 500_000)
    return {"entry_url": entry, "entry_broken": not nxt.ok, "steps": 1,
            "reached_form": bool(nxt.forms), "stopped_before_side_effect": True}


def _deep_seo(observation, backend, clock_iso: str) -> List[RawObservation]:
    """Deep technical-SEO signals beyond the homepage heuristics (static, bounded)."""
    out: List[RawObservation] = []
    base = observation.final_url or observation.url
    origin = _origin(base)

    robots = backend.observe(urljoin(origin, "/robots.txt"), 10.0, 100_000)
    if not robots.ok:
        out.append(_seo_obs(base, "no_robots_txt", "Missing robots.txt", "low",
                            "A robots.txt at the site root", "No robots.txt served",
                            "Crawlers cannot read crawl directives."))
    sitemap = backend.observe(urljoin(origin, "/sitemap.xml"), 10.0, 200_000)
    if not sitemap.ok:
        out.append(_seo_obs(base, "no_sitemap", "Missing sitemap.xml", "low",
                            "An XML sitemap", "No sitemap.xml served",
                            "Search engines lack an explicit URL inventory."))
    # Canonical host conflict (a canonical pointing at a different host).
    canonical = getattr(observation, "canonical", "")
    if canonical:
        c_host = urlsplit(canonical).hostname
        p_host = urlsplit(base).hostname
        if c_host and p_host and c_host != p_host:
            out.append(_seo_obs(base, "canonical_host_conflict",
                                "Canonical points to a different host", "medium",
                                "Canonical on the same host", f"Canonical host {c_host}",
                                "Ranking signals may be split across hosts."))
    return out


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _seo_obs(url, sig, title, severity, expected, actual, impact) -> RawObservation:
    return RawObservation(
        capability=CAP_SEO, category="seo", title=title, severity=severity, confidence="medium",
        url=url, root_impact_key=f"seo:{sig}", signature=sig,
        reproduction_steps=[f"Open {url}"], expected=expected, actual=actual,
        business_impact=impact, provenance={"tool": _MODE, "capability": "seo", "check": sig})


def summarize(observations: List[RawObservation]) -> Dict[str, Any]:
    by_cap: Dict[str, int] = {}
    for obs in observations:
        by_cap[obs.capability] = by_cap.get(obs.capability, 0) + 1
    return {"mode": _MODE, "observations": len(observations), "by_capability": by_cap}
