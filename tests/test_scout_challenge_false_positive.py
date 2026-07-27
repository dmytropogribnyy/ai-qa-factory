"""A site's own anti-spam widget is not a challenge against us.

bookoo.eu answered 200 with its complete landing page (278 KB, real title, axe-core ran clean) and
was still abandoned as "The site requested a human verification check". The marker test was a plain
substring search over the whole HTML, so the site's own Cloudflare Turnstile widget on its signup
form -- and an i18n string "captchaRequired" inside a hydration script -- both matched. The operator
was then offered an "Open manual check" action with nothing to solve. Most B2B SaaS landing pages
carry such a widget, so the naive test silently dropped much of Scout's own target population.

These tests pin the only distinction that matters: did the site refuse to serve its content, or did
it serve the content with an anti-spam widget on its own form? They also pin that low content
density on its own never blocks anything, and that a challenge which keeps the site's navigation
around it is still recognised.
"""
from __future__ import annotations

import itertools

from core.scout.backends import PageObservation, _parse_html
from core.scout.challenge_detect import (CH_BLOCKING, CH_EMBEDDED, CH_NONE, CONF_CONFIRMED,
                                         CONF_SUSPECTED, R_ACCESS, R_CAPTCHA, classify)
from core.scout.config import ScoutRunConfig
from core.scout.dashboard import start_dashboard
from core.scout.engine import P_DONE, P_MANUAL, ScoutEngine
from core.scout.service import ScoutService
from core.scout.store import RunStore
from tests.scout_fixtures import serve_fixtures
from tests.scout_seam_fixtures import get, no_tavily

_counter = itertools.count()


def _clock():
    return f"2026-07-27T00:00:{next(_counter):02d}+00:00"


def _run(tmp_path, base, host, path, run_id):
    cfg = ScoutRunConfig(campaign_name="challenge", seeds=[f"{base}{path}"],
                         allowed_local_hosts=frozenset({host}), browser_mode="static",
                         output_dir=str(tmp_path), max_pages_per_site=6)
    state = ScoutEngine(cfg, RunStore(str(tmp_path), run_id), clock=_clock).run()
    return state["prospects"][next(iter(state["prospects"]))]


def _observe(html: str, status: int = 200) -> PageObservation:
    obs = PageObservation(url="https://site.example/")
    obs.status = status
    obs.ok = status == 200
    _parse_html("https://site.example/", html, obs)
    return obs


_REAL_PAGE_BODY = (
    "<header><nav><a href='/features'>Features</a><a href='/pricing'>Pricing</a>"
    "<a href='/faq'>FAQ</a></nav></header>"
    "<main><h1>Booking Suite</h1><h2>Features</h2>"
    "<p>Let clients book appointments online around the clock, with reminders and a calendar.</p>"
    "<h2>Pricing</h2><p>Start free. No credit card needed. Cancel at any time.</p></main>"
)


# --- 1. a localisation bundle is data, not page content -------------------------------------

def test_localisation_json_mentioning_captcha_does_not_block():
    html = ("<html><head><title>Booking Suite</title></head><body>" + _REAL_PAGE_BODY +
            '<script>window.__I18N__={"captchaRequired":"Please verify that you are not a robot",'
            '"captchaError":"Verification failed."}</script></body></html>')
    obs = _observe(html)

    assert obs.challenge_kind == CH_NONE
    assert obs.captcha_marker is False
    assert obs.captcha_widget_present is False


def test_hydration_script_text_is_not_read_as_visible_content():
    """The exclusion above must come from the parser, not from luck in the phrase list."""
    html = ("<html><head><title>Shop</title></head><body><main><h1>Shop</h1></main>"
            '<script>var t = "please complete the captcha to continue";</script>'
            "<style>.captcha { display: none }</style>"
            "<template><div>i'm not a robot</div></template></body></html>")
    obs = _observe(html)

    assert obs.challenge_kind == CH_NONE, obs.challenge_signal
    assert obs.captcha_marker is False


# --- 2 & 3. the site's own widget on the site's own form ------------------------------------

