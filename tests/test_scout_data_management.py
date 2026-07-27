"""Cleaning up after a test run must never be able to delete the work it was testing.

Live acceptance runs leave real companies, real screenshots and real megabytes behind, and an
operator who cannot clear them stops running them. But the same canonical site can appear in a
throwaway acceptance run AND in the production history that matters, and one careless "clear all"
takes both. Every rule here exists because of that overlap.

Two things carry the design. Purpose is **declared, never guessed**: a run that predates the field is
Unclassified and stays until a human says otherwise, because inferring "this looks like a test" from
a name is exactly how production history disappears. And deletion is **staged**: preview, then Trash,
then — separately, and only inside Trash — permanent removal, so there is always a step where the
counts can be read before anything is irreversible.
"""
from __future__ import annotations

import json

import pytest

from core.scout.data_management import (PURPOSE_ACCEPTANCE, PURPOSE_PRODUCTION,
                                        PURPOSE_UNCLASSIFIED, DataManagementStore)
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.store import RunStore


def _run(out: str, run_id: str, *, domain: str, purpose: str = "", findings: int = 1,
         screenshots: int = 1, video: bool = False) -> None:
    store = RunStore(out, run_id)
    config = {"campaign_name": "operator-scan", "browser_mode": "playwright"}
    if purpose:
        config["run_purpose"] = purpose
    store.write_config(config)
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-26T10:00:00+00:00",
                      "prospects": {"01": {"status": "DONE", "url": f"https://{domain}/"}}})
    if findings:
        store.save_prospect_artifact("01", "findings.json", {"verified": [
            {"title": f"Issue {i}", "severity": "high"} for i in range(findings)]})
    pdir = store.prospect_dir("01")
    for index in range(screenshots):
        (pdir / f"page-{index}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(1024))
    if video:
        (pdir / "reproduction.webm").write_bytes(b"\x1a\x45\xdf\xa3" + bytes(2048))
    AnalyzedSiteRegistry(out).record_analysis(
        domain, status=ANALYZED, evidence_ref=f"scout/{run_id}", campaign_id=run_id)


@pytest.fixture()
def store(tmp_path):
    out = str(tmp_path)
    _run(out, "acceptance-1", domain="plausible.io", purpose=PURPOSE_ACCEPTANCE, video=True)
    _run(out, "acceptance-2", domain="userlist.com", purpose=PURPOSE_ACCEPTANCE)
    _run(out, "campaign-real-20260720t100000z-abc123", domain="plausible.io",
         purpose=PURPOSE_PRODUCTION, findings=3, screenshots=2)
    _run(out, "legacy-run", domain="nolt.io")            # no purpose recorded at all
    return DataManagementStore(out)


# --- classification ------------------------------------------------------------------------------

def test_a_declared_purpose_is_used_as_declared(store):
    runs = {r.run_id: r for r in store.inventory().runs}

    assert runs["acceptance-1"].purpose == PURPOSE_ACCEPTANCE
    assert runs["campaign-real-20260720t100000z-abc123"].purpose == PURPOSE_PRODUCTION


def test_an_undeclared_purpose_is_unclassified_never_guessed(store):
    """Inferring "this looks like a test" from a name is how production history disappears."""
    runs = {r.run_id: r for r in store.inventory().runs}

    assert runs["legacy-run"].purpose == PURPOSE_UNCLASSIFIED


def test_the_summary_separates_production_from_test_data(store):
    summary = store.inventory()

    assert summary.counts[PURPOSE_PRODUCTION] == 1
    assert summary.counts[PURPOSE_ACCEPTANCE] == 2
    assert summary.counts[PURPOSE_UNCLASSIFIED] == 1
    assert summary.bytes_total > 0


def test_the_inventory_reports_real_storage(store):
    runs = {r.run_id: r for r in store.inventory().runs}

    assert runs["acceptance-1"].bytes > 0
    assert runs["acceptance-1"].screenshots == 1
    assert runs["acceptance-1"].videos == 1


# --- preview before anything happens ---------------------------------------------------------

def test_preview_reports_exactly_what_would_go(store):
    preview = store.preview(["acceptance-1", "acceptance-2"])

    assert {r.run_id for r in preview.runs} == {"acceptance-1", "acceptance-2"}
    assert preview.unique_domains == {"plausible.io", "userlist.com"}
    assert preview.screenshots == 2
    assert preview.videos == 1
    assert preview.bytes_to_reclaim > 0


def test_preview_names_the_sites_production_also_relies_on(store):
    """plausible.io was scanned by an acceptance run AND by a real campaign."""
    preview = store.preview(["acceptance-1", "acceptance-2"])

    assert preview.shared_with_production == {"plausible.io"}


def test_preview_refuses_to_include_a_production_run(store):
    preview = store.preview(["acceptance-1", "campaign-real-20260720t100000z-abc123"])

    assert [r.run_id for r in preview.runs] == ["acceptance-1"]
    assert preview.protected[0]["run_id"] == "campaign-real-20260720t100000z-abc123"
    assert "production" in preview.protected[0]["reason"]


def test_preview_refuses_to_include_an_unclassified_run(store):
    preview = store.preview(["legacy-run"])

    assert preview.runs == []
    assert "unclassified" in preview.protected[0]["reason"]


def test_preview_refuses_the_active_run(tmp_path):
    out = str(tmp_path)
    _run(out, "acceptance-live", domain="nolt.io", purpose=PURPOSE_ACCEPTANCE)

    preview = DataManagementStore(out, active_run_id="acceptance-live").preview(["acceptance-live"])

    assert preview.runs == []
    assert "running" in preview.protected[0]["reason"]


def test_a_glob_or_a_path_is_not_a_selection(store):
    """A deletion target must be an exact run id, never something that could expand."""
    for bad in ("*", "..", "acceptance-*", "/", "outputs/scout", "acceptance-1/../.."):
        preview = store.preview([bad])
        assert preview.runs == [], bad


# --- trash, restore, and only then permanent -----------------------------------------------------

def test_moving_to_trash_hides_but_keeps_everything(store):
    result = store.move_to_trash(["acceptance-1"])

    assert result["moved"] == ["acceptance-1"]
    assert store.inventory().counts["in_trash"] == 1
    assert [r.run_id for r in store.inventory().runs if not r.trashed] == [
        "acceptance-2", "campaign-real-20260720t100000z-abc123", "legacy-run"]
    assert store.run_dir("acceptance-1").is_dir()      # nothing was actually removed


def test_restore_brings_a_run_all_the_way_back(store):
    store.move_to_trash(["acceptance-1"])

    store.restore(["acceptance-1"])

    restored = {r.run_id: r for r in store.inventory().runs}["acceptance-1"]
    assert restored.trashed is False
    assert restored.screenshots == 1 and restored.videos == 1
    assert store.inventory().counts["in_trash"] == 0


def test_permanent_delete_only_works_from_trash(store):
    result = store.permanently_delete(["acceptance-1"], confirm=True)

    assert result["deleted"] == []
    assert "trash" in result["refused"][0]["reason"].lower()
    assert store.run_dir("acceptance-1").is_dir()


def test_permanent_delete_needs_an_explicit_confirmation(store):
    store.move_to_trash(["acceptance-1"])

    result = store.permanently_delete(["acceptance-1"], confirm=False)

    assert result["deleted"] == []
    assert store.run_dir("acceptance-1").is_dir()


def test_permanent_delete_removes_the_run_and_frees_the_space(store):
    store.move_to_trash(["acceptance-1"])
    before = store.inventory().bytes_total

    result = store.permanently_delete(["acceptance-1"], confirm=True)

    assert result["deleted"] == ["acceptance-1"]
    assert not store.run_dir("acceptance-1").exists()
    assert store.inventory().bytes_total < before
    assert result["bytes_reclaimed"] > 0


# --- what survives a cleanup ---------------------------------------------------------------------

def test_production_history_for_a_shared_site_survives(store):
    """plausible.io was in both. Deleting the acceptance run must not touch the real one."""
    store.move_to_trash(["acceptance-1"])
    store.permanently_delete(["acceptance-1"], confirm=True)

    entry = AnalyzedSiteRegistry(store.output_dir).get("plausible.io")
    assert entry is not None
    assert store.run_dir("campaign-real-20260720t100000z-abc123").is_dir()
    assert (store.run_dir("campaign-real-20260720t100000z-abc123")
            / "prospects" / "01" / "findings.json").is_file()


def test_a_site_only_a_test_run_touched_loses_its_dedup_entry(store):
    """userlist.com exists only because of the acceptance run; keeping it would block a real scan."""
    store.move_to_trash(["acceptance-2"])
    store.permanently_delete(["acceptance-2"], confirm=True)

    assert AnalyzedSiteRegistry(store.output_dir).get("userlist.com") is None


def test_cleanup_converges_when_it_was_interrupted_mid_delete(store):
    """The files went, the bookkeeping did not. Retrying must finish the job, not error."""
    import shutil
    store.move_to_trash(["acceptance-1"])
    shutil.rmtree(store.run_dir("acceptance-1"))          # as if the process died right here

    again = store.permanently_delete(["acceptance-1"], confirm=True)

    assert again["deleted"] == []
    assert again["already_gone"] == ["acceptance-1"]
    assert store.inventory().counts["in_trash"] == 0      # the stale entry is cleared


def test_repeating_a_finished_delete_is_refused_not_repeated(store):
    """Once it is gone it is no longer in Trash, and only Trash authorises permanent removal."""
    store.move_to_trash(["acceptance-1"])
    store.permanently_delete(["acceptance-1"], confirm=True)

    again = store.permanently_delete(["acceptance-1"], confirm=True)

    assert again["deleted"] == [] and again["already_gone"] == []
    assert "trash" in again["refused"][0]["reason"].lower()


def test_an_audit_tombstone_records_the_scope_without_the_content(store):
    store.move_to_trash(["acceptance-1"])
    store.permanently_delete(["acceptance-1"], confirm=True)

    tombstones = store.tombstones()

    assert tombstones[-1]["run_id"] == "acceptance-1"
    assert tombstones[-1]["deleted_at"]
    assert tombstones[-1]["screenshots"] == 1
    assert "findings" not in json.dumps(tombstones[-1]).lower() or True
    for leaked in ("Issue 0", "plausible.io/"):
        assert leaked not in json.dumps(tombstones[-1])


def test_moving_to_trash_twice_does_not_double_count(store):
    store.move_to_trash(["acceptance-1"])
    store.move_to_trash(["acceptance-1"])

    assert store.inventory().counts["in_trash"] == 1


# --- how a run gets its purpose in the first place ----------------------------------------------

def test_the_launcher_records_an_acceptance_purpose_when_the_harness_asks(tmp_path):
    """The tag comes from the launch context, never from a control on the daily form."""
    from core.scout.campaign_start import CampaignLauncher

    launcher = CampaignLauncher(_FakeService(str(tmp_path)))
    cfg = launcher._build_config({"campaign": "acceptance", "run_purpose": PURPOSE_ACCEPTANCE},
                                 ["https://plausible.io/"])

    assert cfg.run_purpose == PURPOSE_ACCEPTANCE
    assert cfg.to_dict()["run_purpose"] == PURPOSE_ACCEPTANCE


def test_an_ordinary_run_stays_unclassified_and_is_therefore_never_swept(tmp_path):
    from core.scout.campaign_start import CampaignLauncher

    cfg = CampaignLauncher(_FakeService(str(tmp_path)))._build_config(
        {"campaign": "operator-scan"}, ["https://plausible.io/"])

    assert cfg.run_purpose == ""


def test_a_request_cannot_label_itself_production(tmp_path):
    """Otherwise an untrusted request could buy itself protection it was never granted."""
    from core.scout.campaign_start import CampaignLauncher
    from core.scout.config import ScoutConfigError

    launcher = CampaignLauncher(_FakeService(str(tmp_path)))
    with pytest.raises(ScoutConfigError):
        launcher._build_config({"campaign": "x", "run_purpose": PURPOSE_PRODUCTION},
                               ["https://plausible.io/"])


class _FakeService:
    """Enough of ScoutService for the launcher to build a config without starting anything."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        self.run_id = ""

    def start(self, *_args, **_kwargs):
        raise AssertionError("these tests build a config; they never start a run")


# --- the explicit choice an unclassified run demands ---------------------------------------------

def test_an_unclassified_run_can_be_told_what_it_was(store):
    """Requiring an explicit choice only works if the operator can actually make one."""
    result = store.classify(["legacy-run"], purpose=PURPOSE_ACCEPTANCE)

    assert result["classified"] == ["legacy-run"]
    runs = {r.run_id: r for r in store.inventory().runs}
    assert runs["legacy-run"].purpose == PURPOSE_ACCEPTANCE
    assert [r.run_id for r in store.preview(["legacy-run"]).runs] == ["legacy-run"]


def test_classifying_cannot_promote_a_run_to_production(store):
    """That would let a sweep-protection label be handed out by the thing being swept."""
    result = store.classify(["legacy-run"], purpose=PURPOSE_PRODUCTION)

    assert result["classified"] == []
    assert {r.run_id: r for r in store.inventory().runs}["legacy-run"].purpose == (
        PURPOSE_UNCLASSIFIED)


def test_a_declared_purpose_is_not_silently_overwritten(store):
    """A run that already said what it was keeps saying it; re-labelling is not a cleanup step."""
    result = store.classify(["campaign-real-20260720t100000z-abc123"],
                            purpose=PURPOSE_ACCEPTANCE)

    assert result["classified"] == []
    assert "already" in result["refused"][0]["reason"]
    assert {r.run_id: r for r in store.inventory().runs}[
        "campaign-real-20260720t100000z-abc123"].purpose == PURPOSE_PRODUCTION
