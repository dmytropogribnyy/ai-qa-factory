"""Phase 8.3 — Scout URL-safety + run-config tests (deterministic, no real network)."""
from __future__ import annotations

import pytest

from core.scout.url_safety import UrlPolicy, check_url, dedupe_eligible
from core.scout.config import ScoutRunConfig, ScoutConfigError, make_run_id


def _global_resolver(host, port):
    # Pretend every named host resolves to a public IP (deterministic, offline).
    return ["93.184.216.34"]


def _internal_resolver(host, port):
    return ["10.0.0.5"]


class TestUrlSafety:
    def test_public_https_eligible(self):
        r = check_url("https://example.com/path?q=1", resolver=_global_resolver)
        assert r.eligible is True
        assert r.normalized == "https://example.com/path?q=1"

    @pytest.mark.parametrize("url", [
        "ftp://example.com",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:pass@example.com",
        "https://example.com:8443/",
        "https://example.com:22/",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.1.1/",
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://internalhost/",          # single-label
        "http://foo..bar/",              # malformed
        "not a url",
        "",
    ])
    def test_rejects_unsafe(self, url):
        assert check_url(url, resolver=_global_resolver).eligible is False

    def test_dns_rebinding_blocked(self):
        # A public-looking name that resolves to an internal IP is rejected.
        assert check_url("https://sneaky.example/", resolver=_internal_resolver).eligible is False

    def test_dns_failure_rejected(self):
        def _boom(host, port):
            from core.scout.url_safety import _DnsError
            raise _DnsError("nxdomain")
        assert check_url("https://nope.example/", resolver=_boom).eligible is False

    def test_explicit_local_allowlist(self):
        pol = UrlPolicy(allowed_local_hosts=frozenset({"127.0.0.1:8931"}))
        r = check_url("http://127.0.0.1:8931/index.html", policy=pol)
        assert r.eligible is True and "allowlist" in r.reason
        # Same host on a different port is NOT allow-listed.
        assert check_url("http://127.0.0.1:9999/", policy=pol).eligible is False

    def test_localhost_allowlisted_by_name(self):
        pol = UrlPolicy(allowed_local_hosts=frozenset({"localhost"}))
        assert check_url("http://localhost/x", policy=pol).eligible is True

    def test_dedupe_eligible(self):
        seeds = ["https://example.com/", "https://example.com/", "http://127.0.0.1/", "ftp://x"]
        elig, rej = dedupe_eligible(seeds, resolver=_global_resolver)
        assert len(elig) == 1
        assert len(rej) == 2  # duplicate collapses; localhost + ftp rejected


class TestScoutRunConfig:
    def _cfg(self, **kw):
        base = dict(campaign_name="demo", seeds=["https://example.com/"])
        base.update(kw)
        return ScoutRunConfig(**base)

    def test_valid(self):
        c = self._cfg()
        assert c.browser_mode == "static"
        assert set(c.check_families).issubset(
            {"links", "console_resources", "presubmit_validation", "accessibility",
             "performance", "seo", "structured_data", "mobile", "business_flow"})

    @pytest.mark.parametrize("seeds", [[], ["a"] * 11])
    def test_seed_bounds(self, seeds):
        with pytest.raises(ScoutConfigError):
            ScoutRunConfig(seeds=seeds)

    @pytest.mark.parametrize("kw", [
        {"max_pages_per_site": 0}, {"concurrency": 99}, {"request_timeout_s": 0.5},
        {"browser_mode": "chrome"}, {"check_families": ["nope"]}, {"max_response_bytes": 5},
    ])
    def test_invalid_bounds(self, kw):
        with pytest.raises(ScoutConfigError):
            self._cfg(**kw)

    def test_round_trip(self):
        c = self._cfg(allowed_local_hosts=frozenset({"127.0.0.1:8931"}))
        assert ScoutRunConfig.from_dict(c.to_dict()).to_dict() == c.to_dict()

    def test_deterministic_run_id(self):
        a = make_run_id("demo", ["https://example.com/"], "2026-07-17T00:00:00+00:00")
        b = make_run_id("demo", ["https://example.com/"], "2026-07-17T00:00:00+00:00")
        assert a == b and a.startswith("demo-")
