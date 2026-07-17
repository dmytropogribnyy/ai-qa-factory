"""Bundled deterministic discovery fixtures (Phase 8.4).

Provides a committed provider fixture and a local site fixture so the full
discovery-to-Scout pipeline runs with no external network and no browser. Candidate websites
use fake *public* hostnames (so registrable-domain dedup is exercised) that a host-mapping
static backend rewrites to a local 127.0.0.1 fixture server for the actual (read-only) fetch;
unmapped hosts simulate dead/unreachable domains.

Scenario coverage: cross-provider duplicate URL, same-domain URL variant, one suppressed
(NO_OUTREACH), one NO_SCAN, one parked, one hobby/low-value, one unsupported market, one
malformed/private URL, an active SaaS, an ecommerce site, a booking/clinic site, a high-value
one-page brand, an uncertain company identity, a malformed provider result, and a
terms-blocked provider.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Iterator, List, Tuple
from urllib.parse import urlsplit, urlunsplit

from core.schemas.prospect_governance import SuppressionPolicy
from core.scout.backends import PageObservation, StaticHttpBackend
from core.scout.discovery.providers import (
    DiscoveryCandidate,
    FixtureDiscoveryProvider,
    ProviderMetadata,
    ProviderRegistry,
    UnconfiguredRealProvider,
)
from core.scout.url_safety import UrlPolicy, check_url

_DOCTYPE = "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
_VP = "<meta name='viewport' content='width=device-width, initial-scale=1'>"


def _page(title: str, desc: str, body: str, head_extra: str = "", viewport: bool = True) -> str:
    vp = _VP if viewport else ""
    return (f"{_DOCTYPE}{vp}<title>{title}</title>"
            f"<meta name='description' content='{desc}'>{head_extra}</head><body>{body}</body></html>")


_JSONLD = ("<script type='application/ld+json'>"
           "{\"@context\":\"https://schema.org\",\"@type\":\"Organization\",\"name\":\"Fixture\"}"
           "</script>")

# path -> (status, html). Business identity is encoded in the path; the fake host drives dedup.
FIXTURE_PAGES: Dict[str, Tuple[int, str]] = {
    "/saas/index.html": (200, _page(
        "Acme SaaS — Pricing & Plans", "SaaS with pricing, plans, free trial and demo.",
        "<header><nav><a href='/saas/pricing.html'>Pricing</a>"
        "<a href='/saas/signup.html'>Sign up</a><a href='/saas/demo.html'>Demo</a></nav></header>"
        "<main><h1>Acme SaaS</h1><h2>Plans</h2><h2>Pricing</h2>"
        "<p>Start your free trial. Subscribe to a plan. Get started with a demo.</p>"
        "<img src='/img/a.png' alt='logo'><img src='/img/b.png' alt='chart'>"
        "<form action='/saas/signup' method='post'><input name='email' aria-label='email'>"
        "<button type='submit'>Sign up</button></form>"
        "<form action='/saas/contact' method='post'><input name='msg' aria-label='msg'>"
        "<button type='submit'>Contact sales</button></form></main>", _JSONLD)),
    "/ecom/index.html": (200, _page(
        "ShopMart — Online Store", "Ecommerce store with cart, checkout and shop.",
        "<header><nav><a href='/ecom/cart.html'>Cart</a>"
        "<a href='/ecom/checkout.html'>Checkout</a><a href='/ecom/shop.html'>Shop</a></nav></header>"
        "<main><h1>ShopMart</h1><h2>Shop</h2><p>Add to cart and checkout. Buy now. Order today.</p>"
        "<img src='/img/p.png' alt='product'>"
        "<form action='/ecom/order' method='post'><input name='qty' aria-label='qty'>"
        "<button type='submit'>Buy now</button></form></main>", _JSONLD)),
    "/booking/index.html": (200, _page(
        "ClinicBook — Appointments", "Clinic booking site with appointments and reservations.",
        "<header><nav><a href='/booking/book.html'>Book</a>"
        "<a href='/booking/demo.html'>Demo</a></nav></header>"
        "<main><h1>ClinicBook</h1><h2>Booking</h2><p>Book an appointment. Reserve a demo.</p>"
        "<img src='/img/c.png' alt='clinic'>"
        "<form action='/booking/appt' method='post'><input name='name' aria-label='name'>"
        "<button type='submit'>Book appointment</button></form></main>", _JSONLD)),
    "/brand/index.html": (200, _page(
        "Jane Doe Studio — Services", "Personal brand studio offering services and contact.",
        "<main><h1>Jane Doe Studio</h1><h2>Services</h2><p>Get started. Contact for a quote.</p>"
        "<a href='/brand/contact.html'>Contact</a><a href='/brand/pricing.html'>Pricing</a>"
        "<img src='/img/j.png' alt='studio'>"
        "<form action='/brand/contact' method='post'><input name='email' aria-label='email'>"
        "<button type='submit'>Contact</button></form></main>")),
    "/globex/index.html": (200, _page(
        "Globex — Solutions", "Globex commercial solutions with pricing and contact.",
        "<main><h1>Globex</h1><h2>Pricing</h2><p>Subscribe to a plan. Contact sales. Get started.</p>"
        "<a href='/globex/pricing.html'>Pricing</a>"
        "<form action='/globex/contact' method='post'><input name='email' aria-label='email'>"
        "<button type='submit'>Contact sales</button></form></main>", _JSONLD)),
    "/parked/index.html": (200, _page(
        "This domain is for sale", "Parked domain.",
        "<main><h1>Domain for sale</h1><p>Buy this domain. Domain parking by Sedo.</p></main>")),
    "/hobby/index.html": (200, _page(
        "My Hobby Blog", "A personal hobby blog just for fun.",
        "<main><h1>My hobby blog</h1><p>This is my personal blog, just for fun. A hobby project."
        "</p></main>")),
}

# Fake public host -> local server (filled in per-run). Unmapped hosts are unreachable.
_MAPPED_HOSTS = [
    "acme-saas.example", "shopmart.example", "clinicbook.example", "janedoe.example",
    "globex-eu.example", "globex-us.example", "parkedbiz.example", "myhobby.example",
    "auslocal.example", "nsblocked.example", "nooutreach.example",
]


def build_host_map(base_host_port: str) -> Dict[str, str]:
    return {h: base_host_port for h in _MAPPED_HOSTS}


class HostMappedStaticBackend:
    """A StaticHttpBackend that validates the ORIGINAL (fake public) URL against the real policy
    but fetches from a mapped local server. Unmapped hosts return an unreachable observation.
    Used only by the bundled fixtures/E2E — never in production."""

    name = "static"

    def __init__(self, policy: UrlPolicy, host_map: Dict[str, str]) -> None:
        self.policy = policy
        self._host_map = dict(host_map)
        self._inner = StaticHttpBackend(
            policy=UrlPolicy(allowed_local_hosts=frozenset(host_map.values()), resolve_dns=False))

    def observe(self, url: str, timeout_s: float, max_bytes: int) -> PageObservation:
        elig = check_url(url, policy=self.policy)
        if not elig.eligible:
            obs = PageObservation(url=url, final_url=url)
            obs.fetch_error = f"blocked URL: {elig.reason}"
            return obs
        parts = urlsplit(url)
        mapped = self._host_map.get((parts.hostname or "").lower())
        if mapped is None:
            obs = PageObservation(url=url, final_url=url)
            obs.fetch_error = "host not reachable (unmapped/dead domain)"
            return obs
        local = urlunsplit((parts.scheme, mapped, parts.path or "/", parts.query, ""))
        obs = self._inner.observe(local, timeout_s, max_bytes)
        obs.url = url  # present the original public URL, not the mapped local one
        return obs


def _cand(provider_id: str, host: str, path: str, name: str, **hints) -> DiscoveryCandidate:
    return DiscoveryCandidate(provider_id=provider_id, raw_candidate_id=f"{host}{path}",
                              source_url=f"https://directory.example/{host}",
                              source_query="fixture", business_name=name,
                              website=f"http://{host}{path}", confidence="low", **hints)


def demo_candidates() -> List[DiscoveryCandidate]:
    d = "p_directory"
    m = "p_maplisting"
    return [
        # Active, promotable businesses.
        _cand(d, "acme-saas.example", "/saas/index.html", "Acme SaaS", country_hint="US",
              language_hint="en", business_type_hint="saas"),
        _cand(d, "shopmart.example", "/ecom/index.html", "ShopMart", country_hint="US",
              language_hint="en", business_type_hint="ecommerce"),
        _cand(d, "clinicbook.example", "/booking/index.html", "ClinicBook", country_hint="US",
              language_hint="en", business_type_hint="booking"),
        _cand(d, "janedoe.example", "/brand/index.html", "Jane Doe Studio", country_hint="US",
              language_hint="en", business_type_hint="personal_brand"),
        # Same-domain URL variant (deduped by domain; never fetched twice).
        _cand(d, "shopmart.example", "/ecom/deals.html", "ShopMart Deals", country_hint="US",
              language_hint="en"),
        # Cross-provider duplicate URL (same normalized URL from a second provider).
        _cand(m, "acme-saas.example", "/saas/index.html", "Acme SaaS (map)", country_hint="US",
              language_hint="en"),
        # Uncertain company identity: same name, different domain -> held for review.
        _cand(d, "globex-eu.example", "/globex/index.html", "Globex", country_hint="US",
              language_hint="en"),
        _cand(d, "globex-us.example", "/globex/index.html", "Globex", country_hint="US",
              language_hint="en"),
        # Parked / dead / hobby / unsupported.
        _cand(d, "parkedbiz.example", "/parked/index.html", "Parked Biz", country_hint="US",
              language_hint="en"),
        _cand(d, "deadgone.example", "/gone/index.html", "Dead Domain", country_hint="US",
              language_hint="en"),  # unmapped host -> unreachable
        _cand(d, "myhobby.example", "/hobby/index.html", "My Hobby Blog", country_hint="US",
              language_hint="en"),
        _cand(d, "auslocal.example", "/saas/index.html", "Aus Local", country_hint="AU",
              language_hint="en"),  # unsupported market vs a US campaign
        # Suppressed.
        _cand(d, "nsblocked.example", "/saas/index.html", "NoScan Co", country_hint="US",
              language_hint="en"),   # NO_SCAN -> never fetched
        _cand(d, "nooutreach.example", "/ecom/index.html", "NoOutreach Co", country_hint="US",
              language_hint="en"),   # NO_OUTREACH -> profiled read-only, never promoted/outreach
        # Malformed provider result (no website, no name) and a private URL.
        DiscoveryCandidate(provider_id=d, raw_candidate_id="malformed-1", source_query="fixture",
                           business_name="", website="", confidence="low"),
        DiscoveryCandidate(provider_id=d, raw_candidate_id="private-1", source_query="fixture",
                           business_name="Private Co", website="http://127.0.0.1/secret"),
    ]


def demo_suppression_policies() -> List[SuppressionPolicy]:
    return [
        SuppressionPolicy(enabled=True, mode="NO_SCAN", reason="fixture no-scan",
                          applies_to_domains=["nsblocked.example"]),
        SuppressionPolicy(enabled=True, mode="NO_OUTREACH", reason="fixture no-outreach",
                          applies_to_domains=["nooutreach.example"]),
    ]


def build_demo_registry() -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register(FixtureDiscoveryProvider(
        ProviderMetadata(provider_id="p_directory", provider_type="fixture",
                         display_name="Fixture Business Directory", trust_status="semi_trusted",
                         enabled=True, source_category="business_directory",
                         supported_markets=["US"], supported_languages=["en"],
                         query_capabilities=["country", "industry"], terms_review_status="reviewed_approved",
                         max_results_per_request=50, version="1.0.0"),
        demo_candidates()))
    reg.register(FixtureDiscoveryProvider(
        ProviderMetadata(provider_id="p_maplisting", provider_type="fixture",
                         display_name="Fixture Map Listings", trust_status="semi_trusted",
                         enabled=True, source_category="map_listing", supported_markets=["US"],
                         supported_languages=["en"], terms_review_status="reviewed_approved",
                         max_results_per_request=50, version="1.0.0"),
        demo_candidates()))
    # A terms-blocked provider that must never execute.
    reg.register(FixtureDiscoveryProvider(
        ProviderMetadata(provider_id="p_blocked", provider_type="fixture",
                         display_name="Terms-Blocked Source", trust_status="untrusted",
                         enabled=True, source_category="search_engine",
                         terms_review_status="reviewed_blocked", version="0.0.1"),
        [_cand("p_blocked", "acme-saas.example", "/saas/index.html", "Blocked Emit",
               country_hint="US", language_hint="en")]))
    # A real (api) provider adapter that is not configured -> reports readiness, never scrapes.
    reg.register(UnconfiguredRealProvider(
        ProviderMetadata(provider_id="p_real_api", provider_type="api",
                         display_name="Example Licensed API", trust_status="trusted",
                         enabled=True, source_category="business_directory",
                         auth_ref="EXAMPLE_API_KEY", terms_review_status="reviewed_approved",
                         public_or_licensed="licensed", cost_per_result_usd=0.01, version="2.0.0")))
    return reg


@contextmanager
def serve_discovery_site() -> Iterator[Tuple[str, str]]:
    """Yield (base_url, host:port) for the running local fixture site; shuts down on exit."""
    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            entry = FIXTURE_PAGES.get(path)
            if entry is None:
                body = _page("Not found", "404", "<h1>404</h1>").encode("utf-8")
                self.send_response(404)
            else:
                status, html = entry
                body = html.encode("utf-8")
                self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", "sid=discoverysecretcookie; Path=/")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_HEAD = do_GET

    server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", f"127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
