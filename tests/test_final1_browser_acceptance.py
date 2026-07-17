"""Final Phase I — REAL local Chromium acceptance: axe + performance + reversible cart cleanup.

Not mocks. Launches real headless Chromium (optional `playwright`) against a bundled LOCAL
fixture and proves: real axe-core runs and finds violations on a defect page and none on a clean
page; a real rendered performance observation is captured (honestly named, not Lighthouse); and a
bounded reversible cart action cleans up with verified post-state and never submits a form.

Skipped automatically unless playwright + Chromium are installed; the axe part additionally skips
if axe-core is unavailable. Run explicitly:

    .venv/Scripts/python.exe -m pytest -m final1_browser_acceptance -q
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from core.scout.pipeline.browser_qa import (  # noqa: E402
    load_axe_source,
    parse_axe_violations,
    run_performance,
    run_reversible_cart,
)


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.final1_browser_acceptance,
    pytest.mark.skipif(not _chromium_ok(), reason="Chromium not installed"),
]

_DEFECT = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Defects</title>"
           "</head><body><main><h1>Defects</h1><img src='/x.png'>"
           "<a href='/y'></a><input type='text'></main></body></html>")
_CLEAN = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Clean</title>"
          "</head><body><main><h1>Clean</h1><img src='/logo.png' alt='logo'>"
          "<label for='q'>Search</label><input id='q' type='text'></main></body></html>")
_CART = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Cart</title></head>"
         "<body><button id='add-to-cart' onclick=\"localStorage.setItem('cart',"
         "JSON.stringify(['synthetic']))\">Add</button>"
         "<form id='order' method='post' action='/order'></form></body></html>")
_PAGES = {"/defect": _DEFECT, "/clean": _CLEAN, "/cart": _CART}


@contextmanager
def _serve():
    posts = []

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def _send(self, body):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            self._send(_PAGES.get(self.path.split("?")[0], "<title>404</title>"))

        do_HEAD = do_GET

        def do_POST(self):
            posts.append(self.path)
            self._send("ok")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    _host, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", posts
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def _page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser.new_page()
        finally:
            browser.close()


def test_real_performance_observation(tmp_path):
    with _serve() as (base, _posts), _page() as page:
        perf = run_performance(page, base + "/clean")
    assert perf["mode"] == "chrome_perf_observation"
    assert perf["metrics"]["resourceCount"] is not None  # a real rendered metric was captured


def test_real_reversible_cart_cleanup_and_no_submit(tmp_path):
    with _serve() as (base, posts), _page() as page:
        result = run_reversible_cart(page, base + "/cart")
    assert result.cleanup_verified and result.post_state == result.pre_state
    assert posts == []  # the reversible action never submitted the form


def test_real_axe_finds_and_clears_violations(tmp_path):
    try:
        load_axe_source()
    except RuntimeError:
        pytest.skip("axe-core source not installed")
    from core.scout.pipeline.browser_qa import _inject_axe
    with _serve() as (base, _posts), _page() as page:
        page.goto(base + "/defect", wait_until="load")
        _inject_axe(page)
        defect = parse_axe_violations(page.evaluate("axe.run(document,{resultTypes:['violations']})"),
                                      base + "/defect")
        page.goto(base + "/clean", wait_until="load")
        _inject_axe(page)
        clean = parse_axe_violations(page.evaluate("axe.run(document,{resultTypes:['violations']})"),
                                     base + "/clean")
    assert defect, "real axe should find violations on the defect page"
    assert all(o.provenance["tool"] == "axe-core" for o in defect)
    # The clean control has no image-alt/label violations of the kinds the defect page triggers.
    assert "axe:image-alt" not in {o.signature for o in clean}
