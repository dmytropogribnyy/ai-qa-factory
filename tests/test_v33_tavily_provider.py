"""v3.3 Live Scout Discovery — Tavily provider + domain intelligence (deterministic, mocked HTTP).

Covers: valid/empty/malformed responses, missing key, 401, 429 retry/backoff bounds, timeout, result/
request/credit budgets, country+domain filters, canonical-domain normalization, directory/social/
job-board rejection, in-query dedup, NO fixture fallback in live mode, and secret (key) redaction.
"""
from __future__ import annotations

import json

import pytest

from core.scout.discovery.domain_intel import (
    canonical_domain,
    classify_target,
    is_company_domain,
)
from core.scout.discovery.providers import DiscoveryError, ProviderMetadata
from core.scout.discovery.tavily_provider import (
    TavilyAuthError,
    TavilyBudget,
    TavilyDiscoveryProvider,
    TavilyRequestConfig,
    TavilyTransient,
    build_query,
    tavily_country,
)

_KEY = "tvly-SECRET-do-not-leak-123456"


def _meta(**over):
    d = dict(provider_id="tavily", provider_type="api", trust_status="trusted", enabled=True,
             terms_review_status="reviewed_approved", auth_ref="TAVILY_API_KEY",
             public_or_licensed="licensed")
    d.update(over)
    return ProviderMetadata(**d)


def _result(url, title="Co", content="about the company"):
    return {"url": url, "title": title, "content": content, "score": 0.9}


def _provider(transport, *, key=_KEY, budget=None, cfg=None, live=True, inc=None, exc=None, sleeps=None):
    def _sleep(s):
        (sleeps if sleeps is not None else []).append(s)
    return TavilyDiscoveryProvider(
        _meta(), key_provider=(lambda: key), transport=transport, live_approved=live,
        budget=budget or TavilyBudget(max_requests=8, max_results=10),
        request_config=cfg or TavilyRequestConfig(max_retries=3, backoff_base_s=0.01, backoff_cap_s=0.02),
        include_domains=inc, exclude_domains=exc, sleep=_sleep)


# --- domain intelligence --------------------------------------------------------------------------
def test_canonical_domain_normalizes_scheme_case_www_tracking():
    assert canonical_domain("https://WWW.Foo.com/pricing?utm_source=x#top") == "foo.com"
    assert canonical_domain("foo.com") == "foo.com"
    assert canonical_domain("http://sub.foo.co.uk/") == "foo.co.uk"          # multi-label suffix


def test_shared_hosting_tenants_are_not_merged():
    assert canonical_domain("https://acme.myshopify.com") == "acme.myshopify.com"
    assert canonical_domain("https://other.myshopify.com") == "other.myshopify.com"
    assert canonical_domain("https://acme.myshopify.com") != canonical_domain("https://other.myshopify.com")


@pytest.mark.parametrize("url,kind", [
    ("https://acme-saas.com", "company"),
    ("https://www.linkedin.com/company/acme", "social"),
    ("https://indeed.com/jobs?q=acme", "job_board"),
    ("https://crunchbase.com/organization/acme", "aggregator"),
    ("https://g2.com/products/acme", "aggregator"),
    ("not a url", "invalid"),
])
def test_classify_target(url, kind):
    assert classify_target(url)[0] == kind


# --- query + country ------------------------------------------------------------------------------
def test_build_query_is_bounded_and_company_oriented():
    q = build_query({"industry": "B2B SaaS", "business_type": "startup", "keywords": ["billing", "api"]})
    assert '"B2B SaaS"' in q and "company official website" in q and len(q) <= 400


def test_country_mapping():
    assert tavily_country({"country": "US"}) == "united states"
    assert tavily_country({"country": "de"}) == "germany"


