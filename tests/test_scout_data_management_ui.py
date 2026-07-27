"""Data management belongs under More, and its dangerous button must be three clicks away.

Destructive controls on Overview get pressed by accident. This screen therefore lives beside the
other things an operator opens deliberately, and the path to an irreversible action runs through a
preview that names counts and megabytes, then Trash, then a separate confirmation inside Trash.

The one rule the UI has to carry as faithfully as the store does: a preview that is more permissive
than the action behind it is worse than no preview at all. So the page renders the store's own
refusals rather than filtering the list itself.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from core.scout.dashboard import start_dashboard
from core.scout.data_management import PURPOSE_ACCEPTANCE, PURPOSE_PRODUCTION
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.service import ScoutService
from core.scout.store import RunStore


def _run(out: str, run_id: str, *, domain: str, purpose: str = "") -> None:
    store = RunStore(out, run_id)
    config = {"campaign_name": "operator-scan"}
    if purpose:
        config["run_purpose"] = purpose
    store.write_config(config)
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-26T10:00:00+00:00",
                      "prospects": {"01": {"status": "DONE", "url": f"https://{domain}/"}}})
    pdir = store.prospect_dir("01")
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "page.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(1024))
    AnalyzedSiteRegistry(out).record_analysis(
        domain, status=ANALYZED, evidence_ref=f"scout/{run_id}", campaign_id=run_id)


@pytest.fixture()
def dash(tmp_path):
    out = str(tmp_path)
    _run(out, "acceptance-1", domain="plausible.io", purpose=PURPOSE_ACCEPTANCE)
    _run(out, "campaign-real-20260720t100000z-abc123", domain="userlist.com",
         purpose=PURPOSE_PRODUCTION)
    _run(out, "legacy-run", domain="nolt.io")
    server, url = start_dashboard(ScoutService(out), operator_home=True)
    try:
        yield server, url
    finally:
        server.shutdown()


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode("utf-8")


def _post(server, url: str, path: str, payload: dict):
    body = json.dumps({**payload, "csrf_token": server.scout_csrf_token}).encode("utf-8")
    request = urllib.request.Request(url + path, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Scout-CSRF": server.scout_csrf_token,
        "Origin": url})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# --- where it lives ------------------------------------------------------------------------------

def test_the_page_is_reachable_and_named(dash):
    _server, url = dash

    html = _get(url + "/data")

    assert "<title>AI QA Factory — Data management</title>" in html
    assert "<h1>Data management</h1>" in html


def test_it_is_offered_under_more_and_not_on_overview(dash):
    _server, url = dash

    assert 'href="/data"' in _get(url + "/settings")
    overview = _get(url + "/")
    assert "Move" not in overview and "Trash" not in overview


def test_the_summary_separates_production_from_test_data(dash):
    _server, url = dash

    html = _get(url + "/data")

    assert "Production" in html and "Acceptance" in html and "Unclassified" in html
    assert "Storage" in html


# --- the staged path -----------------------------------------------------------------------------

def test_a_preview_is_required_before_anything_can_be_moved(dash):
    server, url = dash

    status, body = _post(server, url, "/api/scout/data/preview", {"run_ids": ["acceptance-1"]})

    assert status == 200 and body["ok"] is True
    assert [r["run_id"] for r in body["preview"]["runs"]] == ["acceptance-1"]
    assert body["preview"]["bytes_to_reclaim"] > 0
    assert body["preview"]["unique_domains"] == ["plausible.io"]


def test_the_preview_shows_the_stores_own_refusals(dash):
    """The page must not filter the list itself — it must show what the store would refuse."""
    server, url = dash

    _status, body = _post(server, url, "/api/scout/data/preview", {
        "run_ids": ["campaign-real-20260720t100000z-abc123", "legacy-run"]})

    reasons = {p["run_id"]: p["reason"] for p in body["preview"]["protected"]}
    assert "production" in reasons["campaign-real-20260720t100000z-abc123"]
    assert "unclassified" in reasons["legacy-run"]
    assert body["preview"]["runs"] == []


def test_moving_to_trash_is_reversible_through_the_api(dash):
    server, url = dash

    _status, moved = _post(server, url, "/api/scout/data/trash", {"run_ids": ["acceptance-1"]})
    trashed_page = _get(url + "/data?view=trash")
    _status2, restored = _post(server, url, "/api/scout/data/restore",
                               {"run_ids": ["acceptance-1"]})

    assert moved["moved"] == ["acceptance-1"]
    assert "acceptance-1" in trashed_page
    assert restored["restored"] == ["acceptance-1"]
    assert "acceptance-1" in _get(url + "/data")


def test_permanent_delete_refuses_without_an_explicit_confirmation(dash):
    server, url = dash
    _post(server, url, "/api/scout/data/trash", {"run_ids": ["acceptance-1"]})

    _status, body = _post(server, url, "/api/scout/data/delete", {"run_ids": ["acceptance-1"]})

    assert body["deleted"] == []
    assert _get(url + "/data?view=trash").count("acceptance-1") >= 1


def test_permanent_delete_works_from_trash_with_confirmation(dash):
    server, url = dash
    _post(server, url, "/api/scout/data/trash", {"run_ids": ["acceptance-1"]})

    _status, body = _post(server, url, "/api/scout/data/delete",
                          {"run_ids": ["acceptance-1"], "confirm": True})

    assert body["deleted"] == ["acceptance-1"]
    assert body["bytes_reclaimed"] > 0
    assert "acceptance-1" not in _get(url + "/data")


def test_production_data_survives_a_test_cleanup(dash):
    server, url = dash
    _post(server, url, "/api/scout/data/trash", {"run_ids": ["acceptance-1"]})
    _post(server, url, "/api/scout/data/delete",
          {"run_ids": ["acceptance-1"], "confirm": True})

    html = _get(url + "/data")

    assert "campaign-real-20260720t100000z-abc123" in html
    assert "userlist.com" in _get(url + "/scout/history")


# --- the guards ----------------------------------------------------------------------------------

def test_every_mutation_is_behind_the_shared_guard(dash):
    _server, url = dash

    for path in ("/api/scout/data/trash", "/api/scout/data/restore", "/api/scout/data/delete"):
        request = urllib.request.Request(
            url + path, data=json.dumps({"run_ids": ["acceptance-1"]}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        assert caught.value.code == 403, path


def test_there_is_no_clear_all_button(dash):
    """One button that takes everything is exactly the control this design refuses to offer."""
    _server, url = dash

    html = _get(url + "/data")

    for banned in ("Clear all", "Delete everything", "Reset all data"):
        assert banned not in html, banned


def test_a_trashed_run_is_hidden_from_the_daily_history(dash):
    server, url = dash

    _post(server, url, "/api/scout/data/trash", {"run_ids": ["acceptance-1"]})

    assert "plausible.io" not in _get(url + "/scout/history")
    assert "userlist.com" in _get(url + "/scout/history")
