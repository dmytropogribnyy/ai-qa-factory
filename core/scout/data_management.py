"""Clearing up after test runs, without ever being able to take the work they were testing.

Live acceptance runs leave real companies, real screenshots and real megabytes behind. An operator
who cannot clear them stops running them, so this exists. But the same canonical site can appear in a
throwaway acceptance run AND in the production history that matters, and one careless sweep takes
both. Every rule below is there because of that overlap.

**Purpose is declared, never guessed.** A run records ``run_purpose`` in its config at launch. A run
that predates the field is ``unclassified`` and stays that way until a human says otherwise. The
codebase already has :func:`core.scout.canonical_runs.is_diagnostic_run`, which infers a run kind
from its id — that is right for deciding what to *show*, and wrong for deciding what to *delete*.
Inferring "this looks like a test" from a name is precisely how production history disappears.

**Deletion is staged.** Preview, then Trash, then — separately, and only from inside Trash —
permanent removal. There is always a point at which the counts can be read before anything becomes
irreversible, and Restore puts a run back whole, because the operator who realises mid-cleanup is
the normal case rather than the exception.

**A selection is a list of exact run ids.** Never a glob, never a path, never anything that could
expand. A deletion target that can widen after it was previewed is not the thing that was previewed.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

PURPOSE_PRODUCTION = "production"
PURPOSE_DIAGNOSTIC = "diagnostic"
PURPOSE_ACCEPTANCE = "acceptance"
PURPOSE_MANUAL_TEST = "manual_test"
PURPOSE_UNCLASSIFIED = "unclassified"

# Purposes whose data is understood to be disposable. Production and unclassified are not here, and
# that is the whole point.
REMOVABLE_PURPOSES = frozenset({PURPOSE_DIAGNOSTIC, PURPOSE_ACCEPTANCE, PURPOSE_MANUAL_TEST})
KNOWN_PURPOSES = REMOVABLE_PURPOSES | {PURPOSE_PRODUCTION, PURPOSE_UNCLASSIFIED}

PURPOSE_LABELS = {
    PURPOSE_PRODUCTION: "Production",
    PURPOSE_DIAGNOSTIC: "Diagnostic",
    PURPOSE_ACCEPTANCE: "Acceptance",
    PURPOSE_MANUAL_TEST: "Manual test",
    PURPOSE_UNCLASSIFIED: "Unclassified",
}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_VIDEO_SUFFIXES = (".webm", ".mp4")
_STATE_NAME = "data_management.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalise_purpose(value: Any) -> str:
    """Map a persisted value onto a known purpose, defaulting to unclassified rather than guessing."""
    text = str(value or "").strip().lower().replace("-", "_")
    return text if text in KNOWN_PURPOSES else PURPOSE_UNCLASSIFIED


@dataclass
class RunRecord:
    run_id: str
    purpose: str
    created_at: str
    domains: List[str] = field(default_factory=list)
    findings: int = 0
    screenshots: int = 0
    videos: int = 0
    files: int = 0
    bytes: int = 0
    trashed: bool = False
    trashed_at: str = ""

    @property
    def purpose_label(self) -> str:
        return PURPOSE_LABELS.get(self.purpose, "Unclassified")

    def to_dict(self) -> Dict[str, Any]:
        return {**self.__dict__, "purpose_label": self.purpose_label}


@dataclass
class Inventory:
    runs: List[RunRecord] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    bytes_total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"runs": [r.to_dict() for r in self.runs], "counts": dict(self.counts),
                "bytes_total": self.bytes_total}


@dataclass
class CleanupPreview:
    """Exactly what would go, and everything that was refused and why."""
    runs: List[RunRecord] = field(default_factory=list)
    protected: List[Dict[str, str]] = field(default_factory=list)
    unique_domains: Set[str] = field(default_factory=set)
    shared_with_production: Set[str] = field(default_factory=set)
    findings: int = 0
    screenshots: int = 0
    videos: int = 0
    bytes_to_reclaim: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"runs": [r.to_dict() for r in self.runs], "protected": list(self.protected),
                "unique_domains": sorted(self.unique_domains),
                "shared_with_production": sorted(self.shared_with_production),
                "findings": self.findings, "screenshots": self.screenshots,
                "videos": self.videos, "bytes_to_reclaim": self.bytes_to_reclaim}


class DataManagementStore:
    """Read the run tree, stage removals, and never touch anything outside one run directory."""

    def __init__(self, output_dir: str = "outputs", *, active_run_id: str = "") -> None:
        self.output_dir = str(output_dir)
        self.active_run_id = str(active_run_id or "").strip()
        self._root = Path(self.output_dir) / "scout"
        self._path = self._root / "_operator" / _STATE_NAME

    # -- reading ---------------------------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        return self._root / self._safe_run(run_id)

    def inventory(self) -> Inventory:
        state = self._state()
        trashed = {item["run_id"]: item for item in state.get("trash", [])}
        runs = [self._describe(path.name, trashed.get(path.name))
                for path in sorted(self._root.glob("*"))
                if path.is_dir() and not path.name.startswith("_")]
        counts: Dict[str, int] = {purpose: 0 for purpose in KNOWN_PURPOSES}
        counts["in_trash"] = 0
        for run in runs:
            counts[run.purpose] = counts.get(run.purpose, 0) + 1
            if run.trashed:
                counts["in_trash"] += 1
        return Inventory(runs=runs, counts=counts, bytes_total=sum(r.bytes for r in runs))

    def preview(self, run_ids: Iterable[str]) -> CleanupPreview:
        """What would actually be removed, with every refusal named.

        Nothing is mutated. This is the step whose numbers the operator reads before agreeing, so it
        must apply the same rules the removal will — a preview that is more permissive than the
        action it precedes is worse than no preview.
        """
        state = self._state()
        trashed = {item["run_id"]: item for item in state.get("trash", [])}
        preview = CleanupPreview()
        production_domains = self._domains_by_purpose(PURPOSE_PRODUCTION)
        for raw in run_ids or []:
            run_id = str(raw or "").strip()
            reason = self._refusal(run_id)
            if reason:
                if run_id:
                    preview.protected.append({"run_id": run_id, "reason": reason})
                continue
            record = self._describe(run_id, trashed.get(run_id))
            preview.runs.append(record)
            preview.unique_domains.update(record.domains)
            preview.findings += record.findings
            preview.screenshots += record.screenshots
            preview.videos += record.videos
            preview.bytes_to_reclaim += record.bytes
        # Named, not silently excluded: the operator should see that a site they are about to clear
        # is also part of real history, and decide with that in view.
        preview.shared_with_production = preview.unique_domains & production_domains
        return preview

    def tombstones(self) -> List[Dict[str, Any]]:
        return list(self._state().get("tombstones", []))

    # -- staging ---------------------------------------------------------------------------------

    def move_to_trash(self, run_ids: Iterable[str]) -> Dict[str, Any]:
        """Recoverable soft delete. Nothing leaves the disk; the run stops appearing in daily views."""
        state = self._state()
        existing = {item["run_id"] for item in state.get("trash", [])}
        moved, refused = [], []
        for raw in run_ids or []:
            run_id = str(raw or "").strip()
            reason = self._refusal(run_id)
            if reason:
                if run_id:
                    refused.append({"run_id": run_id, "reason": reason})
                continue
            if run_id in existing:
                continue                            # already there: moving twice is not two items
            state.setdefault("trash", []).append({"run_id": run_id, "trashed_at": _now()})
            existing.add(run_id)
            moved.append(run_id)
        self._save(state)
        return {"ok": True, "moved": moved, "refused": refused}

    def restore(self, run_ids: Iterable[str]) -> Dict[str, Any]:
        """Put a run back whole — the record, its evidence and its visibility."""
        state = self._state()
        wanted = {str(r or "").strip() for r in (run_ids or [])}
        before = len(state.get("trash", []))
        state["trash"] = [item for item in state.get("trash", [])
                          if item["run_id"] not in wanted]
        self._save(state)
        restored = sorted(w for w in wanted if w)
        return {"ok": True, "restored": restored, "removed_from_trash": before - len(state["trash"])}

    def permanently_delete(self, run_ids: Iterable[str], *, confirm: bool) -> Dict[str, Any]:
        """Irreversible, and reachable only from Trash after a separate confirmation.

        Idempotent on purpose: an interrupted cleanup that is retried must converge rather than
        error, so a run that is already gone is reported as already gone.
        """
        state = self._state()
        in_trash = {item["run_id"] for item in state.get("trash", [])}
        deleted, refused, already_gone, reclaimed = [], [], [], 0
        for raw in run_ids or []:
            run_id = str(raw or "").strip()
            if not run_id or run_id != self._safe_run(run_id):
                continue
            if run_id not in in_trash:
                refused.append({"run_id": run_id,
                                "reason": "only a run already in Trash can be deleted permanently"})
                continue
            if not confirm:
                refused.append({"run_id": run_id, "reason": "explicit confirmation is required"})
                continue
            if run_id == self.active_run_id:
                refused.append({"run_id": run_id, "reason": "the run is still running"})
                continue
            directory = self.run_dir(run_id)
            if not directory.is_dir():
                already_gone.append(run_id)
                state["trash"] = [i for i in state.get("trash", []) if i["run_id"] != run_id]
                continue
            record = self._describe(run_id, None)
            # Forget the dedup entries this run is the ONLY source of. A site that production also
            # scanned keeps its history untouched — only this run's claim on it goes.
            self._release_domains(record, run_id)
            self._confined_rmtree(directory)
            reclaimed += record.bytes
            deleted.append(run_id)
            state["trash"] = [i for i in state.get("trash", []) if i["run_id"] != run_id]
            # Scope, counts and the moment — never the deleted content itself.
            state.setdefault("tombstones", []).append({
                "run_id": run_id, "purpose": record.purpose, "deleted_at": _now(),
                "sites": len(record.domains), "findings": record.findings,
                "screenshots": record.screenshots, "videos": record.videos,
                "bytes_reclaimed": record.bytes})
        self._save(state)
        return {"ok": True, "deleted": deleted, "refused": refused,
                "already_gone": already_gone, "bytes_reclaimed": reclaimed}

    # -- internals -------------------------------------------------------------------------------

    def _refusal(self, run_id: str) -> str:
        """Why this run may not be swept, in words the preview can show. "" means it may."""
        if not run_id or run_id != self._safe_run(run_id):
            return "not an exact run id"
        if not self.run_dir(run_id).is_dir():
            return "no such run"
        if run_id == self.active_run_id:
            return "the run is still running"
        purpose = self._purpose(run_id)
        if purpose == PURPOSE_PRODUCTION:
            return "this is production data"
        if purpose == PURPOSE_UNCLASSIFIED:
            return ("the run is unclassified — its purpose was never recorded, so it is not "
                    "assumed to be test data")
        if self._client_linked(run_id):
            return "a client work item or an approved client package depends on this run"
        return ""

    def _purpose(self, run_id: str) -> str:
        try:
            raw = json.loads((self.run_dir(run_id) / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return PURPOSE_UNCLASSIFIED
        return normalise_purpose((raw or {}).get("run_purpose"))

    def _client_linked(self, run_id: str) -> bool:
        """Has a human already carried this run's result into client work?"""
        try:
            from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
            for entry in AnalyzedSiteRegistry(self.output_dir).all():
                if run_id in (getattr(entry, "campaign_ids", []) or []) and getattr(
                        entry, "work_id", ""):
                    return True
        except Exception:      # noqa: BLE001 - a lookup failure must never authorise a deletion
            return True
        return False

    def _describe(self, run_id: str, trash_item: Optional[Dict[str, Any]]) -> RunRecord:
        directory = self.run_dir(run_id)
        domains, findings = [], 0
        created = ""
        try:
            state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        created = str(state.get("started_at") or state.get("finished_at") or "")
        from core.scout.discovery.domain_intel import canonical_domain
        for prospect in (state.get("prospects", {}) or {}).values():
            if not isinstance(prospect, dict):
                continue
            domain = canonical_domain(prospect.get("url") or prospect.get("final_url") or "")
            if domain and domain not in domains:
                domains.append(domain)
        shots = videos = files = total = 0
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            files += 1
            try:
                total += path.stat().st_size
            except OSError:
                continue
            low = path.name.lower()
            if low.endswith(_IMAGE_SUFFIXES):
                shots += 1
            elif low.endswith(_VIDEO_SUFFIXES):
                videos += 1
            elif low == "findings.json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    findings += len(data.get("verified", []) or [])
                except (OSError, ValueError):
                    pass
        return RunRecord(run_id=run_id, purpose=self._purpose(run_id), created_at=created,
                         domains=domains, findings=findings, screenshots=shots, videos=videos,
                         files=files, bytes=total,
                         trashed=bool(trash_item),
                         trashed_at=str((trash_item or {}).get("trashed_at") or ""))

    def _domains_by_purpose(self, purpose: str) -> Set[str]:
        return {domain
                for run in self.inventory().runs if run.purpose == purpose
                for domain in run.domains}

    def _release_domains(self, record: RunRecord, run_id: str) -> None:
        """Drop dedup entries this run alone is responsible for; leave shared ones alone.

        A site that production also scanned keeps its history, its evidence and its registry entry —
        only this run's claim on it is removed. A site that exists solely because of the test run
        loses its entry, because otherwise dedup would silently block a genuine scan of it later.
        """
        try:
            from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
            registry = AnalyzedSiteRegistry(self.output_dir)
            for domain in record.domains:
                entry = registry.get(domain)
                if entry is None:
                    continue
                others = [c for c in (getattr(entry, "campaign_ids", []) or []) if c != run_id]
                if others:
                    continue                  # another run still stands behind this site
                registry.forget(domain, confirm=True)
        except Exception:      # noqa: BLE001 - bookkeeping must not abort a confirmed deletion
            pass

    def _confined_rmtree(self, directory: Path) -> None:
        resolved = directory.resolve()
        root = self._root.resolve()
        if root not in resolved.parents or resolved == root:
            raise ValueError("refusing to delete outside the Scout run tree")
        shutil.rmtree(resolved)

    @staticmethod
    def _safe_run(run_id: str) -> str:
        """An exact single path component, or "" — never a glob, a path or a traversal."""
        value = str(run_id or "").strip()
        if not value or value.startswith((".", "_")):
            return ""
        if set(value) & set('/\\*?"<>|:'):
            return ""
        return value

    def _state(self) -> Dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        return {"schema": "scout-data-management/v1",
                "trash": [i for i in (raw.get("trash") or []) if isinstance(i, dict)
                          and i.get("run_id")],
                "tombstones": [t for t in (raw.get("tombstones") or []) if isinstance(t, dict)]}

    def _save(self, state: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)
