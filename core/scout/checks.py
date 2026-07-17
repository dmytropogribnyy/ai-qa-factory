"""Bounded read-only QA checks (Phase 8.3).

Each check maps a `PageObservation` (+ context) to zero or more `ScoutFinding`s. All checks
are read-only and never submit forms, log in, or trigger side effects. Findings start
`UNVERIFIED`; independent verification and sanitization happen later.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.scout.backends import PageObservation
from core.scout.findings import ScoutFinding

_EMAIL_HINTS = ("email", "e-mail", "mail")


@dataclass
class CheckContext:
    run_id: str = ""
    prospect_ref: str = ""
    backend: str = "static"
    # link (absolute url) -> observed status code (int) or 0 when unreachable.
    link_status: Dict[str, int] = field(default_factory=dict)
    # business-flow exploration result (set by the engine), if any.
    flow_result: Optional[Dict[str, Any]] = None
    max_response_bytes: int = 3_000_000


def _finding_id(ctx: CheckContext, family: str, signature: str) -> str:
    raw = f"{ctx.run_id}\x00{ctx.prospect_ref}\x00{family}\x00{signature}"
    return "f-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _mk(ctx: CheckContext, obs: PageObservation, *, family: str, category: str, title: str,
        severity: str, confidence: str, signature: str, expected: str = "", actual: str = "",
        business_impact: str = "", steps: Optional[List[str]] = None,
        coverage_limitation: str = "") -> ScoutFinding:
    return ScoutFinding(
        finding_id=_finding_id(ctx, family, signature), run_id=ctx.run_id,
        prospect_ref=ctx.prospect_ref, url=obs.final_url or obs.url, check_family=family,
        category=category, title=title, severity=severity, confidence=confidence,
        reproduction_steps=steps or [f"Open {obs.final_url or obs.url}"],
        expected=expected, actual=actual, business_impact=business_impact,
        environment={"backend": obs.backend, "status": obs.status},
        signature=signature, coverage_limitation=coverage_limitation,
    )


def check_seo(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    if not obs.ok:
        return out
    if not obs.title.strip():
        out.append(_mk(ctx, obs, family="seo", category="seo", title="Missing <title>",
                       severity="medium", confidence="high", signature="missing_title",
                       expected="A descriptive page title", actual="No <title> element",
                       business_impact="Weak search snippets reduce organic clicks."))
    if not obs.meta_description.strip():
        out.append(_mk(ctx, obs, family="seo", category="seo", title="Missing meta description",
                       severity="low", confidence="high", signature="missing_meta_description",
                       expected="A meta description", actual="No meta description",
                       business_impact="Search engines synthesize a lower-quality snippet."))
    if not obs.canonical.strip():
        out.append(_mk(ctx, obs, family="seo", category="seo", title="Missing canonical link",
                       severity="low", confidence="medium", signature="missing_canonical",
                       expected="A rel=canonical link", actual="No canonical link"))
    robots = (obs.robots_meta + " " + obs.x_robots_tag).lower()
    if "noindex" in robots:
        out.append(_mk(ctx, obs, family="seo", category="seo", title="Page marked noindex",
                       severity="high", confidence="high", signature="noindex",
                       expected="Indexable public page", actual="robots noindex present",
                       business_impact="The page is excluded from search results."))
    return out


def check_accessibility(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    if not obs.ok:
        return out
    missing_alt = [i for i in obs.images if not i.get("alt", "").strip()]
    if missing_alt:
        out.append(_mk(ctx, obs, family="accessibility", category="accessibility",
                       title=f"{len(missing_alt)} image(s) missing alt text", severity="medium",
                       confidence="high", signature="img_missing_alt",
                       expected="All content images have alt text",
                       actual=f"{len(missing_alt)} <img> without alt",
                       business_impact="Screen-reader users cannot perceive the images."))
    if not obs.input_labels_ok:
        out.append(_mk(ctx, obs, family="accessibility", category="accessibility",
                       title="Form input(s) without an accessible label", severity="medium",
                       confidence="medium", signature="unlabeled_input",
                       expected="Every input has a label/aria-label",
                       actual="One or more inputs lack an accessible name",
                       business_impact="Assistive tech users cannot identify the field."))
    h1s = [h for h in obs.headings if h["level"] == 1]
    if obs.headings and len(h1s) == 0:
        out.append(_mk(ctx, obs, family="accessibility", category="accessibility",
                       title="No <h1> heading", severity="low", confidence="medium",
                       signature="missing_h1", expected="Exactly one <h1>", actual="No <h1>"))
    if obs.landmarks.get("main", 0) == 0 and obs.headings:
        out.append(_mk(ctx, obs, family="accessibility", category="accessibility",
                       title="No <main> landmark", severity="low", confidence="medium",
                       signature="missing_main", expected="A <main> landmark", actual="No <main>"))
    return out


def check_structured_data(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    bad = [sd for sd in obs.structured_data if not sd.get("valid")]
    if not bad:
        return []
    return [_mk(ctx, obs, family="structured_data", category="structured_data",
                title="Malformed structured data (JSON-LD)", severity="low", confidence="high",
                signature="malformed_jsonld", expected="Valid JSON-LD",
                actual=f"{len(bad)} invalid JSON-LD block(s)",
                business_impact="Rich results may not render for this page.")]


def check_mobile(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    if not obs.ok or obs.has_viewport_meta:
        return []
    return [_mk(ctx, obs, family="mobile", category="mobile",
                title="Missing mobile viewport meta", severity="medium", confidence="high",
                signature="missing_viewport", expected="A responsive viewport meta tag",
                actual="No <meta name=viewport>",
                business_impact="The page renders poorly on phones, hurting mobile conversion.")]


def check_performance(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    if not obs.ok:
        return out
    if obs.html_bytes > 1_500_000:
        out.append(_mk(ctx, obs, family="performance", category="performance",
                       title="Large HTML document", severity="low", confidence="medium",
                       signature="large_html", expected="A lean HTML document",
                       actual=f"{obs.html_bytes} bytes of HTML",
                       business_impact="Large documents slow first render on mobile networks."))
    if not obs.headers.get("cache-control"):
        out.append(_mk(ctx, obs, family="performance", category="performance",
                       title="No Cache-Control header", severity="info", confidence="low",
                       signature="no_cache_control", expected="A Cache-Control policy",
                       actual="No Cache-Control response header"))
    if obs.backend == "static":
        out.append(_mk(ctx, obs, family="performance", category="coverage",
                       title="Runtime performance timing not observed (static backend)",
                       severity="info", confidence="high", signature="perf_static_limitation",
                       coverage_limitation="Real navigation timing requires the Playwright backend."))
    return out


def check_presubmit_validation(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    if not obs.ok:
        return out
    title_hint = any(h in obs.title.lower() for h in ("signup", "subscribe", "newsletter"))
    for idx, form in enumerate(obs.forms):
        haystack = " ".join(form.field_names + form.input_types + [form.action or ""]).lower()
        looks_email = any(h in haystack for h in _EMAIL_HINTS) \
            or any(h in haystack for h in ("signup", "subscribe", "newsletter")) or title_hint
        has_email_type = "email" in form.input_types
        if looks_email and not has_email_type and not form.has_required:
            out.append(_mk(ctx, obs, family="presubmit_validation", category="functional",
                           title="Signup form has no client-side validation", severity="low",
                           confidence="medium", signature=f"weak_form_validation_{idx}",
                           expected="Email field uses type=email and/or required",
                           actual="Text input with no validation attributes",
                           steps=[f"Open {obs.final_url or obs.url}",
                                  "Inspect the signup form (no submission performed)"],
                           business_impact="Invalid submissions increase bounce and lost leads."))
    return out


def check_links(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    broken = sorted(u for u, s in ctx.link_status.items() if s == 0 or s >= 400)
    for url in broken:
        status = ctx.link_status[url]
        out.append(_mk(ctx, obs, family="links", category="functional",
                       title="Broken public link", severity="medium", confidence="high",
                       signature=f"broken_link:{url}", expected="Link resolves (2xx/3xx)",
                       actual=f"Link returned {status or 'no response'}",
                       steps=[f"Open {obs.final_url or obs.url}", f"Follow the link to {url}"],
                       business_impact="Dead links break navigation and erode trust."))
    return out


def check_console_resources(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    for msg in obs.console_errors:
        out.append(_mk(ctx, obs, family="console_resources", category="reliability",
                       title="JavaScript console error", severity="medium", confidence="high",
                       signature=f"console_error:{msg[:80]}", actual=msg[:200],
                       business_impact="Console errors often indicate broken client behavior."))
    for res in obs.failed_resources:
        out.append(_mk(ctx, obs, family="console_resources", category="reliability",
                       title="Failed public resource", severity="low", confidence="high",
                       signature=f"failed_resource:{res}", actual=f"Failed to load {res}"))
    if obs.backend == "static":
        out.append(_mk(ctx, obs, family="console_resources", category="coverage",
                       title="Console/resource errors not observed (static backend)",
                       severity="info", confidence="high", signature="console_static_limitation",
                       coverage_limitation="Console and sub-resource errors require the Playwright backend."))
    return out


def check_business_flow(obs: PageObservation, ctx: CheckContext) -> List[ScoutFinding]:
    fr = ctx.flow_result
    if not fr:
        return []
    if fr.get("entry_broken"):
        return [_mk(ctx, obs, family="business_flow", category="business_flow",
                    title="Primary business flow entry is broken", severity="high",
                    confidence="high", signature="flow_entry_broken",
                    actual=f"Flow entry link failed: {fr.get('entry_url', '')}",
                    business_impact="Users cannot start the primary conversion flow.")]
    # Informational: the flow was explored read-only and stopped before any side effect.
    return [_mk(ctx, obs, family="business_flow", category="coverage",
                title="Primary business flow explored read-only (stopped before side effect)",
                severity="info", confidence="high", signature="flow_explored",
                coverage_limitation=(
                    f"Explored {fr.get('steps', 0)} public step(s) up to a form/side-effect "
                    "boundary; no submission was performed."))]


CHECK_REGISTRY: Dict[str, Callable[[PageObservation, CheckContext], List[ScoutFinding]]] = {
    "seo": check_seo,
    "accessibility": check_accessibility,
    "structured_data": check_structured_data,
    "mobile": check_mobile,
    "performance": check_performance,
    "presubmit_validation": check_presubmit_validation,
    "links": check_links,
    "console_resources": check_console_resources,
    "business_flow": check_business_flow,
}


def run_checks(obs: PageObservation, ctx: CheckContext, families: List[str]) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    for fam in families:
        fn = CHECK_REGISTRY.get(fam)
        if fn is not None:
            out.extend(fn(obs, ctx))
    # Deterministic order.
    out.sort(key=lambda f: (f.check_family, f.signature))
    return out
