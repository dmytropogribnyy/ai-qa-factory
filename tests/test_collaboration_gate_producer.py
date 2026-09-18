"""Trusted gate-manifest producer (Issue #74, A3.5 item 2).

`reviewer_driver` refuses a CHECKPOINT -> GO unless a trusted CI/test manifest exists for the exact
SHA and reports success. `record_gate_manifest` existed but had **no caller anywhere outside its own
test**, so nothing ever wrote a manifest and a CHECKPOINT could only ever escalate to NEEDS_OWNER with
"no trusted CI/test manifest for this exact SHA". The bridge could answer QUESTION and PROPOSAL, but
its material gate was unreachable by construction.

The contract pinned here: a producer that **derives** the evidence from trusted mechanisms — the real
git identity, the real CI conclusion for that exact SHA, and the real exit codes of the required gates
— and never accepts a caller's "tests passed" claim.
"""
from __future__ import annotations

import inspect
import json
import os
import time

import pytest

from core.collaboration.gate_producer import (GateEvidenceError, _ci_admission,
                                              produce_gate_manifest)
from core.collaboration.manifest import build_trusted_manifest

_SHA = "a" * 40
_OTHER = "b" * 40


class _Runs:
    """Scripted command runner: maps a matched command fragment to (returncode, stdout)."""

    def __init__(self, head=_SHA, dirty="", audits=0, tests=(0, "10 passed in 1.0s")):
        self.head, self.dirty, self.audits, self.tests = head, dirty, audits, tests
        self.calls = []

    def __call__(self, cmd, **kw):
        joined = " ".join(str(c) for c in cmd)
        self.calls.append(joined)
        if "rev-parse" in joined:
            return _P(0, self.head)
        if "status" in joined:
            return _P(0, self.dirty)
        if "docs_audit" in joined or "agent_readiness" in joined:
            return _P(self.audits, "  Result: [PASS]" if self.audits == 0 else "  Result: [FAIL]")
        if "pytest" in joined:
            return _P(self.tests[0], self.tests[1])
        return _P(0, "")


class _P:
    def __init__(self, returncode, stdout=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, ""


def _ci(conclusion="success", run_id="123"):
    return lambda sha: {"conclusion": conclusion, "run_id": run_id}


# --- the core contract: evidence is derived, not claimed ---------------------------------------------
def test_producer_accepts_no_caller_supplied_test_or_audit_claim():
    """Structural: a `tests_ok=True` kwarg would reintroduce exactly the trust hole this repairs."""
    params = set(inspect.signature(produce_gate_manifest).parameters)
    for forbidden in ("tests_ok", "audits_ok", "success", "tests_passed", "tests_total",
                      "ci_conclusion"):
        assert forbidden not in params, f"producer must derive {forbidden}, never accept it"


def test_success_requires_ci_tests_and_audits_together(tmp_path):
    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_Runs())
    assert out["success"] is True
    assert out["ci_conclusion"] == "success"
    assert out["tests_ok"] is True and out["audits_ok"] is True


@pytest.mark.parametrize("kwargs,why", [
    ({"ci": "failure"}, "CI failed"),
    ({"tests": (1, "3 failed, 7 passed in 1.0s")}, "tests failed"),
    ({"audits": 1}, "audits failed"),
])
def test_any_failing_input_makes_the_gate_unsuccessful(tmp_path, kwargs, why):
    """NEGATIVE controls: each leg independently blocks success."""
    ci = _ci(kwargs.pop("ci", "success"))
    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=ci, run=_Runs(**kwargs))
    assert out["success"] is False, why


def test_real_test_counts_are_parsed_not_invented(tmp_path):
    runs = _Runs(tests=(0, "6366 passed, 5 skipped, 5 warnings in 1385.24s"))
    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=runs)
    assert out["tests_passed"] == 6366
    assert out["tests_total"] >= 6366


# --- identity: the manifest must describe the SHA it claims ------------------------------------------
def test_refuses_when_head_is_not_the_requested_sha(tmp_path):
    with pytest.raises(GateEvidenceError, match="head"):
        produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_Runs(head=_OTHER))


def test_refuses_when_the_tree_is_dirty(tmp_path):
    """A dirty tree means the gate did not measure the committed SHA."""
    with pytest.raises(GateEvidenceError, match="dirty|clean"):
        produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(),
                              run=_Runs(dirty=" M core/x.py"))


