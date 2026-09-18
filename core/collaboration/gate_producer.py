"""Trusted gate-manifest producer (Issue #74 A3.5) — derives the evidence a CHECKPOINT GO requires.

`reviewer_driver` refuses a CHECKPOINT -> GO unless a trusted CI/test manifest exists for the exact
head SHA and reports success. `record_gate_manifest` provided the record format but had no producer, so
no manifest was ever written and the material gate was unreachable: a CHECKPOINT could only escalate to
NEEDS_OWNER. QUESTION and PROPOSAL were unaffected.

This module is that producer, and its whole point is **who decides**. It accepts no `tests_ok`,
`audits_ok` or `success` argument. Every field is derived here from a trusted mechanism:

- **identity** — the SHA must be the repository's real current HEAD, on a clean tree. A dirty tree
  means the gates did not measure the committed SHA, so the manifest would describe something that
  never existed.
- **CI** — the conclusion for that exact SHA, looked up externally. Absent or non-`success` is not
  success; missing evidence is never PASS.
- **audits and tests** — the real exit codes and real parsed counts of the required gates, run here.

It is invoked by the trusted local workflow (operator/launcher), never by the remote model, and never
across the MCP boundary.

**Known live limitation (owner decision, not a defect).** The CI half derives the REQUIRED-check set
from the repository's own machine-readable rules - branch protection, then rulesets. This repository
currently declares neither, so the producer fails closed: every manifest records
`ci_conclusion=""` with "no machine-readable required-check set", and a CHECKPOINT still cannot
reach GO. That is deliberate. The alternative - inferring which jobs "ought to be" required from
`ci.yml` - would create a second required-check configuration beside the canonical one and let the
two drift, which is the same class of trust hole this module exists to close. Configuring required
status checks on the base branch is what turns the gate on, and it is an owner action.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

from core.collaboration.manifest import record_gate_manifest

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_PASSED = re.compile(r"(\d+)\s+passed")
_FAILED = re.compile(r"(\d+)\s+failed")
_ERRORS = re.compile(r"(\d+)\s+error")
_SKIPPED = re.compile(r"(\d+)\s+skipped")

# The repository-required gate, per CLAUDE.md. Kept here as data so the producer runs exactly the
# declared gate rather than a convenient subset.
# `-m ruff check .` is part of the required gate too: a manifest that never ran it could unlock a
# CHECKPOINT GO on a SHA that fails the repository's own lint gate, and a green CI run does not prove
# it (the PR workflow is path-selective).
AUDIT_COMMANDS = (("-m", "ruff", "check", "."),
                  ("tools/docs_audit.py",),
                  ("tools/agent_readiness_audit.py",))
TEST_COMMAND = ("-m", "pytest", "tests/", "-q")


class GateEvidenceError(ValueError):
    """Raised when the evidence cannot honestly describe the requested SHA."""


def _run_default(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


# A required check is satisfied when it completed and did not fail. `skipped`/`neutral` count as
# satisfied because that is GitHub's own semantics for a required context, which is what the tiered
# CI relies on: `windows-full` legitimately skips on a PR that does not touch platform code. Reading
# a skip as a failure would invent a second, stricter required-check rule beside the canonical one.
_SATISFIED = frozenset({"success", "skipped", "neutral"})


def _gh_json(args: List[str], repo_root: str, timeout: int = 60):
    """One `gh` call returning parsed JSON, or None for any failure. Never raises, never guesses."""
    try:
        proc = subprocess.run(["gh", *args], cwd=repo_root, capture_output=True, text=True,
                              check=False, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if int(getattr(proc, "returncode", 1) or 0) != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except ValueError:
        return None


def _gh_required_contexts(repo_root: str, branch: str) -> Optional[List[str]]:
    """The repository's OWN machine-readable required-check set, or None when it declares none.

    Branch protection first, then rulesets. Nothing is derived from the workflow file: inferring
    "which jobs ought to be required" from `ci.yml` would be a second required-check configuration
    living beside the canonical one, and the two would drift.
    """
    data = _gh_json(["api", "repos/{owner}/{repo}/branches/" + branch
                     + "/protection/required_status_checks"], repo_root)
    # `checks` carries the app binding; the older `contexts` is names only. Prefer `checks`, so a
    # requirement that names its producing GitHub App keeps that binding - a check run is only
    # trustworthy as "the required check" when the app that produced it is the required one.
    if isinstance(data, dict):
        required = []
        for check in data.get("checks") or []:
            if isinstance(check, dict) and check.get("context"):
                required.append({"context": str(check["context"]), "app_id": check.get("app_id")})
        if not required:
            required = [{"context": str(c), "app_id": None} for c in (data.get("contexts") or []) if c]
        if required:
            return sorted(required, key=lambda r: r["context"])

    rules = _gh_json(["api", "repos/{owner}/{repo}/rules/branches/" + branch], repo_root)
    if isinstance(rules, list):
        required = []
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
                continue
            params = rule.get("parameters") or {}
            for check in params.get("required_status_checks") or []:
                if isinstance(check, dict) and check.get("context"):
                    required.append({"context": str(check["context"]),
                                     "app_id": check.get("integration_id")})
        if required:
            return sorted(required, key=lambda r: r["context"])
    return None


def _gh_check_runs(repo_root: str, sha: str) -> Optional[List[Dict[str, Any]]]:
    """Every check run recorded for this exact SHA, or None when the state could not be read."""
    try:
        proc = subprocess.run(
            ["gh", "api", "--paginate", f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs",
             "--jq", ".check_runs[] | "
             "{name, status, conclusion, completed_at, started_at, id, app_id: .app.id}"],
            cwd=repo_root, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if int(getattr(proc, "returncode", 1) or 0) != 0:
        return None
    runs = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except ValueError:
            return None  # a partially readable state is not a readable state
    return runs


def _ci_admission(required: Optional[List[str]],
                  runs: Optional[List[Dict[str, Any]]]) -> tuple:
    """(conclusion, detail) for the exact SHA. Only a satisfied REQUIRED set is `success`.

    This replaces `gh run list --commit <sha> --limit 1`, which could not establish what it was
    used for. A single SHA carries many workflow runs - on the head this was written against, the
    Copilot review run succeeded while the CI run failed, so "the latest run succeeded" and
    "required CI passed" were two different facts and the producer recorded the wrong one.
    """
    if required is None:
        return "", ("no machine-readable required-check set: the repository declares neither "
                    "branch protection nor a ruleset for the base branch, so nothing can say which "
                    "checks are required - evidence is NOT admission-ready")
    if runs is None:
        return "", "the check-run state for this SHA could not be read"

    # One SHA can carry several records of the same check (a re-run leaves the earlier one in
    # place), and they can disagree.
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for run in runs:
        name = str(run.get("name") or "")
        if name:
            by_name.setdefault(name, []).append(run)

    problems = []
    for requirement in required:
        # A plain string is a requirement with no app binding.
        if isinstance(requirement, dict):
            context, required_app = str(requirement.get("context") or ""), requirement.get("app_id")
        else:
            context, required_app = str(requirement), None
        records = by_name.get(context) or []
        if required_app is not None:
            # Fail closed on an unverifiable binding: a check run whose producing app is unknown
            # cannot be shown to be the required one, and a same-named run from a DIFFERENT app
            # must never satisfy the requirement.
            matched, unverifiable = [], False
            for record in records:
                app_id = record.get("app_id")
                if app_id is None:
                    unverifiable = True
                elif str(app_id) == str(required_app):
                    matched.append(record)
            if unverifiable and not matched:
                problems.append(f"{context}: producing app could not be verified "
                                f"(required app {required_app})")
                continue
            if records and not matched:
                problems.append(f"{context}: no check run from the required app {required_app}")
                continue
            records = matched
        if not records:
            problems.append(f"{context}: no check run for this SHA")
            continue

        # ANY record that has not completed blocks, whatever the ordering says.
        #
        # Selecting "the latest" and then testing its status is not enough, and the ordering is
        # exactly where it breaks: an in-progress re-run has an EMPTY `completed_at`, so it sorts
        # below the older successful record it supersedes and is discarded - the gate would report
        # success for a required check that is at that moment still running. Blocking on any active
        # record removes the decision's dependence on the sort key altogether.
        active = [r for r in records if str(r.get("status") or "") != "completed"]
        if active:
            problems.append(f"{context}: {active[0].get('status') or 'unknown status'}")
            continue
        newest = max(records, key=lambda r: (str(r.get("completed_at") or ""),
                                             str(r.get("id") or "")))
        conclusion = str(newest.get("conclusion") or "")
        if conclusion not in _SATISFIED:
            problems.append(f"{context}: {conclusion or 'no conclusion'}")
    if problems:
        return "", "required checks not satisfied: " + "; ".join(sorted(problems))
    return "success", f"all {len(required)} required checks satisfied for this SHA"


def _gh_ci_lookup(repo_root: str, base_branch: str = "main") -> Callable[[str], Dict[str, Any]]:
    """Default CI lookup: the REQUIRED-check state for this exact SHA. Never a local claim."""
    def lookup(sha: str) -> Dict[str, Any]:
        required = _gh_required_contexts(repo_root, base_branch)
        runs = _gh_check_runs(repo_root, sha) if required is not None else None
        conclusion, detail = _ci_admission(required, runs)
        return {"conclusion": conclusion, "run_id": "", "detail": detail,
                "required": list(required or [])}
    return lookup


def _parse_pytest(stdout: str) -> tuple:
    """Real counts from real output. An unparseable summary yields (0, 0) — not an invented pass."""
    passed = int(_PASSED.search(stdout).group(1)) if _PASSED.search(stdout) else 0
    failed = int(_FAILED.search(stdout).group(1)) if _FAILED.search(stdout) else 0
    errors = int(_ERRORS.search(stdout).group(1)) if _ERRORS.search(stdout) else 0
    skipped = int(_SKIPPED.search(stdout).group(1)) if _SKIPPED.search(stdout) else 0
    return passed, passed + failed + errors + skipped


def produce_gate_manifest(output_root: str, repo_root: str, head_sha: str, *,
                          ci_lookup: Optional[Callable[[str], Dict[str, Any]]] = None,
                          run: Optional[Callable[..., Any]] = None,
                          python_bin: str = "python",
                          notes: str = "") -> Dict[str, Any]:
    """Derive and record the trusted gate manifest for one exact SHA.

    Deliberately takes no evidence *values* — only where to look. Raises `GateEvidenceError` when the
    evidence could not describe this SHA; returns the recorded manifest otherwise (which may legitimately
    have ``success: False``).
    """
    sha = str(head_sha or "").strip().lower()
    if not _FULL_SHA.fullmatch(sha):
        raise GateEvidenceError("a gate manifest requires an exact full 40-character head SHA")

    runner = run or _run_default
    lookup = ci_lookup or _gh_ci_lookup(repo_root)

    def _tracked_tree(when: str) -> str:
        """The tree object the manifest claims to describe."""
        proc = runner(["git", "rev-parse", "HEAD^{tree}"], cwd=repo_root)
        if int(getattr(proc, "returncode", 1) or 0) != 0:
            raise GateEvidenceError(f"could not read the head tree ({when}); refusing to record a "
                                    "manifest for an unidentified tree")
        return (getattr(proc, "stdout", "") or "").strip()

    def _worktree_watermark(when: str) -> Dict[str, Any]:
        """A PER-PATH `st_mtime_ns` snapshot of every non-ignored path, files AND directories.

        A clean `status --porcelain` before and after cannot see a tracked file that was modified
        and restored while the gate ran: the bytes match again by the time it is asked, yet the
        commands measured something that never existed as a commit. Content digests are equally
        blind, for the same reason. The write itself is what leaves a trace, so this compares an
        mtime watermark across the measurement window.

        Two refinements over watching tracked files only, both of which that version missed:

        * `--others --exclude-standard` includes untracked-but-not-ignored files. A concurrent
          writer can ADD a `tests/*.py`, let `pytest tests/` collect it, and remove it before the
          final check: no tracked mtime moves and the commit tree is unchanged, yet the gate
          measured bytes that are not in the requested SHA.
        * directories are watermarked too, because a create-and-delete leaves no file behind to
          stat - the trace it does leave is on the parent directory.

        It is a per-path snapshot and not one global maximum, because a maximum is blind in an
        obvious way once pointed out: a writer can modify and restore any file whose mtime sits
        BELOW the current maximum, and the maximum, the count, the status and the tree hash all
        stay identical while the gate measured different bytes. Nanosecond resolution likewise
        matters - a whole-second mtime is coarse enough for a fast write to land inside one tick.

        This DETECTS concurrent writes; it does not PREVENT them. A filesystem that does not update
        directory mtimes, or a writer that restores them, would still evade it. Running the gate in
        an isolated checkout that nothing else writes to remains the only complete guarantee, and
        that is the direction this should move; the snapshot is the fail-closed check until then.
        """
        proc = runner(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                      cwd=repo_root)
        if int(getattr(proc, "returncode", 1) or 0) != 0:
            raise GateEvidenceError(f"could not list worktree files ({when}); refusing to treat an "
                                    "unverifiable worktree as stable")
        snapshot, directories = {}, {""}
        for rel in (getattr(proc, "stdout", "") or "").split("\0"):
            if not rel.strip():
                continue
            directories.add(os.path.dirname(rel))
            try:
                snapshot[rel] = os.stat(os.path.join(repo_root, rel)).st_mtime_ns
            except OSError:
                snapshot[rel] = None  # present in the listing but unreadable: still a difference
        for rel in sorted(directories):
            try:
                snapshot["dir:" + rel] = os.stat(os.path.join(repo_root, rel)).st_mtime_ns
            except OSError:
                snapshot["dir:" + rel] = None
        return snapshot

    def _assert_identity(when: str) -> None:
        head_proc = runner(["git", "rev-parse", "HEAD"], cwd=repo_root)
        if int(getattr(head_proc, "returncode", 1) or 0) != 0:
            raise GateEvidenceError(f"could not read repository head ({when}); refusing to record "
                                    "a manifest for an unverified checkout")
        head = (getattr(head_proc, "stdout", "") or "").strip()
        if head.lower() != sha:
            raise GateEvidenceError(
                f"repository head {head[:12] or '<unknown>'} is not the requested SHA {sha[:12]} "
                f"({when}); gate evidence would describe a different commit")
        status_proc = runner(["git", "status", "--porcelain"], cwd=repo_root)
        # Empty stdout from a FAILED status is not a clean tree. Without this, a transient
        # repository/permission failure would look like "nothing modified" and let the producer
        # record a manifest for a checkout whose cleanliness was never actually verified.
        if int(getattr(status_proc, "returncode", 1) or 0) != 0:
            raise GateEvidenceError(f"could not determine working-tree status ({when}); refusing to "
                                    "treat an unreadable status as clean")
        dirty = (getattr(status_proc, "stdout", "") or "").strip()
        if dirty:
            raise GateEvidenceError(
                f"working tree is not clean ({when}); gate evidence would not describe the "
                "committed SHA")

    # --- identity: the gates must measure the SHA the manifest names -------------------------------
    _assert_identity("before running the gate")
    tree_before = _tracked_tree("before running the gate")
    watermark_before = _worktree_watermark("before running the gate")

    # --- CI: external, exact-SHA, absent is not success --------------------------------------------
    # Sampled here only as an early signal. The AUTHORITATIVE read happens after the gate: the
    # audits and the full suite take many minutes, and a required check can be re-run, go
    # in-progress or fail inside that window. Persisting this pre-gate snapshot would allow an
    # exact-SHA GO on a CI state that no longer holds - the same time-of-check/time-of-use shape
    # the identity re-validation below exists to close, one field over.
    ci_before = lookup(sha) or {}

    # --- audits: real exit codes -------------------------------------------------------------------
    audits_ok = True
    audit_notes = []
    for cmd in AUDIT_COMMANDS:
        proc = runner([python_bin, *cmd], cwd=repo_root)
        rc = int(getattr(proc, "returncode", 1) or 0)
        audits_ok = audits_ok and rc == 0
        audit_notes.append(f"{' '.join(cmd)} rc={rc}")

    # --- tests: real exit code + real counts -------------------------------------------------------
    proc = runner([python_bin, *TEST_COMMAND], cwd=repo_root)
    tests_rc = int(getattr(proc, "returncode", 1) or 0)
    tests_passed, tests_total = _parse_pytest(str(getattr(proc, "stdout", "") or ""))
    tests_ok = tests_rc == 0 and tests_passed > 0

    # The gate above takes many minutes. Re-check identity immediately before persisting: if HEAD
    # advanced or a tracked file changed meanwhile, the commands measured a different checkout and a
    # manifest written for `sha` would authorise an exact-SHA GO on mismatched evidence.
    _assert_identity("after running the gate")
    tree_after = _tracked_tree("after running the gate")
    if tree_after != tree_before:
        raise GateEvidenceError(
            f"the measured tree changed during the gate ({tree_before[:12]} -> "
            f"{tree_after[:12]}); the commands did not all measure one tree")
    watermark_after = _worktree_watermark("after running the gate")
    if watermark_after != watermark_before:
        changed = sorted(set(watermark_before) ^ set(watermark_after)) or sorted(
            p for p in watermark_before if watermark_before[p] != watermark_after.get(p))
        raise GateEvidenceError(
            "the worktree was written to while the gate was running, so the commands did not all "
            f"measure the same bytes ({', '.join(changed[:5])}); re-run the gate on a checkout "
            "nothing else is writing to")

    # The authoritative CI read: immediately before persisting, not before the gate.
    ci = lookup(sha) or {}
    ci_conclusion = str(ci.get("conclusion") or "")
    ci_run = str(ci.get("run_id") or "")
    before_conclusion = str(ci_before.get("conclusion") or "")
    ci_detail = str(ci.get("detail") or "")
    if before_conclusion != ci_conclusion:
        ci_detail = (f"required-check state CHANGED during the gate "
                     f"({before_conclusion or 'unavailable'} -> {ci_conclusion or 'unavailable'}); "
                     f"{ci_detail}")
    detail = (f"ci={ci_conclusion or 'unavailable'}"
              + (f" ({ci_detail})" if ci_detail else "")
              + f"; tree={tree_before[:12]}; tests rc={tests_rc} "
              f"{tests_passed}/{tests_total}; " + ", ".join(audit_notes))
    return record_gate_manifest(
        output_root, sha,
        ci_conclusion=ci_conclusion, ci_run=ci_run,
        tests_passed=tests_passed, tests_total=tests_total,
        tests_ok=tests_ok, audits_ok=audits_ok,
        notes=(f"{notes} | {detail}" if notes else detail))
