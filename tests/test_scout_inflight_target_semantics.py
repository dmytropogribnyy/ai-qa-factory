"""Scout stabilization — a target being analyzed right now is not a queued one.

Found by an independent review of this slice: the "Skip queued" banner added earlier told the
operator that selected targets "will not start", and the engine's own comment says the opposite for
one of them — "the currently-running page is never interrupted mid-operation". The compact state
could not tell the two apart, because the engine only wrote a prospect's state AFTER it finished, so
the target the browser was loading read PENDING for the whole of its analysis.

That single missing fact produced three false statements at once: the run row called a target that
was being analyzed "Queued", the skip request was accepted for it, and the banner promised it would
not start. The engine now records ``started_at`` before it begins a target, and every surface reads
that instead of guessing from the status alone.
"""
from __future__ import annotations

from core.scout.backends import PageObservation
from core.scout.config import ScoutRunConfig
from core.scout.dashboard import _run_prospect_label, _run_status_summary, start_dashboard
from core.scout.engine import ScoutEngine
from core.scout.operator_state import OperatorStateStore
from core.scout.service import ScoutService
from core.scout.store import RunStore
from tests.scout_seam_fixtures import RUN_A, build_seam_stand, get, no_tavily


def _mark_started(out: str, pid: str) -> None:
    """Put a prospect into the exact shape the engine now persists while it works on a target."""
    store = RunStore(out, RUN_A)
    state = store.load_state()
    state["prospects"][pid]["started_at"] = "2026-07-26T20:00:00+00:00"
    store.save_state(state)


# -- the engine must record that a target has started ----------------------------------------------


class _SlowOkBackend:
    name = "static"
    screenshot_dir = None

    def __init__(self, store: RunStore, pid: str):
        self._store, self._pid = store, pid
        self.seen_started_at = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        # Read what is on disk at the moment the browser work begins — this is precisely the window
        # in which the operator can click "Skip queued" on a target that is already being analyzed.
        state = self._store.load_state() or {}
        self.seen_started_at = (state.get("prospects", {}).get(self._pid) or {}).get("started_at")
        return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                               title="T", meta_description="", html_bytes=1000,
                               headings=[{"level": 1, "text": "h"}], landmarks={"main": 1},
                               headers={"content-type": "text/html"})


def test_the_engine_persists_that_a_target_has_started_before_working_on_it(tmp_path):
    """Without this the run cannot distinguish "waiting its turn" from "being analyzed right now"."""
    cfg = ScoutRunConfig(campaign_name="inflight", browser_mode="static", resolve_dns=False,
                         output_dir=str(tmp_path), run_id="inflight-run",
                         seeds=["https://first.example/"])
    store = RunStore(str(tmp_path), "inflight-run")
    backend = _SlowOkBackend(store, "01-first-example")
    ScoutEngine(cfg, store, backend=backend).run()

    assert backend.seen_started_at, (
        "the prospect was not persisted as started before its analysis began, so no surface can "
        "tell an in-flight target from a queued one")


# -- a started target may not be skipped, and must not be advertised as skippable -------------------


def test_a_started_target_cannot_be_skipped_and_is_refused_honestly(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    _mark_started(str(tmp_path), "04-delta")

    result = OperatorStateStore(str(tmp_path)).request_skip(RUN_A, ["04-delta"])

    assert result["requested"] == []
    assert result["refused"] == [{"prospect_id": "04-delta", "status": "already started"}]


def test_a_target_that_has_not_started_is_still_skippable(tmp_path, monkeypatch):
    """The refusal must be about having started, not about being PENDING."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))

    result = OperatorStateStore(str(tmp_path)).request_skip(RUN_A, ["04-delta"])

    assert result["requested"] == ["04-delta"]
    assert result["refused"] == []


def test_a_started_target_shows_no_skip_marker_even_if_a_request_is_on_file(tmp_path, monkeypatch):
    """The request can legitimately predate the start. The page must reflect what can still happen."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    OperatorStateStore(str(tmp_path)).request_skip(RUN_A, ["04-delta"])   # queued while waiting
    _mark_started(str(tmp_path), "04-delta")                             # then the engine began it

    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    assert "Skip requested" not in html, (
        "the page promises a skip for a target the engine can no longer stop")
    assert "will not start" not in html


# -- a started target reads as in progress, everywhere ---------------------------------------------


def test_a_started_target_is_not_called_queued(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    _mark_started(str(tmp_path), "04-delta")

    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    import re
    row = re.search(r'<td data-label="Target">delta\.example</td>.*?</tr>', html, re.S)
    assert row and "In progress" in row.group(0)
    assert ">Queued<" not in row.group(0)


def test_the_summary_still_partitions_when_a_target_is_in_flight(tmp_path, monkeypatch):
    """Adding a category must not let a target fall out of the count."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    _mark_started(str(tmp_path), "04-delta")

    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    import re
    tiles = {m.group(1): int(m.group(2)) for m in
             re.finditer(r'<span class="muted">([^<]+)</span><strong>(\d+)</strong>', html)}
    assert tiles["Targets"] == 7
    assert tiles.get("In progress") == 1
    assert "Queued" not in tiles
    assert sum(v for k, v in tiles.items() if k != "Targets") == 7


# -- the label and summary helpers, directly --------------------------------------------------------


def test_label_helper_separates_queued_from_in_flight():
    assert _run_prospect_label({"status": "PENDING"}) == "Queued"
    assert _run_prospect_label({"status": "PENDING", "started_at": "2026-01-01T00:00:00Z"}) \
        == "In progress"
    assert _run_prospect_label({"status": "DONE", "started_at": "x"}) == "Completed"


def test_summary_counts_an_unknown_status_instead_of_dropping_it():
    """The guide states this rule; nothing in the seeded stand exercises it."""
    assert _run_status_summary({"a": {"status": "QUARANTINED"}}) == [("Quarantined", 1)]
    mixed = _run_status_summary({"a": {"status": "DONE"}, "b": {"status": "WARP_CORE_BREACH"}})
    assert dict(mixed) == {"Completed": 1, "Warp Core Breach": 1}
    assert sum(n for _, n in mixed) == 2
