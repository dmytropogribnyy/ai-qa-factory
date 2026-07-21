"""Direct Collaboration Driver v1 (Issue #14.B) — bounded, redacted evidence for one exact SHA."""
from __future__ import annotations

from core.collaboration.evidence import gather_evidence

_HEAD = "a" * 40
_BASE = "b" * 40


def _runner(mapping):
    def run(args):
        key = " ".join(args)
        for prefix, out in mapping.items():
            if key.startswith(prefix):
                return out
        return ""
    return run


def _complete_runner():
    return _runner({"rev-parse --verify": _HEAD, "diff --name-only": "core/a.py\ncore/b.py",
                    "diff --stat": " 2 files changed", "diff " + _BASE: "+ok\n" * 5,
                    "log -1": "feat: change"})


def test_verified_sha_and_completeness_flags():
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=_complete_runner())
    assert ev["sha_verified"] is True
    assert ev["git_ok"] is True
    assert ev["evidence_complete"] is True
    assert ev["incompleteness"] == []


def test_unverifiable_sha_marks_evidence_incomplete():
    # rev-parse --verify returns nothing -> the commit cannot be confirmed to exist.
    run = _runner({"diff --name-only": "core/a.py", "diff --stat": "x", "diff " + _BASE: "d",
                   "log -1": "s"})
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=run)
    assert ev["sha_verified"] is False
    assert ev["evidence_complete"] is False
    assert any("verif" in r.lower() for r in ev["incompleteness"])


def test_material_truncation_marks_incomplete():
    run = _runner({"rev-parse --verify": _HEAD, "diff --name-only": "core/a.py", "diff --stat": "x",
                   "diff " + _BASE: "+line\n" * 100000, "log -1": "s"})
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=run, max_diff_chars=400)
    assert ev["diff_truncated"] is True
    assert ev["evidence_complete"] is False


def test_pack_includes_canonical_criteria_and_manifest_contents():
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=_complete_runner(),
                         request={"body": "slice ready; full suite green"},
                         manifests={"ci": "run 123 success", "tests": "5128 passed"})
    assert "invariant" in ev["canonical_criteria"].lower()      # real content, loaded from the repo doc
    assert ev["checkpoint_manifest"] == "slice ready; full suite green"
    assert ev["manifests"]["ci"] == "run 123 success"
    assert ev["manifests"]["tests"] == "5128 passed"


def test_evidence_binds_head_sha_and_bounds_the_diff():
    big_diff = "+line\n" * 100000
    run = _runner({"diff --name-only": "core/a.py\ncore/b.py",
                   "diff --stat": " 2 files changed",
                   "diff " + _BASE: big_diff,
                   "log -1": "feat: something"})
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=run, max_diff_chars=500)
    assert ev["head_sha"] == _HEAD
    assert ev["base_sha"] == _BASE
    assert len(ev["diff_excerpt"]) <= 500
    assert ev["diff_truncated"] is True
    assert ev["commit_subject"] == "feat: something"


def test_changed_files_are_capped():
    files = "\n".join(f"core/f{i}.py" for i in range(200))
    run = _runner({"diff --name-only": files, "diff --stat": "x", "diff " + _BASE: "d",
                   "log -1": "s"})
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=run, max_files=10)
    assert len(ev["changed_files"]) == 10
    assert ev["changed_files_truncated"] is True
    assert ev["changed_files_total"] == 200


def test_evidence_is_redacted():
    run = _runner({"diff --name-only": "core/a.py", "diff --stat": "x",
                   "diff " + _BASE: "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
                   "log -1": "s"})
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=run)
    assert "abcdefghijklmnopqrstuvwxyz" not in ev["diff_excerpt"]


def test_request_evidence_refs_pass_through():
    run = _runner({"diff --name-only": "a", "diff --stat": "x", "diff " + _BASE: "d", "log -1": "s"})
    ev = gather_evidence(".", _HEAD, base_sha=_BASE, git_runner=run,
                         request={"evidence_refs": ["ci:run/123", "test:scout"],
                                  "pr_number": 14, "branch": "feat/x"})
    assert ev["evidence_refs"] == ["ci:run/123", "test:scout"]
    assert ev["pr_number"] == 14
    assert ev["branch"] == "feat/x"