def test_refuses_a_malformed_sha(tmp_path):
    with pytest.raises((GateEvidenceError, ValueError)):
        produce_gate_manifest(str(tmp_path), ".", "abc", ci_lookup=_ci(), run=_Runs(head="abc"))


def test_refuses_when_ci_conclusion_is_unavailable(tmp_path):
    """Unknown CI is not success. Missing evidence is not PASS."""
    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=lambda sha: {}, run=_Runs())
    assert out["success"] is False


# --- it must actually unblock the reviewer gate -------------------------------------------------------
def test_manifest_is_readable_as_trusted_evidence_for_that_exact_sha(tmp_path):
    produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_Runs())
    trusted = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert trusted["present"] is True and trusted["success"] is True


def test_a_manifest_for_another_sha_does_not_satisfy_this_one(tmp_path):
    """Discriminating: the gate is SHA-bound, so a green neighbour must not unlock it."""
    produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_Runs())
    trusted = build_trusted_manifest(str(tmp_path), ".", _OTHER)
    assert trusted["present"] is False and trusted["success"] is False


def test_manifest_is_persisted_as_json_for_the_exact_sha(tmp_path):
    produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_Runs())
    path = tmp_path / "_review_relay" / "collab_gate" / f"{_SHA}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["head_sha"] == _SHA and data["success"] is True


# --- end to end: the material CHECKPOINT gate is actually reachable now --------------------------------
def _driver(tmp_path, output_root):
    """A reviewer driver whose ONLY missing ingredient is the trusted gate manifest.

    `repo_root` is the real repository so the canonical criteria genuinely load; the git runner is
    stubbed so the evidence pack is complete without depending on a specific commit existing.
    """
    from core.collaboration.budget import BudgetLedger, BudgetPolicy
    from core.collaboration.manifest import build_trusted_manifest
    from core.collaboration.reviewer_client import FixtureReviewerClient
    from core.collaboration.reviewer_driver import ReviewerDriver
    from core.collaboration.store import CollaborationStore

    def git(args):
        a = " ".join(str(x) for x in args)
        if "rev-parse" in a:
            return _SHA
        if "--name-only" in a:
            return "core/x.py\n"
        if "--stat" in a:
            return " core/x.py | 2 +-\n"
        if "--format=%s" in a:
            return "a commit subject\n"
        return "diff --git a/core/x.py b/core/x.py\n+pass\n"

    return ReviewerDriver(
        CollaborationStore(output_root),
        BudgetLedger(output_root, policy=BudgetPolicy(backoff_base_seconds=0.0)),
        FixtureReviewerClient(lambda m: {"decision_type": "DECISION", "verdict": "GO",
                                         "reviewed_sha": _SHA, "message": "scope verified"}),
        repo_root=".", head_resolver=lambda: _SHA, git_runner=git,
        manifest_provider=lambda sha: build_trusted_manifest(output_root, ".", sha))


def _checkpoint(output_root):
    from core.collaboration.service import submit_worker_message
    submit_worker_message(output_root, kind="CHECKPOINT", thread_id="t-gate", body="slice ready",
                          head_sha=_SHA, branch="main", requested_next_action="GO/NO-GO")


def test_without_a_manifest_a_checkpoint_still_escalates(tmp_path):
    """NEGATIVE control — this is the behaviour observed before the producer existed, and it must
    remain the behaviour whenever trusted evidence is genuinely absent."""
    root = str(tmp_path)
    _checkpoint(root)
    out = _driver(tmp_path, root).process_once()
    assert out["status"] == "needs_owner"


def test_with_a_produced_manifest_a_checkpoint_can_reach_go(tmp_path):
    """The repair: the material gate is reachable when the evidence genuinely supports it."""
    root = str(tmp_path)
    produce_gate_manifest(root, ".", _SHA, ci_lookup=_ci(), run=_Runs())
    _checkpoint(root)
    out = _driver(tmp_path, root).process_once()
    assert out["status"] == "reviewed", out
    assert out["verdict"] == "GO"


def test_a_failing_gate_manifest_still_blocks_go(tmp_path):
    """Discriminating: it is the EVIDENCE that unlocks GO, not merely the file's existence."""
    root = str(tmp_path)
    produce_gate_manifest(root, ".", _SHA, ci_lookup=_ci("failure"), run=_Runs())
    _checkpoint(root)
    out = _driver(tmp_path, root).process_once()
    assert out["status"] == "needs_owner"


