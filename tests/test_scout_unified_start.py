"""One Scout, three ways to name sites — and no technical modes in the daily form.

The old form asked the operator to choose a campaign preset, a run size, a discovery strategy, a
coverage profile, a scan mode, a page cap and a discovery cap before every run. Those are decisions
about the host and the engine, not about the work, and answering them wrongly changed what evidence
came back. They are still available to the API and the CLI; they are gone from the page an operator
uses daily.

What replaces them is a source switch. Find, paste or upload — after that the queue is the same, and
the counts shown before Start come from the same intake code that fills it.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService


@pytest.fixture()
def dash(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        yield server, url
    finally:
        server.shutdown()


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
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


# --- the form itself -----------------------------------------------------------------------------

def test_the_daily_form_offers_three_sources_and_one_button(dash):
    _server, url = dash
    html = _get(url + "/scout/new")

    assert "<title>AI QA Factory — Start Scout</title>" in html
    for source in ("Find websites", "Paste URLs", "Upload file"):
        assert source in html
    assert html.count("Start Scout</button>") == 1
    assert "Maximum sites" in html


def test_technical_modes_are_gone_from_the_daily_form(dash):
    """Each of these made the outcome depend on the operator knowing the engine."""
    _server, url = dash
    html = _get(url + "/scout/new")

    for gone in ("Campaign preset", "Run size", "Conservative", "Adaptive coverage",
                 "Deep coverage", "Capture screenshots", "Page cap per site", "Discovery cap",
                 "System readiness", "Minimum commercial fit"):
        assert gone not in html, gone


def test_the_safety_summary_states_what_will_and_will_not_happen(dash):
    _server, url = dash
    html = _get(url + "/scout/new")

    assert "Read-only scan" in html
    assert "no forms, purchases or messages" in html


# --- the preview an operator presses Start on ----------------------------------------------------

def test_pasted_urls_are_previewed_by_the_code_that_will_queue_them(dash):
    server, url = dash

    status, body = _post(server, url, "/api/scout/intake/preview", {
        "text": "https://userlist.com/\nhttps://nolt.io/\nhttps://www.nolt.io/\n0.1\n"
                "http://localhost/"})

    assert status == 200 and body["ok"] is True
    assert body["counts"] == {"lines_read": 5, "unique_sites": 2, "duplicates": 1,
                              "rejected": 2, "already_analyzed": 0}
    assert [t["domain"] for t in body["targets"]] == ["userlist.com", "nolt.io"]
    assert {r["value"] for r in body["rejected"]} == {"0.1", "http://localhost/"}
    assert all(r["reason"] for r in body["rejected"])


def test_an_uploaded_list_is_previewed_the_same_way(dash):
    server, url = dash

    status, body = _post(server, url, "/api/scout/intake/preview", {
        "rows": [["Scout seed URL"], ["https://plausible.io/"], ["www.plausible.io"], ["0.1"]]})

    assert status == 200
    assert body["counts"]["unique_sites"] == 1
    assert body["counts"]["duplicates"] == 1
    assert body["counts"]["rejected"] == 2          # the header row and 0.1


def test_operator_named_targets_are_pinned(dash):
    """Explicitly named sites are scanned; commercial scoring may rank them, not silently drop them."""
    server, url = dash

    _status, body = _post(server, url, "/api/scout/intake/preview", {"text": "https://nolt.io/"})

    assert body["targets"][0]["pinned"] is True


def test_the_preview_refuses_a_cross_origin_or_unauthenticated_caller(dash):
    server, url = dash
    request = urllib.request.Request(
        url + "/api/scout/intake/preview", data=json.dumps({"text": "https://a.com"}).encode(),
        method="POST", headers={"Content-Type": "application/json"})

    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)

    assert caught.value.code == 403


def test_the_preview_queues_nothing(dash):
    """It is what the operator reads before deciding, so it must not start anything."""
    server, url = dash

    _post(server, url, "/api/scout/intake/preview", {"text": "https://nolt.io/"})
    status = json.loads(_get(url + "/api/status"))

    assert status.get("running") is not True
