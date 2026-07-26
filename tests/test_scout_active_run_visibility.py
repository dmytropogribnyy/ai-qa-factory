"""Scout stabilization — an ACTIVE run must not present itself as an empty one.

Found by the owner on a live stand: while Chromium was loading and analyzing a target, the Scout
home showed `Scan mode ACTIVE` with live Pause / Stop & save controls and, directly underneath,
"No prospects in this run." The operator sees "running" and "nothing here" at the same moment and
cannot tell what the system is working on.

The cause is a persistence ordering the inspection already documented: `core/scout/engine.py:115`
saves the run state BEFORE lines 122-126 populate the prospect map, and the populated map only
reaches disk after the first target finishes (`engine.py:156`). So during the first target the
persisted prospect map is genuinely empty — but the run's seeds ARE persisted in config.json, so the
page has real data to show and was showing none of it.

This is the same defect family as the summary that did not account for its own targets and the bulk
action that confirmed nothing: the product holds the fact and does not surface it.
"""
from __future__ import annotations

from core.scout.config import ScoutRunConfig
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore
from tests.scout_seam_fixtures import get, no_tavily

_RUN = "active-run-1"
_SEEDS = ["https://alpha.example/", "https://beta.example/"]


def _running_stand(tmp_path, monkeypatch, *, running: bool, prospects: dict | None = None,
                   with_config: bool = True):
    """A dashboard whose bound ScoutService reports an ACTIVE run whose prospect map is still empty.

    This is the real mid-run shape: the engine persists the run and its config first, and only writes
    the prospect map once the first target completes.
    """
    out = str(tmp_path)
    store = RunStore(out, _RUN)
    store.save_state({"status": "RUNNING" if running else "COMPLETED",
                      "prospects": prospects or {}})
    if with_config:
        store.write_config(ScoutRunConfig(campaign_name="adhoc", seeds=list(_SEEDS),
                                          browser_mode="static", resolve_dns=False,
                                          output_dir=out, run_id=_RUN).to_dict())
    service = ScoutService(out)

    def _status(self):
        return {"run_id": _RUN, "running": running, "mode": "ACTIVE" if running else "OWNED_FINISHED",
                "controllable": running, "control": {},
                "state": store.load_state() or {}}

    monkeypatch.setattr(ScoutService, "status", _status)
    monkeypatch.setattr(ScoutService, "store", property(lambda self: store))
    return start_dashboard(service, operator_home=True)


def test_an_active_run_does_not_claim_it_has_no_prospects(tmp_path, monkeypatch):
    """The exact contradiction the owner photographed: ACTIVE next to "No prospects in this run.\""""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True)
    try:
        status, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert status == 200
    assert "ACTIVE" in html                       # the run really is active — that part was honest
    assert "No prospects in this run" not in html


def test_an_active_run_says_the_analysis_is_under_way(tmp_path, monkeypatch):
    """Absence of a false statement is not enough; the operator must learn what is happening.

    The assertion names the exact sentence rather than a loose "in progress": the page already
    renders "In progress" as a run-status label (dashboard.py maps RUNNING to it), so a loose match
    would pass without the fix and prove nothing.
    """
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True)
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert "no target has finished yet" in html.lower()


def test_an_active_run_names_the_targets_it_is_working_through(tmp_path, monkeypatch):
    """The seeds are persisted in the run's own config, so naming them invents nothing."""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True)
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert "alpha.example" in html
    assert "beta.example" in html


def test_an_active_run_without_a_readable_config_stays_honest(tmp_path, monkeypatch):
    """No config, no invented target list — but still no false "nothing here" either."""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True, with_config=False)
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert "No prospects in this run" not in html
    assert "no target has finished yet" in html.lower()
    assert "alpha.example" not in html            # nothing is fabricated when nothing is persisted


def test_a_finished_run_with_no_targets_still_says_so(tmp_path, monkeypatch):
    """The empty state is correct when the run really did finish with nothing — do not lose it."""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=False)
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert "No prospects in this run" in html
    assert "no target has finished yet" not in html.lower()


def test_a_running_run_that_has_results_shows_them_normally(tmp_path, monkeypatch):
    """Once the first target lands, the normal table takes over — the in-progress notice is for the
    genuinely empty window only."""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True, prospects={
        "01-alpha": {"status": "DONE", "url": "https://alpha.example/", "verified_defects": 2}})
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert "Targets in this run" in html          # the real table
    assert "No prospects in this run" not in html
