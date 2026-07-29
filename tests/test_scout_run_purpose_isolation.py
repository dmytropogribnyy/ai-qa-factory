"""Acceptance data is real data — it just is not the operator's work.

A release check scans plausible.io. The next morning History shows plausible.io as a company to
follow up, Overview counts it, and Needs attention offers to chase it. Nothing failed; the run was
simply indistinguishable from work. These tests pin the separation down at every point it can be
lost: at creation, on every default view, through an explicit filter, across a restart, and — the
one that actually bit — after the acceptance run itself has been deleted.
"""
from __future__ import annotations

import json

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.data_management import DataManagementStore
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.run_purpose import (PURPOSE_ACCEPTANCE, PURPOSE_PRODUCTION, PURPOSE_UNCLASSIFIED,
                                    TEST_PURPOSE_ENV, PurposeNotPermitted, RunPurposeIndex,
                                    resolve_requested_purpose)
from core.scout.store import RunStore


def _run(out: str, run_id: str, *, domain: str, purpose: str = "") -> None:
    """One completed run on disk, exactly as the engine leaves it."""
    store = RunStore(out, run_id)
    config = {"campaign_name": run_id, "browser_mode": "playwright"}
    if purpose:
        config["run_purpose"] = purpose
    store.write_config(config)
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-27T10:00:00+00:00",
                      "prospects": {"01": {"status": "DONE", "url": f"https://{domain}/"}}})
    store.save_prospect_artifact("01", "findings.json",
                                 {"verified": [{"title": "Issue", "severity": "high"}]})
    (store.prospect_dir("01") / "page.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(512))
    AnalyzedSiteRegistry(out).record_analysis(domain, status=ANALYZED,
                                              evidence_ref=f"scout/{run_id}", campaign_id=run_id)


@pytest.fixture()
def tree(tmp_path):
    """The overlap that makes this hard: one domain scanned by BOTH kinds of run."""
    out = str(tmp_path)
    _run(out, "campaign-real-20260720t100000z-abc123", domain="plausible.io",
         purpose=PURPOSE_PRODUCTION)
    _run(out, "acceptance-live-20260727t100000z-def456", domain="plausible.io",
         purpose=PURPOSE_ACCEPTANCE)
    _run(out, "acceptance-only-20260727t110000z-ghi789", domain="userlist.com",
         purpose=PURPOSE_ACCEPTANCE)
    _run(out, "legacy-run-no-purpose", domain="nolt.io")
    return out


# --- what a run is for, decided once at creation -------------------------------------------------

def test_an_ordinary_new_run_is_production_not_unclassified():
    """"Unclassified" now means only "written before this field existed"."""
    from core.scout.config import ScoutRunConfig

    cfg = ScoutRunConfig(seeds=["https://plausible.io/"])

    assert cfg.run_purpose == PURPOSE_PRODUCTION
    assert cfg.to_dict()["run_purpose"] == PURPOSE_PRODUCTION


def test_a_run_written_before_the_field_existed_stays_unclassified():
    from core.scout.config import ScoutRunConfig

    assert ScoutRunConfig.from_dict(
        {"seeds": ["https://plausible.io/"]}).run_purpose == PURPOSE_UNCLASSIFIED


def test_a_discovery_campaign_hands_its_purpose_to_every_run_it_promotes():
    """Otherwise an acceptance discovery leaves production-looking per-target runs behind it."""
    from core.scout.discovery.config import DiscoveryCampaignConfig

    cfg = DiscoveryCampaignConfig(campaign_name="acc", provider_allowlist=["tavily"],
                                  run_purpose=PURPOSE_ACCEPTANCE)

    assert cfg.to_dict()["run_purpose"] == PURPOSE_ACCEPTANCE


@pytest.mark.parametrize("requested", ["acceptance", "diagnostic", "manual_test", "MANUAL-TEST"])
def test_a_request_cannot_hand_itself_a_disposable_purpose(requested):
    with pytest.raises(PurposeNotPermitted):
        resolve_requested_purpose(requested, allow_test=False)


def test_a_server_started_for_a_harness_may_hand_out_one(monkeypatch):
    from core.scout.run_purpose import test_purposes_enabled

    monkeypatch.setenv(TEST_PURPOSE_ENV, "1")
    assert test_purposes_enabled() is True
    assert resolve_requested_purpose("acceptance", allow_test=True) == PURPOSE_ACCEPTANCE


def test_an_unknown_purpose_value_is_refused_not_silently_ignored():
    with pytest.raises(PurposeNotPermitted):
        resolve_requested_purpose("whatever-i-like", allow_test=True)


# --- the default views ---------------------------------------------------------------------------

def test_default_history_shows_production_and_hides_test_only_sites(tree):
    rows = {r["domain"] for r in CampaignService(tree).history()}

    assert "plausible.io" in rows          # production also scanned it, so it is still work
    assert "userlist.com" not in rows      # only an acceptance run ever touched it
    assert "nolt.io" in rows               # unknown provenance is treated as real, never hidden


def test_an_explicit_filter_shows_the_test_runs_without_changing_the_data(tree):
    service = CampaignService(tree)

    everything = {r["domain"] for r in service.history(filters={"purpose": "all"})}
    acceptance = {r["domain"] for r in service.history(filters={"purpose": PURPOSE_ACCEPTANCE})}

    assert {"plausible.io", "userlist.com", "nolt.io"} <= everything
    assert acceptance == {"plausible.io", "userlist.com"}
    # Reading a filtered view changed nothing: the default is exactly what it was.
    assert {r["domain"] for r in service.history()} == {"plausible.io", "nolt.io"}


def test_an_acceptance_run_does_not_move_the_production_campaign_count(tree):
    from core.scout.canonical_runs import campaign_counts

    control = __import__("pathlib").Path(tree) / "scout" / "_runcontrol"
    control.mkdir(parents=True, exist_ok=True)
    for run_id in ("campaign-real-20260720t100000z-abc123",
                   "acceptance-live-20260727t100000z-def456"):
        (control / f"{run_id}.json").write_text(json.dumps({"campaign_id": run_id}),
                                                encoding="utf-8")

    counts = campaign_counts(tree)

    # Both ids are structurally production-shaped; only the declared purpose separates them.
    assert counts["production"] == 1
    assert counts["diagnostic"] == 1


def test_the_purpose_of_a_run_survives_a_restart(tree):
    """Nothing is cached in the process: a fresh index reads the same answer off disk."""
    first = RunPurposeIndex(tree).purpose_of("acceptance-live-20260727t100000z-def456")
    second = RunPurposeIndex(tree).purpose_of("acceptance-live-20260727t100000z-def456")

    assert first == second == PURPOSE_ACCEPTANCE
    assert {r["domain"] for r in CampaignService(tree).history()} == {"plausible.io", "nolt.io"}


# --- the failure that was actually reported ------------------------------------------------------

def test_deleting_an_acceptance_run_does_not_promote_its_sites_into_production(tree):
    """The isolation must outlive the run.

    A deleted run leaves no config.json, so its purpose became unreadable and its companies
    reappeared in production History — the cleanup undoing the separation the run was created with.
    The tombstone the deletion writes is now the provenance that keeps them classified.
    """
    store = DataManagementStore(tree)
    store.move_to_trash(["acceptance-only-20260727t110000z-ghi789"])
    result = store.permanently_delete(["acceptance-only-20260727t110000z-ghi789"], confirm=True)

    assert result["deleted"] == ["acceptance-only-20260727t110000z-ghi789"]
    assert "userlist.com" not in {r["domain"] for r in CampaignService(tree).history()}


def test_deleting_an_acceptance_run_leaves_the_production_run_of_the_same_domain_whole(tree):
    store = DataManagementStore(tree)
    store.move_to_trash(["acceptance-live-20260727t100000z-def456"])
    store.permanently_delete(["acceptance-live-20260727t100000z-def456"], confirm=True)

    production = RunStore(tree, "campaign-real-20260720t100000z-abc123")
    assert production.exists()
    assert (production.prospect_dir("01") / "page.png").is_file()
    assert AnalyzedSiteRegistry(tree).get("plausible.io") is not None
    assert "plausible.io" in {r["domain"] for r in CampaignService(tree).history()}


def test_a_production_run_is_never_removable_however_it_is_asked_for(tree):
    """The spoofing direction: a purpose supplied later must not unlock a real run."""
    store = DataManagementStore(tree)

    refused = store.preview(["campaign-real-20260720t100000z-abc123"]).protected
    relabel = store.classify(["campaign-real-20260720t100000z-abc123"], purpose=PURPOSE_ACCEPTANCE)

    assert refused and "production" in refused[0]["reason"]
    assert relabel["classified"] == []
    assert store.move_to_trash(["campaign-real-20260720t100000z-abc123"])["moved"] == []
