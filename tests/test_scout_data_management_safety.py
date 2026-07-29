"""What happens when a cleanup goes wrong halfway.

Deleting a run touches three things that must agree: the files, the dedup registry, and the operator
state. The old order released the registry first and removed the files second, so a filesystem
failure left a run that still existed on disk, was missing from the registry, and would be
rediscovered as though it had never been scanned. These tests inject a failure at each seam and
assert the system lands in one of the two states an operator can act on — fully removed, or
untouched — and never between them.

The other half is the guard in front of all of it: "the run is still running" must mean a run that
is running, not merely the last one whose id the service still holds.
"""
from __future__ import annotations

import os
import shutil

import pytest

from core.scout.data_management import DataManagementStore
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.run_purpose import PURPOSE_ACCEPTANCE, PURPOSE_PRODUCTION
from core.scout.store import RunStore

ACCEPT = "acceptance-20260727t120000z-aaa111"
PROD = "campaign-real-20260720t100000z-bbb222"


def _run(out: str, run_id: str, *, domain: str, purpose: str, when: str = "2026-07-27T12:00:00+00:00"):
    store = RunStore(out, run_id)
    store.write_config({"campaign_name": run_id, "run_purpose": purpose})
    store.save_state({"status": "COMPLETED", "started_at": when,
                      "prospects": {"01": {"status": "DONE", "url": f"https://{domain}/"}}})
    store.save_prospect_artifact("01", "findings.json",
                                 {"verified": [{"title": "Issue", "severity": "high"}]})
    (store.prospect_dir("01") / "page.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(512))
    AnalyzedSiteRegistry(out).record_analysis(domain, status=ANALYZED,
                                              evidence_ref=f"scout/{run_id}", campaign_id=run_id)


@pytest.fixture()
def out(tmp_path):
    root = str(tmp_path)
    _run(root, ACCEPT, domain="userlist.com", purpose=PURPOSE_ACCEPTANCE)
    _run(root, PROD, domain="plausible.io", purpose=PURPOSE_PRODUCTION,
         when="2026-07-20T10:00:00+00:00")
    return root


def _trashed(out: str) -> DataManagementStore:
    store = DataManagementStore(out)
    store.move_to_trash([ACCEPT])
    return store


# --- the active-run guard ------------------------------------------------------------------------

def test_a_genuinely_running_run_is_protected(out):
    store = DataManagementStore(out, active_run_id=ACCEPT, run_active=True)

    assert store.preview([ACCEPT]).protected[0]["reason"] == "the run is still running"


def test_the_last_finished_run_is_not_treated_as_running(out):
    """``service.run_id`` outlives the run it names. Reading it as "active" made the most recent
    run permanently unmanageable — the one an operator is most likely to want to clear."""
    store = DataManagementStore(out, active_run_id=ACCEPT, run_active=False)

    assert store.preview([ACCEPT]).protected == []
    assert [r.run_id for r in store.preview([ACCEPT]).runs] == [ACCEPT]


def test_a_different_active_run_does_not_block_an_unrelated_one(out):
    store = DataManagementStore(out, active_run_id="some-other-run", run_active=True)

    assert store.preview([ACCEPT]).protected == []


# --- injected failures ---------------------------------------------------------------------------

def test_a_failure_before_the_move_changes_nothing(out, monkeypatch):
    store = _trashed(out)
    monkeypatch.setattr(os, "rename", lambda *_a, **_k: (_ for _ in ()).throw(OSError("locked")))

    result = store.permanently_delete([ACCEPT], confirm=True)

    assert result["deleted"] == []
    assert result["refused"][0]["run_id"] == ACCEPT
    assert RunStore(out, ACCEPT).exists()                       # files intact
    assert AnalyzedSiteRegistry(out).get("userlist.com") is not None   # registry intact


def test_a_failure_after_the_move_puts_the_run_back(out, monkeypatch):
    """The seam the old order got wrong: the registry must still own the site afterwards."""
    store = _trashed(out)
    monkeypatch.setattr(shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("busy")))

    result = store.permanently_delete([ACCEPT], confirm=True)

    assert result["deleted"] == []
    assert "restored" in result["refused"][0]["reason"]
    assert RunStore(out, ACCEPT).exists()
    assert AnalyzedSiteRegistry(out).get("userlist.com") is not None
    assert [r.run_id for r in store.inventory().runs if r.run_id == ACCEPT]


