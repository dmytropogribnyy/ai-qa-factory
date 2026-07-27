"""A state write must not be lost because something was reading the file for a moment.

On Windows ``os.replace`` fails with ``PermissionError [WinError 5]`` when a concurrent reader holds
the destination — the Dashboard polling a run while the engine saves it is enough. One live
discovery run has already died that way, losing a write that had nothing wrong with it.

The retry is easy. The discipline is in what is NOT retried: a missing source, a destination that is
a directory, a genuine permission problem. Retrying those turns an immediate, clear error into a
slow, confusing one, so each has a test saying it fails on the first attempt.
"""
from __future__ import annotations

import os

import pytest

from core.atomic_io import atomic_replace


def _permission_error(winerror: int) -> PermissionError:
    """The error Windows actually raises, including the code the retry decides on."""
    exc = PermissionError(13, "Access is denied")
    exc.winerror = winerror
    return exc


class _FlakyReplace:
    """Fails a set number of times, then succeeds by doing the real thing."""

    def __init__(self, failures: int, winerror: int = 5) -> None:
        self.failures = failures
        self.winerror = winerror
        self.calls = 0
        self._real = os.replace

    def __call__(self, src, dst):
        self.calls += 1
        if self.calls <= self.failures:
            raise _permission_error(self.winerror)
        return self._real(src, dst)


@pytest.fixture()
def pair(tmp_path):
    tmp, path = tmp_path / "state.json.tmp", tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")
    tmp.write_text("new", encoding="utf-8")
    return tmp, path


@pytest.mark.parametrize("failures", [1, 2, 4])
def test_a_transient_lock_is_waited_out(pair, monkeypatch, failures):
    tmp, path = pair
    flaky = _FlakyReplace(failures)
    monkeypatch.setattr(os, "replace", flaky)

    atomic_replace(tmp, path)

    assert path.read_text(encoding="utf-8") == "new"
    assert flaky.calls == failures + 1
    assert not tmp.exists()                    # nothing temporary is left behind


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_every_sharing_violation_code_is_treated_as_transient(pair, monkeypatch, winerror):
    tmp, path = pair
    flaky = _FlakyReplace(1, winerror=winerror)
    monkeypatch.setattr(os, "replace", flaky)

    atomic_replace(tmp, path)

    assert path.read_text(encoding="utf-8") == "new"


def test_a_lock_that_never_clears_surfaces_the_original_error(pair, monkeypatch):
    """The winerror a reader will search for must survive the retry loop."""
    tmp, path = pair
    always = _FlakyReplace(99)
    monkeypatch.setattr(os, "replace", always)

    with pytest.raises(PermissionError) as raised:
        atomic_replace(tmp, path, attempts=4)

    assert always.calls == 4
    assert raised.value.winerror == 5
    assert "still failing after 4 attempts" in str(raised.value)
    assert path.read_text(encoding="utf-8") == "old"     # the last good content is intact


def test_the_loop_is_bounded_and_cannot_spin(pair, monkeypatch):
    tmp, path = pair
    always = _FlakyReplace(10_000)
    monkeypatch.setattr(os, "replace", always)

    with pytest.raises(PermissionError):
        atomic_replace(tmp, path)

    assert always.calls <= 5


def test_a_missing_source_fails_at_once_rather_than_being_retried(tmp_path, monkeypatch):
    calls = []
    real = os.replace

    def counting(src, dst):
        calls.append(src)
        return real(src, dst)

    monkeypatch.setattr(os, "replace", counting)

    with pytest.raises(FileNotFoundError):
        atomic_replace(tmp_path / "never-written.tmp", tmp_path / "state.json")

    assert len(calls) == 1


def test_a_permanent_permission_problem_is_not_retried(pair, monkeypatch):
    """A read-only destination fails the same way on the fifth attempt as on the first."""
    tmp, path = pair
    exc = PermissionError(13, "Access is denied")
    exc.winerror = 1920            # ERROR_CANT_ACCESS_FILE — not a contention code
    calls = []

    def always_denied(src, dst):
        calls.append(src)
        raise exc

    monkeypatch.setattr(os, "replace", always_denied)

    with pytest.raises(PermissionError):
        atomic_replace(tmp, path)

    assert len(calls) == 1


def test_a_posix_permission_error_is_not_retried(pair, monkeypatch):
    """Without a winerror there is no contention to wait out — it is a real permission error."""
    calls = []

    def denied(src, dst):
        calls.append(src)
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", denied)

    with pytest.raises(PermissionError):
        atomic_replace(*pair)

    assert len(calls) == 1


def test_a_destination_that_is_a_directory_is_not_retried(tmp_path, monkeypatch):
    tmp = tmp_path / "x.tmp"
    tmp.write_text("new", encoding="utf-8")
    target = tmp_path / "adirectory"
    target.mkdir()
    calls = []

    def contended(src, dst):
        calls.append(src)
        raise _permission_error(5)

    monkeypatch.setattr(os, "replace", contended)

    with pytest.raises(PermissionError):
        atomic_replace(tmp, target)

    assert len(calls) == 1


def test_the_write_happens_exactly_once_however_many_attempts_it_took(tmp_path, monkeypatch):
    """A retry re-attempts the SAME rename; it never re-runs whatever produced the content."""
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-1")
    produced = []

    def counting_state(state):
        produced.append(state)
        return state

    flaky = _FlakyReplace(2)
    monkeypatch.setattr(os, "replace", flaky)

    store.save_state(counting_state({"status": "COMPLETED", "prospects": {}}))

    assert len(produced) == 1
    assert flaky.calls == 3
    assert store.load_state()["status"] == "COMPLETED"


def test_a_real_store_survives_a_reader_holding_the_file(tmp_path, monkeypatch):
    """The end-to-end shape of the reported failure, through the store that suffered it."""
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-2")
    store.save_state({"status": "RUNNING", "prospects": {}})
    monkeypatch.setattr(os, "replace", _FlakyReplace(3))

    store.save_state({"status": "COMPLETED", "prospects": {"01": {"status": "DONE"}}})

    assert store.load_state()["status"] == "COMPLETED"
    assert not list(store.root.glob("*.tmp"))
