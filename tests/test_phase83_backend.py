"""Phase 8.3 — StaticHttpBackend against deterministic local fixtures (no external network)."""
from __future__ import annotations

from core.scout.url_safety import UrlPolicy
from core.scout.backends import StaticHttpBackend
from tests.scout_fixtures import serve_fixtures


def _backend(allowed_host):
    return StaticHttpBackend(policy=UrlPolicy(allowed_local_hosts=frozenset({allowed_host})))


def test_clean_page_parsed():
    with serve_fixtures() as (base, host):
        obs = _backend(host).observe(f"{base}/clean/index.html", 10, 2_000_000)
    assert obs.ok and obs.status == 200
    assert obs.title == "Clean Clinic — Book a visit"
    assert obs.canonical.endswith("/clean/index.html")
    assert obs.meta_description
    assert any(sd["valid"] for sd in obs.structured_data)
    assert obs.landmarks.get("main", 0) >= 1
    assert obs.images and obs.images[0]["alt"] == "Clean Clinic logo"


def test_headers_sanitized_no_cookie():
    with serve_fixtures() as (base, host):
        obs = _backend(host).observe(f"{base}/clean/index.html", 10, 2_000_000)
    # The fixture sets Set-Cookie; the backend must drop it and never expose it.
    joined = "\n".join(f"{k}: {v}" for k, v in obs.headers.items())
    assert "set-cookie" not in obs.headers
    assert "secretcookievalue" not in joined
    assert "content-type" in obs.headers


def test_redirect_followed_and_recorded():
    with serve_fixtures() as (base, host):
        obs = _backend(host).observe(f"{base}/redirect/start.html", 10, 2_000_000)
    assert obs.redirect_chain and obs.final_url.endswith("/clean/index.html")
    assert obs.ok


def test_access_prohibition_and_captcha_markers():
    with serve_fixtures() as (base, host):
        b = _backend(host)
        blocked = b.observe(f"{base}/access_prohibition/index.html", 10, 2_000_000)
        captcha = b.observe(f"{base}/captcha/index.html", 10, 2_000_000)
    assert blocked.status == 403 and blocked.access_blocked_marker is True
    assert captcha.captcha_marker is True


def test_malformed_structured_data_flagged():
    with serve_fixtures() as (base, host):
        obs = _backend(host).observe(f"{base}/structured_data/index.html", 10, 2_000_000)
    assert any(not sd["valid"] for sd in obs.structured_data)


def test_blocked_host_not_fetched():
    # With no allowlist, a localhost URL is refused before any fetch.
    obs = StaticHttpBackend(policy=UrlPolicy()).observe("http://127.0.0.1:1/x", 2, 10_000)
    assert obs.ok is False and "blocked URL" in obs.fetch_error
