"""Bounded, verified, redacted evidence for one exact SHA (Issue #14.B / P0-3).

The reviewer must judge a specific commit from independent evidence, not the worker's claims. This
gathers a strictly bounded pack for one head SHA and, crucially, *verifies* it: the SHA must exist and
the git commands must have produced output, and the pack carries explicit completeness/truncation
flags. It also includes the CONTENTS of the canonical invariants and of any checkpoint/CI/test
manifest — not just reference strings — so the model reasons over real criteria. Everything is capped
and redacted; there is no repository dump. When evidence is missing, unreadable, or materially
truncated the driver refuses to let a CHECKPOINT produce GO.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.orchestration.content_safety import redact_intake_text

GitRunner = Callable[[List[str]], str]

_INVARIANTS_DOC = "docs/COLLABORATIVE_AI_ENGINEERING_MODEL.md"
_INVARIANTS_MARKER = "## 14. Canonical product invariants"


def _default_git_runner(repo_root: str) -> GitRunner:
    def run(args: List[str]) -> str:
        try:
            proc = subprocess.run(["git", *args], cwd=repo_root, capture_output=True,
                                  text=True, timeout=30, check=False)
            return proc.stdout or ""
        except (OSError, subprocess.SubprocessError):
            return ""
    return run


def _redact(text: str, *, limit: int) -> str:
    return redact_intake_text(str(text or "")).text[:limit]


def _canonical_criteria(repo_root: str, limit: int = 6000) -> str:
    try:
        text = (Path(repo_root) / _INVARIANTS_DOC).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""
    idx = text.find(_INVARIANTS_MARKER)
    section = text[idx:] if idx >= 0 else text
    return _redact(section, limit=limit)


def gather_evidence(
    repo_root: str,
    head_sha: str,
    *,
    base_sha: str = "",
    request: Optional[Dict[str, Any]] = None,
    manifests: Optional[Dict[str, str]] = None,
    git_runner: Optional[GitRunner] = None,
    max_files: int = 60,
    max_diff_chars: int = 40000,
    max_manifest_chars: int = 8000,
) -> Dict[str, Any]:
    run = git_runner or _default_git_runner(repo_root)
    head = str(head_sha or "").strip().lower()
    base = str(base_sha or "").strip().lower()
    request = request or {}
    span = f"{base}..{head}" if base else head

    # Verify the exact commit exists before trusting any derived evidence.
    sha_verified = bool(run(["rev-parse", "--verify", "--quiet", f"{head}^{{commit}}"]).strip())

    name_only = run(["diff", "--name-only", span]) if base else run(
        ["show", "--name-only", "--format=", head])
    all_files = [f.strip() for f in name_only.splitlines() if f.strip()]
    changed_files = all_files[:max_files]

    stat = run(["diff", "--stat", span]) if base else run(["show", "--stat", "--format=", head])
    raw_diff = run(["diff", span]) if base else run(["show", "--format=", head])
    diff_excerpt = _redact(raw_diff, limit=max_diff_chars)
    subject = run(["log", "-1", "--format=%s", head]).strip()

    diff_truncated = len(raw_diff) > len(diff_excerpt)
    git_ok = bool(name_only.strip()) and bool(raw_diff.strip())
    # Complete = the commit exists, git produced file+diff output, and the diff is not truncated.
    evidence_complete = sha_verified and git_ok and bool(changed_files) and not diff_truncated
    incompleteness: List[str] = []
    if not sha_verified:
        incompleteness.append("head SHA could not be verified to exist")
    if not git_ok:
        incompleteness.append("git produced no file/diff output")
    if not changed_files:
        incompleteness.append("no changed files found")
    if diff_truncated:
        incompleteness.append("diff was materially truncated")

    refs = [str(r).strip() for r in (request.get("evidence_refs") or []) if str(r).strip()]
    manifest_contents = {str(k): _redact(v, limit=max_manifest_chars)
                         for k, v in (manifests or {}).items()}
    return {
        "head_sha": head,
        "base_sha": base,
        "sha_verified": sha_verified,
        "git_ok": git_ok,
        "branch": _redact(request.get("branch", ""), limit=200),
        "pr_number": request.get("pr_number"),
        "commit_subject": _redact(subject, limit=400),
        "changed_files": [_redact(f, limit=400) for f in changed_files],
        "changed_files_total": len(all_files),
        "changed_files_truncated": len(all_files) > len(changed_files),
        "diff_stat": _redact(stat, limit=8000),
        "diff_excerpt": diff_excerpt,
        "diff_truncated": diff_truncated,
        "evidence_refs": refs,
        # Contents, not just references, so the reviewer reasons over real criteria (P0-3).
        "canonical_criteria": _canonical_criteria(repo_root),
        "checkpoint_manifest": _redact(request.get("body", ""), limit=max_manifest_chars),
        "manifests": manifest_contents,
        "evidence_complete": evidence_complete,
        "incompleteness": incompleteness,
    }