def test_ruff_is_part_of_the_derived_gate(tmp_path):
    """CLAUDE.md's required gate is ruff + pytest + docs audit + agent readiness. A manifest that
    never ran ruff could unlock GO on a SHA that fails the repository's own lint gate."""
    runs = _Runs()
    produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=runs)
    assert any("ruff" in c for c in runs.calls), f"ruff never ran: {runs.calls}"


def test_a_ruff_failure_blocks_success(tmp_path):
    """NEGATIVE control: including ruff is worthless unless its failure actually blocks."""
    class _RuffFails(_Runs):
        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            self.calls.append(joined)
            if "ruff" in joined:
                return _P(1, "1 error found")
            return super().__call__(cmd, **kw)

    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_RuffFails())
    assert out["success"] is False


def test_identity_is_revalidated_after_the_long_running_gate(tmp_path):
    """TOCTOU: the gate takes 20+ minutes. If HEAD advances or the tree goes dirty while ruff, the
    audits and the full suite run, the manifest would still be persisted for the REQUESTED sha while
    the commands measured a different checkout - exact-SHA GO on mismatched evidence."""
    class _MovesAfterChecks(_Runs):
        def __init__(self):
            super().__init__()
            self.head_reads = 0

        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if "rev-parse" in joined:
                self.head_reads += 1
                # first read: the requested sha; after the gate ran, HEAD has moved on
                return _P(0, _SHA if self.head_reads == 1 else _OTHER)
            return super().__call__(cmd, **kw)

    runs = _MovesAfterChecks()
    with pytest.raises(GateEvidenceError, match="head|moved|changed"):
        produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=runs)
    assert not (tmp_path / "_review_relay" / "collab_gate" / f"{_SHA}.json").exists(), \
        "a manifest was persisted even though the checkout moved during the gate"


def test_a_tree_dirtied_during_the_gate_is_refused(tmp_path):
    class _DirtiesAfterChecks(_Runs):
        def __init__(self):
            super().__init__()
            self.status_reads = 0

        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if "status" in joined:
                self.status_reads += 1
                return _P(0, "" if self.status_reads == 1 else " M core/x.py")
            return super().__call__(cmd, **kw)

    with pytest.raises(GateEvidenceError, match="dirty|clean|changed"):
        produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_DirtiesAfterChecks())


@pytest.mark.parametrize("failing", ["rev-parse", "status"])
def test_a_failed_git_command_is_not_treated_as_a_clean_checkout(tmp_path, failing):
    """Empty stdout from a FAILED git command is not evidence of a clean tree. A transient
    repository or permission failure must refuse, not silently look like "nothing modified"."""
    class _GitFails(_Runs):
        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if failing in joined:
                return _P(128, "")          # non-zero, empty output
            return super().__call__(cmd, **kw)

    with pytest.raises(GateEvidenceError):
        produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_GitFails())
    assert not (tmp_path / "_review_relay" / "collab_gate" / f"{_SHA}.json").exists()
# --- exact-SHA REQUIRED-check admission ---------------------------------------------------------
#
# The first version asked `gh run list --commit <sha> --limit 1` and treated the answer as "CI
# passed". That cannot establish what it was used for: one SHA carries many workflow runs. On the
# very head this was written against, the Copilot review run SUCCEEDED while the CI run FAILED, so
# the single latest run was a review bot and the manifest would have unlocked an exact-SHA GO on a
# red build. Each test below fails against that implementation.

_REQUIRED = ["fast", "meta", "windows-full"]


def _run(name, conclusion, status="completed", at="2026-09-18T11:00:00Z"):
    return {"name": name, "status": status, "conclusion": conclusion, "completed_at": at}


def test_an_unrelated_successful_run_never_satisfies_a_failed_required_check():
    """The concrete shape observed on this PR: review bot green, required CI red."""
    runs = [_run("Running Copilot Code Review", "success", at="2026-09-18T11:30:00Z"),
            _run("fast", "failure"), _run("meta", "success"), _run("windows-full", "success")]
    conclusion, detail = _ci_admission(_REQUIRED, runs)
    assert conclusion != "success"
    assert "fast" in detail and "failure" in detail


