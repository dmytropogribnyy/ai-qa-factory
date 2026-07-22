"""Phase 8.3.1 — REAL local Chromium acceptance for the Scout browser backend.

This is not a mock. It launches a real headless Chromium (via the optional ``playwright``
package) against an explicitly allow-listed LOCAL fixture server and proves the live path:
Chromium launches, the page renders, console errors and failed resources are captured, a
screenshot is written to a confined path, a CAPTCHA marker yields manual action with no
interaction, an internal subresource is blocked, no form is submitted, and the full
engine → verification → report pipeline completes with the real backend.

Skipped automatically unless playwright + Chromium are installed, so the ordinary suite stays
deterministic. Run explicitly with:

    .venv/Scripts/python.exe -m pytest -m playwright_acceptance -q
"""
from __future__ import annotations

import itertools
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from core.scout.backends import PlaywrightBackend  # noqa: E402
from core.scout.config import ScoutRunConfig  # noqa: E402
from core.scout.engine import ScoutEngine  # noqa: E402
from core.scout.report import build_report  # noqa: E402
from core.scout.store import RunStore  # noqa: E402
from core.scout.url_safety import UrlPolicy  # noqa: E402


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.playwright_acceptance,
    pytest.mark.skipif(not _chromium_available(),
                       reason="Chromium build not available (run: python -m playwright install chromium)"),
]

# A page that a REAL browser exercises: viewport, a console error, a failed same-origin
# resource, an internal cross-origin subresource (must be blocked), and a form (never submitted).
_OK = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>Live Fixture</title>"
    "<meta name='description' content='Real browser acceptance fixture.'>"
    "<link rel='canonical' href='/ok/index.html'></head><body>"
    "<main><h1>Live</h1>"
    "<img src='/missing.png' alt='will 404'>"                 # failed resource
    "<img src='http://10.0.0.5/evil.png' alt='internal'>"     # blocked subresource
    "<form method='post' action='/submit'>"
    "<input type='text' name='email' aria-label='email'><button type='submit'>Go</button></form>"
    "<script>console.error('scout-acceptance-console-error');</script>"
    "</main></body></html>"
)
_CAPTCHA = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>Protected</title></head><body>"
    "<main><h1>Verify</h1><div class='g-recaptcha'>Please complete the reCAPTCHA to continue.</div>"
    "</main></body></html>"
)
# A page with GUARANTEED axe violations (image without alt, input without a label) so the live axe
# run has something real to find.
_A11Y = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>A11y issues</title></head><body>"
    "<main><h1>Issues</h1><img src='/logo.png'>"
    "<form><input type='text' name='q'></form></main></body></html>"
)


def _make_handler(post_counter):
    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def _send(self, status, body):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/ok/index.html":
                return self._send(200, _OK)
            if path == "/captcha/index.html":
                return self._send(200, _CAPTCHA)
            if path == "/a11y/index.html":
                return self._send(200, _A11Y)
            return self._send(404, "<title>nope</title><h1>404</h1>")

        do_HEAD = do_GET

        def do_POST(self):  # must never be reached — the Scout never submits
            post_counter.append(self.path)
            self._send(200, "ok")

    return _H


@contextmanager
def _serve():
    posts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(posts))
    host, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", f"127.0.0.1:{port}", posts
    finally:
        server.shutdown()
        server.server_close()


def _policy(host):
    return UrlPolicy(allowed_local_hosts=frozenset({host}), resolve_dns=False)


def test_real_browser_backend_capabilities(tmp_path):
    with _serve() as (base, host, posts):
        shots = tmp_path / "shots"
        backend = PlaywrightBackend(policy=_policy(host), screenshot_dir=str(shots))
        obs = backend.observe(f"{base}/ok/index.html", 20, 3_000_000)

        assert obs.ok is True and obs.status == 200          # Chromium launched + rendered
        assert obs.has_viewport_meta is True
        assert any("scout-acceptance-console-error" in m for m in obs.console_errors)
        assert obs.failed_resources                          # /missing.png failed to load
        assert any("10.0.0.5" in b for b in obs.blocked_requests)  # internal subresource blocked
        assert obs.screenshot_ref == "page.png" and (shots / "page.png").exists()

        captcha = backend.observe(f"{base}/captcha/index.html", 20, 3_000_000)
        assert captcha.captcha_marker is True                # detected, never interacted with

        assert posts == []                                   # no form was ever submitted