# --- valid / empty / malformed --------------------------------------------------------------------
def test_valid_response_returns_company_candidates_rejecting_aggregators():
    calls = {}

    def t(body, key):
        calls["body"] = body
        return {"results": [_result("https://acme-saas.com/"), _result("https://www.linkedin.com/x"),
                            _result("https://beta-saas.de/pricing")]}
    p = _provider(t)
    cands = p.discover({"industry": "B2B SaaS", "country": "us"}, limit=10)
    domains = sorted(c.raw_candidate_id for c in cands)
    assert domains == ["acme-saas.com", "beta-saas.de"]         # linkedin rejected
    assert any(r["reason"].startswith("social") for r in p.rejections)
    assert calls["body"]["country"] == "united states" and calls["body"]["search_depth"] == "basic"
    assert calls["body"]["include_answer"] is False and calls["body"]["include_raw_content"] is False


def test_empty_response_returns_no_candidates():
    assert _provider(lambda b, k: {"results": []}).discover({"industry": "x"}, 10) == []


def test_malformed_response_fails_closed():
    with pytest.raises(DiscoveryError):
        _provider(lambda b, k: {"no_results_key": 1}).discover({"industry": "x"}, 10)
    with pytest.raises(DiscoveryError):
        _provider(lambda b, k: "not a dict").discover({"industry": "x"}, 10)


# --- fail-closed conditions -----------------------------------------------------------------------
def test_missing_key_fails_closed():
    p = _provider(lambda b, k: {"results": []}, key=None)
    with pytest.raises(DiscoveryError):
        p.discover({"industry": "x"}, 10)


def test_not_live_approved_fails_closed():
    p = _provider(lambda b, k: {"results": []}, live=False)
    with pytest.raises(DiscoveryError):
        p.discover({"industry": "x"}, 10)


def test_auth_401_fails_closed_and_is_not_retried():
    sleeps = []

    def t(body, key):
        raise TavilyAuthError("tavily authentication failed")
    with pytest.raises(TavilyAuthError):
        _provider(t, sleeps=sleeps).discover({"industry": "x"}, 10)
    assert sleeps == []                                         # auth errors are never retried


# --- retry / backoff bounds -----------------------------------------------------------------------
def test_429_transient_retries_then_succeeds():
    sleeps = []
    state = {"n": 0}

    def t(body, key):
        state["n"] += 1
        if state["n"] <= 2:
            raise TavilyTransient("http 429")
        return {"results": [_result("https://acme.com")]}
    p = _provider(t, sleeps=sleeps)
    cands = p.discover({"industry": "x"}, 10)
    assert [c.raw_candidate_id for c in cands] == ["acme.com"]
    assert state["n"] == 3 and len(sleeps) == 2                 # 2 backoff sleeps, bounded


def test_transient_exhausts_retries_then_fails_closed():
    sleeps = []

    def t(body, key):
        raise TavilyTransient("http 429")
    with pytest.raises(DiscoveryError):
        _provider(t, sleeps=sleeps).discover({"industry": "x"}, 10)
    assert len(sleeps) == 3                                     # exactly max_retries backoffs


# --- budgets --------------------------------------------------------------------------------------
def test_result_budget_caps_returned_and_second_call_fails_closed():
    b = TavilyBudget(max_requests=8, max_results=2)
    p = _provider(lambda body, k: {"results": [_result("https://a.com"), _result("https://b.com"),
                                               _result("https://c.com")]}, budget=b)
    # request asks for min(limit, remaining=2) -> body max_results capped at 2
    cands = p.discover({"industry": "x"}, 10)
    assert len(cands) <= 3 and b.results_returned == 3          # returned counted; budget now exhausted
    with pytest.raises(DiscoveryError):
        p.discover({"industry": "x"}, 10)                       # remaining_results 0 -> fail closed


def test_request_budget_fails_closed():
    b = TavilyBudget(max_requests=1, max_results=50)
    p = _provider(lambda body, k: {"results": [_result("https://a.com")]}, budget=b)
    p.discover({"industry": "x"}, 10)
    with pytest.raises(DiscoveryError):
        p.discover({"industry": "x"}, 10)