def test_an_unrelated_successful_run_never_satisfies_an_in_progress_required_check():
    runs = [_run("Running Copilot Code Review", "success", at="2026-09-18T11:30:00Z"),
            _run("fast", None, status="in_progress", at=""),
            _run("meta", "success"), _run("windows-full", "success")]
    conclusion, detail = _ci_admission(_REQUIRED, runs)
    assert conclusion != "success"
    assert "in_progress" in detail


def test_a_required_check_with_no_run_at_all_is_not_success():
    """Absent evidence is the easiest thing to read as a pass, so it gets its own control."""
    runs = [_run("Running Copilot Code Review", "success"), _run("fast", "success"),
            _run("meta", "success")]
    conclusion, detail = _ci_admission(_REQUIRED, runs)
    assert conclusion != "success"
    assert "windows-full" in detail and "no check run" in detail


def test_all_required_green_with_an_intentional_skip_is_success():
    """A skipped required context is GitHub's own "satisfied", which the tiered CI depends on."""
    runs = [_run("Running Copilot Code Review", "failure"), _run("fast", "success"),
            _run("meta", "success"), _run("windows-full", "skipped")]
    conclusion, _ = _ci_admission(_REQUIRED, runs)
    assert conclusion == "success"


def test_the_most_recent_record_of_a_rerun_check_is_the_one_that_counts():
    """A re-run leaves the earlier record in place, and the two disagree."""
    runs = [_run("fast", "failure", at="2026-09-18T10:00:00Z"),
            _run("fast", "success", at="2026-09-18T12:00:00Z"),
            _run("meta", "success"), _run("windows-full", "success")]
    assert _ci_admission(_REQUIRED, runs)[0] == "success"

    stale_green = [_run("fast", "success", at="2026-09-18T10:00:00Z"),
                   _run("fast", "failure", at="2026-09-18T12:00:00Z"),
                   _run("meta", "success"), _run("windows-full", "success")]
    assert _ci_admission(_REQUIRED, stale_green)[0] != "success"


def test_without_a_machine_readable_required_set_the_evidence_is_not_admission_ready():
    """Fail closed rather than invent a second required-check configuration beside the canonical one."""
    runs = [_run("fast", "success"), _run("meta", "success")]
    conclusion, detail = _ci_admission(None, runs)
    assert conclusion != "success"
    assert "no machine-readable required-check set" in detail


def test_an_unreadable_check_state_is_not_success():
    conclusion, detail = _ci_admission(_REQUIRED, None)
    assert conclusion != "success"
    assert "could not be read" in detail


# --- the gate must measure ONE tree, and nothing may write to it while it runs -------------------

class _RunsWithTree(_Runs):
    """Answers `rev-parse HEAD^{tree}` from a script, so the tree can move mid-gate."""

    def __init__(self, trees, **kw):
        super().__init__(**kw)
        self.trees = list(trees)

    def __call__(self, cmd, **kw):
        joined = " ".join(str(c) for c in cmd)
        if "HEAD^{tree}" in joined:
            self.calls.append(joined)
            return _P(0, self.trees.pop(0) if len(self.trees) > 1 else self.trees[0])
        return super().__call__(cmd, **kw)


def test_a_tree_that_moves_during_the_gate_refuses_the_manifest(tmp_path):
    with pytest.raises(GateEvidenceError, match="measured tree changed"):
        produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(),
                              run=_RunsWithTree(["c" * 40, "d" * 40]))


def test_a_stable_tree_still_produces_a_manifest(tmp_path):
    """The control for the test above: without the mutation it must still succeed."""
    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(),
                                run=_RunsWithTree(["c" * 40]))
    assert out["success"] is True