def test_real_browser_records_and_omits_reproduction_video(tmp_path):
    """Live proof of the record step (slice D): a real Chromium context writes a genuine .webm when
    asked, and writes nothing when not asked. Qualify->keep/delete is proven deterministically in
    tests/test_scout_video_capture.py; this pins that the recording itself is real, not simulated."""
    with _serve() as (base, host, posts):
        pdir = tmp_path / "prospect"
        backend = PlaywrightBackend(policy=_policy(host), screenshot_dir=str(pdir))

        obs = backend.observe(f"{base}/ok/index.html", 20, 3_000_000, record_video=True)
        assert obs.ok is True
        assert obs.video_ref.startswith("_vidtmp") and obs.video_ref.endswith(".webm")
        clip = pdir / obs.video_ref
        assert clip.exists() and clip.stat().st_size > 0     # a real, non-empty recording on disk

        obs2 = backend.observe(f"{base}/ok/index.html", 20, 3_000_000, record_video=False)
        assert obs2.video_ref == ""                          # opt-out: nothing recorded
        assert posts == []                                   # still never submits a form


def test_real_browser_deep_qa_runs_axe_and_perf_without_network_fetch(tmp_path):
    """Live proof the operator deep-QA path is real: a real Chromium injects the PINNED LOCAL axe
    bundle (no CDN), runs axe against the DOM (finds the seeded image-alt violation), and captures
    real navigation timing — all on the already-open page."""
    with _serve() as (base, host, posts):
        backend = PlaywrightBackend(policy=_policy(host), screenshot_dir=str(tmp_path / "p"))
        obs = backend.observe(f"{base}/a11y/index.html", 20, 3_000_000, deep_qa=True)
        assert obs.ok is True
        assert obs.axe_status == "ok"                          # real axe-core ran to completion
        rules = {v["rule"] for v in obs.axe_violations}
        assert "image-alt" in rules                            # axe genuinely analyzed the rendered DOM
        assert obs.perf.get("loadEvent") is not None           # real navigation timing captured
        # axe came from the local bundle — no CDN/network fetch was made for it.
        assert not any("axe" in r.lower() or "cdn" in r.lower()
                       for r in obs.blocked_requests + obs.failed_resources)
        assert posts == []                                     # still never submits a form


def test_real_browser_engine_pipeline_and_report(tmp_path):
    _c = itertools.count()

    def _clock():
        return f"2026-07-17T05:00:{next(_c):02d}+00:00"

    with _serve() as (base, host, posts):
        cfg = ScoutRunConfig(campaign_name="pw-accept",
                             seeds=[f"{base}/ok/index.html", f"{base}/captcha/index.html"],
                             allowed_local_hosts=frozenset({host}), browser_mode="playwright",
                             resolve_dns=False, output_dir=str(tmp_path), run_id="pw-accept",
                             max_pages_per_site=3)
        store = RunStore(str(tmp_path), "pw-accept")
        state = ScoutEngine(cfg, store, clock=_clock).run()
        summary = build_report(store)

    assert state["status"] == "COMPLETED"
    prospects = state["prospects"]
    assert any(p["status"] == "MANUAL_ACTION_REQUIRED" and "captcha" in p["url"]
               for p in prospects.values())
    assert summary["verified_findings"] >= 1                 # real-browser findings verified
    report = json.loads((store.report_dir() / "REPORT.json").read_text(encoding="utf-8"))
    assert all(f["is_client_safe"] for f in report["verified_findings"])
    assert posts == []                                       # engine never submitted a form
