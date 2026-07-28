"""A crash at every boundary of a deletion, and a store that converges from each of them.

A permanent delete touches four things in a fixed order: the files are staged out of the tree, the
staged copy is removed, the registry claims are released, and Trash plus the journal are updated.
Because the order is fixed, a crash can only leave one of a few knowable shapes — and each of them
used to be invisible:

* recovery from staging existed as a method with NO CALLER anywhere in the product, so a crash left
  disk occupied by data everyone believed was gone;
* a run's claim on a SHARED site kept the deleted run's id, so History offered a link to a run that
  could not be opened;
* a claim on a site the run never held as a prospect was never swept at all;
* registry failures were caught and discarded, and the deletion still reported success.

Each test below crashes at one boundary, restarts, and asserts the store settles — and that it
settles the same way whether recovery runs once or twice.
"""
from __future__ import annotations

import json

import pytest

from core.scout.data_management import DataManagementStore
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.run_purpose import PURPOSE_ACCEPTANCE, PURPOSE_PRODUCTION
from core.scout.store import RunStore

ACCEPT = "acceptance-20260728t090000z-aaa111"
PROD = "campaign-real-20260720t100000z-bbb222"


def _make_run(out: str, run_id: str, *, domain: str, purpose: str) -> None:
    store = RunStore(out, run_id)
    store.write_config({"campaign_name": run_id, "run_purpose": purpose})
    store.save_state({"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
                      "prospects": {"01": {"status": "DONE", "url": f"https://{domain}/"}}})
    store.save_prospect_artifact("01", "findings.json",
                                 {"verified": [{"title": "Issue", "severity": "high"}]})
    (store.prospect_dir("01") / "page.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(256))
    AnalyzedSiteRegistry(out).record_analysis(domain, status=ANALYZED,
                                              evidence_ref=f"scout/{run_id}", campaign_id=run_id)


@pytest.fixture()
def out(tmp_path):
    root = str(tmp_path)
    _make_run(root, ACCEPT, domain="userlist.com", purpose=PURPOSE_ACCEPTANCE)
    _make_run(root, PROD, domain="plausible.io", purpose=PURPOSE_PRODUCTION)
    return root


def _trashed(out: str) -> DataManagementStore:
    store = DataManagementStore(out)
    store.move_to_trash([ACCEPT])
    return store


# --- boundary 1: the files were staged and the removal never happened -----------------------------

class _CrashAfterStaging(DataManagementStore):
    def _confined_rmtree(self, directory, *, root=None):
        raise KeyboardInterrupt("power cut between staging and removal")


def test_a_crash_between_staging_and_removal_is_finished_on_restart(out):
    store = _CrashAfterStaging(out)
    store.move_to_trash([ACCEPT])
    with pytest.raises(KeyboardInterrupt):
        store.permanently_delete([ACCEPT], confirm=True)

    # Restart: a fresh store over the same tree, exactly as the dashboard builds one.
    fresh = DataManagementStore(out)
    assert fresh.reconcile()["ok"] is False                 # the inconsistency is VISIBLE
    outcome = fresh.reconcile(repair=True)

    # ONE crash leaves three disagreements — files staged, a Trash entry for a run that is gone, and
    # a registry claim on a run nobody can open. A single pass has to settle all of them.
    assert {r["kind"] for r in outcome["repaired"]} == {
        "staged", "trash_without_run", "dangling_claim"}
    assert DataManagementStore(out).reconcile()["ok"] is True
    assert not (fresh.run_dir(ACCEPT)).is_dir()


def test_recovery_is_idempotent(out):
    store = _CrashAfterStaging(out)
    store.move_to_trash([ACCEPT])
    with pytest.raises(KeyboardInterrupt):
        store.permanently_delete([ACCEPT], confirm=True)

    first = DataManagementStore(out).reconcile(repair=True)
    second = DataManagementStore(out).reconcile(repair=True)

    assert first["repaired"] and second["repaired"] == []
    assert DataManagementStore(out).reconcile()["ok"] is True


# --- boundary 2: the files went and the bookkeeping did not ---------------------------------------

def test_a_trash_entry_for_a_run_that_is_already_gone_is_settled(out):
    store = _trashed(out)
    import shutil
    shutil.rmtree(store.run_dir(ACCEPT))                    # the delete finished; the crash followed

    before = DataManagementStore(out).reconcile()
    after = DataManagementStore(out).reconcile(repair=True)

    assert "trash_without_run" in [p["kind"] for p in before["problems"]]
    # The Trash entry AND the claim that belonged to it settle together: dropping one and leaving
    # the other is how a site kept pointing at a run that had already been removed.
    assert {r["kind"] for r in after["repaired"]} == {"trash_without_run", "dangling_claim"}
    assert DataManagementStore(out).reconcile()["ok"] is True


# --- boundary 3: the registry still points at a run nobody can open -------------------------------

def test_a_claim_naming_a_run_that_no_longer_exists_is_released(out):
    """History offering a link to a run that cannot be opened is the visible symptom."""
    AnalyzedSiteRegistry(out).record_analysis("plausible.io", status=ANALYZED,
                                              campaign_id="deleted-long-ago")

    problems = DataManagementStore(out).reconcile()["problems"]
    assert [p["kind"] for p in problems] == ["dangling_claim"]

    DataManagementStore(out).reconcile(repair=True)

    entry = AnalyzedSiteRegistry(out).get("plausible.io")
    assert "deleted-long-ago" not in entry.campaign_ids
    assert PROD in entry.campaign_ids                        # the real run keeps its history


# --- the deletion itself: claims, shared sites, and honest reporting ------------------------------

def test_deleting_a_run_removes_its_claim_from_a_site_it_shares(out):
    AnalyzedSiteRegistry(out).record_analysis("plausible.io", status=ANALYZED, campaign_id=ACCEPT)

    result = _trashed(out).permanently_delete([ACCEPT], confirm=True)

    entry = AnalyzedSiteRegistry(out).get("plausible.io")
    assert result["ok"] is True and result["registry_problems"] == []
    assert PROD in entry.campaign_ids                        # the surviving run keeps its claim
    assert ACCEPT not in entry.campaign_ids                  # the deleted one does not
    assert DataManagementStore(out).reconcile()["ok"] is True


def test_deleting_a_run_releases_a_claim_on_a_site_it_never_held_as_a_prospect(out):
    """A curated import registers an analysis the run's own prospect list never mentions."""
    AnalyzedSiteRegistry(out).record_analysis("imported.example", status=ANALYZED,
                                              campaign_id=ACCEPT)

    _trashed(out).permanently_delete([ACCEPT], confirm=True)

    assert AnalyzedSiteRegistry(out).get("imported.example") is None
    assert DataManagementStore(out).reconcile()["ok"] is True


def test_a_registry_failure_is_reported_rather_than_reported_as_success(out, monkeypatch):
    """The files really are gone — but a deletion that left the registry inconsistent is not ok."""
    def _boom(self, *a, **k):
        raise OSError("registry volume unavailable")

    monkeypatch.setattr(AnalyzedSiteRegistry, "forget", _boom)
    store = _trashed(out)

    result = store.permanently_delete([ACCEPT], confirm=True)

    assert result["deleted"] == [ACCEPT]                     # the removal did happen
    assert result["ok"] is False                             # and it is NOT reported as clean
    assert result["registry_problems"][0]["run_id"] == ACCEPT
    assert "OSError" in json.dumps(result["registry_problems"])


# --- a settled store reports settled ---------------------------------------------------------------

def test_an_untouched_store_is_consistent(out):
    """Without this, every test above would pass on a reconcile that always complains."""
    assert DataManagementStore(out).reconcile() == {"ok": True, "problems": [], "repaired": []}