def test_a_tracked_file_written_during_the_gate_refuses_the_manifest(tmp_path):
    """The hole a before/after clean check cannot see.

    A writer that modifies a tracked file and restores it before the final check leaves `status
    --porcelain` clean and the content identical, while the gates measured different bytes. The
    write itself is the evidence, so the mtime watermark is what closes it.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = repo / "module.py"
    tracked.write_bytes(b"original")

    class _WritesMidGate(_Runs):
        def __init__(self):
            super().__init__()
            self.listings = 0

        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if "ls-files" in joined:
                self.listings += 1
                if self.listings == 2:
                    # modified and restored: same bytes, same status, different write
                    tracked.write_bytes(b"original")
                    later = time.time() + 30
                    os.utime(tracked, (later, later))
                return _P(0, "module.py\0")
            return super().__call__(cmd, **kw)

    with pytest.raises(GateEvidenceError, match="worktree was written to while the gate"):
        produce_gate_manifest(str(tmp_path / "out"), str(repo), _SHA,
                              ci_lookup=_ci(), run=_WritesMidGate())


def test_an_untouched_worktree_passes_the_watermark_check(tmp_path):
    """Control: the watermark must not refuse a checkout nobody wrote to."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_bytes(b"original")

    class _Quiet(_Runs):
        def __call__(self, cmd, **kw):
            if "ls-files" in " ".join(str(c) for c in cmd):
                return _P(0, "module.py\0")
            return super().__call__(cmd, **kw)

    out = produce_gate_manifest(str(tmp_path / "out"), str(repo), _SHA,
                                ci_lookup=_ci(), run=_Quiet())
    assert out["success"] is True
def test_an_in_progress_rerun_blocks_even_though_an_older_record_succeeded():
    """The ordering hole: an active re-run has no `completed_at`, so it sorts BELOW the record it
    supersedes. Selecting "the latest" and then testing its status would discard it and report
    success for a required check that is at that moment still running.
    """
    runs = [_run("fast", "success", at="2026-09-18T10:00:00Z"),
            _run("fast", None, status="in_progress", at=""),
            _run("meta", "success"), _run("windows-full", "success")]
    conclusion, detail = _ci_admission(_REQUIRED, runs)
    assert conclusion != "success", "an active re-run of a required check must block"
    assert "in_progress" in detail

    # Control: the same records once the re-run has completed green.
    finished = [_run("fast", "success", at="2026-09-18T10:00:00Z"),
                _run("fast", "success", at="2026-09-18T12:00:00Z"),
                _run("meta", "success"), _run("windows-full", "success")]
    assert _ci_admission(_REQUIRED, finished)[0] == "success"


def test_a_queued_rerun_blocks_for_the_same_reason():
    runs = [_run("meta", "success", at="2026-09-18T10:00:00Z"),
            _run("meta", None, status="queued", at=""),
            _run("fast", "success"), _run("windows-full", "success")]
    assert _ci_admission(_REQUIRED, runs)[0] != "success"


def test_an_untracked_file_injected_and_removed_during_the_gate_refuses(tmp_path):
    """The sibling of the tracked-file hole, and the one the first watermark missed.

    A writer can ADD a `tests/*.py`, let `pytest tests/` collect it, and remove it before the final
    check. No tracked mtime moves and the commit tree is unchanged, yet the gate measured bytes that
    are not in the requested SHA. The trace a create-and-delete leaves is on the parent DIRECTORY,
    which is why the watermark covers directories and not only files.
    """
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "real.py").write_bytes(b"real")

    class _InjectsUntracked(_Runs):
        def __init__(self):
            super().__init__()
            self.listings = 0

        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if "ls-files" in joined:
                self.listings += 1
                if self.listings == 2:
                    # created and removed while the gate ran: nothing is left to stat
                    transient = repo / "tests" / "transient.py"
                    transient.write_bytes(b"injected")
                    transient.unlink()
                    later = time.time() + 30
                    os.utime(repo / "tests", (later, later))
                return _P(0, "tests/real.py\0")
            return super().__call__(cmd, **kw)

    with pytest.raises(GateEvidenceError, match="worktree was written to while the gate"):
        produce_gate_manifest(str(tmp_path / "out"), str(repo), _SHA,
                              ci_lookup=_ci(), run=_InjectsUntracked())


