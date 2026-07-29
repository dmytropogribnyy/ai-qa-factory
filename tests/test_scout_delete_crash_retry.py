"""A confirmed deletion that was interrupted must be FINISHED, not merely tidied up.

A permanent delete touches four places in a fixed order: stage the files out of the tree, remove
them, release the registry claims the run held, then update Trash and the journal. The order exists
so a crash can only leave a known shape.

Recovery, though, only completed the first two. It deleted the staged files and stopped — and it
could not have done more, because everything the remaining steps need (which sites the run claimed,
how many findings it held) is read from the directory it had just destroyed. The retry then found no
directory, called the run "already gone", dropped the Trash entry and returned ``ok: True``. The
registry was left naming a run that no longer existed anywhere, so the operator got a success and a
store that ``reconcile`` immediately called broken.

What this pins: the metadata a completion needs is captured BEFORE the irreversible step, so a
recovery can release the claims, write the tombstone and close the bookkeeping from the record
rather than from the wreckage.
"""
from __future__ import annotations

import json
import shutil

import pytest

_DOMAIN = "deleted-site.example"
_RUN = "run-crashed"


class _Crash(RuntimeError):
    """Not an OSError: a compensating unstage must NOT run. This is the process dying."""


def _seed(tmp_path, *, purpose="diagnostic"):
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), _RUN)
    # config.json is immutable by design, so an undeclared run has to be seeded undeclared — it
    # cannot be un-declared afterwards.
    config = {"campaign_name": "adhoc"}
    if purpose:
        config["run_purpose"] = purpose
    store.write_config(config)
    store.save_state({"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": f"https://{_DOMAIN}/",
               "verified_findings": 2, "verified_defects": 2}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": "Broken checkout", "url": f"https://{_DOMAIN}/cart", "severity": "high",
         "signature": "cart-1"},
        {"title": "Slow first paint", "url": f"https://{_DOMAIN}/", "severity": "medium",
         "signature": "perf-1"}]})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis(_DOMAIN, status=ANALYZED,
                                                        campaign_id=_RUN)
    return store


def _claims(tmp_path, domain=_DOMAIN):
    from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
    entry = AnalyzedSiteRegistry(str(tmp_path)).get(domain)
    return list(getattr(entry, "campaign_ids", []) or []) if entry else []


def _run_dir(tmp_path):
    return tmp_path / "scout" / _RUN


def _staged(tmp_path):
    return tmp_path / "scout" / "_operator" / "_pending_delete" / _RUN


def _state_file(tmp_path):
    return tmp_path / "scout" / "_operator" / "data_management.json"


@pytest.fixture
def crashed(tmp_path, monkeypatch):
    """A store left exactly as a power loss between staging and removal leaves it."""
    from core.scout.data_management import DataManagementStore

    _seed(tmp_path)
    store = DataManagementStore(str(tmp_path))
    assert store.move_to_trash([_RUN])["moved"] == [_RUN]

    monkeypatch.setattr(DataManagementStore, "_confined_rmtree",
                        lambda self, directory, root=None: (_ for _ in ()).throw(_Crash()))
    with pytest.raises(_Crash):
        store.permanently_delete([_RUN], confirm=True)

    monkeypatch.undo()
    assert _staged(tmp_path).is_dir(), "the fixture did not reproduce the interrupted state"
    assert _claims(tmp_path) == [_RUN], "the registry claim should still be there after the crash"
    return tmp_path


def test_the_retry_finishes_the_deletion(crashed):
    from core.scout.data_management import DataManagementStore

    result = DataManagementStore(str(crashed)).permanently_delete([_RUN], confirm=True)

    assert result["ok"] is True
    assert not result["registry_problems"]
    assert not _run_dir(crashed).exists()
    assert not _staged(crashed).exists()


def test_the_retry_releases_the_registry_claim(crashed):
    """The dangling claim: history naming a run nobody can open."""
    from core.scout.data_management import DataManagementStore

    DataManagementStore(str(crashed)).permanently_delete([_RUN], confirm=True)

    assert _claims(crashed) == []


def test_the_store_reconciles_clean_after_the_retry(crashed):
    """The whole point. A delete that reports success and leaves the store inconsistent is a lie."""
    from core.scout.data_management import DataManagementStore

    DataManagementStore(str(crashed)).permanently_delete([_RUN], confirm=True)
    report = DataManagementStore(str(crashed)).reconcile()

    assert report["ok"] is True, report["problems"]


def test_the_tombstone_survives_the_crash_with_its_metadata(crashed):
    """Captured before the irreversible step, so what the run held is still tellable afterwards."""
    from core.scout.data_management import DataManagementStore

    DataManagementStore(str(crashed)).permanently_delete([_RUN], confirm=True)
    stones = [t for t in DataManagementStore(str(crashed)).tombstones()
              if t.get("run_id") == _RUN]

    assert len(stones) == 1
    assert stones[0]["sites"] == 1
    assert stones[0]["findings"] == 2
    assert stones[0]["purpose"] == "diagnostic"


