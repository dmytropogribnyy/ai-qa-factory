"""Scout — an incomplete target must be described by what actually happened to it.

The incomplete screen was written for a challenge (CAPTCHA / blocked access) and offers to open a
manual check. A PENDING target was interrupted and a SKIPPED target was skipped: neither was blocked,
and neither has a challenge session to open. Saying otherwise is a false story about the run.

The badge, the page title and the "Needs attention" chip must agree with that same story: only a
real challenge (MANUAL_ACTION_REQUIRED, or a persisted reason) ever reaches /scout/attention — its
list is filtered by status in core/scout/challenge_session.py's `_blocked_targets` — so promising that
destination for a PENDING, SKIPPED, or otherwise-failed target is a dead-end the operator can never
resolve.
"""
from __future__ import annotations

import pytest

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from tests.scout_seam_fixtures import RUN_A, build_seam_stand, get, no_tavily


def _card(url: str, domain: str) -> str:
    return get(f"{url}/scout/target?run={RUN_A}&domain={domain}")[1]


def test_challenge_target_keeps_its_challenge_story(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _card(url, "beta.example")
    finally:
        server.shutdown()

    assert "human verification check" in html          # the persisted reason, unchanged
    assert "Open manual check" in html                 # the action is real for this target
    assert "0 confirmed findings" in html
    assert "Needs your help" in html                                # badge: a real challenge
    assert '<title>AI QA Factory — Needs attention</title>' in html  # page title matches
    assert 'href="/scout/attention"' in html                        # the chip is a real path


def test_interrupted_target_is_not_described_as_blocked(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _card(url, "delta.example")
    finally:
        server.shutdown()

    assert "0 confirmed findings" in html                                  # still fail-closed
    assert "could not complete this target automatically" not in html      # it was never blocked
    assert "Open manual check" not in html                                 # no challenge to open
    assert "did not finish" in html
    assert "Needs your help" not in html                            # not a challenge target
    assert "Not analyzed" in html                                   # badge matches the real status
    assert '<title>AI QA Factory — Not analyzed</title>' in html
    assert 'href="/scout/attention"' not in html                    # never listed there — no dead end


def test_skipped_target_says_it_was_skipped(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _card(url, "eta.example")
    finally:
        server.shutdown()

    assert "was skipped" in html
    assert "Open manual check" not in html
    assert "Needs your help" not in html
    assert "Skipped" in html
    assert '<title>AI QA Factory — Skipped</title>' in html
    assert 'href="/scout/attention"' not in html


def test_failed_target_says_it_could_not_complete(tmp_path, monkeypatch):
    """gamma is FAILED with no manual_action.json record at all: interrupted, never blocked, and it
    can never appear on /scout/attention (that list is filtered to MANUAL_ACTION_REQUIRED only)."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _card(url, "gamma.example")
    finally:
        server.shutdown()

    assert "0 confirmed findings" in html
    assert "Open manual check" not in html
    assert "Needs your help" not in html
    assert "Could not complete" in html
    assert '<title>AI QA Factory — Could not complete</title>' in html
    assert 'href="/scout/attention"' not in html


@pytest.mark.parametrize(
    "domain,badge_text,title_suffix,chip_expected",
    [
        ("beta.example", "Needs your help", "Needs attention", True),
        ("delta.example", "Not analyzed", "Not analyzed", False),
        ("eta.example", "Skipped", "Skipped", False),
        ("gamma.example", "Could not complete", "Could not complete", False),
    ],
)
def test_heading_badge_chip_and_title_agree_on_the_same_page(
    tmp_path, monkeypatch, domain, badge_text, title_suffix, chip_expected
):
    """One glance at the page must tell one story: the badge, the page <title> and whether the
    'Needs attention' chip is offered must all agree with the target's real status — never a
    'Needs your help' badge next to a message that says nothing is pending, and never a chip that
    points at a destination this target can never reach."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _card(url, domain)
    finally:
        server.shutdown()

    assert f"<title>AI QA Factory — {title_suffix}</title>" in html
    assert badge_text in html
    assert ('href="/scout/attention"' in html) is chip_expected
    if domain != "beta.example":
        assert "Needs your help" not in html
