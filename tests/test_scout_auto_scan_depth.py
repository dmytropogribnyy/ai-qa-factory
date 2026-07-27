"""Scout picks the scan depth; the operator does not.

The daily form used to ask "Static or Deep Capture?" — a question that needs knowledge of what is
installed on the host to answer. The unified form sends `auto` and the launcher decides against a
real Chromium probe, in the policy core rather than in the page script.

Two things must stay true while it does: the decision is never made by the untrusted request, and a
downgrade is never silent — a run that went static because no browser exists must say so, or the
operator will look for screenshots that were never possible.
"""
from __future__ import annotations

import pytest

from core.scout.campaign_start import AUTO_BROWSER_MODE, CampaignLauncher


class _Service:
    def __init__(self, tmp_path):
        self.output_dir = str(tmp_path)
        self.started = []

    def is_running(self) -> bool:
        return False                     # the one-active-campaign guard has nothing to refuse here

    def start(self, cfg):
        self.started.append(cfg)
        return cfg.run_id


def _launcher(tmp_path, *, browser_ready: bool):
    service = _Service(tmp_path)
    launcher = CampaignLauncher(service, resolve_dns=False,
                                browser_probe=lambda: browser_ready,
                                starter=service.start)
    return service, launcher


def _start(launcher, **extra):
    request = {"confirm": True, "idempotency_key": "k" + str(len(extra)),
               "seeds": ["https://example.com/"], "browser_mode": AUTO_BROWSER_MODE}
    request.update(extra)
    return launcher.start(request)


def test_auto_uses_deep_capture_when_a_real_browser_is_available(tmp_path):
    service, launcher = _launcher(tmp_path, browser_ready=True)

    result = _start(launcher)

    assert result.ok and result.status == 202
    assert service.started[0].browser_mode == "playwright"
    assert "deep evidence capture" in result.message


def test_auto_falls_back_to_static_and_says_so(tmp_path):
    """A downgrade is a fact about the evidence the operator will get, not an implementation detail."""
    service, launcher = _launcher(tmp_path, browser_ready=False)

    result = _start(launcher)

    assert result.ok
    assert service.started[0].browser_mode == "static"
    assert "static scan" in result.message
    assert "no screenshots" in result.message


def test_an_explicit_deep_request_still_refuses_rather_than_downgrading(tmp_path):
    """`auto` means "you choose"; `playwright` means "I need this" — and that promise is kept."""
    _service, launcher = _launcher(tmp_path, browser_ready=False)

    result = _start(launcher, browser_mode="playwright")

    assert not result.ok and result.status == 503
    assert "silently downgrading" in result.message


def test_an_arbitrary_mode_is_still_refused(tmp_path):
    """Adding `auto` must not turn this field into a free-text backend selector."""
    _service, launcher = _launcher(tmp_path, browser_ready=True)

    for bogus in ("chrome", "auto ", "PLAYWRIGHT", "", 1, None, ["auto"]):
        result = _start(launcher, browser_mode=bogus, idempotency_key=f"k-{bogus!r}")
        assert not result.ok, bogus
        assert result.status == 422, bogus


@pytest.mark.parametrize("ready, expected", [(True, "playwright"), (False, "static")])
def test_the_resolved_depth_is_what_actually_runs(tmp_path, ready, expected):
    service, launcher = _launcher(tmp_path, browser_ready=ready)

    _start(launcher)

    assert service.started[0].browser_mode == expected
