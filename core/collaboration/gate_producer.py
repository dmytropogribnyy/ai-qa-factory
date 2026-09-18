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
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable, Dict, Optional

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


def _gh_ci_lookup(repo_root: str) -> Callable[[str], Dict[str, Any]]:
    """Default CI lookup: the real conclusion for this exact SHA, from GitHub. Never a local claim."""
    def lookup(sha: str) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                ["gh", "run", "list", "--commit", sha, "--limit", "1",
                 "--json", "conclusion,databaseId"],
                cwd=repo_root, capture_output=True, text=True, check=False, timeout=60)
            rows = json.loads(proc.stdout or "[]")
        except (OSError, ValueError, subprocess.SubprocessError):
            return {}
        if not rows:
            return {}
        return {"conclusion": str(rows[0].get("conclusion") or ""),
                "run_id": str(rows[0].get("databaseId") or "")}
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

    def _assert_identity(when: str) -> None:
        head = (getattr(runner(["git", "rev-parse", "HEAD"], cwd=repo_root), "stdout", "")
                or "").strip()
        if head.lower() != sha:
            raise GateEvidenceError(
                f"repository head {head[:12] or '<unknown>'} is not the requested SHA {sha[:12]} "
                f"({when}); gate evidence would describe a different commit")
        dirty = (getattr(runner(["git", "status", "--porcelain"], cwd=repo_root), "stdout", "")
                 or "").strip()
        if dirty:
            raise GateEvidenceError(
                f"working tree is not clean ({when}); gate evidence would not describe the "
                "committed SHA")

    # --- identity: the gates must measure the SHA the manifest names -------------------------------
    _assert_identity("before running the gate")

    # --- CI: external, exact-SHA, absent is not success --------------------------------------------
    ci = lookup(sha) or {}
    ci_conclusion = str(ci.get("conclusion") or "")
    ci_run = str(ci.get("run_id") or "")

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

    detail = (f"ci={ci_conclusion or 'unavailable'}; tests rc={tests_rc} "
              f"{tests_passed}/{tests_total}; " + ", ".join(audit_notes))
    return record_gate_manifest(
        output_root, sha,
        ci_conclusion=ci_conclusion, ci_run=ci_run,
        tests_passed=tests_passed, tests_total=tests_total,
        tests_ok=tests_ok, audits_ok=audits_ok,
        notes=(f"{notes} | {detail}" if notes else detail))
