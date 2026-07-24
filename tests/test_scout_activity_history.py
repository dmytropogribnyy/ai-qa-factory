"""Regression coverage for persisted Scout activity across Dashboard restarts."""
from __future__ import annotations

import json
import urllib.request

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore

_PROD_A = "campaign-acme-saas-20260724t090000z-0f9d21"
_PROD_B = "campaign-beta-commerce-20260724t091000z-a1b2c3"
_DIAGNOSTIC = "smoke-activity"


def _register_campaign(output_dir, campaign_id):
    runcontrol = output_dir / "scout" / "_runcontrol"
    runcontrol.mkdir(parents=True, exist_ok=True)
    (runcontrol / f"{campaign_id}.json").write_text(
        json.dumps({"campaign_id": campaign_id, "state": "completed"}),
        encoding="utf-8",
    )


def _event(output_dir, run_id, at, kind, **fields):
    store = RunStore(str(output_dir), run_id)
    store.append_event({"at": at, "event": kind, **fields})


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_html(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def test_activity_loads_all_persisted_production_campaigns_after_restart(tmp_path):
    for campaign_id in (_PROD_A, _PROD_B, _DIAGNOSTIC):
        _register_campaign(tmp_path, campaign_id)
    _event(tmp_path, _PROD_A, "2026-07-24T09:00:00+00:00", "campaign_started",
           campaign_id=_PROD_A)
    _event(tmp_path, _PROD_A, "2026-07-24T09:01:00+00:00", "promoted_to_scout",
           candidate="acme.example")
    _event(tmp_path, _PROD_B, "2026-07-24T09:10:00+00:00", "campaign_finished",
           campaign_id=_PROD_B)
    _event(tmp_path, _DIAGNOSTIC, "2026-07-24T09:20:00+00:00", "campaign_started",
           campaign_id=_DIAGNOSTIC)

    # An idle service models the real post-restart state: no campaign is attached in memory.
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        production = _get_json(f"{url}/api/activity")
        html = _get_html(f"{url}/activity")
        with_diagnostics = _get_json(f"{url}/api/activity?diagnostics=1")
    finally:
        server.shutdown()

    assert production["scout_campaigns_considered"] == 2
    assert {event["campaign_id"] for event in production["events"]} == {_PROD_A, _PROD_B}
    assert [event["event_id"] for event in production["events"]].count(f"{_PROD_A}#0") == 1
    assert _DIAGNOSTIC not in json.dumps(production)
    assert "No operator activity yet" not in html
    assert "Campaign started" in html and "Target promoted to Scout" in html

    assert with_diagnostics["scout_campaigns_considered"] == 3
    assert {event["campaign_id"] for event in with_diagnostics["events"]} == {
        _PROD_A, _PROD_B, _DIAGNOSTIC,
    }


def test_attached_canonical_campaign_is_not_duplicated(tmp_path):
    _register_campaign(tmp_path, _PROD_A)
    _event(tmp_path, _PROD_A, "2026-07-24T09:00:00+00:00", "campaign_started",
           campaign_id=_PROD_A)
    service = ScoutService(str(tmp_path))
    service.attach(_PROD_A)
    server, url = start_dashboard(service, operator_home=True)
    try:
        payload = _get_json(f"{url}/api/activity")
    finally:
        server.shutdown()

    scout_events = [event for event in payload["events"] if event.get("campaign_id") == _PROD_A]
    assert payload["scout_campaigns_considered"] == 1
    assert len(scout_events) == 1
    assert scout_events[0]["event_id"] == f"{_PROD_A}#0"


def test_saved_campaign_without_event_log_has_honest_history_state_after_restart(tmp_path):
    _register_campaign(tmp_path, _PROD_A)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        payload = _get_json(f"{url}/api/activity")
        html = _get_html(f"{url}/activity")
    finally:
        server.shutdown()

    assert payload["events"] == []
    assert payload["scout_run_partial"] is True
    assert payload["scout_campaigns_without_history"] == 1
    assert "No operator activity yet" not in html
    assert "historical activity is unavailable" in html


def test_diagnostic_attached_run_stays_hidden_without_explicit_toggle(tmp_path):
    _event(tmp_path, _DIAGNOSTIC, "2026-07-24T09:00:00+00:00", "campaign_started",
           campaign_id=_DIAGNOSTIC)
    service = ScoutService(str(tmp_path))
    service.attach(_DIAGNOSTIC)
    server, url = start_dashboard(service, operator_home=True)
    try:
        production = _get_json(f"{url}/api/activity")
        diagnostics = _get_json(f"{url}/api/activity?diagnostics=1")
        diagnostics_html = _get_html(f"{url}/activity?diagnostics=1")
    finally:
        server.shutdown()

    assert production["events"] == []
    assert production["scout_campaigns_considered"] == 0
    assert {event["campaign_id"] for event in diagnostics["events"]} == {_DIAGNOSTIC}
    assert "is included below and should not be treated as production" in diagnostics_html
