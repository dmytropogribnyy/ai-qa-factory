"""Scout operator polish — Dashboard friendliness + registry-honesty.

Pins the operator-facing improvements from the 2026-07-22 review:
  * History shows an HONEST count ("N shown of T total") when a filter hides rows, so a filtered view
    is never mistaken for "that's all there is" (the confusion that prompted this work).
  * History Notes shows a human reason, not the internal `scout/<domain>/qa` evidence path.
  * Settings de-alarms the readiness board: operator/client items are labelled optional / not blocking.
  * reconcile_history validates persisted brain files defensively and reports domains actually persisted.
"""
from __future__ import annotations

import urllib.request

from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.service import ScoutService


def _dash(tmp_path):
    return start_dashboard(ScoutService(str(tmp_path)), operator_home=True)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


# -- History: honest count + human Notes ------------------------------------------------------------


def test_history_shows_shown_of_total_when_a_filter_hides_rows(tmp_path):
    CampaignService(str(tmp_path))._register_analyzed("c1", ["alpha.com", "beta.com"])
    server, url = _dash(tmp_path)
    try:
        _, filtered = _get(url + "/scout/history?text=alpha")
        assert "1 shown of 2 total" in filtered        # honest: the filter hid one row
        _, full = _get(url + "/scout/history")
        assert "2 total" in full                        # unfiltered still communicates the total
    finally:
        server.shutdown()


def test_history_zero_result_filter_is_not_mistaken_for_empty_history(tmp_path):
    CampaignService(str(tmp_path))._register_analyzed("c1", ["alpha.com", "beta.com"])
    server, url = _dash(tmp_path)
    try:
        _, body = _get(url + "/scout/history?text=zzz-no-match")   # a filter that hides every row
        assert "No analyzed sites yet" not in body       # must NOT read as an empty history
        assert "2 total" in body                          # the true total is still surfaced
    finally:
        server.shutdown()


def test_history_notes_shows_reason_not_the_internal_evidence_path(tmp_path):
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.record_analysis("clean.com", status=ANALYZED, evidence_ref="scout/clean.com/qa")
    reg.record_rejection("spam.com", "social network, not a company target")
    server, url = _dash(tmp_path)
    try:
        _, body = _get(url + "/scout/history")
        assert "social network, not a company target" in body   # the useful rejection reason shows
        assert "scout/clean.com/qa" not in body                  # internal path is not surfaced
    finally:
        server.shutdown()


# -- Settings: de-alarm the readiness board --------------------------------------------------------


def test_settings_frames_readiness_as_opt_in_not_required(tmp_path):
    server, url = _dash(tmp_path)
    try:
        _, body = _get(url + "/settings")
        assert "opt-in" in body.lower()                  # always-present de-alarmed framing
        assert "Operator actions required" not in body   # no longer framed as required/alarming
    finally:
        server.shutdown()


# -- reconcile_history hardening: attempted-vs-persisted + defensive validation --------------------


def test_register_analyzed_returns_actually_persisted_domains(tmp_path):
    persisted = CampaignService(str(tmp_path))._register_analyzed("c1", ["a.com", "", "  ", "b.com"])
    assert persisted == ["a.com", "b.com"]               # blanks skipped; real ones reported


def test_reconcile_reports_persisted_and_defensively_skips_malformed(tmp_path):
    svc = CampaignService(str(tmp_path))
    svc._write("camp-ok", "BRAIN_DECISIONS.json",
               {"campaign_id": "camp-ok", "decisions": [{"domain": "good.com"}]})
    svc._write("camp-shape", "BRAIN_DECISIONS.json",
               {"campaign_id": "camp-shape", "decisions": "not-a-list"})   # wrong shape
    svc._write("camp-mixed", "BRAIN_DECISIONS.json",
               {"campaign_id": "camp-mixed", "decisions": [{"domain": "b.com"}, "junk", {"x": 1}]})
    out = svc.reconcile_history()
    assert set(out["domains_registered"]) == {"good.com", "b.com"}   # only real domains persisted
    assert out["skipped_malformed"] >= 1                             # the wrong-shape file was skipped
