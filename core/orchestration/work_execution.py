"""WorkExecutionService (v3.0.0 Milestone 7) - the persisted client-work execution lifecycle.

Factory drives and PERSISTS: approval -> execution started -> progress/blockers -> produced
artifacts -> evidence registration -> validation -> delivery package -> resume after restart. The
Executor is pluggable: real work is Claude-Code-driven and human-approved (Factory records what was
produced); deterministic acceptance FIXTURE executors drive the same contract in CI. This is NOT a
second Claude Code and never claims an autonomous agent ran. No LLM/network is used here; state and
artifacts live on disk in the existing project workspace, so a later Claude session resumes cleanly.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.orchestration.content_safety import ContentSecretScanner
from core.orchestration.providers import ClockProvider, IdProvider
from core.orchestration.work_state_manager import WorkStateManager
from core.schemas.work_execution import ExecutionContext, ExecutionOutcome, ValidationOutcome
from core.schemas.work_run_state import WorkRunState

# Delivery content scanning. Read size is a memory bound, not a coverage bound: every byte of every
# member is read exactly once, and the same bytes produce the member's SHA-256, so what was scanned
# and what gets sealed cannot drift apart.
_SCAN_CHUNK_BYTES = 256 * 1024
# How far back a still-possible match may begin. Beyond this the member is refused rather than
# scanned with a prefix quietly dropped.
_SCAN_PENDING_MAX_CHARS = 1024 * 1024
# Always retained, so a pattern's opening literal split across two reads survives. The longest
# opening literal is `-----BEGIN OPENSSH PRIVATE KEY-----`; 256 is far above it.
_SCAN_MIN_TAIL_CHARS = 256

# Recognition of a match that has STARTED but cannot yet be decided, for the three patterns whose
# interior contains unbounded whitespace. A carry measured in fixed characters cannot cover these:
# `password_assignment` is `\bpass(?:word|wd)?\s*[:=]\s*['"]?[^\s'"]{4,}`, so `password`, a long run
# of spaces, `=`, another long run, and three value characters can push the keyword arbitrarily far
# back while the value is still one character short of matching. Each expression below must reach the
# end of the buffer, so `re.search` returns the leftmost — that is, the earliest — position from
# which a match could still complete. Every other supported pattern is whitespace-free, so a pending
# one can only sit inside the trailing non-whitespace run, which is handled separately.
_PENDING_MATCH_PATTERNS: Tuple["re.Pattern[str]", ...] = (
    re.compile(r"\bBearer\s*[A-Za-z0-9._\-]{0,15}$"),
    re.compile(r"(?i)\b(?:set-)?cookie\s*(?:[:=]\s*\S{0,}?)?$"),
    re.compile(r"(?i)\bpass(?:word|wd)?\s*(?:[:=]\s*(?:['\"]?[^\s'\"]{0,3})?)?$"),
)


def _carry_start(buf: str) -> int:
    """The earliest index a still-possible match could begin at — never a fixed offset.

    Returns -1 when a pending candidate is older than `_SCAN_PENDING_MAX_CHARS`, i.e. when the
    caller must refuse the member instead of silently discarding the prefix.
    """
    start = max(0, len(buf) - _SCAN_MIN_TAIL_CHARS)
    # A whitespace-free pattern can only be pending inside the trailing non-whitespace run.
    run = len(buf)
    while run > 0 and not buf[run - 1].isspace():
        run -= 1
    start = min(start, run)
    # Searched over the WHOLE buffer, deliberately. An earlier version cropped to the last
    # `_SCAN_PENDING_MAX_CHARS` first, which threw away the very anchor the ceiling exists to catch:
    # a candidate reaching back further than the ceiling simply disappeared from the window, no
    # refusal fired, and the prefix was dropped with the secret still pending. The buffer is one
    # carry plus one chunk, and the carry is itself bounded by the ceiling (anything longer has
    # already been refused), so this stays bounded work.
    for pattern in _PENDING_MATCH_PATTERNS:
        match = pattern.search(buf)
        if match is not None:
            start = min(start, match.start())
    if len(buf) - start > _SCAN_PENDING_MAX_CHARS:
        return -1          # the candidate outruns the policy: refuse by name, never crop and forget
    return start
# Beyond this a member is refused rather than scanned, so the work stays bounded and nothing is
# waved through for being inconveniently large.
_SCAN_CEILING_BYTES = 512 * 1024 * 1024

# Binary evidence whose content is not text-scannable. Admission requires BOTH an expected evidence
# extension and a signature that agrees with it. A signature alone is not enough: a `.txt` artifact
# starting with PNG magic would otherwise be promoted to an allowed binary and the rest of it never
# read, so the scan could be bypassed by prepending eight bytes.
_VERIFIED_BINARY_SIGNATURES: Tuple[Tuple[str, bytes], ...] = (
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpeg", b"\xff\xd8\xff"),
    ("gif", b"GIF87a"),
    ("gif", b"GIF89a"),
    ("webm", b"\x1a\x45\xdf\xa3"),
    ("pdf", b"%PDF-"),
    ("zip", b"PK\x03\x04"),
)
_EXPECTED_BINARY_TYPES: Dict[str, Tuple[str, ...]] = {
    ".png": ("png",), ".jpg": ("jpeg",), ".jpeg": ("jpeg",), ".gif": ("gif",),
    ".webm": ("webm",), ".mp4": ("mp4",), ".mov": ("mp4",), ".m4v": ("mp4",),
    ".pdf": ("pdf",), ".zip": ("zip",),
}


def _detected_binary_type(head: bytes) -> str:
    """The format `head` actually is, by signature alone — never inferred from the name."""
    for label, signature in _VERIFIED_BINARY_SIGNATURES:
        if head.startswith(signature):
            return label
    # ISO base media (mp4/mov/m4v): the brand marker sits at offset 4, not 0.
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    return ""


def _verified_binary_type(rel: str, head: bytes) -> str:
    """The allowed evidence type, only where the name's expectation and the bytes agree.

    Disagreement in either direction fails closed: an unexpected extension (`notes.txt` holding PNG
    magic) and a mismatched signature (`shot.png` holding a ZIP) are both refused rather than
    admitted as an unscannable limitation.
    """
    expected = _EXPECTED_BINARY_TYPES.get(Path(rel).suffix.lower())
    if not expected:
        return ""
    detected = _detected_binary_type(head)
    return detected if detected in expected else ""


_ARK = "40_ark_work"
_PROGRESS = {"READY_TO_EXECUTE": 60, "EXECUTING": 75, "EXECUTION_PARTIAL": 75, "VERIFYING": 85,
             "REPAIR_REQUIRED": 70, "READY_FOR_REVIEW": 90, "READY_FOR_DELIVERY": 95,
             "DELIVERY_PREPARED": 98, "COMPLETED": 100, "BLOCKED": 60, "FAILED": 100,
             "CANCELLED": 100}


def _atomic_replace(tmp: Path, path: Path) -> None:
    """The shared bounded retry (see :mod:`core.atomic_io`).

    This module proved the failure first — the Dashboard polling worker status while a background
    worker saved state — and the Scout stores then hit the identical one. Keeping two retry loops
    meant two definitions of "transient", so there is now one.
    """
    from core.atomic_io import atomic_replace
    atomic_replace(tmp, path)


class WorkExecutionError(Exception):
    pass


@dataclass
class LifecycleView:
    project_id: str
    status: str
    progress: int
    evidence_count: int
    tests_run: int
    tests_passed: int
    blockers: List[str]
    next_action: str
    delivery_ready: bool

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class WorkExecutionService:
    def __init__(self, clock: Optional[ClockProvider] = None, ids: Optional[IdProvider] = None,
                 output_dir: str = "outputs") -> None:
        self._clock = clock or ClockProvider()
        self._ids = ids or IdProvider()
        self._out = Path(output_dir)
        self._sm = WorkStateManager(self._clock)
        self._scanner = ContentSecretScanner()

    # --- workspace + safe persistence ------------------------------------------------------------
    @staticmethod
    def _safe_pid(pid: str) -> str:
        # One shared project-id contract at every boundary (workspace/state/artifacts/evidence/
        # validation/delivery) - OS-independent, incl. Windows reserved names.
        from core.orchestration.providers import validate_project_id
        if not validate_project_id(pid):
            raise WorkExecutionError(f"unsafe project id: {pid!r}")
        return pid

    def _ws(self, pid: str) -> Path:
        return self._out / self._safe_pid(pid) / _ARK

    def workspace_dir(self, pid: str) -> Path:
        """The confined project workspace. Validates the project id via the single
        ``validate_project_id`` contract FIRST (raises ``WorkExecutionError`` for any unsafe id),
        so a caller never composes an output path from an unvalidated id."""
        return self._ws(pid)

    def project_exists(self, pid: str) -> bool:
        """True only for a genuinely-existing project. Validates the id first (raises for unsafe),
        so this can gate a write without ever constructing a path from an unvalidated id."""
        return (self._ws(pid) / "WORK_RUN_STATE.json").exists()

    def _confine(self, ws: Path, rel: str) -> Path:
        """Resolve ``rel`` under the workspace, refusing any path that escapes it (traversal-safe)."""
        target = (ws / rel).resolve()
        wsr = ws.resolve()
        if target != wsr and wsr not in target.parents:
            raise WorkExecutionError(f"artifact path escapes the workspace: {rel!r}")
        return target

    @staticmethod
    def _hash_file(path: Path) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _artifact_files(outcome: Dict[str, Any]) -> List[str]:
        arts = [a.get("filename") for a in outcome.get("artifacts", [])]
        evs = [e.get("relative_path") for e in outcome.get("evidence", [])]
        return sorted({p for p in (arts + evs) if p})

    def _hash_map(self, pid: str, rels: List[str]) -> Dict[str, str]:
        ws = self._ws(pid)
        out: Dict[str, str] = {}
        for rel in rels:
            target = self._confine(ws, rel)   # refuses traversal even from a malicious executor
            if target.is_file():
                out[rel] = self._hash_file(target)
        return out

    def _append_evidence(self, pid: str, items: List[Any]) -> None:
        """Append evidence items to EVIDENCE_INDEX.json (dedupe by evidence_id, keep latest)."""
        idx = self._read_json(self._ws(pid) / "EVIDENCE_INDEX.json")
        merged: Dict[str, Dict[str, Any]] = {}
        for e in idx.get("evidence", []):
            if isinstance(e, dict) and e.get("evidence_id"):
                merged[e["evidence_id"]] = e
        for item in items:
            d = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            if d.get("evidence_id"):
                merged[d["evidence_id"]] = d
        out = list(merged.values())
        self._write(self._ws(pid) / "EVIDENCE_INDEX.json",
                    json.dumps({"evidence": out, "count": len(out)}, indent=2, sort_keys=True))

    def _registered_files(self, pid: str) -> List[str]:
        """Every registered artifact + evidence relative path (execution outcome + evidence index,
        which also carries validation-run evidence)."""
        prog = self._read_json(self._ws(pid) / "EXECUTION_PROGRESS.json")
        files = set(self._artifact_files(prog.get("outcome", {})))
        idx = self._read_json(self._ws(pid) / "EVIDENCE_INDEX.json")
        files.update(e.get("relative_path") for e in idx.get("evidence", [])
                     if isinstance(e, dict) and e.get("relative_path"))
        return sorted(files)

    @staticmethod
    def _manifest_digest(hashes: Dict[str, str]) -> str:
        """Deterministic package digest over the sorted (path, sha256) pairs."""
        import hashlib
        payload = "\n".join(f"{k}:{hashes[k]}" for k in sorted(hashes))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _read_json(self, path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, path: Path, text: str) -> None:
        """Atomic per-file write with a secret scan (never wipes the workspace)."""
        if self._scanner.scan_text(path.name, text):
            raise WorkExecutionError(f"refusing to persist {path.name}: secret-like content detected")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        _atomic_replace(tmp, path)

    def _load_state(self, pid: str) -> WorkRunState:
        p = self._ws(pid) / "WORK_RUN_STATE.json"
        if not p.exists():
            raise WorkExecutionError(f"no work run state for '{pid}' (run analyze-job first)")
        return WorkRunState.from_dict(self._read_json(p))

    def _save_state(self, pid: str, state: WorkRunState) -> None:
        self._write(self._ws(pid) / "WORK_RUN_STATE.json",
                    json.dumps(state.to_dict(), indent=2, sort_keys=True))

    def _enforce_execution_boundary(self, pid: str, executor: Any) -> None:
        """Fail-closed trust + private-work-dir preflight at the ACTUAL execution boundary — enforced
        for any executor that runs client code, regardless of whether the caller is the CLI, the
        Dashboard, or a direct service/adapter call. FAIL-CLOSED: an executor must EXPLICITLY declare a
        boolean ``executes_client_code`` capability — a missing/non-boolean capability is refused, not
        assumed safe. Only an executor that explicitly declares ``False`` (a fixture / recording-only
        adapter that runs no untrusted code) is exempt. Never simulates isolation."""
        cap = getattr(executor, "executes_client_code", None)
        if not isinstance(cap, bool):
            raise WorkExecutionError(
                "refused (fail-closed): executor "
                f"{getattr(executor, 'executor_id', type(executor).__name__)!r} does not declare a "
                "boolean executes_client_code capability; declare it explicitly (True runs client "
                "code and is gated; False is a recording/fixture adapter)")
        if not cap:
            return                                            # explicitly declared recording/fixture
        from core.orchestration.execution_trust import (
            assess_execution_trust,
            preflight_work_isolation,
        )
        ws = str(self._ws(pid))
        trust = assess_execution_trust(ws)
        if not trust.trusted:
            raise WorkExecutionError(f"refused (untrusted repository): {trust.reason}. {trust.action}")
        pf = preflight_work_isolation(ws)
        if not pf.ok:
            raise WorkExecutionError(f"refused (work-isolation preflight): {pf.reason}. {pf.action}")

    def _context(self, pid: str) -> ExecutionContext:
        wp = self._read_json(self._ws(pid) / "WORK_PACKET.json")
        reqs = [self._req(r) for r in wp.get("requirements", [])]
        return ExecutionContext(project_id=pid, profile=wp.get("capability_profile", ""),
                                workspace_dir=str(self._ws(pid)), requirements=reqs,
                                now=self._clock.now_iso())

    @staticmethod
    def _req(r: Any) -> str:
        return str(r.get("text") or r.get("requirement") or r) if isinstance(r, dict) else str(r)

    # --- lifecycle ------------------------------------------------------------------------------
    def approve(self, pid: str, reviewer: str, note: str = "") -> WorkRunState:
        if not reviewer.strip():
            raise WorkExecutionError("reviewer identity is required to approve")
        state = self._load_state(pid)
        if state.status == "WAITING_FOR_INFORMATION":
            # The operator has resolved the questions and chosen to proceed.
            state = self._sm.transition(state, "PLANNED", "operator resolved missing information",
                                        reviewer)
        if state.status not in ("PLANNED", "WAITING_FOR_APPROVAL"):
            raise WorkExecutionError(f"cannot approve from state {state.status}")
        state = self._sm.transition(state, "READY_TO_EXECUTE", f"approved by {reviewer}: {note}"[:200],
                                    reviewer)
        now = state.updated_at or self._clock.now_iso()   # SAME timestamp for grant + APPROVAL evidence
        self._write(self._ws(pid) / "APPROVAL.json",
                    json.dumps({"reviewer": reviewer, "note": note, "approved": True, "at": now},
                               indent=2, sort_keys=True))
        # AUTHORITATIVE execution approval lives in the operator-only control store OUTSIDE the client
        # work dir (P0-1); the workspace marker is EVIDENCE only. The grant is bound to the project,
        # the resolved workspace, the approval timestamp, and the approval generation (state version).
        from core.orchestration.execution_trust import TRUST_MARKER, grant_execution_authority
        grant_execution_authority(str(self._ws(pid)), reviewer=reviewer, approval_at=now,
                                  generation=state.state_version, env=dict(os.environ))
        self._write(self._ws(pid) / TRUST_MARKER, json.dumps(
            {"approved_for_execution": True, "reviewer": reviewer, "project_id": pid, "at": now,
             "note": "EVIDENCE ONLY — authority is the control-store grant (execution_trust)"},
            indent=2, sort_keys=True))
        self._save_state(pid, state)
        return state

    def execute(self, pid: str, executor: Any) -> Tuple[WorkRunState, ExecutionOutcome]:
        state = self._load_state(pid)
        if state.status in ("REPAIR_REQUIRED", "BLOCKED"):
            state = self._sm.transition(state, "READY_TO_EXECUTE", "repair/resume requested", "cli")
        if state.status != "READY_TO_EXECUTE":
            raise WorkExecutionError(f"cannot start execution from state {state.status} (approve first)")
        self._enforce_execution_boundary(pid, executor)   # fail-closed trust + isolation preflight
        eid = getattr(executor, "executor_id", "executor")
        state = self._sm.transition(state, "EXECUTING", "execution started", eid)
        self._save_state(pid, state)                      # persist BEFORE running the executor
        outcome = executor.execute(self._context(pid))
        outcome_dict = outcome.to_dict()
        self._write(self._ws(pid) / "EXECUTION_PROGRESS.json", json.dumps({
            "executor": eid, "is_acceptance_fixture": bool(getattr(executor, "is_acceptance_fixture",
                                                                   False)),
            "at": self._clock.now_iso(), "outcome": outcome_dict}, indent=2, sort_keys=True))
        # Rebuild the index from this execution, but PRESERVE validation-run evidence from earlier
        # attempts (evidence/validation/<id>/ is append-only; later attempts never overwrite it).
        prior = self._read_json(self._ws(pid) / "EVIDENCE_INDEX.json").get("evidence", [])
        kept = [e for e in prior if isinstance(e, dict)
                and str(e.get("relative_path", "")).startswith("evidence/validation/")]
        merged = kept + [e.to_dict() for e in outcome.evidence]
        self._write(self._ws(pid) / "EVIDENCE_INDEX.json", json.dumps({
            "evidence": merged, "count": len(merged)}, indent=2, sort_keys=True))
        # Content-hash every produced artifact + evidence file (confined) so a later change is detectable.
        hashes = self._hash_map(pid, self._artifact_files(outcome_dict))
        self._write(self._ws(pid) / "ARTIFACT_HASHES.json",
                    json.dumps({"at": self._clock.now_iso(), "hashes": hashes}, indent=2, sort_keys=True))
        to = "BLOCKED" if outcome.blockers else "VERIFYING"
        state = self._sm.transition(state, to, "execution produced artifacts", eid)
        self._save_state(pid, state)
        return state, outcome

    def record_background_failure(self, pid: str, error: str) -> None:
        """Make a background-worker failure OBSERVABLE and fail-closed: persist a bounded,
        secret-redacted blocker (type + message only, never a traceback) so ``status`` surfaces an
        actionable blocker instead of a silent state, and move the run to BLOCKED when permitted.
        The caller must pass an already-redacted, bounded reason."""
        from core.orchestration.work_state_manager import InvalidTransitionError
        from core.schemas.work_run_state import TERMINAL_STATES
        reason = (error or "background worker failed").strip()[:300]
        try:
            state = self._load_state(pid)
        except WorkExecutionError:
            return
        prog = self._read_json(self._ws(pid) / "EXECUTION_PROGRESS.json")
        outcome = prog.get("outcome", {}) if isinstance(prog, dict) else {}
        outcome.setdefault("blockers", [])
        if reason not in outcome["blockers"]:
            outcome["blockers"].append(reason)
        prog["outcome"] = outcome
        prog["background_error"] = reason
        prog["failed_at"] = self._clock.now_iso()
        self._write(self._ws(pid) / "EXECUTION_PROGRESS.json",
                    json.dumps(prog, indent=2, sort_keys=True))
        if state.status not in TERMINAL_STATES and state.status != "BLOCKED":
            try:
                state = self._sm.transition(state, "BLOCKED",
                                            f"background worker failure: {reason}"[:200], "worker")
                self._save_state(pid, state)
            except InvalidTransitionError:
                pass

    def recover_interrupted(self, pid: str) -> Optional[WorkRunState]:
        """Reconcile a worker that died mid-run. ``execute`` persists EXECUTING before running the
        executor and only leaves EXECUTING once the executor returns; so a project still at EXECUTING
        with no live worker means the process was interrupted (a restart/crash). Move it to BLOCKED
        with an explicit blocker so it can be safely resumed - never silently reset or lost. Idempotent
        (returns None when there is nothing to recover). The caller is responsible for confirming no
        worker is actually running in-process before calling this."""
        try:
            state = self._load_state(pid)
        except WorkExecutionError:
            return None
        if state.status != "EXECUTING":
            return None
        state = self._sm.transition(state, "BLOCKED",
                                    "worker interrupted (process restart); resume to continue",
                                    "recovery")
        # Surface the interruption through status() by recording it as an execution blocker.
        prog = self._read_json(self._ws(pid) / "EXECUTION_PROGRESS.json")
        outcome = prog.get("outcome", {}) if isinstance(prog, dict) else {}
        outcome.setdefault("blockers", [])
        if "worker interrupted (process restart); resume to continue" not in outcome["blockers"]:
            outcome["blockers"].append("worker interrupted (process restart); resume to continue")
        prog["outcome"] = outcome
        prog.setdefault("executor", "recovery")
        prog["recovered_at"] = self._clock.now_iso()
        self._write(self._ws(pid) / "EXECUTION_PROGRESS.json", json.dumps(prog, indent=2, sort_keys=True))
        self._save_state(pid, state)
        return state

    def validate(self, pid: str, executor: Any) -> Tuple[WorkRunState, ValidationOutcome]:
        state = self._load_state(pid)
        if state.status != "VERIFYING":
            raise WorkExecutionError(f"cannot validate from state {state.status}")
        self._enforce_execution_boundary(pid, executor)   # fail-closed trust + isolation preflight
        eid = getattr(executor, "executor_id", "executor")
        result = executor.validate(self._context(pid))
        self._write(self._ws(pid) / "TEST_RESULTS.json",
                    json.dumps(result.to_dict(), indent=2, sort_keys=True))
        # Register validation-produced evidence (pass, fail, and timeout alike) in the real
        # evidence index BEFORE snapshotting, so it is part of the validated integrity set.
        if getattr(result, "evidence", None):
            self._append_evidence(pid, result.evidence)
        if result.passed:
            # Snapshot the exact artifact hashes that were validated, so any later change is caught
            # before delivery. Validation stops at READY_FOR_REVIEW - delivery needs explicit review.
            validated = self._hash_map(pid, self._registered_files(pid))
            self._write(self._ws(pid) / "VALIDATED_ARTIFACTS.json", json.dumps(
                {"at": self._clock.now_iso(), "hashes": validated}, indent=2, sort_keys=True))
            state = self._sm.transition(state, "READY_FOR_REVIEW", "validation passed", eid)
        else:
            state = self._sm.transition(state, "REPAIR_REQUIRED",
                                        f"validation failed: {len(result.failures)} failure(s)", eid)
        self._save_state(pid, state)
        return state, result

    def review(self, pid: str, reviewer: str, approved: bool = True, note: str = "") -> WorkRunState:
        """Explicit operator review gate. Only an approved review advances READY_FOR_REVIEW ->
        READY_FOR_DELIVERY; a rejected review sends it back to REPAIR_REQUIRED."""
        if not reviewer.strip():
            raise WorkExecutionError("reviewer identity is required to review")
        state = self._load_state(pid)
        if state.status != "READY_FOR_REVIEW":
            raise WorkExecutionError(f"cannot review from state {state.status} (validate first)")
        decision = "approved" if approved else "rejected"
        self._write(self._ws(pid) / "REVIEW.json", json.dumps(
            {"reviewer": reviewer, "approved": bool(approved), "note": note,
             "at": self._clock.now_iso()}, indent=2, sort_keys=True))
        target = "READY_FOR_DELIVERY" if approved else "REPAIR_REQUIRED"
        state = self._sm.transition(state, target, f"review {decision} by {reviewer}: {note}"[:200],
                                    reviewer)
        self._save_state(pid, state)
        return state

    def prepare_delivery(self, pid: str) -> Dict[str, Any]:
        """The durable delivery-preparation boundary (v3.0.2 M1).

        Rehashes every registered artifact + evidence file, compares them to the validated
        snapshot, secret-scans the exact delivery file set, requires the approved explicit
        review, writes the exact delivery manifest (per-file SHA-256 + deterministic package
        digest), and only then transitions READY_FOR_DELIVERY -> DELIVERY_PREPARED. Completion
        (``mark_delivered``) is impossible without this step.
        """
        state = self._load_state(pid)
        if state.status != "READY_FOR_DELIVERY":
            raise WorkExecutionError(f"delivery preparation needs state READY_FOR_DELIVERY "
                                     f"(is {state.status})")
        ws = self._ws(pid)
        review = self._read_json(ws / "REVIEW.json")
        if not review.get("approved"):
            raise WorkExecutionError("delivery needs an approved explicit operator review "
                                     "(REVIEW.json); run the review step first")
        ev = self._read_json(ws / "EVIDENCE_INDEX.json")
        tr = self._read_json(ws / "TEST_RESULTS.json")
        fr = self._read_json(ws / "FEASIBILITY_REPORT.json")
        prog = self._read_json(ws / "EXECUTION_PROGRESS.json")
        files = self._registered_files(pid)

        # Rehash and compare with the validated snapshot: reject missing, added, removed, or
        # changed registered files.
        validated = self._read_json(ws / "VALIDATED_ARTIFACTS.json").get("hashes", {})
        if not validated:
            raise WorkExecutionError("no validated artifact snapshot exists; validate before delivery")
        current = self._hash_map(pid, files)
        changed = sorted(k for k in set(validated) | set(current) if validated.get(k) != current.get(k))
        if changed:
            raise WorkExecutionError(
                f"artifacts changed after validation ({', '.join(changed[:5])}"
                f"{'...' if len(changed) > 5 else ''}); re-validate before delivery")
        # Scan the registered members first, so a leak refuses before any document is generated.
        # `_scan_package` raises on anything it cannot read, decode or recognise; it never returns a
        # partial verdict that a caller could mistake for "clean".
        scanned = self._scan_package(pid, files)
        # Compare the bytes that were SCANNED against the validated snapshot, not a third reading of
        # the same paths. The `_hash_map` comparison above opens and reads the files again, so a
        # member replaced between that pass and this one would be scanned and sealed while never
        # having been validated — the delivered package would carry bytes no validation ever saw.
        scanned_hashes = {entry["path"]: entry["sha256"] for entry in scanned}
        drifted = sorted(k for k in set(validated) | set(scanned_hashes)
                         if validated.get(k) != scanned_hashes.get(k))
        if drifted:
            raise WorkExecutionError(
                f"artifacts changed after validation ({', '.join(drifted[:5])}"
                f"{'...' if len(drifted) > 5 else ''}); re-validate before delivery")

        produced = [a.get("filename") for a in prog.get("outcome", {}).get("artifacts", [])]
        # Partition the registered files into artifacts vs evidence by the actual evidence paths
        # (the operator executor records an evidence file as both an artifact and evidence).
        ev_rels = {e.get("relative_path") for e in ev.get("evidence", [])
                   if isinstance(e, dict) and e.get("relative_path")}
        ev_rels |= {e.get("relative_path") for e in prog.get("outcome", {}).get("evidence", [])
                    if isinstance(e, dict) and e.get("relative_path")}
        evidence_files = sorted(f for f in files if f in ev_rels)
        artifacts = sorted(f for f in files if f not in ev_rels)
        # Generate/preserve the delivery documents BEFORE sealing and INCLUDE them in the exact
        # package integrity set (M0.2). The report is always regenerated; the client message is
        # preserved when it already exists (never silently overwriting an operator edit).
        self._write(ws / "DELIVERY_REPORT.md",
                    self._delivery_md(pid, fr, tr, artifacts, evidence_files))
        cm_path = ws / "CLIENT_MESSAGE.md"
        if cm_path.exists():
            client_message_source = "preserved"      # may be operator-edited; never overwritten here
        else:
            self._write(cm_path, self._client_message_md(pid, fr))
            client_message_source = "generated"
        delivery_docs = ["DELIVERY_REPORT.md", "CLIENT_MESSAGE.md"]
        # Secret-scan the delivery documents too, then hash the EXACT package (registered files +
        # the delivery documents) - not the whole workspace.
        scanned += self._scan_package(pid, delivery_docs)
        package_files = files + delivery_docs
        # The sealed hashes ARE the ones computed from the scanned byte stream. Hashing the files
        # again here would reopen the gap the single pass exists to close: a member could change
        # between being read and being hashed, and the manifest would then attest to bytes nobody
        # scanned.
        package_hashes = {entry["path"]: entry["sha256"] for entry in scanned}
        if sorted(package_hashes) != sorted(package_files):
            raise WorkExecutionError(
                "refusing to deliver: the scanned set does not match the set being sealed "
                f"({sorted(set(package_files) ^ set(package_hashes))})")
        digest = self._manifest_digest(package_hashes)
        manifest = {"project_id": pid, "generated_at": self._clock.now_iso(),
                    "deliverables": fr.get("expected_deliverables", []),
                    "produced_artifacts": produced, "evidence_count": ev.get("count", 0),
                    "validation_passed": bool(tr.get("passed")), "tests_run": tr.get("tests_run", 0),
                    "reviewed_by": review.get("reviewer", ""), "review_approved": bool(review.get("approved")),
                    "included": {"artifacts": artifacts, "evidence": evidence_files,
                                 "delivery_docs": delivery_docs},
                    "included_files": package_files, "artifact_hashes": package_hashes,
                    # Per-member content-scan disposition over exactly the sealed set. Only
                    # successful dispositions can appear here: anything unreadable, undecodable or
                    # unrecognised refuses the delivery outright, so this record never doubles as a
                    # place to log what was skipped.
                    "content_scan": {"scanner": "streaming-content-secret-scan/v1",
                                     "chunk_bytes": _SCAN_CHUNK_BYTES,
                                     "pending_max_chars": _SCAN_PENDING_MAX_CHARS,
                                     "files": sorted(scanned, key=lambda e: e["path"])},
                    "manifest_digest": digest, "client_message_source": client_message_source,
                    "approved_for_delivery": True,
                    "note": "validated + operator-reviewed; exact delivery package prepared (not sent)"}
        text = json.dumps(manifest, indent=2, sort_keys=True)
        self._write(ws / "WORK_DELIVERY_MANIFEST.json", text)
        # Record the exact manifest bytes AS WRITTEN, so a later manifest edit is detected.
        self._write(ws / "DELIVERY_PREPARED.json", json.dumps(
            {"prepared_at": self._clock.now_iso(), "manifest_digest": digest,
             "manifest_sha256": self._hash_file(ws / "WORK_DELIVERY_MANIFEST.json"),
             "included_file_count": len(package_files)}, indent=2, sort_keys=True))
        state = self._sm.transition(state, "DELIVERY_PREPARED",
                                    "delivery package prepared; all integrity checks passed", "cli")
        self._save_state(pid, state)
        return manifest

    def reopen_delivery(self, pid: str, reviewer: str, reason: str) -> Dict[str, Any]:
        """Recover a prepared delivery (M0.1). Only from DELIVERY_PREPARED. Archives the prepared
        manifest + seal as audit history, then either returns to READY_FOR_DELIVERY (only drafts /
        metadata changed) or, if the validated registered content changed, invalidates preparation
        AND review and drops to REPAIR_REQUIRED so the operator redoes execution/validation/review.
        Never silently accepts changed content."""
        if not reviewer.strip():
            raise WorkExecutionError("reviewer identity is required to reopen a delivery")
        state = self._load_state(pid)
        if state.status != "DELIVERY_PREPARED":
            raise WorkExecutionError(f"reopen-delivery needs state DELIVERY_PREPARED "
                                     f"(is {state.status})")
        ws = self._ws(pid)
        manifest = self._read_json(ws / "WORK_DELIVERY_MANIFEST.json")
        prev_digest = manifest.get("manifest_digest", "")
        self._archive_delivery(pid, prev_digest)          # preserve old manifest + seal as history
        validated = self._read_json(ws / "VALIDATED_ARTIFACTS.json").get("hashes", {})
        current = self._hash_map(pid, self._registered_files(pid))
        changed = sorted(k for k in set(validated) | set(current) if validated.get(k) != current.get(k))
        # Invalidate the prepared seal either way.
        try:
            (ws / "DELIVERY_PREPARED.json").unlink()
        except OSError:
            pass
        entry = {"at": self._clock.now_iso(), "reviewer": reviewer, "reason": reason[:500],
                 "previous_manifest_digest": prev_digest, "registered_changed": changed}
        if changed:
            # Validated content changed: invalidate the review and require the full loop again.
            self._write(ws / "REVIEW.json", json.dumps(
                {"reviewer": reviewer, "approved": False,
                 "note": f"invalidated by reopen-delivery: {reason}"[:200],
                 "at": self._clock.now_iso()}, indent=2, sort_keys=True))
            entry["outcome"] = "REPAIR_REQUIRED"
            state = self._sm.transition(
                state, "REPAIR_REQUIRED",
                f"delivery reopened; validated content changed ({len(changed)} file(s)): {reason}"[:200],
                reviewer)
        else:
            entry["outcome"] = "READY_FOR_DELIVERY"
            state = self._sm.transition(
                state, "READY_FOR_DELIVERY",
                f"delivery reopened (drafts/metadata only): {reason}"[:200], reviewer)
        self._append_delivery_history(pid, entry)
        self._save_state(pid, state)
        return entry

    def _archive_delivery(self, pid: str, digest: str) -> None:
        """Copy the current manifest + prepared seal into delivery_history/<n>/ so provenance is
        preserved rather than overwritten."""
        ws = self._ws(pid)
        base = ws / "delivery_history"
        n = 1
        while (base / f"{n:03d}").exists():
            n += 1
        dest = base / f"{n:03d}"
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("WORK_DELIVERY_MANIFEST.json", "DELIVERY_PREPARED.json", "REVIEW.json"):
            src = ws / name
            if src.is_file():
                (dest / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        (dest / "_archived.json").write_text(json.dumps(
            {"archived_at": self._clock.now_iso(), "manifest_digest": digest}, indent=2,
            sort_keys=True), encoding="utf-8")

    def _append_delivery_history(self, pid: str, entry: Dict[str, Any]) -> None:
        ws = self._ws(pid)
        hist = self._read_json(ws / "DELIVERY_HISTORY.json")
        events = hist.get("events", []) if isinstance(hist, dict) else []
        events.append(entry)
        self._write(ws / "DELIVERY_HISTORY.json",
                    json.dumps({"events": events}, indent=2, sort_keys=True))

    def _scan_member(self, rel: str, target: Path) -> Dict[str, Any]:
        """Stream one delivery member once: the same bytes feed the SHA-256 and the secret scan.

        Returns its content-scan disposition. Raises rather than returning a "could not read" value:
        every caller writes a success artifact, and a success artifact may only describe success.

        Why streaming rather than a size cap. The previous code skipped anything over 2 MB and
        anything that failed strict UTF-8, in both cases with a bare ``continue``. An empty result
        was then read as "clean", so an unread file shipped inside a manifest marked
        ``approved_for_delivery``.

        Why an incremental decoder. A multi-byte character split across two reads is valid text; a
        per-chunk ``bytes.decode`` would call it undecodable and refuse an ordinary non-English
        deliverable.

        Why the carry is candidate-driven rather than a fixed length. A first version of this kept
        the last N characters and argued that every pattern is either whitespace-free or
        keyword-plus-one-whitespace-run. That argument was wrong: ``password_assignment`` is
        ``\\bpass(?:word|wd)?\\s*[:=]\\s*['"]?[^\\s'"]{4,}`` — two independently unbounded whitespace
        runs before the four value characters — so ``password``, 40 KiB of spaces, ``=``, 40 KiB
        more and three value characters push the keyword out of any fixed carry while the match is
        still one character from completing. See ``_carry_start``: the carry now begins wherever a
        match could still be in progress, and refuses when that reaches further back than
        ``_SCAN_PENDING_MAX_CHARS`` rather than dropping the prefix.
        """
        try:
            size = target.stat().st_size
        except OSError as exc:
            raise WorkExecutionError(
                f"refusing to deliver: cannot read {rel} to scan it ({exc})") from exc
        if size > _SCAN_CEILING_BYTES:
            raise WorkExecutionError(
                f"refusing to deliver: {rel} is {size} bytes, above the scannable ceiling "
                f"({_SCAN_CEILING_BYTES}); it cannot be proven free of secrets")

        import codecs
        import hashlib
        streamed = 0
        digest = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        carry = ""
        head = b""
        binary_type = ""
        try:
            with open(target, "rb") as fh:
                while True:
                    chunk = fh.read(_SCAN_CHUNK_BYTES)
                    if not chunk:
                        break
                    streamed += len(chunk)
                    if streamed > _SCAN_CEILING_BYTES:
                        # Enforced on the bytes actually read, not on the earlier stat: a member can
                        # grow between the two, and the ceiling must bind what is really scanned.
                        raise WorkExecutionError(
                            f"refusing to deliver: {rel} exceeds the scannable ceiling "
                            f"({_SCAN_CEILING_BYTES} bytes) while streaming; it cannot be proven "
                            f"free of secrets")
                    digest.update(chunk)
                    if len(head) < 16:
                        head = (head + chunk)[:16]
                    if binary_type:
                        continue           # identified evidence: hashed, deliberately not text-scanned
                    try:
                        text = decoder.decode(chunk)
                    except UnicodeDecodeError:
                        binary_type = _verified_binary_type(rel, head)
                        if not binary_type:
                            # One bad byte must not promote an arbitrary artifact to "allowed binary".
                            raise WorkExecutionError(
                                f"refusing to deliver: {rel} is neither decodable text nor a "
                                f"recognised evidence format, so its content cannot be scanned")
                        continue
                    buf = carry + text
                    found = self._scanner.scan_text(rel, buf)
                    if found:
                        raise WorkExecutionError(
                            f"refusing to deliver: secret-like content in {rel} ({found[0]})")
                    start = _carry_start(buf)
                    if start < 0:
                        raise WorkExecutionError(
                            f"refusing to deliver: {rel} holds an undecided secret candidate "
                            f"reaching further back than {_SCAN_PENDING_MAX_CHARS} characters, so a "
                            f"match spanning a read boundary could not be ruled out")
                    carry = buf[start:]
        except OSError as exc:
            raise WorkExecutionError(
                f"refusing to deliver: cannot read {rel} to scan it ({exc})") from exc

        if not binary_type:
            try:
                tail = decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                raise WorkExecutionError(
                    f"refusing to deliver: {rel} ends mid-character and is not valid text, so its "
                    f"content cannot be scanned") from None
            found = self._scanner.scan_text(rel, carry + tail)
            if found:
                raise WorkExecutionError(
                    f"refusing to deliver: secret-like content in {rel} ({found[0]})")

        # `bytes` is the streamed count, not the earlier stat: what the manifest attests to must be
        # what was actually read and hashed.
        entry: Dict[str, Any] = {"path": rel, "bytes": streamed, "sha256": digest.hexdigest()}
        if binary_type:
            entry.update({"disposition": "verified_binary", "type": binary_type,
                          "reason": "recognised binary evidence format; content is not text-scanned"})
        else:
            entry["disposition"] = "scanned_text"
        return entry

    def _scan_package(self, pid: str, files: List[str]) -> List[Dict[str, Any]]:
        """Scan every member of the delivery set, or refuse. Never returns a partial verdict."""
        ws = self._ws(pid)
        out: List[Dict[str, Any]] = []
        for rel in files:
            target = self._confine(ws, rel)
            if not target.is_file():
                raise WorkExecutionError(
                    f"refusing to deliver: {rel} is registered in the package but is not a file")
            out.append(self._scan_member(rel, target))
        return out

    def mark_delivered(self, pid: str, note: str = "") -> WorkRunState:
        """Record the operator's assertion that the PREPARED package was delivered manually.

        Requires DELIVERY_PREPARED and re-verifies the prepared manifest + every included file
        before completing; it sends nothing itself. Any change after preparation (a file, the
        manifest, a missing file) refuses completion.
        """
        state = self._load_state(pid)
        if state.status != "DELIVERY_PREPARED":
            raise WorkExecutionError(f"mark-delivered needs state DELIVERY_PREPARED "
                                     f"(is {state.status}); run prepare-delivery first")
        ws = self._ws(pid)
        prepared = self._read_json(ws / "DELIVERY_PREPARED.json")
        mpath = ws / "WORK_DELIVERY_MANIFEST.json"
        manifest = self._read_json(mpath)
        if (not prepared.get("manifest_sha256") or not mpath.is_file()
                or not manifest.get("included_files") or not manifest.get("manifest_digest")):
            raise WorkExecutionError("prepared delivery manifest is missing or corrupt; "
                                     "re-run prepare-delivery")
        if self._hash_file(mpath) != prepared["manifest_sha256"]:
            raise WorkExecutionError("delivery manifest changed after preparation; "
                                     "re-run prepare-delivery")
        recorded = manifest.get("artifact_hashes", {})
        if self._manifest_digest(recorded) != manifest["manifest_digest"]:
            raise WorkExecutionError("delivery manifest digest mismatch (corrupt manifest); "
                                     "re-run prepare-delivery")
        current = self._hash_map(pid, [str(f) for f in manifest["included_files"]])
        bad = sorted(k for k in set(recorded) | set(current) if recorded.get(k) != current.get(k))
        if bad:
            raise WorkExecutionError(
                f"delivery contents changed after preparation ({', '.join(bad[:5])}"
                f"{'...' if len(bad) > 5 else ''}); re-run prepare-delivery")
        state = self._sm.transition(state, "COMPLETED",
                                    f"operator recorded manual delivery: {note}"[:200], "cli")
        self._write(ws / "DELIVERY_RECORD.json", json.dumps(
            {"at": self._clock.now_iso(), "note": note, "manifest_digest": manifest["manifest_digest"],
             "statement": "operator asserts the prepared package was delivered manually; "
                          "this command sent nothing itself"}, indent=2, sort_keys=True))
        self._save_state(pid, state)
        return state

    def status(self, pid: str) -> LifecycleView:
        state = self._load_state(pid)
        ev = self._read_json(self._ws(pid) / "EVIDENCE_INDEX.json")
        tr = self._read_json(self._ws(pid) / "TEST_RESULTS.json")
        prog = self._read_json(self._ws(pid) / "EXECUTION_PROGRESS.json")
        blockers = list(prog.get("outcome", {}).get("blockers", []))
        return LifecycleView(
            project_id=pid, status=state.status, progress=_PROGRESS.get(state.status, 40),
            evidence_count=ev.get("count", 0), tests_run=tr.get("tests_run", 0),
            tests_passed=tr.get("tests_passed", 0), blockers=blockers,
            next_action=self._next_action(state.status, blockers),
            delivery_ready=state.status in ("READY_FOR_DELIVERY", "DELIVERY_PREPARED", "COMPLETED"))

    def resume(self, pid: str) -> LifecycleView:
        """Reload the persisted state from disk (proves resume after restart / a new Claude session)."""
        return self.status(pid)

    @staticmethod
    def _next_action(status: str, blockers: List[str]) -> str:
        if blockers:
            return "resolve execution blockers, then re-run execution"
        return {"PLANNED": "review the feasibility summary, then approve",
                "WAITING_FOR_APPROVAL": "approve the plan to proceed",
                "READY_TO_EXECUTE": "start execution (Claude-Code-driven or a fixture executor)",
                "EXECUTING": "execution in progress",
                "VERIFYING": "run validation on the produced artifacts",
                "REPAIR_REQUIRED": "fix the failures and re-run execution",
                "READY_FOR_REVIEW": "review, then advance to delivery",
                "READY_FOR_DELIVERY": "prepare the delivery package (prepare-delivery)",
                "DELIVERY_PREPARED": "send the prepared package to the client yourself, then "
                                     "mark-delivered (records your assertion; sends nothing)",
                "COMPLETED": "delivered"}.get(status, "review the project state")

    @staticmethod
    def _delivery_md(pid: str, fr: Dict[str, Any], tr: Dict[str, Any], artifacts: List[str],
                     evidence_files: List[str]) -> str:
        lines = [f"# Delivery Report - {pid}", "",
                 f"**Scope.** {fr.get('client_intent', '')}", "",
                 "## Deliverables (exact package)", *[f"- {a}" for a in artifacts], "",
                 "## Evidence included", *[f"- {e}" for e in evidence_files], "",
                 f"## Validation\n- tests run: {tr.get('tests_run', 0)} · passed: "
                 f"{tr.get('tests_passed', 0)} · result: {'PASS' if tr.get('passed') else 'FAIL'}", "",
                 "## Known limitations", "- as noted during execution", "",
                 "_The exact delivery package is defined by WORK_DELIVERY_MANIFEST.json (this report + "
                 "the client message are part of it). Validation passed before preparation. Nothing "
                 "was sent to the client automatically._"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _client_message_md(pid: str, fr: Dict[str, Any]) -> str:
        return (f"# Client Message (draft) - {pid}\n\nHi,\n\nThe work is complete and validated. The "
                "delivery package includes the implementation, test results, evidence, and setup "
                "instructions. Please review; happy to walk through anything.\n\n"
                "_Draft for you to edit before sending._\n")
