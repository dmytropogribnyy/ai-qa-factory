"""Bounded, redacted evidence for one exact SHA (Issue #14.B step 2).

The reviewer must judge a specific commit, not the whole repository. This gathers a strictly bounded
evidence pack for one head SHA — changed file list (capped), a truncated diff excerpt, the commit
subject, and the request's own evidence refs — and redacts it before it can reach the model. There is
no unrestricted repository dump: file count and diff size are hard-capped. Git access is read-only and
injectable so the gatherer is deterministic under test.
"""
from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, List, Optional

from core.orchestration.content_safety import redact_intake_text

GitRunner = Callable[[List[str]], str]


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


def gather_evidence(
    repo_root: str,
    head_sha: str,
    *,
    base_sha: str = "",
    request: Optional[Dict[str, Any]] = None,
    git_runner: Optional[GitRunner] = None,
    max_files: int = 50,
    max_diff_chars: int = 24000,
) -> Dict[str, Any]:
    run = git_runner or _default_git_runner(repo_root)
    head = str(head_sha or "").strip().lower()
    base = str(base_sha or "").strip().lower()
    request = request or {}
    span = f"{base}..{head}" if base else head

    name_only = run(["diff", "--name-only", span]) if base else run(
        ["show", "--name-only", "--format=", head])
    all_files = [f.strip() for f in name_only.splitlines() if f.strip()]
    changed_files = all_files[:max_files]

    stat = run(["diff", "--stat", span]) if base else run(["show", "--stat", "--format=", head])
    raw_diff = run(["diff", span]) if base else run(["show", "--format=", head])
    diff_excerpt = _redact(raw_diff, limit=max_diff_chars)
    subject = run(["log", "-1", "--format=%s", head]).strip()

    refs = [str(r).strip() for r in (request.get("evidence_refs") or []) if str(r).strip()]
    return {
        "head_sha": head,
        "base_sha": base,
        "branch": _redact(request.get("branch", ""), limit=200),
        "pr_number": request.get("pr_number"),
        "commit_subject": _redact(subject, limit=400),
        "changed_files": [_redact(f, limit=400) for f in changed_files],
        "changed_files_total": len(all_files),
        "changed_files_truncated": len(all_files) > len(changed_files),
        "diff_stat": _redact(stat, limit=8000),
        "diff_excerpt": diff_excerpt,
        "diff_truncated": len(raw_diff) > len(diff_excerpt),
        "evidence_refs": refs,
    }
