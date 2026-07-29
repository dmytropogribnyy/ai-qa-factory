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

from core.atomic_io import atomic_replace
# The purpose vocabulary is shared with History, Overview and Needs attention — one definition of
# what a run was for, so a site cannot be disposable on one screen and production on the next.
from core.scout.run_purpose import (KNOWN_PURPOSES, PURPOSE_ACCEPTANCE,  # noqa: F401 (re-exported)
                                    PURPOSE_DIAGNOSTIC, PURPOSE_LABELS, PURPOSE_MANUAL_TEST,
                                    PURPOSE_PRODUCTION, PURPOSE_UNCLASSIFIED, REMOVABLE_PURPOSES,
                                    RunPurposeIndex, normalise_purpose)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_VIDEO_SUFFIXES = (".webm", ".mp4")
_STATE_NAME = "data_management.json"
# Where a run being deleted lives between "no longer reachable" and "gone". A crash in between
# leaves a directory here rather than a half-deleted run and a registry that already forgot it.
_STAGING_NAME = "_pending_delete"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    files: int = 0
    bytes_to_reclaim: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"runs": [r.to_dict() for r in self.runs], "protected": list(self.protected),
                "unique_domains": sorted(self.unique_domains),
                "shared_with_production": sorted(self.shared_with_production),
                "findings": self.findings, "screenshots": self.screenshots,
                "videos": self.videos, "files": self.files,
                "bytes_to_reclaim": self.bytes_to_reclaim}


