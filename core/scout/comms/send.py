"""Transactional send reservation, idempotency, and crash handling (Final Phase II).

Sending is disabled by default and dry-run by default. A live send: revalidates from authoritative
truth, atomically consumes the single-use approval AND reserves the message (one idempotency key
per provider+revision+recipient+channel), then calls the provider EXACTLY ONCE. An ambiguous
provider outcome becomes OUTCOME_UNKNOWN and is NEVER auto-retried. A crash leaves a reconcilable
state. Exactly-once external delivery is not claimed — at most once automatic provider invocation
per approval, with manual reconciliation for ambiguous outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from core.scout.comms.controls import precall_blockers
from core.scout.comms.providers import (
    ACCEPTED,
    FAILED_DEFINITE,
    ProviderError,
    ProviderRegistry,
    ProviderTimeout,
)
from core.scout.comms.repository import (
    ATT_ACCEPTED,
    ATT_CANCELLED,
    ATT_FAILED,
    ATT_UNKNOWN,
    CommsError,
    CommsRepository,
    M_ACCEPTED,
    M_CANCELLED,
    M_FAILED,
    M_IN_PROGRESS,
    M_RESERVED,
    M_UNKNOWN,
    R_CONSUMED,
)
from core.scout.comms.revalidation import RevalidationResult, revalidate
from core.scout.comms.snapshots import canonical_hash
from core.scout.memory.repository import MemoryRepository

# Send outcomes (CLI exit-status classes).
S_BLOCKED, S_DRY_RUN, S_ACCEPTED, S_FAILED, S_UNKNOWN, S_IDEMPOTENT = (
    "blocked", "dry_run", "accepted", "definite_failure", "outcome_unknown", "idempotent_noop")

# Blockers that reflect a MATERIAL change and invalidate the approval (vs transient control blocks).
_MATERIAL = ("changed_", "finding_not_sendable", "finding_missing", "contact_missing",
             "contact_not_verified", "contact_blocked_by_event", "evidence_expired",
             "evidence_not_client_safe", "no_outreach_suppression", "company_suppressed",
             "revision_superseded", "revision_expired", "approval_expired", "placeholder_reference",
             "provenance_", "contact_not_publicly_published", "named_person_review_incomplete")


@dataclass
class SendOutcome:
    status: str = S_BLOCKED
    message_id: str = ""
    provider_message_id: str = ""
    blockers: List[str] = field(default_factory=list)
    recipient: str = ""
    revalidation: Dict[str, Any] = field(default_factory=dict)
    provider_result: Dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class SendService:
    def __init__(self, mem: MemoryRepository, comms: CommsRepository, providers: ProviderRegistry,
                 clock: Callable[[], str]) -> None:
        self.mem = mem
        self.comms = comms
        self.providers = providers
        self.clock = clock
        # Test-only hook fired AFTER reservation and BEFORE the final pre-provider control re-check,
        # so a race (kill/disable/opt-out/bounce inserted at the last moment) can be exercised.
        self.before_invoke: Callable[[], None] = None

    def _idempotency_key(self, provider_id: str, rev: Dict[str, Any], channel: str) -> str:
        return canonical_hash({"provider": provider_id, "revision_id": rev["revision_id"],
                               "recipient_hash": rev["recipient_hash"], "channel": channel})

    def send(self, revision_id: str, approval_id: str, provider_id: str, *, campaign_id: str,
             channel: str = "email", live: bool = False, reviewer: str = "",
             confirm_recipient: str = "") -> SendOutcome:
        now = self.clock()
        reval = revalidate(self.mem, self.comms, revision_id, approval_id, campaign_id=campaign_id,
                           provider_id=provider_id, channel=channel, live=live, now=now)

        if not live:
            # Dry-run: report gates + preview; never reserve or call a provider.
            return SendOutcome(status=S_DRY_RUN, blockers=reval.blockers,
                               recipient=reval.recipient_value, revalidation=reval.artifact,
                               note="dry-run: no reservation, no provider call")

        if reval.blockers:
            self._maybe_invalidate(approval_id, reval, now)
            return SendOutcome(status=S_BLOCKED, blockers=reval.blockers,
                               recipient=reval.recipient_value, revalidation=reval.artifact)

        if not reviewer.strip():
            return SendOutcome(status=S_BLOCKED, blockers=["missing_reviewer"],
                               revalidation=reval.artifact)
        if confirm_recipient.strip() != reval.recipient_value:
            return SendOutcome(status=S_BLOCKED, blockers=["recipient_confirmation_mismatch"],
                               recipient=reval.recipient_value, revalidation=reval.artifact)

        rev = self.comms.get_revision(revision_id)
        key = self._idempotency_key(provider_id, rev, channel)
        msg = {"message_id": f"msg-{key[7:23]}", "revision_id": revision_id,
               "approval_id": approval_id, "company_id": rev["company_id"],
               "contact_id": rev["contact_id"], "channel": channel, "provider_id": provider_id,
               "idempotency_key": key, "now": now}
        try:
            message_id, status = self.comms.reserve_and_authorize(msg, approval_id)
        except CommsError:
            return SendOutcome(status=S_BLOCKED, blockers=["approval_not_consumable"],
                               recipient=reval.recipient_value, revalidation=reval.artifact)
        if status == "idempotent_existing":
            existing = self.comms.get_message(message_id)
            return SendOutcome(status=S_IDEMPOTENT, message_id=message_id,
                               provider_message_id=existing.get("provider_message_id", ""),
                               recipient=reval.recipient_value, revalidation=reval.artifact,
                               note=f"already reserved (state={existing.get('state')}); not re-sent")

        return self._invoke_provider(message_id, provider_id, campaign_id, rev, reval, now)

    def _precall_cancel(self, message_id: str, provider_id: str, blockers: List[str],
                        idempotency_key: str, started_at: str, reval: RevalidationResult
                        ) -> SendOutcome:
        """A blocker appeared after reservation: cancel the reserved message with ZERO provider
        calls and finalize a CANCELLED_BEFORE_PROVIDER attempt."""
        att_id = f"att-{message_id}-c"
        self.comms.add_attempt({"attempt_id": att_id, "message_id": message_id,
                                "provider": provider_id, "idempotency_key": idempotency_key,
                                "started_at": started_at, "finished_at": self.clock(),
                                "outcome": ATT_CANCELLED, "ambiguity_state": "provider_call_count=0",
                                "error": ";".join(blockers)[:200]})
        self.comms.transition_message(message_id, M_CANCELLED, self.clock(),
                                      error="cancelled before provider")
        return SendOutcome(status=S_BLOCKED, message_id=message_id, blockers=blockers,
                           recipient=reval.recipient_value, revalidation=reval.artifact,
                           note="cancelled before provider call (control race); 0 provider calls")

    def _invoke_provider(self, message_id: str, provider_id: str, campaign_id: str,
                         rev: Dict[str, Any], reval: RevalidationResult, now: str) -> SendOutcome:
        provider = self.providers.get(provider_id)
        msg = self.comms.get_message(message_id)
        key = (msg or {}).get("idempotency_key", "")

        # --- Pre-provider control race: re-read ALL authoritative gates after reservation ---------
        if self.before_invoke is not None:
            self.before_invoke()
        blockers = precall_blockers(self.mem, self.comms, campaign_id=campaign_id,
                                    provider_id=provider_id, channel=rev["channel"],
                                    recipient=reval.recipient_value, contact_id=rev["contact_id"],
                                    company_id=rev["company_id"], live=True)
        if msg is None or msg["state"] != M_RESERVED:
            blockers.append("reservation_lost")
        if blockers:
            return self._precall_cancel(message_id, provider_id, sorted(set(blockers)), key, now, reval)

        # --- Atomically move RESERVED -> PROVIDER_CALL_IN_PROGRESS, then invoke EXACTLY once -------
        self.comms.transition_message(message_id, M_IN_PROGRESS, now)
        attempt_id = f"att-{message_id}"
        request_hash = canonical_hash({"provider": provider_id, "idempotency_key": key,
                                       "channel": rev["channel"], "body_hash": rev["body_hash"],
                                       "recipient_hash": rev["recipient_hash"]})
        self.comms.add_attempt({"attempt_id": attempt_id, "message_id": message_id,
                                "provider": provider_id, "request_hash": request_hash,
                                "idempotency_key": key, "attempt_number": 1, "started_at": now})
        envelope = {"channel": rev["channel"], "recipient_ref": rev["contact_id"],
                    "subject": rev["subject"], "body_hash": rev["body_hash"], "idempotency_key": key}
        try:
            result = provider.send(envelope)          # exactly one provider call
        except ProviderTimeout as exc:
            # Ambiguous outcome: never auto-retry; requires human/idempotency reconciliation.
            self.comms.finalize_attempt(attempt_id, outcome=ATT_UNKNOWN, finished_at=self.clock(),
                                        ambiguity_state="ambiguous_after_transmission",
                                        error=str(exc)[:200])
            self.comms.transition_message(message_id, M_UNKNOWN, self.clock(), error=str(exc)[:200])
            return SendOutcome(status=S_UNKNOWN, message_id=message_id,
                               recipient=reval.recipient_value, revalidation=reval.artifact,
                               note="ambiguous provider outcome; not retried automatically")
        except ProviderError as exc:
            self.comms.finalize_attempt(attempt_id, outcome=ATT_FAILED, finished_at=self.clock(),
                                        error=str(exc)[:200])
            self.comms.transition_message(message_id, M_FAILED, self.clock(), error=str(exc)[:200])
            return SendOutcome(status=S_FAILED, message_id=message_id,
                               recipient=reval.recipient_value, revalidation=reval.artifact,
                               provider_result={"error": str(exc)[:200]})

        if result.outcome == ACCEPTED:
            self.comms.finalize_attempt(attempt_id, outcome=ATT_ACCEPTED, finished_at=self.clock(),
                                        provider_response_ref=result.provider_message_id)
            self.comms.transition_message(message_id, M_ACCEPTED, self.clock(),
                                          provider_message_id=result.provider_message_id, sent=True)
            self.comms.transition_revision(rev["revision_id"], R_CONSUMED, self.clock())
            self.mem.add_event("outbound", message_id, "ACCEPTED", provider_id, self.clock())
            return SendOutcome(status=S_ACCEPTED, message_id=message_id,
                               provider_message_id=result.provider_message_id,
                               recipient=reval.recipient_value, revalidation=reval.artifact,
                               provider_result=result.to_dict())
        if result.outcome == FAILED_DEFINITE:
            self.comms.finalize_attempt(attempt_id, outcome=ATT_FAILED, finished_at=self.clock())
            self.comms.transition_message(message_id, M_FAILED, self.clock())
            return SendOutcome(status=S_FAILED, message_id=message_id,
                               recipient=reval.recipient_value, revalidation=reval.artifact,
                               provider_result=result.to_dict())
        self.comms.finalize_attempt(attempt_id, outcome=ATT_UNKNOWN, finished_at=self.clock(),
                                    ambiguity_state="unknown_provider_result")
        self.comms.transition_message(message_id, M_UNKNOWN, self.clock())
        return SendOutcome(status=S_UNKNOWN, message_id=message_id,
                           recipient=reval.recipient_value, revalidation=reval.artifact,
                           provider_result=result.to_dict())

    def _maybe_invalidate(self, approval_id: str, reval: RevalidationResult, now: str) -> None:
        if any(b.startswith(_MATERIAL) for b in reval.blockers):
            self.comms.invalidate_approval(approval_id, ";".join(reval.blockers)[:200], now)

    def reconcile(self) -> Dict[str, int]:
        """Crash recovery: a message stuck IN_PROGRESS with no accepted result becomes
        OUTCOME_UNKNOWN (never auto-retried; its open attempt is finalized); a bare RESERVED message
        (never invoked, zero provider calls) is safely cancelled."""
        now = self.clock()
        unknown = cancelled = 0
        for m in self.comms.messages_in_state(M_IN_PROGRESS):
            for att in self.comms.attempts_for(m["message_id"]):
                if not att["finished_at"]:
                    self.comms.finalize_attempt(att["attempt_id"], outcome=ATT_UNKNOWN,
                                                finished_at=now,
                                                ambiguity_state="reconciled_after_interruption")
            self.comms.transition_message(m["message_id"], M_UNKNOWN, now,
                                          error="reconciled after interruption")
            unknown += 1
        for m in self.comms.messages_in_state(M_RESERVED):
            self.comms.transition_message(m["message_id"], M_CANCELLED, now,
                                          error="reserved but never invoked; cancelled")
            cancelled += 1
        return {"outcome_unknown": unknown, "cancelled": cancelled}
