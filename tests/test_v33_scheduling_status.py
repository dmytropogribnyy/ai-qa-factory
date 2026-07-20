"""v3.3 — run-lock overlap guard, live-discovery status read-model, and scheduler no-key guarantee."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core.scout.discovery.discovery_status import discovery_status
from core.scout.discovery.run_lock import CampaignBusy, CampaignRunLock, read_lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import scout_schedule  # noqa: E402


# --- run-lock (overlap protection) ----------------------------------------------------------------
def test_run_lock_blocks_overlapping_run(tmp_path):
    lock = CampaignRunLock(str(tmp_path), "c1")
    lock.acquire()
    with pytest.raises(CampaignBusy):
        CampaignRunLock(str(tmp_path), "c1").acquire()   # second concurrent run refused
    lock.release()
    CampaignRunLock(str(tmp_path), "c1").acquire()       # released -> can acquire again


def test_run_lock_reclaims_stale_lease(tmp_path):
    clock = [1000.0]
    CampaignRunLock(str(tmp_path), "c1", lease_s=100, clock=lambda: clock[0]).acquire()
    clock[0] += 1000                                     # lease expired (crashed owner)
    # a fresh run reclaims the stale lease rather than being wedged forever
    CampaignRunLock(str(tmp_path), "c1", lease_s=100, clock=lambda: clock[0]).acquire()
    assert read_lock(str(tmp_path), "c1") is not None


def test_run_lock_context_manager_releases(tmp_path):
    with CampaignRunLock(str(tmp_path), "c2"):
        with pytest.raises(CampaignBusy):
            CampaignRunLock(str(tmp_path), "c2").acquire()
    CampaignRunLock(str(tmp_path), "c2").acquire()       # released on exit


# --- discovery status read-model ------------------------------------------------------------------
def test_discovery_status_surfaces_campaign_and_history(tmp_path, monkeypatch):
    from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.observe("https://acme-saas.com", campaign_id="c1", provider="tavily")
    reg.record_analysis("acme-saas.com", evidence_ref="scout/acme-saas.com/qa")
    # a fake persisted live campaign
    d = tmp_path / "scout" / "c1"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({
        "status": "COMPLETED", "counts": {"candidates": 3, "unique": 2, "promoted": 1},
        "budget": {"provider_calls": 1, "results": 3}, "events": []}), encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"countries": ["us", "de"],
                                               "industries": ["B2B SaaS"]}), encoding="utf-8")
    (d / "REGISTRY_RECONCILIATION.json").write_text(json.dumps({
        "campaign_id": "c1", "provider": "tavily", "newly_discovered": ["acme-saas.com"],
        "skipped_already_analyzed": []}), encoding="utf-8")

    monkeypatch.setenv("PROSPECT_RADAR_EXTERNAL_SEND_DISABLED", "1")
    snap = discovery_status(str(tmp_path))
    assert snap["kill_switch"] == "disabled" and snap["provider"] == "tavily"
    assert snap["last_campaign"]["campaign_id"] == "c1"
    assert snap["last_campaign"]["filters"]["countries"] == ["us", "de"]
    assert snap["analyzed_counts"]["analyzed"] == 1
    assert snap["analyzed_sites"][0]["domain"] == "acme-saas.com"
    assert snap["analyzed_sites"][0]["evidence_ref"] == "scout/acme-saas.com/qa"
    # no secret anywhere in the snapshot
    assert "tvly-" not in json.dumps(snap)


# --- scheduler: never embeds the key --------------------------------------------------------------
class _Args:
    campaign_id = "v33-sched"
    countries = "us,de"
    industries = "B2B SaaS"
    business_types = ""
    keywords = ""
    time = "09:00"
    max_results = 10
    max_requests = 8
    output = "outputs"


def test_scheduler_command_never_contains_the_key():
    argv = scout_schedule.build_create_argv(_Args())
    blob = " ".join(argv)
    assert "tvly-" not in blob and "TAVILY_API_KEY" not in blob        # key never in the task command
    assert "/DISABLE" in argv                                          # created disabled by default
    assert "campaign-run" in blob and "--approve-live-discovery" in blob
    cli = scout_schedule.discovery_cli_args(_Args())
    assert "tvly-" not in " ".join(cli)


def test_task_name_is_sanitized():
    assert scout_schedule.task_name("a b/c..\\d") == "AIQA-Scout-Discovery-abcd"