class DataManagementStore:
    """Read the run tree, stage removals, and never touch anything outside one run directory."""

    def __init__(self, output_dir: str = "outputs", *, active_run_id: str = "",
                 run_active: bool = True) -> None:
        """``active_run_id`` protects the run that is executing right now.

        It protects nothing when ``run_active`` is False. A service keeps the last run's id long
        after that run finished, so an id on its own means "the most recent run", not "a run in
        progress" — treating the two as the same thing left a finished run permanently unmanageable.
        """
        self.output_dir = str(output_dir)
        self.active_run_id = str(active_run_id or "").strip() if run_active else ""
        self._root = Path(self.output_dir) / "scout"
        self._path = self._root / "_operator" / _STATE_NAME
        self._purposes = RunPurposeIndex(self.output_dir)

    # -- reading ---------------------------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        return self._root / self._safe_run(run_id)

    def inventory(self, *, filters: Optional[Dict[str, str]] = None) -> Inventory:
        """Every stored run, narrowed by the operator's filters.

        The counts describe what is STORED, not what survived the filter — an operator narrowing to
        one domain still needs to see that ten production runs exist, or the tiles would report the
        library shrinking every time they typed.
        """
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
        total = sum(r.bytes for r in runs)
        return Inventory(runs=self._filtered(runs, filters), counts=counts, bytes_total=total)

    @staticmethod
    def _filtered(runs: List[RunRecord], filters: Optional[Dict[str, str]]) -> List[RunRecord]:
        """Narrow a run list. Every filter is a plain AND, so a preview can never select more than
        the table the operator was looking at."""
        f = {k: str(v or "").strip() for k, v in (filters or {}).items()}
        purpose = f.get("purpose", "").lower().replace("-", "_")
        if purpose and purpose != "all":
            runs = [r for r in runs if r.purpose == purpose]
        run_q = f.get("run", "").lower()
        if run_q:
            runs = [r for r in runs if run_q in r.run_id.lower()]
        text = f.get("text", "").lower()
        if text:
            runs = [r for r in runs
                    if text in r.run_id.lower() or any(text in d.lower() for d in r.domains)]
        since, until = f.get("since", ""), f.get("until", "")
        if since:
            runs = [r for r in runs if r.created_at and r.created_at >= since]
        if until:
            # A bare date means the whole of that day, so compare only as far as the operator typed.
            runs = [r for r in runs if r.created_at and r.created_at[:len(until)] <= until]
        trash = f.get("trash", "").lower()
        if trash in ("1", "true", "yes", "only"):
            runs = [r for r in runs if r.trashed]
        elif trash in ("0", "false", "no", "exclude"):
            runs = [r for r in runs if not r.trashed]
        return runs

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
            preview.files += record.files
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

    def classify(self, run_ids: Iterable[str], *, purpose: str) -> Dict[str, Any]:
        """Record what an unclassified run actually was — the explicit choice it demands.

        Requiring a human decision only works if there is a way to make one. Two limits keep it from
        becoming a loophole: a run may only be labelled with a *removable* purpose, so this cannot
        hand out production's sweep-protection; and a run that already declared its purpose keeps it,
        because re-labelling something to make it deletable is not a cleanup step, it is a way to
        delete the thing you were told not to.
        """
        wanted = normalise_purpose(purpose)
        classified, refused = [], []
        for raw in run_ids or []:
            run_id = self._safe_run(str(raw or ""))
            if not run_id or not self.run_dir(run_id).is_dir():
                continue
            if wanted not in REMOVABLE_PURPOSES:
                refused.append({"run_id": run_id,
                                "reason": f"a run cannot be labelled {purpose!r} here"})
                continue
            current = self._purpose(run_id)
            if current != PURPOSE_UNCLASSIFIED:
                refused.append({"run_id": run_id,
                                "reason": f"the run already declared its purpose ({current})"})
                continue
            # config.json is immutable by design, so the operator's decision is recorded as an
            # OVERLAY beside it rather than by rewriting what the run itself claimed at launch.
            state = self._state()
            state.setdefault("classified", {})[run_id] = {
                "purpose": wanted, "decided_at": _now()}
            self._save(state)
            self._purposes = RunPurposeIndex(self.output_dir)   # the decision is effective at once
            classified.append(run_id)
        return {"ok": True, "classified": classified, "refused": refused}

    def restore(self, run_ids: Iterable[str]) -> Dict[str, Any]:
        """Put a run back whole — the record, its evidence and its visibility.

        Only a run that is actually in Trash can come back. Reporting "restored" for an id that was
        never there (or whose directory is gone) would tell the operator their evidence is safe at
        the exact moment they need to know it is not.
        """
        state = self._state()
        in_trash = {item["run_id"] for item in state.get("trash", [])}
        restored, missing = [], []
        for raw in run_ids or []:
            run_id = str(raw or "").strip()
            if not run_id:
                continue
            if run_id not in in_trash:
                missing.append({"run_id": run_id, "reason": "not found in Trash"})
                continue
            if not self.run_dir(run_id).is_dir():
                missing.append({"run_id": run_id, "reason": "the run directory no longer exists"})
                continue
            restored.append(run_id)
        if restored:
            state["trash"] = [item for item in state.get("trash", [])
                              if item["run_id"] not in set(restored)]
            self._save(state)
        return {"ok": True, "restored": sorted(restored), "missing": missing,
                "removed_from_trash": len(restored)}

    def permanently_delete(self, run_ids: Iterable[str], *, confirm: bool) -> Dict[str, Any]:
        """Irreversible, and reachable only from Trash after a separate confirmation.

        Idempotent on purpose: an interrupted cleanup that is retried must converge rather than
        error, so a run that is already gone is reported as already gone.
        """
        # Finish anything a crash left half-done BEFORE deciding what is on disk now, so this pass
        # sees a settled tree rather than one still holding a previous run's staged remains. A run
        # completed here IS deleted — reporting it as "not in Trash" would refuse the operator the
        # very deletion that just finished on their behalf.
        recovered = set(self.recover_interrupted_deletes())
        state = self._state()
        in_trash = {item["run_id"] for item in state.get("trash", [])}
        deleted, refused, already_gone, reclaimed = [], [], [], 0
        registry_problems: List[Dict[str, str]] = []
        for raw in run_ids or []:
            run_id = str(raw or "").strip()
            if not run_id or run_id != self._safe_run(run_id):
                continue
            if run_id in recovered:
                already_gone.append(run_id)      # this call's own recovery just completed it
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
                # The files are gone and the bookkeeping is not: an older build's recovery, or a
                # directory removed outside the product. Dropping the Trash row and calling the run
                # "already gone" left the registry naming a run that exists nowhere, inside a result
                # that reported ok — the inconsistency was discoverable only by reconciling
                # afterwards. Whatever removed the files, these claims are this store's to release.
                already_gone.append(run_id)
                problems = self._finish_delete(state, self._recorded(None, run_id),
                                               metadata_known=False)
                registry_problems.extend({**p, "run_id": run_id} for p in problems)
                continue
            record = self._describe(run_id, None)
            # ORDER MATTERS. Releasing the dedup entry first and then failing to remove the files
            # leaves a run that exists on disk, is missing from the registry, and can be discovered
            # again as if it had never been scanned. So: make the run unreachable by a recoverable
            # move, complete the irreversible removal, and only then let go of what it owned.
            #
            # The record is written down BEFORE any of that. Everything the last step owes — which
            # sites this run claimed, how much it held — is read from the directory the middle step
            # destroys, so a crash used to leave a completion that had nothing left to work from.
            state.setdefault("pending_deletes", []).append(
                {"run_id": run_id, "record": record.to_dict(), "at": _now()})
            self._save(state)
            try:
                staged = self._stage_for_delete(run_id, directory)
            except OSError as exc:
                # Nothing irreversible happened and the operator is being told so: the intent must
                # go with it, or a later recovery would carry out a deletion they were told failed.
                self._drop_pending(state, run_id)
                self._save(state)
                refused.append({"run_id": run_id,
                                "reason": f"the run could not be moved for deletion ({exc.__class__.__name__})"})
                continue
            try:
                self._confined_rmtree(staged, root=self._staging_root())
            except OSError as exc:
                self._unstage(run_id, staged, directory)     # compensate: put it back untouched
                self._drop_pending(state, run_id)
                self._save(state)
                refused.append({"run_id": run_id,
                                "reason": f"deletion failed and the run was restored ({exc.__class__.__name__})"})
                continue
            # Irreversible removal is done: close the bookkeeping it owes. The same routine runs in
            # recovery, so an interrupted delete converges on exactly this state rather than a
            # cheaper one that merely looks finished.
            problems = self._finish_delete(state, record)
            registry_problems.extend({**p, "run_id": run_id} for p in problems)
            reclaimed += record.bytes
            deleted.append(run_id)
        self._save(state)
        # The files really are gone, so `deleted` is true — but a deletion that left the registry
        # inconsistent is not a success, and saying so was how a broken dedup state stayed invisible.
        return {"ok": not registry_problems, "deleted": deleted, "refused": refused,
                "already_gone": already_gone, "bytes_reclaimed": reclaimed,
                "registry_problems": registry_problems}

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
        """What the run declared at launch, or what the operator later decided it had been."""
        return self._purposes.purpose_of(run_id)

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

    def _release_domains(self, record: RunRecord, run_id: str) -> List[Dict[str, str]]:
        """Drop what this run alone justified; keep what other runs still stand behind.

        Two failures this used to have. A SHARED site kept the deleted run's id in its
        ``campaign_ids`` — History then offered a link to a run that cannot be opened, and the site
        looked as though more work stood behind it than did. And every registry failure was
        swallowed, so a deletion that left the registry inconsistent still reported success; the
        problems are returned now and travel back to the caller.
        """
        problems: List[Dict[str, str]] = []
        try:
            from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
            registry = AnalyzedSiteRegistry(self.output_dir)
        except Exception as exc:      # noqa: BLE001 - reported, never silently accepted
            return [{"domain": "*", "reason": f"the registry could not be opened "
                                              f"({type(exc).__name__})"}]
        # Every site this run has a CLAIM on, not only the ones its own prospects visited. A run can
        # be recorded against a domain it never held as a prospect — a curated import registers the
        # analysis, a target fails after registration — and sweeping only `record.domains` left those
        # claims pointing at a run that no longer exists.
        targets = set(record.domains)
        try:
            for entry in registry.all():
                if run_id in (getattr(entry, "campaign_ids", []) or []):
                    targets.add(getattr(entry, "domain", ""))
        except Exception as exc:      # noqa: BLE001 - reported, never silently accepted
            problems.append({"domain": "*",
                             "reason": f"the registry could not be listed ({type(exc).__name__})"})
        for domain in sorted(d for d in targets if d):
            try:
                entry = registry.get(domain)
                if entry is None:
                    continue
                others = [c for c in (getattr(entry, "campaign_ids", []) or []) if c != run_id]
                if others:
                    # Another run still stands behind this site: keep the entry and its history,
                    # drop only the claim that belonged to the run being deleted.
                    registry.release_campaign(domain, run_id)
                    continue
                if not registry.forget(domain, confirm=True):
                    problems.append({"domain": domain,
                                     "reason": "the registry refused to forget the site"})
            except Exception as exc:      # noqa: BLE001 - one bad domain never aborts the rest
                problems.append({"domain": domain,
                                 "reason": f"registry update failed ({type(exc).__name__})"})
        return problems

    @staticmethod
    def _pending(state: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [p for p in (state.get("pending_deletes") or [])
                if isinstance(p, dict) and p.get("run_id")]

    def _drop_pending(self, state: Dict[str, Any], run_id: str) -> None:
        state["pending_deletes"] = [p for p in self._pending(state) if p["run_id"] != run_id]

    def _recorded(self, intent: Optional[Dict[str, Any]], run_id: str) -> RunRecord:
        """Rebuild the record captured before the files went. Fields the dataclass does not own
        (`purpose_label` is derived) are dropped rather than passed back into it.

        With no record at all the purpose is still recoverable: an operator's classification is an
        overlay beside the run, not inside it, so it outlives the directory.
        """
        raw = dict((intent or {}).get("record") or {})
        kept = {k: v for k, v in raw.items() if k in RunRecord.__dataclass_fields__}
        kept["run_id"] = run_id
        if not kept.get("purpose"):
            kept["purpose"] = self._purpose(run_id) or PURPOSE_UNCLASSIFIED
        kept.setdefault("created_at", "")
        return RunRecord(**kept)

    def _finish_delete(self, state: Dict[str, Any], record: RunRecord, *,
                       metadata_known: bool = True) -> List[Dict[str, str]]:
        """Everything a completed removal owes, done from the record instead of from the tree.

        Shared by the delete and by recovery so both converge on ONE state. Recovery used to stop
        after removing the files, which left the registry claiming a run that existed nowhere and a
        retry reporting success over it.
        """
        run_id = record.run_id
        # Forget the dedup entries this run is the ONLY source of. A site production also scanned
        # keeps its history untouched — only this run's claim on it goes.
        problems = self._release_domains(record, run_id)
        state.setdefault("journal", []).append(
            {"run_id": run_id, "op": "permanent_delete", "at": _now(),
             "registry_problems": len(problems)})
        state["journal"] = state["journal"][-200:]
        state["trash"] = [i for i in state.get("trash", []) if i.get("run_id") != run_id]
        if not any(t.get("run_id") == run_id for t in (state.get("tombstones") or [])):
            # Scope, counts and the moment — never the deleted content itself. A directory staged by
            # an older build carries no record, and zeroes would be asserted as facts, so the
            # tombstone says the counts went with the files.
            state.setdefault("tombstones", []).append({
                "run_id": run_id, "purpose": record.purpose, "deleted_at": _now(),
                "sites": len(record.domains), "findings": record.findings,
                "screenshots": record.screenshots, "videos": record.videos,
                "bytes_reclaimed": record.bytes,
                "metadata": "recorded" if metadata_known else "lost with the files"})
        self._drop_pending(state, run_id)
        return problems

    def _staging_root(self) -> Path:
        return self._root / "_operator" / _STAGING_NAME

    def _stage_for_delete(self, run_id: str, directory: Path) -> Path:
        """Move a run out of the visible tree. Recoverable: nothing is lost if the next step fails."""
        staging = self._staging_root()
        staging.mkdir(parents=True, exist_ok=True)
        target = staging / run_id
        if target.exists():
            self._confined_rmtree(target, root=staging)   # a leftover from an interrupted delete
        os.rename(directory, target)
        return target

    def _unstage(self, run_id: str, staged: Path, original: Path) -> None:
        """Undo a staging move after a failed deletion, so the run is exactly where it was."""
        try:
            if staged.is_dir() and not original.exists():
                os.rename(staged, original)
        except OSError:
            pass          # the run is still whole in staging; recovery reports it rather than lying

    def reconcile(self, *, repair: bool = False) -> Dict[str, Any]:
        """Compare the four places a deletion touches and report where they disagree.

        A permanent delete writes, in this order: stage the files out of the tree, remove them,
        release the registry claims, then update Trash and the journal. Because the order is fixed,
        a crash can only leave one of a few KNOWN shapes — and naming those shapes is what turns
        recovery into a decision instead of a guess:

        * files still in staging — the operator confirmed them away and the removal did not finish;
        * a Trash entry for a run whose directory is gone — the delete completed and the bookkeeping
          did not;
        * a registry claim naming a run that exists in neither the tree nor Trash — history pointing
          at a run nobody can open.

        With ``repair`` it converges each of them; without, it only reports, so the same routine can
        answer "is this store consistent?" without changing anything.
        """
        problems: List[Dict[str, str]] = []
        repaired: List[Dict[str, str]] = []

        def _staged_now() -> List[str]:
            root = self._staging_root()
            return [p.name for p in sorted(root.iterdir()) if p.is_dir()] if root.is_dir() else []

        staged = _staged_now()
        for run_id in staged:
            problems.append({"run_id": run_id, "kind": "staged",
                             "reason": "a confirmed deletion did not finish"})
        # Repaired in the SAME order the delete writes, so one pass converges. Fixing staging and
        # then judging Trash against the pre-repair picture is what made recovery need two runs —
        # and a store that needs recovering twice is a store nobody can call settled.
        if repair and staged:
            repaired += [{"run_id": r, "kind": "staged", "action": "deletion completed"}
                         for r in self.recover_interrupted_deletes()]
            staged = _staged_now()

        state = self._state()
        live_trash = []
        for item in state.get("trash", []):
            run_id = str(item.get("run_id") or "")
            if run_id and not self.run_dir(run_id).is_dir() and run_id not in staged:
                problems.append({"run_id": run_id, "kind": "trash_without_run",
                                 "reason": "Trash holds a run whose files are already gone"})
                if repair:
                    repaired.append({"run_id": run_id, "kind": "trash_without_run",
                                     "action": "trash entry dropped"})
                    continue
            live_trash.append(item)

        # The claims are judged against what Trash will hold AFTER this pass; otherwise a claim
        # belonging to an entry dropped a moment ago survives until the next restart.
        known = {str(i.get("run_id") or "") for i in (live_trash if repair else state.get("trash", []))}
        try:
            from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
            registry = AnalyzedSiteRegistry(self.output_dir)
            for entry in registry.all():
                domain = getattr(entry, "domain", "")
                for claim in list(getattr(entry, "campaign_ids", []) or []):
                    if self.run_dir(claim).is_dir() or claim in known or claim in staged:
                        continue
                    problems.append({"run_id": claim, "kind": "dangling_claim",
                                     "reason": f"{domain} still names a run that no longer exists"})
                    if repair and registry.release_campaign(domain, claim):
                        repaired.append({"run_id": claim, "kind": "dangling_claim",
                                         "action": f"claim on {domain} released"})
        except Exception as exc:      # noqa: BLE001 - reported, never silently accepted
            problems.append({"run_id": "*", "kind": "registry",
                             "reason": f"the registry could not be read ({type(exc).__name__})"})

        if repair and repaired:
            state["trash"] = live_trash
            state.setdefault("journal", []).append(
                {"op": "reconcile", "at": _now(), "repaired": len(repaired)})
            state["journal"] = state["journal"][-200:]
            self._save(state)
        return {"ok": not problems, "problems": problems, "repaired": repaired}

    def recover_interrupted_deletes(self) -> List[str]:
        """Finish what a crash left half-done. A staged run is one whose files the operator already
        confirmed away, so completing the removal is the consistent state — not resurrection.

        Completing means all of it: remove the files, release the claims, write the tombstone, close
        Trash and the journal. Stopping after the files was the defect — the retry that followed saw
        no directory, called the run already gone, and returned success over a registry still naming
        it. The record captured before the point of no return is what makes the rest possible.

        An intent with the run still whole in the tree is the one shape that is NOT completed: the
        irreversible step never began, nothing was lost, and a recovery pass must not delete files on
        a confirmation the operator can simply give again.
        """
        state = self._state()
        pending = {p["run_id"]: p for p in self._pending(state)}
        staging = self._staging_root()
        staged = {p.name: p for p in sorted(staging.iterdir())
                  if p.is_dir()} if staging.is_dir() else {}
        finished: List[str] = []
        changed = False
        for run_id in sorted(set(pending) | set(staged)):
            directory = staged.get(run_id)
            if directory is None:
                if self.run_dir(run_id).is_dir():
                    self._drop_pending(state, run_id)     # never started; give the confirmation back
                    changed = True
                    continue
            else:
                try:
                    self._confined_rmtree(directory, root=staging)
                except OSError:
                    continue      # still on disk: reconcile keeps reporting it rather than lying
            self._finish_delete(state, self._recorded(pending.get(run_id), run_id),
                                metadata_known=run_id in pending)
            finished.append(run_id)
            changed = True
        if changed:
            self._save(state)
        return finished

    def _confined_rmtree(self, directory: Path, *, root: Optional[Path] = None) -> None:
        resolved = directory.resolve()
        base = (root or self._root).resolve()
        if base not in resolved.parents or resolved == base:
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
                "tombstones": [t for t in (raw.get("tombstones") or []) if isinstance(t, dict)],
                # Deletions confirmed and past the point of no return, each carrying what its
                # completion needs after the files it describes are gone.
                "pending_deletes": [p for p in (raw.get("pending_deletes") or [])
                                    if isinstance(p, dict) and p.get("run_id")],
                "journal": [j for j in (raw.get("journal") or []) if isinstance(j, dict)],
                "classified": {k: v for k, v in (raw.get("classified") or {}).items()
                               if isinstance(v, dict)}}

    def _save(self, state: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        atomic_replace(tmp, self._path)
