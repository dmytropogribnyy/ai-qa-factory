"""One run, one state, whichever surface is asked.

A completed direct Scout run — targets supplied, not discovered — read as terminal in Activity and
on its own target pages, and as *queued with empty counters and no timestamps* in campaign detail.
Nothing was miscomputed: the campaign surface built a run-control record for an id that has none and
reported the DEFAULT. A default is a fine answer to "what is the state of a campaign that has not
started"; it is a wrong answer to "what is the state of this run", and the two questions were not
being told apart.

The same root cause emptied the evidence manifest: it looks for promoted children, a direct run has
none, and zero children was reported as zero evidence while the target page listed screenshots.

The rule these tests pin: a campaign-shaped question asked about a direct run is REFUSED, explicitly,
and the state that comes back is the one the store that owns the run actually recorded.
"""
from __future__ import annotations

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.canonical_runs import (KIND_CAMPAIGN, KIND_DIRECT, KIND_UNKNOWN, NOT_APPLICABLE,
                                       canonical_run_state, run_kind)
from core.scout.store import RunStore

DIRECT = "operator-scan-20260728t090000z-aa11bb"
CAMPAIGN = "campaign-dental-20260728t090000z-cc22dd"

_FUNNEL = ("discovered", "eligible", "qa_analyzed", "actionable", "already_analyzed",
           "rejected", "failed")


@pytest.fixture()
def out(tmp_path):
    """A finished direct run holding real evidence, and nothing else."""
    store = RunStore(str(tmp_path), DIRECT)
    store.write_config({"campaign_name": "operator-scan", "run_purpose": "production",
                        "seeds": ["https://t1.example/"]})
    store.save_state({"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
                      "finished_at": "2026-07-28T09:06:00+00:00",
                      "prospects": {"01": {"status": "DONE", "url": "https://t1.example/",
                                           "verified_findings": 1, "verified_defects": 1}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        {"finding_id": "01-a", "title": "Issue", "severity": "high", "signature": "s1",
         "url": "https://t1.example/"}]})
    (store.prospect_dir("01") / "landing.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    return str(tmp_path)


# --- the kind of a run is read off disk, never guessed from its name -------------------------------

def test_a_direct_run_is_recognised_as_a_direct_run(out):
    assert run_kind(out, DIRECT) == KIND_DIRECT


def test_an_id_nothing_exists_for_is_unknown_rather_than_direct(out):
    """Fail closed: absence must not be classified as a run whose state can then be reported."""
    assert run_kind(out, "never-existed") == KIND_UNKNOWN
    assert canonical_run_state(out, "never-existed")["state"] == ""


def test_a_campaign_is_recognised_by_its_run_control_record(out, tmp_path):
    rc = tmp_path / "scout" / "_runcontrol"
    rc.mkdir(parents=True, exist_ok=True)
    (rc / f"{CAMPAIGN}.json").write_text("{}", encoding="utf-8")

    assert run_kind(out, CAMPAIGN) == KIND_CAMPAIGN


# --- the state comes from the store that owns the run ----------------------------------------------

def test_the_canonical_state_of_a_finished_direct_run_is_terminal(out):
    canonical = canonical_run_state(out, DIRECT)

    assert canonical["state"] == "COMPLETED"
    assert canonical["terminal"] is True
    assert canonical["source"] == f"scout/{DIRECT}/state.json"
    assert canonical["updated_at"] == "2026-07-28T09:06:00+00:00"


def test_campaign_detail_no_longer_calls_a_finished_run_queued(out):
    """The exact contradiction: terminal in Activity, queued in campaign detail."""
    progress = CampaignService(out).progress(DIRECT)

    assert progress["run_state"] == "COMPLETED"
    assert progress["applicable"] is False
    assert progress["run_kind"] == KIND_DIRECT
    assert "not a discovery campaign" in progress["not_applicable_reason"]


def test_the_discovery_funnel_is_refused_rather_than_reported_as_zero(out):
    """Zero discovered says nothing was found. Nothing was ever discoverable — different fact."""
    counters = CampaignService(out).progress(DIRECT)["counters"]

    assert set(counters) == set(_FUNNEL)
    assert all(value == NOT_APPLICABLE for value in counters.values())
    assert 0 not in counters.values()


def test_an_empty_timestamp_is_not_reported_for_a_run_that_finished(out):
    assert CampaignService(out).progress(DIRECT)["updated_at"] == "2026-07-28T09:06:00+00:00"


# --- the evidence a direct run holds is its own ----------------------------------------------------

def test_the_evidence_manifest_of_a_direct_run_is_not_empty(out):
    from core.scout.observer_api import ObserverAPI

    manifest = ObserverAPI(out).get_evidence_manifest(DIRECT)
    refs = [item["ref"] for item in manifest["evidence"]]

    assert any(ref.endswith("landing.png") for ref in refs), refs
    assert any(ref.endswith("findings.json") for ref in refs), refs


def test_the_findings_of_a_direct_run_are_visible_to_the_observer(out):
    from core.scout.observer_api import ObserverAPI

    listed = ObserverAPI(out).list_findings(DIRECT)

    assert listed["total"] == 1
    assert listed["findings"][0]["title"] == "Issue"


def test_target_detail_and_the_observer_agree_about_the_same_run(out):
    """The reconciliation the whole blocker is about, asserted in one place."""
    from core.scout.observer_api import ObserverAPI

    detail = CampaignService(out).target_detail("t1.example", run=DIRECT)
    listed = ObserverAPI(out).list_findings(DIRECT)
    manifest = ObserverAPI(out).get_evidence_manifest(DIRECT)

    assert detail["actionable_summary"]["confirmed_issues"] == listed["total"] == 1
    assert detail["analysis_complete"] is True
    assert manifest["evidence"], "target detail lists evidence the manifest reports as absent"