def test_credit_ceiling_fails_closed():
    b = TavilyBudget(max_requests=9, max_results=50, max_credits=0.05, cost_per_request=0.05)
    p = _provider(lambda body, k: {"results": [_result("https://a.com")]}, budget=b)
    p.discover({"industry": "x"}, 10)                           # uses 0.05 credit
    with pytest.raises(DiscoveryError):
        p.discover({"industry": "x"}, 10)                       # next would exceed the ceiling


# --- filters + dedup ------------------------------------------------------------------------------
def test_include_exclude_domains_passed_and_excluded_rejected():
    calls = {}

    def t(body, k):
        calls["body"] = body
        return {"results": [_result("https://keepme.com"), _result("https://blocked.com")]}
    p = _provider(t, inc=["keepme.com"], exc=["blocked.com"])
    cands = p.discover({"industry": "x"}, 10)
    assert calls["body"]["include_domains"] == ["keepme.com"]
    assert calls["body"]["exclude_domains"] == ["blocked.com"]
    assert [c.raw_candidate_id for c in cands] == ["keepme.com"]
    assert any(r["reason"] == "excluded domain" for r in p.rejections)


def test_in_query_dedup_same_domain():
    p = _provider(lambda b, k: {"results": [_result("https://acme.com/a"), _result("https://acme.com/b")]})
    cands = p.discover({"industry": "x"}, 10)
    assert [c.raw_candidate_id for c in cands] == ["acme.com"]


# --- no fixture fallback + redaction --------------------------------------------------------------
def test_no_fixture_fallback_on_failure():
    # On any failure the live provider raises; it NEVER returns fabricated/fixture candidates.
    p = _provider(lambda b, k: (_ for _ in ()).throw(TavilyTransient("boom")))
    with pytest.raises(DiscoveryError):
        p.discover({"industry": "x"}, 10)


def test_key_never_appears_in_readiness_or_outputs():
    def t(body, k):
        assert k == _KEY                                        # key reaches the transport (header only)
        return {"results": [_result("https://acme.com")]}
    p = _provider(t)
    cands = p.discover({"industry": "x"}, 10)
    blob = json.dumps(p.readiness()) + json.dumps([c.to_dict() for c in cands]) + json.dumps(p.rejections)
    assert _KEY not in blob                                     # the secret is never surfaced
    assert p.readiness()["configured"] is True and is_company_domain("https://acme.com")


# -- credit-exhaustion classification (HTTP 432 plan / 433 PAYGO) — the Tavily Usage Guard core ------


def test_tavily_432_433_are_distinct_usage_limits_not_generic_or_transient():
    from core.scout.discovery.tavily_provider import (
        DiscoveryError, TavilyAuthError, TavilyTransient, TavilyUsageLimit, _raise_for_tavily_status)
    for code in (432, 433):
        with pytest.raises(TavilyUsageLimit):
            _raise_for_tavily_status(code)               # credit exhaustion -> its own actionable error
    with pytest.raises(TavilyTransient):
        _raise_for_tavily_status(429)                    # rate-limit stays transient (wait/retry)
    with pytest.raises(TavilyAuthError):
        _raise_for_tavily_status(401)
    with pytest.raises(DiscoveryError):
        _raise_for_tavily_status(418)                    # any other non-200 -> generic
    _raise_for_tavily_status(200)                        # 200 -> no raise
    # A usage limit must never be retried (it is a DiscoveryError, NOT a TavilyTransient).
    assert issubclass(TavilyUsageLimit, DiscoveryError)
    assert not issubclass(TavilyUsageLimit, TavilyTransient)


def test_tavily_usage_limit_messages_are_actionable():
    from core.scout.discovery.tavily_provider import TavilyUsageLimit, _raise_for_tavily_status
    with pytest.raises(TavilyUsageLimit) as e432:
        _raise_for_tavily_status(432)
    assert "432" in str(e432.value) and "upgrade" in str(e432.value).lower()
    with pytest.raises(TavilyUsageLimit) as e433:
        _raise_for_tavily_status(433)
    assert "433" in str(e433.value) and "paygo" in str(e433.value).lower()