def test_turnstile_inside_a_signup_form_is_embedded_not_blocking():
    html = ("<html><head><title>Booking Suite</title></head><body>"
            "<form action='/signup'><input type='email' name='email' aria-label='email'>"
            "<div class='cf-turnstile' data-sitekey='0xABC'></div>"
            "<button type='submit'>Free sign up</button></form>" + _REAL_PAGE_BODY +
            "</body></html>")
    obs = _observe(html)

    assert obs.challenge_kind == CH_EMBEDDED
    assert obs.captcha_marker is False
    assert obs.captcha_widget_present is True          # recorded honestly, just not as a blocker


def test_recaptcha_and_hcaptcha_in_a_form_are_embedded_too():
    for widget in ("<div class='g-recaptcha' data-sitekey='6LcABC'></div>",
                   "<div class='h-captcha' data-sitekey='abc-123'></div>"):
        html = ("<html><head><title>Booking Suite</title></head><body>"
                f"<form action='/contact'><input name='msg' aria-label='msg'>{widget}"
                "<button type='submit'>Send</button></form>" + _REAL_PAGE_BODY + "</body></html>")
        obs = _observe(html)

        assert obs.challenge_kind == CH_EMBEDDED, widget
        assert obs.captcha_marker is False, widget


def test_widget_outside_a_form_on_a_served_page_is_still_not_a_block():
    """Plenty of real sites mount the widget with JS and never wrap it in a <form> element."""
    html = ("<html><head><title>Booking Suite</title></head><body>" + _REAL_PAGE_BODY +
            "<div class='cf-turnstile' data-sitekey='0xABC'></div></body></html>")
    obs = _observe(html)

    assert obs.challenge_kind == CH_EMBEDDED
    assert obs.captcha_marker is False


# --- 4, 5, 7. a challenge that stands between us and the content ----------------------------

def test_full_page_captcha_with_http_200_blocks():
    html = ("<html><head><title>Verify</title></head><body><main><h1>Verify you are human</h1>"
            "<div class='g-recaptcha'></div></main></body></html>")
    obs = _observe(html)

    assert obs.challenge_kind == CH_BLOCKING
    assert obs.challenge_confidence == CONF_CONFIRMED
    assert obs.captcha_marker is True


def test_blocking_http_status_with_a_challenge_signal_blocks():
    for status in (403, 429, 503):
        verdict = classify(status=status, title="Attention Required",
                           visible_text="Please complete the security check to continue.",
                           widgets=[{"kind": "turnstile", "in_form": False}])
        assert verdict.kind == CH_BLOCKING, status
        assert verdict.confidence == CONF_CONFIRMED, status
        assert str(status) in verdict.signal, status


def test_access_prohibition_is_reported_as_prohibition_not_as_a_human_check():
    verdict = classify(status=403, title="Access Denied",
                       visible_text="403 Forbidden. Access denied. Please log in to continue.")
    assert verdict.kind == CH_BLOCKING
    assert verdict.reason == R_ACCESS


def test_challenge_keeping_the_site_navigation_is_still_blocking():
    """Density is not the signal: this page has a nav, links and a footer, and is still a wall."""
    html = ("<html><head><title>Just a moment...</title></head><body>"
            "<header><nav><a href='/a'>Home</a><a href='/b'>About</a><a href='/c'>Contact</a>"
            "</nav></header><main><h1>Checking your browser before you continue</h1>"
            "<div class='cf-turnstile'></div></main><footer>Protected</footer></body></html>")
    obs = _observe(html)

    assert obs.challenge_kind == CH_BLOCKING
    assert obs.challenge_confidence == CONF_CONFIRMED
    assert obs.captcha_marker is True
    assert "just a moment" in obs.challenge_signal.lower()


# --- 6. a small honest page is never blocked for being small --------------------------------

def test_a_tiny_legitimate_page_is_not_blocked_for_low_density():
    html = ("<html><head><title>Anna's Studio</title></head><body><main><h1>Anna's Studio</h1>"
            "<p>Call 555-0100 to book.</p></main></body></html>")
    obs = _observe(html)

    assert obs.challenge_kind == CH_NONE
    assert obs.captcha_marker is False
    assert obs.access_blocked_marker is False


def test_ambiguous_low_content_challenge_wording_fails_closed_but_says_so():
    verdict = classify(status=200, title="Please wait",
                       visible_text="Complete the security check to continue.")
    assert verdict.kind == CH_BLOCKING
    assert verdict.confidence == CONF_SUSPECTED       # fail closed, but do not claim proof
    assert verdict.reason == R_CAPTCHA


