"""Bundled deterministic demo site for the Scout (Phase 8.3).

Serves a fixed set of scenario pages over http://127.0.0.1:<ephemeral>/ so automated tests
never touch an external site and never need a real browser. The handler serves only known
in-memory paths (path-safe: no filesystem access, no traversal).

Scenarios: clean control, broken link, accessibility violations, missing/incorrect metadata,
malformed structured data, safe pre-submit validation defect, public business flow, simulated
CAPTCHA, explicit access prohibition, the three filter-oracle shapes (Apply-gated group,
auto-applied all-matching, provably broken by the page's own facet count), plus a redirect and
a 404 target.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Iterator, Tuple

_DOCTYPE = "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
_VIEWPORT = "<meta name='viewport' content='width=device-width, initial-scale=1'>"


def _page(title_tag: str, body: str, head_extra: str = "", viewport: bool = True) -> str:
    vp = _VIEWPORT if viewport else ""
    return f"{_DOCTYPE}{vp}{title_tag}{head_extra}</head><body>{body}</body></html>"


# path -> (status, content_type, body)
FIXTURE_PAGES: Dict[str, Tuple[int, str, str]] = {
    "/clean/index.html": (200, "text/html", _page(
        "<title>Clean Clinic — Book a visit</title>"
        "<meta name='description' content='A clean control page with valid metadata.'>"
        "<link rel='canonical' href='/clean/index.html'>",
        "<header><nav><a href='/clean/index.html'>Home</a></nav></header>"
        "<main><h1>Clean Clinic</h1><h2>Services</h2>"
        "<img src='/img/logo.png' alt='Clean Clinic logo'>"
        "<a href='/clean/about.html'>About</a></main><footer>ok</footer>",
        "<script type='application/ld+json'>"
        "{\"@context\":\"https://schema.org\",\"@type\":\"MedicalClinic\",\"name\":\"Clean Clinic\"}"
        "</script>")),
    "/clean/about.html": (200, "text/html", _page(
        "<title>About — Clean Clinic</title>"
        "<meta name='description' content='About the clean clinic.'>",
        "<main><h1>About</h1><p>About us.</p></main>")),

    "/broken_link/index.html": (200, "text/html", _page(
        "<title>Broken Link Co</title>"
        "<meta name='description' content='Has a broken internal link.'>",
        "<main><h1>Broken Link Co</h1>"
        "<a href='/broken_link/missing.html'>Dead page</a>"
        "<a href='/clean/about.html'>Good page</a></main>")),

    "/accessibility/index.html": (200, "text/html", _page(
        "<title>Access Issues Ltd</title>"
        "<meta name='description' content='Accessibility violations present.'>",
        "<main><h1>Access Issues</h1>"
        "<img src='/img/x.png'>"                       # missing alt
        "<form method='get' action='/accessibility/search'>"
        "<input type='text' name='q'></form></main>")),  # unlabeled input

    "/seo/index.html": (200, "text/html", _page(
        "",                                            # missing <title>
        "<main><h1>SEO Gaps</h1><p>No title, no description, no canonical.</p></main>")),

    "/structured_data/index.html": (200, "text/html", _page(
        "<title>Structured Data Broken</title>"
        "<meta name='description' content='Malformed JSON-LD present.'>",
        "<main><h1>SD</h1></main>",
        "<script type='application/ld+json'>{ this is : not json, }</script>")),

    "/presubmit/index.html": (200, "text/html", _page(
        "<title>Newsletter Signup</title>"
        "<meta name='description' content='A signup form with no validation.'>",
        "<main><h1>Signup</h1>"
        "<form method='post' action='/presubmit/submit'>"          # no required, no email type
        "<input type='text' name='email' aria-label='email'>"
        "<button type='submit'>Join</button></form></main>")),

    "/mobile/index.html": (200, "text/html", _page(
        "<title>No Viewport Site</title>"
        "<meta name='description' content='Missing mobile viewport meta.'>",
        "<main><h1>Desktop only</h1></main>", viewport=False)),

    "/business_flow/index.html": (200, "text/html", _page(
        "<title>Booking Flow</title>"
        "<meta name='description' content='A public booking flow entry.'>",
        "<main><h1>Book</h1><a href='/business_flow/step2.html'>Start booking</a></main>")),
    "/business_flow/step2.html": (200, "text/html", _page(
        "<title>Booking — details</title>"
        "<meta name='description' content='Booking details form.'>",
        "<main><h1>Your details</h1>"
        "<form method='post' action='/business_flow/confirm'>"
        "<input type='text' name='name' required aria-label='name'>"
        "<button type='submit'>Confirm booking</button></form></main>")),

    # A site whose primary conversion flow is genuinely dead: the "Book now" entry 404s. This is the
    # one shape that earns a reproduction video -- an action that really misbehaves, not a page that
    # merely loads.
    "/broken_flow/index.html": (200, "text/html", _page(
        "<title>Salon Nova — Book an appointment</title>"
        "<meta name='description' content='Book a visit with Salon Nova online.'>",
        "<header><nav><a href='/broken_flow/index.html'>Home</a>"
        "<a href='/clean/about.html'>About</a></nav></header>"
        "<main><h1>Salon Nova</h1><h2>Appointments</h2>"
        "<p>Choose a time that suits you and book it online in under a minute.</p>"
        "<a href='/broken_flow/booking.html'>Book now</a>"
        "<img src='/img/salon.png' alt='Salon Nova interior'></main><footer>Salon Nova</footer>")),

    "/captcha/index.html": (200, "text/html", _page(
        "<title>Protected Site</title>"
        "<meta name='description' content='Behind a CAPTCHA.'>",
        "<main><h1>Verify</h1><div class='g-recaptcha'>Please complete the reCAPTCHA to continue.</div>"
        "</main>")),

    # A real, fully served site whose OWN signup form carries an anti-spam widget. The site never
    # challenged us: it answered 200 with its complete content. Only the widget markup and an i18n
    # string mention a human check. This is the shape of most B2B SaaS landing pages.
    "/own_widget/index.html": (200, "text/html", _page(
        "<title>Booking Suite — Online booking for your business</title>"
        "<meta name='description' content='Let clients book appointments online 24/7.'>",
        "<header><nav>"
        "<a href='/own_widget/index.html'>Home</a>"
        "<a href='/clean/index.html'>Customers</a>"
        "<a href='/clean/about.html'>About</a>"
        "</nav>"
        "<form method='post' action='/own_widget/index.html'>"
        "<input type='email' name='email' aria-label='email'>"
        "<div class='cf-turnstile' data-sitekey='0x4AAAAAAADEMOKEY' data-size='compact'></div>"
        "<button type='submit'>Free sign up</button></form></header>"
        "<main><h1>Booking Suite</h1>"
        "<h2>Features</h2><p>Calendar, SMS reminders and client management in one app.</p>"
        "<h2>Pricing</h2><p>Start free, no credit card needed.</p>"
        "<img src='/img/hero.png' alt='Booking dashboard on a laptop'></main>"
        "<footer>Booking Suite</footer>"
        "<script>window.__I18N__={\"registerError\":\"Could not create account\","
        "\"captchaRequired\":\"Please verify that you are not a robot\"}</script>")),

    # A genuine interstitial that keeps the site's chrome around it. Density alone cannot tell this
    # apart from a thin real page; the title and the standalone widget can.
    "/challenge_with_nav/index.html": (200, "text/html", _page(
        "<title>Just a moment...</title>",
        "<header><nav>"
        "<a href='/clean/index.html'>Home</a>"
        "<a href='/clean/about.html'>About</a>"
        "<a href='/own_widget/index.html'>Contact</a>"
        "</nav></header>"
        "<main><h1>Checking your browser before you continue</h1>"
        "<div class='cf-turnstile' data-sitekey='0x4AAAAAAAGATE'></div></main>"
        "<footer>Protected by a verification service</footer>")),

    # --- filter-oracle fixtures: the three shapes that decide what a filter clip may claim -------
    # 1. The commonest filter on the web: a facet group with its own Apply button. Ticking a box
    #    is SUPPOSED to change nothing until the button is pressed — zero findings here, ever.
    "/filter_apply/index.html": (200, "text/html", _page(
        "<title>Mug Shop — Catalogue</title>"
        "<meta name='description' content='Mugs by colour, filtered with an Apply button.'>",
        "<main><h1>Mug Shop</h1><p>6 results</p>"
        "<fieldset class='filters'><legend>Colour</legend>"
        "<label><input type='checkbox'> Blue (2)</label>"
        "<label><input type='checkbox'> Red (3)</label>"
        "<label><input type='checkbox'> Green (1)</label>"
        "<button type='button'>Apply filters</button></fieldset>"
        "<ul class='grid'>"
        "<li class='item'>Blue mug — classic</li><li class='item'>Blue mug — large</li>"
        "<li class='item'>Red mug — classic</li><li class='item'>Red mug — matte</li>"
        "<li class='item'>Red mug — mini</li><li class='item'>Green mug — forest</li>"
        "</ul></main>")),

    # 2. An auto-applied filter that legitimately changes nothing: everything listed IS in stock.
    #    The URL moves (the site's own "applied" signal) and no facet count exists, so there is no
    #    machine-checkable witness of a non-matching item — nothing may be claimed.
    "/filter_all_match/index.html": (200, "text/html", _page(
        "<title>Mug Shop — In stock</title>"
        "<meta name='description' content='Every mug listed ships today.'>",
        "<main><h1>Mug Shop</h1><p>6 results</p>"
        "<div class='filters'>"
        "<label><input type='checkbox' class='auto'> In stock</label>"
        "<label><input type='checkbox' class='auto'> Ships from EU</label>"
        "</div>"
        "<ul class='grid'>"
        "<li class='item'>Blue mug — classic</li><li class='item'>Blue mug — large</li>"
        "<li class='item'>Red mug — classic</li><li class='item'>Red mug — matte</li>"
        "<li class='item'>Red mug — mini</li><li class='item'>Green mug — forest</li>"
        "</ul></main>"
        "<script>document.querySelectorAll('input.auto').forEach(function(b){"
        "b.addEventListener('change',function(){"
        "var any=Array.prototype.some.call(document.querySelectorAll('input.auto'),"
        "function(x){return x.checked});"
        "history.pushState({},'',location.pathname+(any?'?instock=1':''));});});</script>")),

    # 3. The defect shape, provable from the page's own numbers: the facet label promises 2
    #    matching mugs, the URL confirms the filter applied, and all 6 results stay listed — at
    #    least 4 listed results cannot match, by the site's own arithmetic. Un-ticking restores
    #    the URL, so cleanup and a second identical pass are both verifiable.
    "/filter_broken/index.html": (200, "text/html", _page(
        "<title>Mug Shop — Colour filter</title>"
        "<meta name='description' content='A colour filter that filters nothing.'>",
        "<main><h1>Mug Shop</h1><p>6 results</p>"
        "<div class='filters'>"
        "<label><input type='checkbox' class='auto'> Blue (2)</label>"
        "<label><input type='checkbox' class='auto'> Red (4)</label>"
        "</div>"
        "<ul class='grid'>"
        "<li class='item'>Blue mug — classic</li><li class='item'>Blue mug — large</li>"
        "<li class='item'>Red mug — classic</li><li class='item'>Red mug — matte</li>"
        "<li class='item'>Red mug — mini</li><li class='item'>Green mug — forest</li>"
        "</ul></main>"
        "<script>document.querySelectorAll('input.auto').forEach(function(b){"
        "b.addEventListener('change',function(){"
        "var any=Array.prototype.some.call(document.querySelectorAll('input.auto'),"
        "function(x){return x.checked});"
        "history.pushState({},'',location.pathname+(any?'?colour=blue':''));});});</script>")),

    "/access_prohibition/index.html": (403, "text/html", _page(
        "<title>Access Denied</title>",
        "<main><h1>403 Forbidden</h1><p>Access denied. Please log in to continue.</p></main>")),

    "/redirect/start.html": (301, "text/html", ""),   # redirects (Location set by handler)
}

# Explicit redirect map (path -> location).
_REDIRECTS = {"/redirect/start.html": "/clean/index.html"}


def make_handler():
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            return

        def _send(self, status: int, ctype: str, body: str, location: str = ""):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            # Deliberately include a sensitive header to prove sanitization drops it.
            self.send_header("Set-Cookie", "session=secretcookievalue; Path=/")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0].split("#", 1)[0]
            if path in _REDIRECTS:
                self._send(301, "text/html", "", location=_REDIRECTS[path])
                return
            entry = FIXTURE_PAGES.get(path)
            if entry is None:
                self._send(404, "text/html", _page("<title>Not found</title>", "<h1>404</h1>"))
                return
            status, ctype, body = entry
            self._send(status, ctype, body)

        do_HEAD = do_GET

    return _Handler


@contextmanager
def serve_demo_site() -> Iterator[Tuple[str, str]]:
    """Yield (base_url, allowed_host) for the running fixture server; shuts down on exit."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler())
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    allowed_host = f"127.0.0.1:{port}"
    try:
        yield base_url, allowed_host
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
