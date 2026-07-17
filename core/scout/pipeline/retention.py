"""Retention + storage management (Final Phase I).

Computes a retention plan per prospect class and provides archive / soft-delete / restore /
explicit confirmed purge. Purge requires explicit confirmation, is path-confined to application
storage, preserves the minimum suppression/history, and always writes an audit event. It never
deletes outside application storage.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from core.scout.memory.repository import MemoryRepository

RETENTION_DAYS = {
    "failed_eligibility": 30, "no_finding_quick_scan": 30, "weak_rejected": 30,
    "verified_prospect": 180, "draft_ready": 365, "quarantine_secret_pii": 0,
}


class RetentionError(Exception):
    pass


@dataclass
class RetentionPlan:
    entries: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {"entries": self.entries, "policy_days": RETENTION_DAYS}


def build_retention_plan(prospects: List[Dict[str, Any]]) -> RetentionPlan:
    entries = []
    for p in prospects:
        klass = _classify(p)
        entries.append({"subject_ref": p.get("company_id") or p.get("candidate_id"),
                        "klass": klass, "retention_days": RETENTION_DAYS[klass],
                        "state": "ACTIVE"})
    return RetentionPlan(entries)


def _classify(p: Dict[str, Any]) -> str:
    if p.get("draft_ready"):
        return "draft_ready"
    if p.get("verified_findings", 0) > 0:
        return "verified_prospect"
    if p.get("eligibility_status") == "technical_reject":
        return "failed_eligibility"
    return "no_finding_quick_scan"


class StorageManager:
    """Confined archive/soft-delete/restore/purge over a run's storage root."""

    def __init__(self, storage_root: str, repo: MemoryRepository,
                 clock: Callable[[], str]) -> None:
        self.root = Path(storage_root).resolve()
        self.repo = repo
        self.clock = clock

    def _confine(self, subdir: str) -> Path:
        target = (self.root / subdir).resolve()
        if target != self.root and self.root not in target.parents:
            raise RetentionError(f"path escapes storage root: {subdir!r}")
        return target

    def archive(self, subject_ref: str) -> None:
        self.repo.add_event("retention", subject_ref, "ARCHIVED", "", self.clock())

    def soft_delete(self, subject_ref: str) -> None:
        self.repo.add_event("retention", subject_ref, "SOFT_DELETED", "", self.clock())

    def restore(self, subject_ref: str) -> None:
        self.repo.add_event("retention", subject_ref, "RESTORED", "", self.clock())

    def purge(self, subject_ref: str, subdir: str, *, confirm: bool) -> None:
        """Explicit, confirmed, path-confined purge. Suppression history is preserved (it lives
        in the DB, which this never deletes). Always audited."""
        if not confirm:
            raise RetentionError("purge requires explicit confirmation")
        target = self._confine(subdir)
        if target == self.root:
            raise RetentionError("refusing to purge the storage root itself")
        if target.exists():
            shutil.rmtree(target)
        self.repo.add_event("retention", subject_ref, "PURGED", subdir, self.clock())