def test_the_watermark_enumerates_untracked_files_too(tmp_path):
    """Structural: a tracked-only listing cannot see an untracked file that is still present."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "kept.py").write_bytes(b"x")
    seen = []

    class _Records(_Runs):
        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if "ls-files" in joined:
                seen.append(joined)
                return _P(0, "kept.py\0")
            return super().__call__(cmd, **kw)

    produce_gate_manifest(str(tmp_path / "out"), str(repo), _SHA, ci_lookup=_ci(), run=_Records())
    assert seen, "the gate never listed the worktree"
    for call in seen:
        assert "--others" in call and "--exclude-standard" in call, (
            "the watermark must include untracked-but-not-ignored files, or a file injected into "
            "tests/ during the gate is invisible to it: " + call)
# --- a required check is only satisfied by the app that is required ------------------------------

def _run_app(name, conclusion, app_id, at="2026-09-18T11:00:00Z"):
    return {"name": name, "status": "completed", "conclusion": conclusion,
            "completed_at": at, "app_id": app_id}


def test_a_same_named_check_from_another_app_does_not_satisfy_the_requirement():
    """Branch protection binds a required check to the App that produces it.

    Dropping the binding and matching on name alone means any installed app - or anything that can
    create a check run - can publish a green `fast` and satisfy the gate.
    """
    required = [{"context": "fast", "app_id": 15368}]
    impostor = [_run_app("fast", "success", 99999)]
    conclusion, detail = _ci_admission(required, impostor)
    assert conclusion != "success"
    assert "required app" in detail

    genuine = [_run_app("fast", "success", 15368)]
    assert _ci_admission(required, genuine)[0] == "success"


def test_an_unverifiable_producing_app_fails_closed():
    """A check run with no app identity cannot be shown to be the required one."""
    required = [{"context": "fast", "app_id": 15368}]
    conclusion, detail = _ci_admission(required, [_run_app("fast", "success", None)])
    assert conclusion != "success"
    assert "could not be verified" in detail


def test_a_requirement_without_an_app_binding_still_matches_by_name():
    """Control: the older `contexts` shape carries no app, and must keep working."""
    assert _ci_admission(["fast"], [_run_app("fast", "success", 12345)])[0] == "success"


# --- the worktree snapshot must be per-path, not one global maximum ------------------------------

def test_a_file_restored_below_the_mtime_maximum_is_still_detected(tmp_path):
    """The defeat of a global maximum, made concrete.

    Two files: one recent (it sets the maximum) and one old. A writer touches the OLD one during
    the gate and leaves its mtime still below the maximum. The maximum, the file count, the tree
    hash and `status --porcelain` are all unchanged - only a per-path snapshot sees it.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    old_file, recent = repo / "old.py", repo / "recent.py"
    old_file.write_bytes(b"old")
    recent.write_bytes(b"recent")
    now = time.time()
    os.utime(old_file, (now - 10000, now - 10000))
    os.utime(recent, (now, now))          # `recent` holds the maximum throughout

    class _TouchesTheOldFile(_Runs):
        def __init__(self):
            super().__init__()
            self.listings = 0

        def __call__(self, cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if "ls-files" in joined:
                self.listings += 1
                if self.listings == 2:
                    # modified and restored, mtime moved but still far BELOW the maximum
                    old_file.write_bytes(b"old")
                    os.utime(old_file, (now - 5000, now - 5000))
                return _P(0, "old.py\0recent.py\0")
            return super().__call__(cmd, **kw)

    with pytest.raises(GateEvidenceError, match="worktree was written to while the gate"):
        produce_gate_manifest(str(tmp_path / "out"), str(repo), _SHA,
                              ci_lookup=_ci(), run=_TouchesTheOldFile())


# --- the CI state must be read AFTER the long gate, not before it --------------------------------

def test_ci_that_goes_red_during_the_gate_does_not_persist_the_pre_gate_success(tmp_path):
    """The audits and the full suite take many minutes; a required check can change inside that.

    Reading CI once before the gate and persisting that answer authorises an exact-SHA GO on a
    state that no longer holds - the same time-of-check/time-of-use shape as the identity
    re-validation, one field over.
    """
    calls = []

    def _flaps(sha):
        calls.append(sha)
        if len(calls) == 1:
            return {"conclusion": "success", "run_id": "1", "detail": "all required checks green"}
        return {"conclusion": "", "run_id": "1", "detail": "required checks not satisfied: fast: failure"}

    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_flaps, run=_Runs())
    assert len(calls) >= 2, "the CI state must be re-read after the gate, not only before it"
    assert out["success"] is False, "a pre-gate success must not survive CI going red during the gate"
    assert "CHANGED during the gate" in out["notes"]


def test_ci_that_stays_green_across_the_gate_still_succeeds(tmp_path):
    """Control: re-reading must not make a stable green gate fail."""
    out = produce_gate_manifest(str(tmp_path), ".", _SHA, ci_lookup=_ci(), run=_Runs())
    assert out["success"] is True
