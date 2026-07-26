"""Scout — an incomplete target must be described by what actually happened to it.

The incomplete screen was written for a challenge (CAPTCHA / blocked access) and offers to open a
manual check. A PENDING target was interrupted and a SKIPPED target was skipped: neither was blocked,
and neither has a challenge session to open. Saying otherwise is a false story about the run.
"""
from __future__ import annotations

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
