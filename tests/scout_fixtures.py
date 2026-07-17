"""Deterministic in-memory fixture sites for the Scout E2E (Phase 8.3).

Serves a fixed set of scenario pages over http://127.0.0.1:<ephemeral>/ so automated tests
never touch an external site and never need a real browser. The handler serves only known
in-memory paths (path-safe: no filesystem access, no traversal).

Scenarios: clean control, broken link, accessibility violations, missing/incorrect metadata,
malformed structured data, safe pre-submit validation defect, public business flow, simulated
CAPTCHA, explicit access prohibition, plus a redirect and a 404 target.
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

    "/captcha/index.html": (200, "text/html", _page(
        "<title>Protected Site</title>"
        "<meta name='description' content='Behind a CAPTCHA.'>",
        "<main><h1>Verify</h1><div class='g-recaptcha'>Please complete the reCAPTCHA to continue.</div>"
        "</main>")),

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
def serve_fixtures() -> Iterator[Tuple[str, str]]:
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
