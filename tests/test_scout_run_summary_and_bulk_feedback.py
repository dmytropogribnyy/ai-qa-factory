"""Scout stabilization — the run-results summary must account for every target, and a bulk action
must leave visible, persistent, honest evidence that it happened.

Two defects found by driving the live product during the seam inspection:

F3 — the summary tiles counted Targets, Completed and Need attention. A FAILED target, an
interrupted PENDING one and an operator-SKIPPED one fell into no tile at all, so an operator reading
"7 targets, 3 completed, 1 needs attention" had no way to learn that three targets produced no
result. Every number was individually true and the set of them was not exhaustive.

F2 — "Skip queued" genuinely persisted the request (operator_actions.json), but the page reloaded
with no confirmation and the row still read "Queued": the operator could not tell whether the click
had worked, and nothing anywhere distinguished "the skip is queued and will apply when the run
reaches that target" from "the target has actually been skipped".
"""
from __future__ import annotations

import re

from core.scout.dashboard import start_dashboard
from core.scout.operator_state import OperatorStateStore
from core.scout.service import ScoutService
from core.scout.store import RunStore
from tests.scout_seam_fixtures import RUN_A, build_seam_stand, get, no_tavily

# The seeded run holds one prospect per meaningful outcome: three DONE (alpha/epsilon/theta), one
# MANUAL_ACTION_REQUIRED (beta), one FAILED (gamma), one PENDING (delta) and one SKIPPED (eta).
_TOTAL_TARGETS = 7

_TILE = re.compile(r'<span class="muted">([^<]+)</span><strong>(\d+)</strong>')


def _serve(out: str):
    return start_dashboard(ScoutService(out), operator_home=True)


def _tiles(html: str) -> dict[str, int]:
    return {m.group(1).strip(): int(m.group(2)) for m in _TILE.finditer(html)}


def _row(html: str, domain: str) -> str:
    m = re.search(rf'<td data-label="Target">{re.escape(domain)}</td>.*?</tr>', html, re.S)
    assert m, f"no row rendered for {domain}"
    return m.group(0)


# -- F3: the summary must explain every target -----------------------------------------------------


def test_summary_categories_account_for_every_target(tmp_path, monkeypatch):
    """The categories must partition the run: their sum equals the total, with nothing unexplained.

    This is the PR #49 defect class one level down — a headline number that does not account for its
    own population lets an operator conclude "nothing else needs me" from an incomplete summary.
    """
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    tiles = _tiles(html)
    assert tiles.get("Targets") == _TOTAL_TARGETS

    categories = {k: v for k, v in tiles.items() if k != "Targets"}
    assert sum(categories.values()) == _TOTAL_TARGETS, (
        f"categories {categories} sum to {sum(categories.values())}, "
        f"leaving {_TOTAL_TARGETS - sum(categories.values())} target(s) unexplained")


def test_summary_names_the_outcomes_that_produced_no_result(tmp_path, monkeypatch):
    """A failed, an interrupted and a skipped target must each be visible in the summary itself —
    not only in the table below it."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    tiles = _tiles(html)
    assert tiles.get("Completed") == 3                       # alpha, epsilon, theta
    assert tiles.get("Needs your help") == 1                 # beta — the real challenge
    assert tiles.get("Could not complete") == 1              # gamma — FAILED
    assert tiles.get("Queued") == 1                          # delta — interrupted, never analyzed
    assert tiles.get("Skipped") == 1                         # eta — operator skip


def test_summary_labels_match_the_row_labels(tmp_path, monkeypatch):
    """One vocabulary: a tile and the rows it counts must call the same state the same thing."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    tiles = _tiles(html)
    # Bind to the TARGETS table by its caption, not by position. "The last tbody on the page" broke
    # the moment the page grew a second table below it (the run's Requested/Effective/Observed
    # reconciliation) — and it broke by silently checking the wrong table, which is the failure mode
    # a locator like that always has.
    targets = html.split('<caption>Targets in this run</caption>', 1)
    assert len(targets) == 2, "the targets table is no longer identifiable by its caption"
    body = targets[1].split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    for label in ("Completed", "Needs your help", "Could not complete", "Queued", "Skipped"):
        assert label in tiles, f"tile {label!r} missing"
        # The rows must use the SAME word. Asserting `label in html` would be a tautology — label was
        # parsed out of that very html — so look for it inside the table body specifically.
        assert f">{label}</span>" in body, f"rows do not use the tile's word for {label!r}"


# -- F2: a bulk action must leave visible, persistent, honest evidence ------------------------------


def test_a_queued_skip_is_visible_on_the_page_after_a_reload(tmp_path, monkeypatch):
    """The confirmation must survive a reload, so it cannot be a toast the operator misses.

    Reproduces the live finding: the request really was persisted, but the page said nothing and the
    row still read "Queued" — indistinguishable from never having clicked.
    """
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    OperatorStateStore(str(tmp_path)).request_skip(RUN_A, ["04-delta"])   # what the button does
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    assert "Skip requested" in html, "a queued skip leaves no visible trace on the page"
    assert "Skip requested" in _row(html, "delta.example")


def test_queued_and_applied_are_distinguishable(tmp_path, monkeypatch):
    """"The skip is queued and will apply when the run reaches this target" and "this target has
    been skipped" are different facts and must read differently."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    OperatorStateStore(str(tmp_path)).request_skip(RUN_A, ["04-delta"])
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    queued_row = _row(html, "delta.example")      # PENDING + queued request  -> queued
    applied_row = _row(html, "eta.example")       # already SKIPPED           -> applied

    assert "Skip requested" in queued_row
    assert "Skip requested" not in applied_row, (
        "an already-skipped target must not claim a pending request")
    assert "Skipped" in applied_row


def test_a_target_that_cannot_be_skipped_is_refused_honestly(tmp_path, monkeypatch):
    """Only a still-queued target can be skipped. Asking for a completed one must be refused with
    its real reason rather than silently accepted."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    result = OperatorStateStore(str(tmp_path)).request_skip(RUN_A, ["01-alpha", "04-delta"])

    assert result["requested"] == ["04-delta"]
    assert [r["prospect_id"] for r in result["refused"]] == ["01-alpha"]
    assert result["refused"][0]["status"] == "DONE"

    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    # The refused target keeps its own truthful state and gains no phantom request marker.
    assert "Skip requested" not in _row(html, "alpha.example")
    assert "Skip requested" in _row(html, "delta.example")


def test_the_page_explains_what_a_queued_skip_will_do(tmp_path, monkeypatch):
    """A marker the operator cannot interpret is not a confirmation. The page must say what happens
    next, and the statement must be true of this product: the engine checks the request before each
    new target, so a queued target never starts."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    OperatorStateStore(str(tmp_path)).request_skip(RUN_A, ["04-delta"])
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    assert "will not start" in html


def test_no_marker_appears_when_nothing_was_requested(tmp_path, monkeypatch):
    """The marker must be evidence of a real request, not decoration."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    assert "Skip requested" not in html
    assert "will not start" not in html


def test_a_stale_request_for_an_already_finished_target_is_not_advertised(tmp_path, monkeypatch):
    """operator_actions.json is append-only: a request for a target that later completed stays in
    the file. The page must reflect the target's real state, not the stale request."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    store = RunStore(str(tmp_path), RUN_A)
    store.save_artifact("operator_actions.json", {
        "schema": "scout-operator-actions/v1",
        "skip_prospects": ["01-alpha"],          # alpha is DONE — the request can never apply
        "updated_at": "2026-07-26T00:00:00+00:00",
    })
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    assert "Skip requested" not in _row(html, "alpha.example")