# --- 8 & 9. the whole engine, and the operator path it feeds --------------------------------

def test_site_serving_its_content_with_an_own_widget_is_analyzed(tmp_path):
    """The bookoo.eu shape: 200 + full content + the site's own Turnstile + a hydration marker."""
    with serve_fixtures() as (base, host):
        prospect = _run(tmp_path, base, host, "/own_widget/index.html", "run-own-widget")

    assert prospect["status"] == P_DONE, (
        f"a fully served page was abandoned as {prospect['status']} / "
        f"{prospect.get('reason')!r} -- the site never challenged us")
    assert prospect.get("analysis_complete") is not False


def test_real_challenge_interstitial_still_stops_the_target(tmp_path):
    """Safety guard: a page that replaces the site with a challenge is still manual-action."""
    with serve_fixtures() as (base, host):
        prospect = _run(tmp_path, base, host, "/captcha/index.html", "run-real-captcha")

    assert prospect["status"] == P_MANUAL
    assert prospect["reason"] == "captcha_detected"


def test_challenge_with_navigation_still_stops_the_target(tmp_path):
    with serve_fixtures() as (base, host):
        prospect = _run(tmp_path, base, host, "/challenge_with_nav/index.html", "run-nav-captcha")

    assert prospect["status"] == P_MANUAL
    assert prospect["reason"] == "captcha_detected"


def test_engine_persists_the_evidence_behind_a_manual_action(tmp_path):
    """The operator surface can only hedge honestly if the engine writes down what it saw."""
    with serve_fixtures() as (base, host):
        cfg = ScoutRunConfig(campaign_name="challenge", seeds=[f"{base}/captcha/index.html"],
                             allowed_local_hosts=frozenset({host}), browser_mode="static",
                             output_dir=str(tmp_path), max_pages_per_site=6)
        store = RunStore(str(tmp_path), "run-evidence")
        state = ScoutEngine(cfg, store, clock=_clock).run()
        pid = next(iter(state["prospects"]))
        record = store.load_prospect_artifact(pid, "manual_action.json")

    assert record["challenge_confidence"] == CONF_CONFIRMED
    assert record["challenge_signal"]


# --- the operator wording follows the evidence ----------------------------------------------

_RUN = "wording-run"


def _wording_stand(out: str) -> None:
    store = RunStore(out, _RUN)
    store.save_prospect_artifact("01-proven", "manual_action.json", {
        "reason": "captcha_detected", "stage": "post_landing_precheck",
        "stop_boundary": "stopped_before_interaction", "chromium_started": True,
        "landing_loaded": True, "analysis_complete": False,
        "challenge_confidence": CONF_CONFIRMED,
        "challenge_signal": 'page title "Just a moment..."',
        "recommended_action": "Solve it yourself, then rescan."})
    store.save_prospect_artifact("02-guessed", "manual_action.json", {
        "reason": "captcha_detected", "stage": "post_landing_precheck",
        "stop_boundary": "stopped_before_interaction", "chromium_started": True,
        "landing_loaded": True, "analysis_complete": False,
        "challenge_confidence": CONF_SUSPECTED,
        "challenge_signal": '"security check" appears on a page with no readable content',
        "recommended_action": "Open it yourself, then rescan."})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-proven": {"status": "MANUAL_ACTION_REQUIRED", "url": "https://proven.example/",
                      "reason": "captcha_detected", "analysis_complete": False},
        "02-guessed": {"status": "MANUAL_ACTION_REQUIRED", "url": "https://guessed.example/",
                       "reason": "captcha_detected", "analysis_complete": False}}})


def test_proven_challenge_may_be_stated_as_fact_and_names_its_evidence(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    _wording_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = get(f"{url}/scout/target?run={_RUN}&domain=proven.example")[1]
    finally:
        server.shutdown()

    assert "The site requested a human verification check." in html
    assert "Just a moment" in html                     # the evidence is shown, not just the verdict


def test_suspected_challenge_is_not_stated_as_fact(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    _wording_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = get(f"{url}/scout/target?run={_RUN}&domain=guessed.example")[1]
    finally:
        server.shutdown()

    assert "may have prevented analysis" in html
    assert "The site requested a human verification check." not in html
    assert "no readable content" in html               # the operator can judge the signal itself
