"""What "Needs attention" is actually about: sites, not attempts.

The screen answers one question — which companies still need a human before Scout can finish them.
Everything here exists to keep that answer honest in three ways the old inventory got wrong.

**A domain is one row however often it was tried.** Each campaign that hits the same blocked site
wrote another row, so one company retried four times read as four companies. The retries are real and
are kept, but as that site's history, not as separate work.

**A value that is not a website is not listed as one.** ``canonical_domain`` is a normaliser, not a
validator: it answers ``0.1`` for ``0.1`` and — worse — ``1.5`` for ``192.168.1.5``, inventing a
domain that looks plausible and never existed. Such values are reported as what they are, beside the
real sites but never among them.

**Sites and attempts are counted separately.** "13 targets were blocked" was really 13 attempts at
some smaller number of sites, which made the queue look far worse than it was.

Classification is delegated to :mod:`core.scout.intake` on purpose: the rule for "is this a public
website" must be the same one that guards the queue, or a value could be refused at intake and still
appear here as a company.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from core.scout.intake import parse_targets
from core.scout.url_safety import UrlPolicy

# The one prospect status that means "a human is needed before this target can be finished".
BLOCKED_STATUS = "MANUAL_ACTION_REQUIRED"


@dataclass
class AttentionSite:
    """One company waiting for a human, with every blocked attempt at it."""
    domain: str
    run_id: str                 # the most recent attempt — what Open should take you to
    prospect_id: str
    reason: str
    updated_at: str
    attempts: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def to_dict(self) -> Dict[str, Any]:
        return {"domain": self.domain, "run_id": self.run_id, "prospect_id": self.prospect_id,
                "reason": self.reason, "updated_at": self.updated_at,
                "attempts": list(self.attempts), "attempt_count": self.attempt_count}


@dataclass
class AttentionInvalid:
    """A recorded target that is not a public website, named as what it is."""
    value: str
    kind: str                   # malformed | non_public | unsupported | unreachable
    reason: str                 # operator-facing wording
    run_id: str
    prospect_id: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class AttentionInventory:
    sites: List[AttentionSite] = field(default_factory=list)
    invalid: List[AttentionInvalid] = field(default_factory=list)

    @property
    def unique_sites(self) -> int:
        return len(self.sites)

    @property
    def attempt_events(self) -> int:
        return sum(s.attempt_count for s in self.sites)

    def headline(self) -> str:
        """The sentence at the top of the screen, with both numbers named for what they are."""
        if not self.sites:
            return "No sites need review."
        sites = (f"{self.unique_sites} site needs review." if self.unique_sites == 1
                 else f"{self.unique_sites} sites need review.")
        events = self.attempt_events
        attempts = (f"{events} blocked attempt was recorded." if events == 1
                    else f"{events} blocked attempts were recorded.")
        return f"{sites} {attempts}"

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": "scout-needs-attention/v1",
                "unique_sites": self.unique_sites, "attempt_events": self.attempt_events,
                "headline": self.headline(),
                "sites": [s.to_dict() for s in self.sites],
                "invalid": [i.to_dict() for i in self.invalid]}


def scan_blocked_attempts(output_dir: str) -> List[Dict[str, Any]]:
    """Every persisted blocked prospect, raw — one entry per attempt, URL preserved.

    The raw URL is kept rather than a canonical domain because deciding whether the value IS a site
    is the caller's job here; normalising first is exactly how ``0.1`` became a domain.
    """
    base = Path(output_dir) / "scout"
    rows: List[Dict[str, Any]] = []
    if not base.is_dir():
        return rows
    for state_path in base.glob("*/state.json"):
        run_id = state_path.parent.name
        if run_id.startswith("_"):
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # A manual attempt at a target that already has a row elsewhere is that row's history, not
        # an independent event. Counting it would inflate the attempt total the headline reports.
        if str(state.get("manual_attempt_for") or "").strip():
            continue
        when = str(state.get("finished_at") or state.get("updated_at") or "")
        for pid, prospect in (state.get("prospects", {}) or {}).items():
            if not isinstance(prospect, dict) or prospect.get("status") != BLOCKED_STATUS:
                continue
            url = str(prospect.get("url") or prospect.get("final_url") or "")
            reason = str(prospect.get("reason") or "")
            try:
                manual = json.loads(
                    (state_path.parent / "prospects" / pid / "manual_action.json").read_text(
                        encoding="utf-8"))
                reason = str(manual.get("reason") or reason)
            except (OSError, ValueError):
                pass
            rows.append({"url": url, "run_id": run_id, "prospect_id": pid, "reason": reason,
                         "updated_at": when})
    rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return rows


def attention_inventory(output_dir: str) -> AttentionInventory:
    """Group every blocked attempt into one current row per real site.

    DNS is not consulted: this reads what already happened on disk, and a site that has since gone
    offline still needs the operator to see why it was blocked.
    """
    rows = scan_blocked_attempts(output_dir)
    policy = UrlPolicy(resolve_dns=False)
    by_domain: Dict[str, AttentionSite] = {}
    invalid: Dict[str, AttentionInvalid] = {}
    for row in rows:                                    # already newest-first
        parsed = parse_targets([row["url"]], policy=policy)
        if not parsed.targets:
            value = row["url"]
            if value in invalid:
                continue                                # one entry per bad value, newest kept
            rejection = parsed.rejected[0] if parsed.rejected else None
            invalid[value] = AttentionInvalid(
                value=value,
                kind=rejection.kind if rejection else "malformed",
                reason=rejection.reason if rejection else "not a website address",
                run_id=row["run_id"], prospect_id=row["prospect_id"],
                updated_at=row["updated_at"])
            continue
        domain = parsed.targets[0].domain
        attempt = {"run_id": row["run_id"], "prospect_id": row["prospect_id"],
                   "reason": row["reason"], "updated_at": row["updated_at"]}
        site = by_domain.get(domain)
        if site is None:
            by_domain[domain] = AttentionSite(
                domain=domain, run_id=row["run_id"], prospect_id=row["prospect_id"],
                reason=row["reason"], updated_at=row["updated_at"], attempts=[attempt])
        else:
            site.attempts.append(attempt)               # an earlier try at a site already listed
    return AttentionInventory(sites=list(by_domain.values()), invalid=list(invalid.values()))
