"""Final Phase I — reversible-session cleanup gating + performance/axe parsing (deterministic)."""
from __future__ import annotations

from core.scout.pipeline.browser_qa import (
    CLEAR_CART_JS,
    PERF_JS,
    READ_CART_JS,
    parse_axe_violations,
    performance_observations,
    run_performance,
    run_reversible_cart,
)
from core.scout.pipeline.normalize import normalize_findings, verify_findings


class _FakeCartPage:
    def __init__(self, cleanup_works=True, click_raises=False):
        self.cart = ""
        self.cleanup_works = cleanup_works
        self.click_raises = click_raises

    def goto(self, url, **kw):
        pass

    def click(self, selector):
        if self.click_raises:
            raise RuntimeError("element not found")
        self.cart = "synthetic-item"

    def evaluate(self, js):
        if js == READ_CART_JS:
            return self.cart
        if js == CLEAR_CART_JS:
            if self.cleanup_works:
                self.cart = ""
            return self.cart
        return None


def test_reversible_cart_cleanup_verified():
    result = run_reversible_cart(_FakeCartPage(cleanup_works=True), "http://fixture/cart")
    assert result.cleanup_verified and result.post_state == result.pre_state == ""
    assert not result.observations  # clean session -> no unclean marker


def test_reversible_cleanup_failure_blocks_client_safe():
    result = run_reversible_cart(_FakeCartPage(cleanup_works=False), "http://fixture/cart")
    assert not result.cleanup_verified
    assert result.observations and result.observations[0].from_clean_session is False
    # A finding from an unclean session can never become client-safe.
    findings = normalize_findings(result.observations, campaign_id="c", company_id="co",
                                  session_id="s", url="http://fixture/cart", clock_iso="t")
    verified, rejected = verify_findings(findings, {findings[0].signature})
    assert not verified and not rejected[0].is_client_safe


def test_reversible_action_exception_is_fail_closed():
    result = run_reversible_cart(_FakeCartPage(click_raises=True), "http://fixture/cart")
    assert not result.cleanup_verified
    assert result.observations[0].from_clean_session is False


class _FakePerfPage:
    def __init__(self, metrics):
        self._metrics = metrics

    def goto(self, url, **kw):
        pass

    def evaluate(self, js):
        return self._metrics if js == PERF_JS else None


def test_performance_observation_and_thresholds():
    page = _FakePerfPage({"loadEvent": 6000, "largestResourceBytes": 2_000_000, "resourceCount": 40,
                          "transferBytes": 3_000_000, "domContentLoaded": 3000, "responseEnd": 500})
    perf = run_performance(page, "http://fixture/")
    assert perf["mode"] == "chrome_perf_observation"  # honestly named, not Lighthouse
    obs = performance_observations(perf, thresholds={"load_ms": 4000,
                                                     "largest_resource_bytes": 1_500_000})
    sigs = {o.signature for o in obs}
    assert "slow_load" in sigs and "large_resource" in sigs


def test_axe_parsing_is_bounded_and_deduped():
    report = {"violations": [
        {"id": "image-alt", "impact": "critical", "help": "Images must have alt text",
         "nodes": [{"target": ["img.hero"]}]},
        {"id": "image-alt", "impact": "critical", "help": "dup", "nodes": []},  # dedup
        {"id": "color-contrast", "impact": "serious", "help": "Contrast", "nodes": [{"target": ["a"]}]},
    ]}
    obs = parse_axe_violations(report, "http://fixture/")
    rules = {o.signature for o in obs}
    assert rules == {"axe:image-alt", "axe:color-contrast"}  # deduped by rule
    assert all(o.provenance["tool"] == "axe-core" for o in obs)  # real axe, not a heuristic
    assert all(o.severity in ("high", "medium", "low") for o in obs)