def test_the_trash_entry_is_gone_and_the_journal_records_the_delete(crashed):
    from core.scout.data_management import DataManagementStore

    DataManagementStore(str(crashed)).permanently_delete([_RUN], confirm=True)
    state = json.loads(_state_file(crashed).read_text(encoding="utf-8"))

    assert [i for i in state["trash"] if i["run_id"] == _RUN] == []
    assert [j for j in state["journal"] if j.get("run_id") == _RUN
            and j.get("op") == "permanent_delete"]


def test_recovery_alone_converges_without_a_retry(crashed):
    """An operator who never presses Delete again still gets a consistent store: startup recovery
    is a completion, so the claims and the tombstone do not wait for a second confirmation."""
    from core.scout.data_management import DataManagementStore

    assert DataManagementStore(str(crashed)).recover_interrupted_deletes() == [_RUN]

    assert _claims(crashed) == []
    assert DataManagementStore(str(crashed)).reconcile()["ok"] is True


def test_a_trash_entry_whose_files_vanished_still_closes_its_bookkeeping(tmp_path):
    """The same lie by a quieter route: no staging, no intent, just a Trash entry naming files that
    are no longer there — an older build's recovery, or a directory removed outside the product.

    The retry called it "already gone", dropped the Trash entry and returned ok=True while the
    registry went on naming the run. Nothing about the outcome told anyone; ``reconcile`` had to be
    run separately to discover it. Whatever removed the files, the claims are this store's to
    release.
    """
    from core.scout.data_management import DataManagementStore

    _seed(tmp_path)
    store = DataManagementStore(str(tmp_path))
    store.move_to_trash([_RUN])
    shutil.rmtree(_run_dir(tmp_path))                 # the files go, the bookkeeping does not

    result = DataManagementStore(str(tmp_path)).permanently_delete([_RUN], confirm=True)

    assert result["already_gone"] == [_RUN]
    assert _claims(tmp_path) == [], "the registry still names a run that exists nowhere"
    assert DataManagementStore(str(tmp_path)).reconcile()["ok"] is True
    stones = [t for t in DataManagementStore(str(tmp_path)).tombstones() if t["run_id"] == _RUN]
    assert len(stones) == 1
    assert stones[0]["metadata"] == "lost with the files", (
        "counts nobody recorded must not be reported as zeroes")
    # A purpose the run DECLARED lives in its own config.json and went with the directory, so the
    # honest answer here is that it is no longer known — not a purpose reconstructed from a guess.
    assert stones[0]["purpose"] == "unclassified"


def test_an_operators_classification_outlives_the_files_it_described(tmp_path):
    """The other half: a decision the OPERATOR made is an overlay beside the run, not inside it, so
    a tombstone for a vanished run can still say what the operator said it was."""
    from core.scout.data_management import DataManagementStore

    store_root = tmp_path
    _seed(store_root, purpose=None)     # declares nothing: the operator's decision is all there is
    store = DataManagementStore(str(store_root))
    assert store.classify([_RUN], purpose="diagnostic")["classified"] == [_RUN]
    store.move_to_trash([_RUN])
    shutil.rmtree(_run_dir(store_root))

    DataManagementStore(str(store_root)).permanently_delete([_RUN], confirm=True)
    stone = next(t for t in DataManagementStore(str(store_root)).tombstones()
                 if t["run_id"] == _RUN)

    assert stone["purpose"] == "diagnostic"


def test_a_failed_staging_leaves_no_intent_to_roll_forward(tmp_path, monkeypatch):
    """The other side of the rule: an intent must mean "past the point of no return". If staging
    fails the operator is told the run was NOT deleted, so nothing may later complete it for them."""
    from core.scout.data_management import DataManagementStore

    _seed(tmp_path)
    store = DataManagementStore(str(tmp_path))
    store.move_to_trash([_RUN])
    monkeypatch.setattr(DataManagementStore, "_stage_for_delete",
                        lambda self, run_id, directory: (_ for _ in ()).throw(OSError("locked")))

    result = store.permanently_delete([_RUN], confirm=True)
    monkeypatch.undo()

    assert result["deleted"] == []
    assert result["refused"], "a run that could not be staged must be refused, not silently kept"
    assert _run_dir(tmp_path).is_dir(), "the run must still be there"
    assert DataManagementStore(str(tmp_path)).recover_interrupted_deletes() == []
    assert _run_dir(tmp_path).is_dir(), "recovery deleted a run the operator was told was refused"
    assert _claims(tmp_path) == [_RUN]
