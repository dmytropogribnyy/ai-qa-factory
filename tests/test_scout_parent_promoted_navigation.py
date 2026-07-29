"""A discovery campaign's results live in its promoted children — the page must say so.

A discovery campaign holds no prospect evidence of its own: it promotes candidates into their own
runs, and everything those runs found belongs to THEM. The run-results page rendered that truth as
"No results for run <id>" — literally false for an operator staring at a campaign that promoted a
candidate and produced findings. The fix is navigation, not copying: the parent page names and
links each promoted child, keeps provenance where it is, and the plain empty state remains for a
run that genuinely produced nothing.
"""
from __future__ import annotations

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore

from tests.scout_seam_fixtures import get, no_tavily

CAMPAIGN = "camp-nav"
CHILD = "camp-nav-promo-01"

_CONFIG = {"campaign_name": "nav", "run_purpose": "acceptance", "browser_mode": "static",
           "video_mode": "manual", "coverage": "adaptive", "max_pages_per_site": 12,
           "max_sites": 5, "concurrency": 1, "check_families": ["seo"]}


def _seed_discovery(out: str, *, promoted: bool = True) -> None:
    campaign = RunStore(out, CAMPAIGN)
    campaign.write_config({**_CONFIG, "intake": {"kind": "discovery", "query": "clinics, DE"}})
    candidates = []
    if promoted:
        candidates = [{"registrable_domain": "found.example", "candidate_id": "c0",
                       "promotion_decision": "promoted", "promoted_scout_run": CHILD}]
    campaign.save_state({"status": "COMPLETED", "config": campaign.load_config(),
                         "candidates": candidates, "prospects": {}})
    if promoted:
        child = RunStore(out, CHILD)
        child.write_config({**_CONFIG, "seeds": ["https://found.example/"],
                            "intake": {"kind": "discovery", "source_name": CAMPAIGN}})
        child.save_state({"status": "COMPLETED", "prospects": {
            "01": {"status": "DONE", "url": "https://found.example/",
                   "verified_findings": 1, "verified_defects": 1}}})


def _serve(out: str):
    return start_dashboard(ScoutService(out), operator_home=True)


def test_a_parent_with_promoted_children_links_to_them_instead_of_no_results(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    _seed_discovery(str(tmp_path))
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={CAMPAIGN}")
    finally:
        server.shutdown()

    assert "No results for run" not in html
    assert f"/scout/run?id={CHILD}" in html                  # navigation to the promoted child
    assert "found.example" in html                           # named by the site it analyzed
    assert "promoted" in html.lower()                        # and the provenance is explained


def test_the_parent_does_not_absorb_the_childs_results(tmp_path, monkeypatch):
    """Navigation, never copying: the child's targets must not render as the parent's own rows."""
    no_tavily(monkeypatch)
    _seed_discovery(str(tmp_path))
    server, url = _serve(str(tmp_path))
    try:
        _, parent_html = get(f"{url}/scout/run?id={CAMPAIGN}")
        _, child_html = get(f"{url}/scout/run?id={CHILD}")
    finally:
        server.shutdown()

    assert 'data-label="Target">found.example' not in parent_html   # no borrowed result rows
    assert 'data-label="Target">found.example' in child_html        # the child renders its own


def test_a_run_that_genuinely_produced_nothing_keeps_the_honest_empty_state(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    _seed_discovery(str(tmp_path), promoted=False)
    server, url = _serve(str(tmp_path))
    try:
        _, html = get(f"{url}/scout/run?id={CAMPAIGN}")
    finally:
        server.shutdown()

    assert "No results for run" in html
