"""Real-browser acceptance for the filter oracle — what a filter interaction may claim, and when.

The deterministic oracle tests pin the classifier against hand-written measurements. These drive
the whole recorded path — a real Chromium context, the bundled fixture site, the engine's two-pass
confirmation — through the three shapes that decide everything:

- a facet group behind an **Apply** button: ticking a box is supposed to change nothing, so no
  finding may exist, however the run is repeated;
- an auto-applied filter where every listed item legitimately matches: the site confirms
  application (the URL moves) and that is still not a defect, because nothing machine-checkable
  proves any listed item fails the facet;
- a filter provably broken by the page's own arithmetic: the facet label promises 2 matching
  items, the URL confirms application, and all 6 results stay listed — at least 4 cannot match,
  by the site's own two numbers. Only THIS shape may become an actionable finding.

No external site is touched; every page is served from the bundled fixture server.
"""
from __future__ import annotations

import itertools

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from core.scout.backends import PlaywrightBackend  # noqa: E402
from core.scout.config import ScoutRunConfig
from core.scout.engine import P_DONE, ScoutEngine
from core.scout.interaction_scenario import (DEFECT_SIGNATURE, OUTCOME_DEFECT,
                                             OUTCOME_NOT_APPLICABLE)
from core.scout.store import RunStore
from tests.scout_fixtures import serve_fixtures


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.playwright_acceptance,
    pytest.mark.skipif(not _chromium_available(),
                       reason="Chromium build not available (run: python -m playwright install chromium)"),
]

_counter = itertools.count()


def _clock():
    return f"2026-07-28T12:00:{next(_counter):02d}+00:00"


def _run(tmp_path, base, host, path, run_id):
    cfg = ScoutRunConfig(campaign_name="filter-oracle", seeds=[f"{base}{path}"],
                         allowed_local_hosts=frozenset({host}), browser_mode="playwright",
                         output_dir=str(tmp_path), max_pages_per_site=4,
                         video_mode="qualified_auto", resolve_dns=False)
    store = RunStore(str(tmp_path), run_id)
    backend = PlaywrightBackend(policy=cfg.url_policy())
    state = ScoutEngine(cfg, store, backend=backend, clock=_clock).run()
    pid = next(iter(state["prospects"]))
    assert state["prospects"][pid]["status"] == P_DONE
    return store, pid


def _scenario(store, pid):
    return store.load_prospect_artifact(pid, "interaction_scenario.json") or {}


def _filter_findings(store, pid):
    record = store.load_prospect_artifact(pid, "findings.json") or {}
    return [f for f in (record.get("verified") or [])
            if f.get("signature") == DEFECT_SIGNATURE]


def test_a_facet_group_behind_an_apply_button_yields_no_finding(tmp_path):
    """Correct behaviour must never travel to a client as a defect — the original false positive."""
    with serve_fixtures() as (base, host):
        store, pid = _run(tmp_path, base, host, "/filter_apply/index.html", "run-filter-apply")

    record = _scenario(store, pid)
    assert record.get("outcome") == OUTCOME_NOT_APPLICABLE
    assert "Apply filters" in record.get("reason", "")
    assert record.get("cleanup_ok") is True
    assert _filter_findings(store, pid) == []


def test_an_auto_applied_filter_where_everything_matches_yields_no_finding(tmp_path):
    """The site SAYS the filter applied (the URL moves) and the list stays — and that is still not
    a defect, because every listed mug may legitimately be in stock. No witness, no claim."""
    with serve_fixtures() as (base, host):
        store, pid = _run(tmp_path, base, host, "/filter_all_match/index.html", "run-filter-match")

    record = _scenario(store, pid)
    assert record.get("outcome") == OUTCOME_NOT_APPLICABLE
    assert "match" in record.get("reason", "").lower()
    assert record.get("baseline", {}).get("facet_count") is None
    assert record.get("cleanup_ok") is True
    assert _filter_findings(store, pid) == []


def test_a_filter_broken_by_the_pages_own_numbers_is_the_only_defect(tmp_path):
    """The positive case, machine-proven: facet promises 2, application confirmed, 6 stay listed.
    The defect survives the engine's independent second pass and carries the site's own numbers."""
    with serve_fixtures() as (base, host):
        store, pid = _run(tmp_path, base, host, "/filter_broken/index.html", "run-filter-broken")

    record = _scenario(store, pid)
    assert record.get("outcome") == OUTCOME_DEFECT
    assert record.get("baseline", {}).get("facet_count") == 2
    assert record.get("observed", {}).get("result_count") == 6
    assert record.get("cleanup_ok") is True
    assert record.get("confirmation", {}).get("agreed") is True   # repeatable, not a one-off

    findings = _filter_findings(store, pid)
    assert len(findings) == 1
    actual = findings[0].get("actual", "")
    assert "2" in actual and "6" in actual
    assert "non-matching items remain" not in actual
