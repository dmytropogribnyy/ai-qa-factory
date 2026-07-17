"""Phase 8.3.1 — adversarial PlaywrightBackend URL-safety (deterministic; no real browser).

Drives the full observe() flow through a controlled fake Playwright factory to prove SSRF
hardening: private redirects, private subresources, credentialed/unsupported navigation,
unsafe final URLs, oversized documents, event bounding, screenshot path safety, and browser
cleanup on error. The live browser is exercised separately in the marked acceptance test.
"""
from __future__ import annotations

import types

from core.scout.backends import PlaywrightBackend
from core.scout.url_safety import UrlPolicy

_POLICY = UrlPolicy(resolve_dns=False)  # offline: named hosts pass without a real DNS lookup


class _FakeRoute:
    def __init__(self, url):
        self.request = types.SimpleNamespace(url=url)
        self.action = None

    def continue_(self):
        self.action = "continue"

    def abort(self):
        self.action = "abort"


class _FakePage:
    def __init__(self, *, final_url, content="<html><head><title>Doc</title></head><body></body></html>",
                 status=200, headers=None, subresources=(), console=(), failed=(),
                 goto_raises=False, response=True):
        self._final_url = final_url
        self._content = content
        self._status = status
        self._headers = headers or {"content-type": "text/html"}
        self._subresources = list(subresources)
        self._console = list(console)
        self._failed = list(failed)
        self._goto_raises = goto_raises
        self._response = response
        self._routes = []
        self._listeners = {}
        self.routes_seen = []
        self.screenshotted = None

    @property
    def url(self):
        return self._final_url

    def on(self, event, cb):
        self._listeners.setdefault(event, []).append(cb)

    def route(self, pattern, handler):
        self._handler = handler

    def goto(self, url, wait_until=None, timeout=None):
        if self._goto_raises:
            raise RuntimeError("navigation crashed")
        for u in self._subresources:               # simulate subresource loads
            r = _FakeRoute(u)
            self._handler(r)
            self.routes_seen.append((u, r.action))
        for m in self._console:
            for cb in self._listeners.get("console", []):
                cb(m)
        for u in self._failed:
            for cb in self._listeners.get("requestfailed", []):
                cb(types.SimpleNamespace(url=u))
        if not self._response:
            return None
        return types.SimpleNamespace(status=self._status, headers=self._headers)

    def content(self):
        return self._content

    def screenshot(self, path=None):
        self.screenshotted = path


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, context):
        self._context = context
        self.closed = False

    def new_context(self):
        return self._context

    def close(self):
        self.closed = True


class _FakeFactory:
    def __init__(self, page):
        self.context = _FakeContext(page)
        self.browser = _FakeBrowser(self.context)
        self.p = types.SimpleNamespace(chromium=types.SimpleNamespace(
            launch=lambda headless=True: self.browser))

    def __call__(self):
        return self

    def __enter__(self):
        return self.p

    def __exit__(self, *a):
        return False


def _backend(page, **kw):
    return PlaywrightBackend(policy=_POLICY, _playwright_factory=_FakeFactory(page), **kw)


def test_private_redirect_final_url_blocked():
    page = _FakePage(final_url="http://10.0.0.5/internal")
    obs = _backend(page).observe("https://example.com/", 5, 1_000_000)
    assert obs.ok is False
    assert "final URL blocked" in obs.fetch_error
    assert obs.title == ""  # unsafe destination content is never parsed


def test_private_subresource_aborted_safe_continues():
    page = _FakePage(final_url="https://example.com/",
                     subresources=["https://example.com/app.js", "http://127.0.0.1/secret",
                                   "http://169.254.169.254/latest/meta-data"])
    obs = _backend(page).observe("https://example.com/", 5, 1_000_000)
    actions = dict(page.routes_seen)
    assert actions["https://example.com/app.js"] == "continue"
    assert actions["http://127.0.0.1/secret"] == "abort"
    assert actions["http://169.254.169.254/latest/meta-data"] == "abort"
    assert "http://127.0.0.1/secret" in obs.blocked_requests
    assert "http://169.254.169.254/latest/meta-data" in obs.blocked_requests
    assert obs.ok is True


def test_credentialed_navigation_blocked_before_launch():
    factory = _FakeFactory(_FakePage(final_url="https://example.com/"))
    obs = PlaywrightBackend(policy=_POLICY, _playwright_factory=factory).observe(
        "https://user:pass@example.com/", 5, 1_000_000)
    assert obs.ok is False and "blocked URL" in obs.fetch_error
    assert factory.browser.closed is False  # never launched a browser


def test_unsupported_scheme_blocked():
    obs = _backend(_FakePage(final_url="ftp://example.com/")).observe("ftp://example.com/", 5, 10_000)
    assert obs.ok is False and "blocked URL" in obs.fetch_error


def test_oversized_document_truncated():
    big = "<html><body>" + ("x" * 50_000) + "</body></html>"
    page = _FakePage(final_url="https://example.com/", content=big)
    obs = _backend(page).observe("https://example.com/", 5, 500)
    assert obs.truncated is True and obs.html_bytes == 500


def test_browser_exception_records_error_and_closes():
    factory = _FakeFactory(_FakePage(final_url="https://example.com/", goto_raises=True))
    obs = PlaywrightBackend(policy=_POLICY, _playwright_factory=factory).observe(
        "https://example.com/", 5, 1_000_000)
    assert obs.ok is False and "browser error" in obs.fetch_error
    assert factory.context.closed is True and factory.browser.closed is True


def test_event_arrays_are_bounded():
    page = _FakePage(final_url="https://example.com/",
                     console=[types.SimpleNamespace(type="error", text=f"e{i}") for i in range(300)],
                     failed=[f"https://example.com/x{i}.png" for i in range(300)])
    obs = _backend(page).observe("https://example.com/", 5, 1_000_000)
    assert len(obs.console_errors) == 200 and len(obs.failed_resources) == 200


def test_screenshot_ref_is_basename_only(tmp_path):
    page = _FakePage(final_url="https://example.com/")
    shot_dir = tmp_path / "shots"
    obs = _backend(page, screenshot_dir=str(shot_dir)).observe("https://example.com/", 5, 1_000_000)
    assert obs.screenshot_ref == "page.png"          # never an absolute path
    assert page.screenshotted.endswith("page.png")   # actually written into the confined dir
