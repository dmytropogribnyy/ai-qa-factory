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
                   with_config: bool = True, run_status: str | None = None):
    """A dashboard whose bound ScoutService reports an ACTIVE run whose prospect map is still empty.

    This is the real mid-run shape: the engine persists the run and its config first, and only writes
    the prospect map once the first target completes.
    """
    out = str(tmp_path)
    store = RunStore(out, _RUN)
    if run_status != "__absent__":
        store.save_state({"status": run_status or ("RUNNING" if running else "COMPLETED"),
                          "prospects": prospects or {}})
    if with_config:
        store.write_config(ScoutRunConfig(campaign_name="adhoc", seeds=list(_SEEDS),
                                          browser_mode="static", resolve_dns=False,
                                          output_dir=out, run_id=_RUN).to_dict())
    service = ScoutService(out)

    def _status(self):
        state = {} if run_status == "__absent__" else (store.load_state() or {})
        return {"run_id": _RUN, "running": running, "mode": "ACTIVE" if running else "OWNED_FINISHED",
                "controllable": running, "control": {}, "state": state}

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


def test_a_starting_run_does_not_claim_analysis_is_already_under_way(tmp_path, monkeypatch):
    """The engine persists a run as PENDING and only flips it to RUNNING once it actually begins, so
    while the worker starts and the browser launches the status badge reads "Queued". The notice must
    agree with that badge instead of announcing analysis that has not started — the owner's live
    screen showed exactly this pair (ACTIVE / Queued) and it must not read as a contradiction."""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True, run_status="PENDING")
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert "The run is starting" in html
    assert "Analysis in progress" not in html
    assert "no target has finished yet" in html.lower()
    assert "No prospects in this run" not in html


def test_a_run_whose_state_is_not_on_disk_yet_still_reads_honestly(tmp_path, monkeypatch):
    """The earliest moment of all, photographed by the owner on a live stand: the worker has been
    started but nothing has been persisted, so the status badge reads N/A. The notice must agree with
    that badge — "the run is starting" — and must not claim analysis is already under way."""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True, run_status="__absent__")
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert "The run is starting" in html
    assert "Analysis in progress" not in html
    assert "No prospects in this run" not in html


# -- the notice must not be allowed to go stale --------------------------------------------------


def test_a_bound_run_page_reports_its_own_freshness(tmp_path, monkeypatch):
    """A screen that states what a live process is doing must show whether that statement is current.

    Found by the owner: after a run had finished, the Scout page still read "The run is starting",
    because this page never polls — the sibling operator screens do (they carry the same freshness
    row and poll helper), but the one that describes an ACTIVE run did not, so its claim silently
    aged into a lie.
    """
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True)
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert 'id="pollstate"' in html          # the shared freshness indicator
    assert 'id="pollbanner"' in html         # "Updates available — Refresh"
    assert "/api/status" in html             # it polls the run's own status endpoint


def test_the_poll_signature_covers_what_the_page_claims(tmp_path, monkeypatch):
    """Polling that ignores the run's status would leave the same stale claim in place. The signature
    has to include the fields the page renders: the run status and each target's status."""
    no_tavily(monkeypatch)
    server, url = _running_stand(tmp_path, monkeypatch, running=True)
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    script = html.split("<script>")[-1]
    assert "running" in script
    assert "status" in script
    assert "prospects" in script


def test_an_idle_page_does_not_poll(tmp_path, monkeypatch):
    """Nothing is happening, so nothing needs watching — do not burn a request every ten seconds."""
    no_tavily(monkeypatch)
    out = str(tmp_path)
    service = ScoutService(out)
    monkeypatch.setattr(ScoutService, "status", lambda self: {
        "run_id": "", "running": False, "mode": "IDLE", "controllable": False,
        "control": {}, "state": {}})
    server, url = start_dashboard(service, operator_home=True)
    try:
        _, html = get(f"{url}/scout")
    finally:
        server.shutdown()

    assert 'id="pollstate"' not in html