def test_a_registry_failure_after_the_files_are_gone_still_reports_the_deletion(out, monkeypatch):
    """Bookkeeping runs last precisely so it cannot strand the irreversible half."""
    import core.scout.discovery.analyzed_registry as registry_mod

    store = _trashed(out)
    monkeypatch.setattr(registry_mod.AnalyzedSiteRegistry, "forget",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("registry down")))

    result = store.permanently_delete([ACCEPT], confirm=True)

    assert result["deleted"] == [ACCEPT]
    assert not RunStore(out, ACCEPT).exists()
    assert not (store.run_dir(ACCEPT)).exists()


def test_an_interrupted_delete_is_finished_rather_than_half_undone(out, monkeypatch):
    store = _trashed(out)
    monkeypatch.setattr(shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("busy")))
    store.permanently_delete([ACCEPT], confirm=True)
    monkeypatch.undo()

    # Simulate a crash between the move and the removal by staging without completing.
    staged = store._stage_for_delete(ACCEPT, store.run_dir(ACCEPT))
    assert staged.is_dir()

    assert store.recover_interrupted_deletes() == [ACCEPT]
    assert not staged.exists()


def test_deleting_twice_converges_instead_of_erroring(out):
    store = _trashed(out)
    store.permanently_delete([ACCEPT], confirm=True)

    repeat = store.permanently_delete([ACCEPT], confirm=True)

    assert repeat["deleted"] == []
    assert repeat["refused"] or repeat["already_gone"]


def test_a_shared_domain_keeps_its_production_registry_entry(out):
    """Both runs scanned the same company; only the acceptance one is being removed."""
    AnalyzedSiteRegistry(out).record_analysis("plausible.io", status=ANALYZED,
                                              campaign_id=ACCEPT)
    store = _trashed(out)

    store.permanently_delete([ACCEPT], confirm=True)

    entry = AnalyzedSiteRegistry(out).get("plausible.io")
    assert entry is not None
    assert PROD in entry.campaign_ids                 # the surviving run keeps its claim
    # The deleted run's claim goes with the run. Left behind, History offers a link to a run that
    # cannot be opened and the site reads as having more work behind it than it has. This assertion
    # was written as `... or True` — it could not fail, and the claim was in fact never removed.
    assert ACCEPT not in entry.campaign_ids


# --- restore -------------------------------------------------------------------------------------

def test_restoring_a_run_that_is_not_in_trash_says_so(out):
    result = DataManagementStore(out).restore(["never-existed"])

    assert result["restored"] == []
    assert result["missing"][0]["reason"] == "not found in Trash"


def test_restoring_a_trashed_run_returns_it_whole(out):
    store = _trashed(out)

    result = store.restore([ACCEPT])

    assert result["restored"] == [ACCEPT]
    assert result["missing"] == []
    assert [r for r in store.inventory().runs if r.run_id == ACCEPT and not r.trashed]
    assert (RunStore(out, ACCEPT).prospect_dir("01") / "page.png").is_file()


def test_restoring_a_deleted_run_does_not_claim_success(out):
    store = _trashed(out)
    store.permanently_delete([ACCEPT], confirm=True)
    store._save({**store._state(), "trash": [{"run_id": ACCEPT, "trashed_at": "2026-07-27"}]})

    result = store.restore([ACCEPT])

    assert result["restored"] == []
    assert "no longer exists" in result["missing"][0]["reason"]


# --- filters -------------------------------------------------------------------------------------

def test_filters_narrow_the_table_without_changing_the_totals(out):
    store = DataManagementStore(out)

    everything = store.inventory()
    only_acceptance = store.inventory(filters={"purpose": PURPOSE_ACCEPTANCE})

    assert {r.run_id for r in everything.runs} == {ACCEPT, PROD}
    assert [r.run_id for r in only_acceptance.runs] == [ACCEPT]
    # The tiles describe what is STORED, so they do not shrink when the operator types.
    assert only_acceptance.counts == everything.counts
    assert only_acceptance.bytes_total == everything.bytes_total


@pytest.mark.parametrize("filters,expected", [
    ({"text": "userlist"}, [ACCEPT]),
    ({"text": "campaign-real"}, [PROD]),
    ({"run": ACCEPT}, [ACCEPT]),
    ({"since": "2026-07-25"}, [ACCEPT]),
    ({"until": "2026-07-21"}, [PROD]),
    ({"purpose": "all"}, [ACCEPT, PROD]),
    ({"purpose": PURPOSE_PRODUCTION, "text": "userlist"}, []),
])
def test_each_filter_selects_exactly_what_it_says(out, filters, expected):
    runs = DataManagementStore(out).inventory(filters=filters).runs

    assert sorted(r.run_id for r in runs) == sorted(expected)
