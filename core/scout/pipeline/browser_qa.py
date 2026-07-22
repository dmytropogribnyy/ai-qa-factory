"""Real-browser deep-QA capabilities (Final Phase I).

Runs against a real rendered page (Playwright) OR a controlled fake page (for deterministic
tests):

- `run_reversible_cart` performs ONE bounded reversible cart/session action with synthetic data:
  it records pre-state, performs the action, cleans up, and verifies the post-cleanup state. If
  cleanup is NOT verified, the session is UNCLEAN and every finding from it is marked
  `from_clean_session=False` so it can never become CLIENT_SAFE.
- `run_performance` observes real rendered navigation timings / resource counts / transfer sizes
  (honestly named — NOT Lighthouse).
- `run_axe` injects and runs real axe-core against the rendered page (distinct from the static
  heuristics), returning bounded, deduplicated, sanitized violations.

Nothing here submits a form, logs in, orders, pays, uploads, or sends anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.scout.pipeline.normalize import RawObservation

# JS snippets (bounded, read-only except the explicit reversible cart mutation + cleanup).
READ_CART_JS = "window.localStorage.getItem('cart') || ''"
CLEAR_CART_JS = "window.localStorage.removeItem('cart'); window.localStorage.getItem('cart') || ''"
PERF_JS = (
    "(() => { const n = performance.getEntriesByType('navigation')[0] || {};"
    " const r = performance.getEntriesByType('resource');"
    " let bytes = 0, largest = 0; for (const e of r) { bytes += (e.transferSize||0);"
    " if ((e.transferSize||0) > largest) largest = e.transferSize||0; }"
    " return { domContentLoaded: Math.round(n.domContentLoadedEventEnd||0),"
    " loadEvent: Math.round(n.loadEventEnd||0), responseEnd: Math.round(n.responseEnd||0),"
    " resourceCount: r.length, transferBytes: bytes, largestResourceBytes: largest }; })()"
)
AXE_RUN_JS = "axe.run(document, {resultTypes:['violations']})"

_MAX_A11Y_FINDINGS = 100


@dataclass
class ReversibleResult:
    action_class: str = "REVERSIBLE_SESSION_WRITE"
    pre_state: str = ""
    mutated_state: str = ""
    post_state: str = ""
    cleanup_verified: bool = False
    observations: List[RawObservation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"action_class": self.action_class, "pre_state": self.pre_state,
                "mutated_state": self.mutated_state, "post_state": self.post_state,
                "cleanup_verified": self.cleanup_verified,
                "cleanup_status": "VERIFIED" if self.cleanup_verified else "FAILED"}


def run_reversible_cart(page, url: str, *, add_selector: str = "#add-to-cart") -> ReversibleResult:
    """One bounded reversible cart action with synthetic data + verified cleanup.

    Fail-closed: any exception during the action or cleanup yields cleanup_verified=False, which
    marks the whole session unclean (its findings can never be CLIENT_SAFE)."""
    result = ReversibleResult()
    try:
        page.goto(url, wait_until="load", timeout=15000)
        result.pre_state = str(page.evaluate(READ_CART_JS))
        page.click(add_selector)                     # synthetic, reversible session write
        result.mutated_state = str(page.evaluate(READ_CART_JS))
        result.post_state = str(page.evaluate(CLEAR_CART_JS))   # cleanup
        # Cleanup is verified only when the post-cleanup state matches the (empty) pre-state.
        result.cleanup_verified = (result.post_state == result.pre_state)
    except Exception as exc:  # any failure => unclean session, findings cannot be client-safe
        result.cleanup_verified = False
        result.observations.append(RawObservation(
            capability="business_flow", category="business_flow",
            title="Reversible cart action or cleanup failed", severity="info", url=url,
            root_impact_key="flow:reversible_cleanup_failed", signature="reversible_cleanup_failed",
            business_impact="Cleanup could not be verified; findings are not client-safe.",
            from_clean_session=False,
            provenance={"tool": "reversible_cart", "error": str(exc)[:120]}))
    if not result.cleanup_verified and not result.observations:
        result.observations.append(RawObservation(
            capability="business_flow", category="business_flow",
            title="Reversible cart cleanup not verified", severity="info", url=url,
            root_impact_key="flow:reversible_cleanup_failed", signature="reversible_cleanup_failed",
            from_clean_session=False, provenance={"tool": "reversible_cart"}))
    return result


def run_performance(page, url: str) -> Dict[str, Any]:
    """Real rendered performance observation (NOT Lighthouse). Returns a bounded metric summary."""
    page.goto(url, wait_until="load", timeout=20000)
    metrics = page.evaluate(PERF_JS)
    return {"mode": "chrome_perf_observation", "tool": "playwright", "url": url,
            "metrics": {k: metrics.get(k) for k in
                        ("domContentLoaded", "loadEvent", "responseEnd", "resourceCount",
                         "transferBytes", "largestResourceBytes")},
            "coverage_limitations": ["Not Lighthouse; no lab-throttled scoring or filmstrip."]}


def performance_observations(perf: Dict[str, Any], *, thresholds: Dict[str, int]) -> List[RawObservation]:
    """Turn a performance summary into findings against configurable, versioned thresholds."""
    out: List[RawObservation] = []
    m = perf.get("metrics", {})
    load = m.get("loadEvent") or 0
    if load and load > thresholds.get("load_ms", 4000):
        out.append(RawObservation(
            capability="performance", category="performance", title="Slow page load", severity="medium",
            url=perf.get("url", ""), root_impact_key="perf:slow_load", signature="slow_load",
            actual=f"load ~{load}ms", expected=f"< {thresholds.get('load_ms', 4000)}ms",
            business_impact="Slow loads increase bounce and lost conversions.",
            provenance={"tool": "chrome_perf_observation", "metric": "loadEvent", "value": load}))
    largest = m.get("largestResourceBytes") or 0
    if largest > thresholds.get("largest_resource_bytes", 1_500_000):
        out.append(RawObservation(
            capability="performance", category="performance", title="Large hero/resource",
            severity="low", url=perf.get("url", ""), root_impact_key="perf:large_resource",
            signature="large_resource", actual=f"{largest} bytes",
            business_impact="Oversized resources slow first render on mobile.",
            provenance={"tool": "chrome_perf_observation", "metric": "largestResourceBytes"}))
    return out


def run_axe(page, url: str) -> List[RawObservation]:
    """Run REAL axe-core against the rendered page (distinct from static heuristics)."""
    page.goto(url, wait_until="load", timeout=20000)
    _inject_axe(page)
    report = page.evaluate(AXE_RUN_JS)
    return parse_axe_violations(report, url)


def collect_axe_on_page(page, *, max_violations: int = _MAX_A11Y_FINDINGS) -> List[Dict[str, Any]]:
    """Run axe-core against an ALREADY-LOADED page (NO navigation of its own — for the operator deep
    capture that already owns the live page). Injects only the pinned repo-local axe bundle (never a
    CDN). Returns BOUNDED, REDACTED raw violations — rule id, impact, help text, and one sanitized
    selector; never a full DOM dump, message list, or node payload."""
    _inject_axe(page)
    report = page.evaluate(AXE_RUN_JS)
    out: List[Dict[str, Any]] = []
    for v in ((report or {}).get("violations", []) or [])[:max_violations]:
        out.append({"rule": str(v.get("id", "unknown"))[:60],
                    "impact": str(v.get("impact", "") or "minor")[:20],
                    "help": str(v.get("help", "") or "")[:160],
                    "selector": _first_selector(v)})
    return out


def parse_axe_violations(report: Dict[str, Any], url: str) -> List[RawObservation]:
    """Parse an axe.run() report into bounded, deduplicated, sanitized accessibility findings."""
    violations = (report or {}).get("violations", [])[:_MAX_A11Y_FINDINGS]
    seen: set = set()
    out: List[RawObservation] = []
    for v in violations:
        rule = v.get("id", "unknown")
        if rule in seen:
            continue
        seen.add(rule)
        impact = v.get("impact") or "minor"
        selector = _first_selector(v)
        out.append(RawObservation(
            capability="accessibility", category="accessibility",
            title=f"axe: {v.get('help', rule)}",
            severity=_axe_severity(impact), confidence="high", url=url,
            root_impact_key=f"axe:{rule}", signature=f"axe:{rule}",
            reproduction_steps=[f"Open {url}", f"Inspect element: {selector}"],
            actual=f"axe rule {rule} ({impact})", expected="No axe violation for this rule",
            business_impact="Accessibility barriers exclude users and carry legal risk.",
            provenance={"tool": "axe-core", "rule": rule, "impact": impact, "selector": selector}))
    return out


def _axe_severity(impact: str) -> str:
    return {"critical": "high", "serious": "high", "moderate": "medium", "minor": "low"}.get(
        impact, "low")


def _first_selector(v: Dict[str, Any]) -> str:
    nodes = v.get("nodes") or []
    if nodes and isinstance(nodes[0], dict):
        target = nodes[0].get("target") or []
        # Bounded, sanitized locator — never a full DOM dump or attribute values.
        return str(target[0])[:120] if target else "(node)"
    return "(node)"


def _inject_axe(page) -> None:
    """Inject the real axe-core source into the page (raises if axe-core is unavailable)."""
    source = load_axe_source()
    page.add_script_tag(content=source)


def load_axe_source() -> str:
    """Load the axe-core JS source from the optional axe-core-python / axe_selenium_python package,
    or a vendored file. Raises RuntimeError when axe-core is not installed (acceptance then skips)."""
    import importlib.util
    from pathlib import Path
    # 1. vendored file (preferred, offline-stable).
    vendored = Path(__file__).with_name("vendor").joinpath("axe.min.js")
    if vendored.exists():
        return vendored.read_text(encoding="utf-8")
    # 2. an installed axe distribution that ships axe.min.js.
    for pkg in ("axe_core_python", "axe_selenium_python", "axe_playwright_python"):
        spec = importlib.util.find_spec(pkg)
        if spec and spec.submodule_search_locations:
            for base in spec.submodule_search_locations:
                for cand in Path(base).rglob("axe.min.js"):
                    return cand.read_text(encoding="utf-8")
    raise RuntimeError("axe-core source not available (install axe-core or vendor axe.min.js)")
