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

import pytest

from core.collaboration.gate_producer import GateEvidenceError, produce_gate_manifest
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
