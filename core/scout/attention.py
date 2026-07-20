"""Operator attention + notification policy (v3.3) — notify only when genuinely needed.

Unattended runs must not spam the operator. Every persisted event is classified into an attention
LEVEL; only Level ≥ the configured minimum, when notifications are explicitly enabled, produces a
(deduplicated, cooldown-gated) operator notification. Operator notifications are SEPARATE from
prospect outreach and go only to the configured operator-owned address; they carry no secrets.

- Level 0 — no notification (weak target skipped, duplicate, page unavailable, ordinary public
  CAPTCHA, retry succeeded, low-value issue, budget reallocation) — persisted, never interrupts.
- Level 1 — digest/informational (campaign completed, A-priority found, several blocked, elevated
  challenge rate, scheduled run with no findings).
- Level 2 — actionable non-urgent (stopped with checkpoint, recoverable interruption, credentials
  need renewal, storage near limit, client info required).
- Level 3 — immediate (authorized Human Checkpoint, global safety blocker, corrupted state,
  irreversible ambiguity, all providers unavailable, cannot continue safely).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

LEVEL_NONE = 0
LEVEL_DIGEST = 1
LEVEL_ACTIONABLE = 2
LEVEL_IMMEDIATE = 3

_EVENT_LEVEL = {
    # Level 0
    "weak_target_skipped": LEVEL_NONE, "duplicate_target": LEVEL_NONE,
    "page_unavailable": LEVEL_NONE, "public_captcha": LEVEL_NONE, "retry_succeeded": LEVEL_NONE,
    "low_value_issue": LEVEL_NONE, "budget_reallocation": LEVEL_NONE, "target_rejected": LEVEL_NONE,
    # Level 1
    "campaign_completed": LEVEL_DIGEST, "a_priority_found": LEVEL_DIGEST,
    "several_targets_blocked": LEVEL_DIGEST, "challenge_rate_elevated": LEVEL_DIGEST,
    "scheduled_run_no_findings": LEVEL_DIGEST,
    # Level 2
    "campaign_stopped_checkpoint": LEVEL_ACTIONABLE, "recoverable_interruption": LEVEL_ACTIONABLE,
    "credentials_need_renewal": LEVEL_ACTIONABLE, "storage_near_limit": LEVEL_ACTIONABLE,
    "client_info_required": LEVEL_ACTIONABLE,
    # Level 3
    "human_checkpoint": LEVEL_IMMEDIATE, "global_safety_blocker": LEVEL_IMMEDIATE,
    "corrupted_state": LEVEL_IMMEDIATE, "irreversible_action_ambiguity": LEVEL_IMMEDIATE,
    "all_providers_unavailable": LEVEL_IMMEDIATE, "cannot_continue_safely": LEVEL_IMMEDIATE,
}


def classify_event(event_type: str) -> int:
    """Map an event type to an attention level (unknown => Level 0, never interrupts)."""
    return _EVENT_LEVEL.get((event_type or "").strip().lower(), LEVEL_NONE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AttentionItem:
    dedup_key: str
    campaign_id: str = ""
    target: str = ""
    level: int = LEVEL_NONE
    event_type: str = ""
    reason: str = ""
    next_action: str = ""
    status: str = "open"                 # open | resolved
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    expires_at: str = ""
    notified_at: str = ""

    @property
    def id(self) -> str:
        return hashlib.sha256(self.dedup_key.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["id"] = self.id
        return d


@dataclass
class NotificationSettings:
    enabled: bool = False                # OFF by default (unattended-only, explicit opt-in)
    operator_email: str = ""             # operator-owned address ONLY (never a prospect)
    min_level: int = LEVEL_ACTIONABLE    # only Level >= 2 notifies when enabled
    cooldown_s: float = 900.0            # per dedup_key cooldown to avoid spam


class AttentionCenter:
    """In-memory attention items with dedup + cooldown. The caller persists via to_dict()."""

    def __init__(self) -> None:
        self._items: Dict[str, AttentionItem] = {}

    def record(self, *, event_type: str, campaign_id: str = "", target: str = "", reason: str = "",
               next_action: str = "", expires_at: str = "") -> AttentionItem:
        level = classify_event(event_type)
        dedup_key = f"{campaign_id}|{target}|{event_type}"
        existing = self._items.get(dedup_key)
        if existing:
            existing.updated_at = _now()      # same key updates in place (no duplicate spam)
            existing.reason = reason or existing.reason
            return existing
        item = AttentionItem(dedup_key=dedup_key, campaign_id=campaign_id, target=target,
                             level=level, event_type=event_type, reason=reason,
                             next_action=next_action, expires_at=expires_at)
        self._items[dedup_key] = item
        return item

    def open_items(self, *, min_level: int = LEVEL_DIGEST) -> list:
        return sorted((i for i in self._items.values()
                       if i.status == "open" and i.level >= min_level),
                      key=lambda i: (-i.level, i.created_at))

    def resolve(self, dedup_key: str) -> bool:
        it = self._items.get(dedup_key)
        if not it:
            return False
        it.status = "resolved"
        it.updated_at = _now()
        return True


def should_notify(item: AttentionItem, settings: NotificationSettings, *,
                  now_epoch: float, last_notified_epoch: Optional[float] = None) -> bool:
    """Decide whether to emit an operator notification for an item. Level 0 never notifies;
    notifications must be enabled, meet the minimum level, and respect the per-key cooldown."""
    if not settings.enabled or item.level == LEVEL_NONE:
        return False
    if item.level < settings.min_level:
        return False
    if last_notified_epoch is not None and (now_epoch - last_notified_epoch) < settings.cooldown_s:
        return False
    return True
