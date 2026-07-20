"""Global analyzed-site history + cross-campaign deduplication (v3.3).

ONE persistent canonical registry of every discovered/analyzed company target, keyed by the canonical
domain (public-suffix + shared-hosting aware, so US/DE queries, keywords, campaigns, and restarts
dedup to one company and unrelated shared-hosting tenants are never merged). Stored as JSON under the
(git-ignored) output dir; writes are atomic; a fresh process reloads it. Safe metadata only — no
secrets, no full page bodies.

Behaviour:
- completed targets are skipped by default ("Already analyzed"); the existing result is shown;
- failed/interrupted targets may resume/retry;
- concurrent campaigns cannot analyze the same target at once (an atomic O_EXCL lease lock);
- rescan is explicit: manual only / after an interval / on a meaningful fingerprint change — never
  merely because the same URL reappeared in another query.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.scout.discovery.domain_intel import canonical_domain

# analysis_status values
DISCOVERED, ANALYZING, ANALYZED, FAILED, SKIPPED, REJECTED = (
    "discovered", "analyzing", "analyzed", "failed", "skipped", "rejected")
# rescan modes
RESCAN_MANUAL, RESCAN_INTERVAL, RESCAN_FINGERPRINT = "manual", "interval", "fingerprint"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SiteEntry:
    domain: str = ""                          # canonical identity (dedup key)
    original_url: str = ""
    normalized_url: str = ""
    discovery_provider: str = ""
    campaign_ids: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    analysis_status: str = DISCOVERED
    first_analysis_at: str = ""
    last_analysis_at: str = ""
    evidence_ref: str = ""
    fingerprint: str = ""
    reason: str = ""                          # rejection/skip reason
    rescan_mode: str = RESCAN_MANUAL
    rescan_interval_s: float = 0.0
    next_rescan_at: str = ""
    lock_owner: str = ""
    lock_until: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SiteEntry":
        known = set(cls().__dict__)
        return cls(**{k: v for k, v in d.items() if k in known})


class AnalyzedSiteRegistry:
    def __init__(self, output_dir: str = "outputs", *, clock=time.time) -> None:
        self._dir = Path(output_dir) / "scout" / "_registry"
        self._path = self._dir / "analyzed_sites.json"
        self._locks = self._dir / "locks"
        self._clock = clock
        self._entries: Dict[str, SiteEntry] = {}
        self._load()

    # -- persistence (atomic; fresh-process resume) ------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for d in data.get("sites", []):
                e = SiteEntry.from_dict(d)
                if e.domain:
                    self._entries[e.domain] = e
        except (OSError, ValueError):
            self._entries = {}

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "analyzed-sites/v1", "count": len(self._entries),
                   "sites": [e.to_dict() for e in self._entries.values()]}
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)

    # -- observation / dedup -----------------------------------------------------------------------
    def observe(self, url: str, *, campaign_id: str, provider: str) -> Tuple[SiteEntry, bool]:
        """Record a discovery. Returns (entry, is_new). Same company across campaigns/queries/restarts
        collapses to ONE entry; the same URL reappearing never triggers re-analysis by itself."""
        domain = canonical_domain(url)
        if not domain:
            raise ValueError("cannot observe a URL with no canonical domain")
        now = _now_iso()
        e = self._entries.get(domain)
        is_new = e is None
        if is_new:
            e = SiteEntry(domain=domain, original_url=url, normalized_url=f"https://{domain}",
                          discovery_provider=provider, first_seen=now)
            self._entries[domain] = e
        e.last_seen = now
        if campaign_id and campaign_id not in e.campaign_ids:
            e.campaign_ids.append(campaign_id)
        self._save()
        return e, is_new

    def get(self, url_or_domain: str) -> Optional[SiteEntry]:
        return self._entries.get(canonical_domain(url_or_domain))

    def should_analyze(self, url_or_domain: str, *, new_fingerprint: str = "") -> Tuple[bool, str]:
        """Decide whether a target should be analyzed now. Completed targets are skipped by default;
        rescan only per the entry's explicit rescan policy."""
        e = self.get(url_or_domain)
        if e is None or e.analysis_status in (DISCOVERED, FAILED):
            return True, "not yet analyzed" if e is None else f"prior status {e.analysis_status}, retry"
        if e.analysis_status == REJECTED:
            return False, f"Already rejected: {e.reason or 'not a company target'}"
        if e.analysis_status == ANALYZING:
            return False, "Analysis in progress in another run"
        # ANALYZED -> skip unless a rescan condition is met.
        if e.rescan_mode == RESCAN_INTERVAL and e.next_rescan_at and _now_iso() >= e.next_rescan_at:
            return True, "rescan interval elapsed"
        if e.rescan_mode == RESCAN_FINGERPRINT and new_fingerprint and new_fingerprint != e.fingerprint:
            return True, "content fingerprint changed"
        return False, "Already analyzed"

    # -- concurrency-safe claim (atomic O_EXCL lease lock) -----------------------------------------
    def claim(self, url_or_domain: str, *, owner: str, lease_s: float = 900.0) -> bool:
        """Atomically claim a target for analysis so concurrent campaigns never analyze it at once.
        Uses an O_EXCL lock file; a stale lease (crashed owner) can be reclaimed."""
        domain = canonical_domain(url_or_domain)
        if not domain:
            return False
        self._locks.mkdir(parents=True, exist_ok=True)
        lock = self._locks / f"{domain}.lock"
        now = self._clock()
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"owner": owner, "until": now + lease_s}).encode())
            os.close(fd)
        except FileExistsError:
            try:
                info = json.loads(lock.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            if float(info.get("until", 0)) > now:                # a live lease held by someone else
                return False
            lock.write_text(json.dumps({"owner": owner, "until": now + lease_s}), encoding="utf-8")
        e = self._entries.get(domain) or SiteEntry(domain=domain, first_seen=_now_iso())
        e.analysis_status = ANALYZING
        e.lock_owner, e.lock_until = owner, now + lease_s
        self._entries[domain] = e
        self._save()
        return True

    def release(self, url_or_domain: str) -> None:
        domain = canonical_domain(url_or_domain)
        lock = self._locks / f"{domain}.lock"
        try:
            lock.unlink()
        except OSError:
            pass
        e = self._entries.get(domain)
        if e:
            e.lock_owner, e.lock_until = "", 0.0
            self._save()

    # -- record outcomes ---------------------------------------------------------------------------
    def record_analysis(self, url_or_domain: str, *, status: str = ANALYZED, evidence_ref: str = "",
                        fingerprint: str = "", rescan_mode: str = RESCAN_MANUAL,
                        rescan_interval_s: float = 0.0) -> SiteEntry:
        domain = canonical_domain(url_or_domain)
        e = self._entries.get(domain) or SiteEntry(domain=domain, first_seen=_now_iso())
        now = _now_iso()
        e.analysis_status = status
        e.first_analysis_at = e.first_analysis_at or now
        e.last_analysis_at = now
        e.evidence_ref = evidence_ref or e.evidence_ref
        if fingerprint:
            e.fingerprint = fingerprint
        e.rescan_mode, e.rescan_interval_s = rescan_mode, rescan_interval_s
        if rescan_mode == RESCAN_INTERVAL and rescan_interval_s > 0:
            e.next_rescan_at = datetime.fromtimestamp(
                time.time() + rescan_interval_s, tz=timezone.utc).isoformat()
        e.lock_owner, e.lock_until = "", 0.0
        self._entries[domain] = e
        self.release(domain)
        self._save()
        return e

    def record_rejection(self, url_or_domain: str, reason: str) -> None:
        domain = canonical_domain(url_or_domain)
        e = self._entries.get(domain) or SiteEntry(domain=domain, first_seen=_now_iso())
        e.analysis_status, e.reason, e.last_seen = REJECTED, reason, _now_iso()
        self._entries[domain] = e
        self._save()

    def request_rescan(self, url_or_domain: str) -> bool:
        """Operator 'Rescan' action: mark an analyzed target eligible for one manual re-analysis."""
        e = self.get(url_or_domain)
        if e is None:
            return False
        e.analysis_status = DISCOVERED           # eligible again; the run will re-claim + analyze
        e.reason = ""
        self._save()
        return True

    # -- views / counts ----------------------------------------------------------------------------
    def all(self) -> List[SiteEntry]:
        return sorted(self._entries.values(), key=lambda e: e.last_seen, reverse=True)

    def counts(self) -> Dict[str, int]:
        c = {"total": len(self._entries), DISCOVERED: 0, ANALYZING: 0, ANALYZED: 0,
             FAILED: 0, SKIPPED: 0, REJECTED: 0}
        for e in self._entries.values():
            c[e.analysis_status] = c.get(e.analysis_status, 0) + 1
        return c

    def snapshot(self) -> Dict[str, Any]:
        return {"schema": "analyzed-sites/v1", "counts": self.counts(),
                "sites": [e.to_dict() for e in self.all()]}
