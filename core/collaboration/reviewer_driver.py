"""Autonomous reviewer driver (Issue #14.B).

A trusted LOCAL service that closes the review loop without owner copy/paste: it watches the
collaboration store for an unanswered question/proposal/checkpoint, gathers bounded evidence for that
exact SHA, asks the independent reviewer (OpenAI in production, a fixture in CI), enforces a strict
output schema, and posts the reply immutably back to the store. It is fail-closed everywhere: a reached
budget cap, a stale head, a malformed model answer, or exhausted retries all escalate to a NEEDS_OWNER
envelope instead of guessing. The remote model is handed text only — it is never given a tool that can
merge, write source, run shell, or send externally.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from core.collaboration.budget import BudgetLedger
from core.collaboration.envelopes import make_envelope
from core.collaboration.evidence import gather_evidence
from core.collaboration.reviewer_client import (
    ReviewerClient,
    ReviewerSchemaError,
    validate_reviewer_output,
)
from core.collaboration.store import CollaborationStore, CollaborationStoreError

CANONICAL_REVIEWER_CONTRACT = (
    "You are an INDEPENDENT engineering reviewer for the AI QA Factory. You review exactly one commit "
    "identified by its full head SHA, using only the bounded evidence provided. You cannot merge, write "
    "source, run shell, or send anything externally; you only return a structured judgement. "
    "The decision_type is fixed by request_kind and you MUST use it: a QUESTION -> decision_type "
    "RESPONSE; a PROPOSAL -> decision_type CRITIQUE or RECOMMENDATION; a CHECKPOINT -> decision_type "
    "DECISION with verdict GO only if the evidence and tests genuinely support it, NO-GO with specific "
    "blockers otherwise, or COMMENT if you truly cannot decide, and echo reviewed_sha exactly. Judge "
    "against the project invariants and the stated scope. Distinguish observed, inferred and unverified "
    "claims; never assume capabilities that are not evidenced. Respond ONLY with the required JSON object."
)

_REPLY_KIND = {"RESPONSE": "RESPONSE", "CRITIQUE": "CRITIQUE",
               "RECOMMENDATION": "RECOMMENDATION", "DECISION": "DECISION"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cost_from_usage(usage: Optional[Dict[str, Any]]) -> float:
    """Truthful cost from REAL tokens and configured per-million-token pricing (0 when unpriced —
    never a fabricated flat charge). The hard budget bound is the call count; spend is only shown as
    actual once pricing is configured (AIQA_REVIEWER_PRICE_PER_MTOK_IN/OUT)."""
    if not usage:
        return 0.0
    p_in = float(os.environ.get("AIQA_REVIEWER_PRICE_PER_MTOK_IN", "0") or 0.0)
    p_out = float(os.environ.get("AIQA_REVIEWER_PRICE_PER_MTOK_OUT", "0") or 0.0)
    return round(usage.get("input_tokens", 0) / 1e6 * p_in
                 + usage.get("output_tokens", 0) / 1e6 * p_out, 6)


class ReviewerDriver:
    def __init__(
        self,
        store: CollaborationStore,
        budget: BudgetLedger,
        reviewer_client: ReviewerClient,
        *,
        repo_root: str = ".",
        head_resolver: Optional[Callable[[], str]] = None,
        git_runner: Optional[Callable[[list], str]] = None,
        reviewer_id: str = "gpt-reviewer",
        system_contract: str = CANONICAL_REVIEWER_CONTRACT,
        cost_estimator: Optional[Callable[[Optional[Dict[str, Any]]], float]] = None,
        manifest_provider: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        clock: Optional[Callable[[], str]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._store = store
        self._budget = budget
        self._client = reviewer_client
        self._repo_root = repo_root
        self._head_resolver = head_resolver or (lambda: "")
        self._git_runner = git_runner
        self._reviewer_id = reviewer_id
        self._contract = system_contract
        # Trusted CI/test manifest for the exact SHA — a CHECKPOINT GO requires it (P0). Default: none.
        self._manifest_provider = manifest_provider or (lambda _sha: None)
        self._cost = cost_estimator or _cost_from_usage
        self._clock = clock or _now
        # Real bounded backoff in production; tests inject a no-op sleep.
        self._sleep = sleep if sleep is not None else time.sleep
        self._state_path = Path(budget._events.parent) / "collab_driver" / "state.json"  # same base
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()

    # --- state / health -------------------------------------------------------------------------
    def _load_state(self) -> Dict[str, Any]:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError):
                pass
        return {"stage": "IDLE", "processed": 0, "last_success_at": "", "last_error": "",
                "updated_at": "", "current_thread": ""}

    def _save_state(self, **changes: Any) -> None:
        self._state.update(changes)
        self._state["updated_at"] = self._clock()          # heartbeat
        tmp = self._state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, sort_keys=True, indent=2),
                       encoding="utf-8")
        tmp.replace(self._state_path)

    def _resolve_head(self, branch: str) -> str:
        """Head of the request's branch (isolated worktrees share one .git). Accepts both a branch-aware
        resolver and a legacy zero-arg one (Issue #17)."""
        try:
            return str(self._head_resolver(branch) or "")
        except TypeError:
            return str(self._head_resolver() or "")

    def health(self) -> Dict[str, Any]:
        daily = self._budget.usage("")                     # thread "" -> daily totals only
        return {"reviewer_id": self._reviewer_id, "stage": self._state.get("stage", "IDLE"),
                "processed": self._state.get("processed", 0),
                "last_success_at": self._state.get("last_success_at", ""),
                "last_error": self._state.get("last_error", ""),
                "heartbeat": self._state.get("updated_at", ""),
                "current_thread": self._state.get("current_thread", ""),
                "model": self._state.get("model", getattr(self._client, "model", "")),
                "reasoning_effort": self._state.get("reasoning_effort",
                                                    getattr(self._client, "reasoning_effort", "")),
                "budget": {"daily_calls": daily["daily_calls"], "daily_usd": daily["daily_usd"],
                           "daily_tokens": daily["daily_tokens"],
                           "policy": {"daily_calls": self._budget.policy.daily_calls,
                                      "daily_usd": self._budget.policy.daily_usd}}}

    # --- the loop -------------------------------------------------------------------------------
    def process_once(self) -> Dict[str, Any]:
        pending = self._store.open_requests()
        if not pending:
            self._save_state(stage="IDLE", current_thread="")
            return {"status": "idle"}
        request = pending[0]
        thread = request["thread_id"]
        self._save_state(stage="REVIEWING", current_thread=thread, last_error="")

        # Stale head: never fabricate a fresh DECISION for a moved branch head. Only a CHECKPOINT is
        # code-exact (a GO binds to the reviewed SHA); a QUESTION/PROPOSAL is advisory and is reviewed at
        # its submitted head. Resolve the REQUEST'S branch head (isolated worktrees share one .git), not a
        # single global controller HEAD — otherwise a writer on another branch is always "stale" (#17).
        if request["kind"] == "CHECKPOINT":
            current_head = str(self._resolve_head(request.get("branch", "")) or "").lower()
            if current_head and str(request.get("head_sha", "")).lower() != current_head:
                self._escalate(request, f"checkpoint head {request['head_sha'][:12]} is stale; branch is "
                                        f"now at {current_head[:12]} — resubmit for the current head")
                return {"status": "stale"}

        # Budget: fail closed BEFORE any spend.
        verdict = self._budget.check(thread)
        if not verdict.allowed:
            self._escalate(request, f"budget cap reached ({verdict.cap}): {verdict.reason}")
            return {"status": "blocked", "cap": verdict.cap}

        manifest = self._manifest_provider(request["head_sha"])
        manifests = {"trusted_gate": json.dumps(manifest)} if manifest else None
        evidence = gather_evidence(self._repo_root, request["head_sha"],
                                   base_sha=str(request.get("base_sha", "")),
                                   request=request, manifests=manifests, git_runner=self._git_runner)
        key = request["idempotency_key"]
        cached = self._budget.cache_get(key)   # only schema-validated replies are ever cached
        if cached is not None:
            raw = cached
        else:
            raw, failure = self._review_with_accounting(thread, request, evidence)
            if failure is not None:
                return failure                 # already escalated (blocked / retries exhausted)

        try:
            result = validate_reviewer_output(raw, request_kind=request["kind"],
                                              expected_sha=request["head_sha"])
        except ReviewerSchemaError as exc:
            self._escalate(request, f"reviewer output rejected by schema: {exc}")
            return {"status": "schema_error"}

        # P0: a CHECKPOINT can NEVER produce GO unless the SHA is verified, the diff is whole, the
        # canonical criteria loaded, AND a trusted CI/test manifest for this exact SHA is present and
        # explicitly successful. The worker's body/refs may supplement but cannot satisfy this gate.
        if (request["kind"] == "CHECKPOINT" and result.decision_type == "DECISION"
                and result.verdict == "GO"):
            reasons = list(evidence.get("incompleteness", []))
            if not evidence.get("criteria_loaded", False):
                reasons.append("canonical criteria did not load")
            if not (manifest and manifest.get("present")):
                reasons.append("no trusted CI/test manifest for this exact SHA")
            elif not manifest.get("success"):
                reasons.append("trusted CI/test manifest is not successful")
            if reasons:
                self._escalate(request, "cannot authorize GO without trusted evidence: "
                               + "; ".join(reasons))
                return {"status": "needs_owner", "reason": "untrusted_or_incomplete_evidence"}

        self._budget.cache_put(key, raw)       # cache ONLY the schema-validated response
        reply = self._append_reply(request, result)
        self._save_state(stage="IDLE", processed=self._state.get("processed", 0) + 1,
                         last_success_at=self._clock(), current_thread="",
                         model=getattr(self._client, "model", ""),
                         reasoning_effort=getattr(self._client, "reasoning_effort", ""))
        return {"status": "reviewed", "decision_type": result.decision_type,
                "verdict": result.verdict, "message_id": reply["message_id"]}

    def _review_with_accounting(self, thread: str, request: Dict[str, Any],
                                evidence: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]],
                                                                   Optional[Dict[str, Any]]]:
        """Call the reviewer with bounded retries, counting EVERY attempt as a call and re-checking
        the budget cap before each attempt (real backoff between them). Returns (raw, None) on success
        or (None, escalation-result) when the cap is hit or retries are exhausted (fail closed)."""
        attempts = max(1, int(self._budget.policy.max_retries))
        last_exc: Optional[BaseException] = None
        for i in range(attempts):
            verdict = self._budget.check(thread)
            if not verdict.allowed:
                self._escalate(request, f"budget cap reached ({verdict.cap}): {verdict.reason}")
                return None, {"status": "blocked", "cap": verdict.cap}
            try:
                raw = self._client.review(system_contract=self._contract, evidence=evidence,
                                          message=request)
            except Exception as exc:  # noqa: BLE001 - a failed attempt still consumed an API call
                last_exc = exc
                self._budget.record(thread, calls=1, usd=0.0)
                if i < attempts - 1:
                    self._sleep(self._budget.policy.backoff_base_seconds * (2 ** i))
                continue
            usage = getattr(self._client, "last_usage", None) or {}
            self._budget.record(thread, calls=1, usd=self._cost(usage),
                                input_tokens=usage.get("input_tokens", 0),
                                output_tokens=usage.get("output_tokens", 0),
                                total_tokens=usage.get("total_tokens", 0))
            return raw, None
        self._escalate(request, f"reviewer call failed after {attempts} attempts: {last_exc}")
        return None, {"status": "needs_owner", "reason": "retries_exhausted"}

    def _append_reply(self, request: Dict[str, Any], result) -> Dict[str, Any]:
        kind = _REPLY_KIND[result.decision_type]
        envelope = make_envelope(
            kind=kind, thread_id=request["thread_id"], actor=self._reviewer_id, body=result.message,
            head_sha=request["head_sha"], branch=str(request.get("branch", "")),
            pr_number=request.get("pr_number"), evidence_refs=result.evidence_used,
            verdict=result.verdict, reviewed_sha=result.reviewed_sha or request["head_sha"],
            in_reply_to=request["idempotency_key"], requested_next_action="ACKNOWLEDGEMENT")
        return self._store.append(envelope)

    def _escalate(self, request: Dict[str, Any], reason: str) -> None:
        try:
            self._store.append(make_envelope(
                kind="NEEDS_OWNER", thread_id=request["thread_id"], actor="collab-driver",
                body=reason, in_reply_to=request["idempotency_key"],
                requested_next_action="owner decision required"))
        except CollaborationStoreError:
            pass
        self._save_state(stage="NEEDS_OWNER", last_error=reason)

    def run_forever(self, *, max_iterations: int = 1000) -> int:
        """Bounded processing loop (never a hidden unlimited loop): stops when idle or capped."""
        processed = 0
        for _ in range(max(1, max_iterations)):
            outcome = self.process_once()
            if outcome["status"] in ("idle", "blocked", "needs_owner", "stale"):
                break
            processed += 1
        return processed
