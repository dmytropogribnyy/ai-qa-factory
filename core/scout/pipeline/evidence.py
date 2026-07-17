"""Evidence center (Final Phase I).

One integrated evidence model with full metadata. Text evidence (axe/perf summaries, SEO
excerpts, sanitized console/network excerpts, reproduction steps) is sanitized (secrets/PII
redacted, bounded, no full DOM dump) and content-secret-scanned; binary evidence (screenshots)
is stored path-confined. Every item is hashed and carries a retention deadline. An item is
client-safe only when sanitized AND its finding is independently verified.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List

from core.orchestration.content_safety import ContentSecretScanner
from core.scout.sanitize import Sanitizer
from core.scout.store import RunStore

EVIDENCE_TYPES = frozenset({
    "screenshot_original", "screenshot_annotated", "axe_summary", "performance_summary",
    "seo_excerpt", "console_sanitized", "network_sanitized", "trace", "video",
    "reproduction_steps", "environment", "cleanup_verification",
})

_MAX_TEXT_CHARS = 20_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class EvidenceItem:
    evidence_id: str = ""
    finding_id: str = ""
    company_id: str = ""
    campaign_id: str = ""
    session_id: str = ""
    page_url: str = ""
    evidence_type: str = "reproduction_steps"
    captured_at: str = ""
    tool: str = ""
    tool_version: str = ""
    viewport: str = ""
    locale: str = ""
    browser: str = ""
    sanitization_status: str = "unsanitized"     # unsanitized | sanitized | rejected
    verification_status: str = "UNVERIFIED"
    client_safe: bool = False
    content_hash: str = ""
    storage_ref: str = ""
    retention_deadline: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceItem":
        known = set(cls().__dict__.keys())
        return cls(**{k: v for k, v in data.items() if k in known})


class EvidenceCenter:
    """Captures, sanitizes, hashes, and stores evidence under one run/session store."""

    def __init__(self, store: RunStore, campaign_id: str, company_id: str, session_id: str,
                 clock: Callable[[], datetime] = _now) -> None:
        self.store = store
        self.campaign_id = campaign_id
        self.company_id = company_id
        self.session_id = session_id
        self.clock = clock
        self._sanitizer = Sanitizer()
        self._scanner = ContentSecretScanner()
        self._seq = 0

    def _evidence_id(self, evidence_type: str) -> str:
        self._seq += 1
        return f"ev-{self.session_id}-{self._seq:03d}-{evidence_type}"

    def add_text(self, evidence_type: str, payload: Dict[str, Any], *, finding_id: str = "",
                 page_url: str = "", tool: str = "", tool_version: str = "",
                 retention_days: int = 90, viewport: str = "", locale: str = "en",
                 browser: str = "") -> EvidenceItem:
        """Sanitize a bounded JSON payload, hash it, store it, and return the evidence item."""
        if evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f"unknown evidence_type: {evidence_type!r}")
        clean = self._sanitize_payload(payload)
        text = json.dumps(clean, indent=2, ensure_ascii=False, sort_keys=True)
        eid = self._evidence_id(evidence_type)
        # A secret-bearing payload is rejected outright (never stored as evidence).
        rejected = bool(self._scanner.scan_text(eid, text))
        item = EvidenceItem(
            evidence_id=eid, finding_id=finding_id, company_id=self.company_id,
            campaign_id=self.campaign_id, session_id=self.session_id, page_url=page_url,
            evidence_type=evidence_type, captured_at=self.clock().isoformat(),
            tool=tool, tool_version=tool_version, viewport=viewport, locale=locale,
            browser=browser, content_hash=_sha256(text.encode("utf-8")),
            sanitization_status="rejected" if rejected else "sanitized",
            retention_deadline=(self.clock() + timedelta(days=retention_days)).isoformat())
        if not rejected:
            item.storage_ref = self.store.save_bytes(
                ["prospects", self.session_id, "evidence", f"{eid}.json"], text.encode("utf-8"))
        return item

    def add_screenshot(self, png_bytes: bytes, *, evidence_type: str = "screenshot_original",
                       finding_id: str = "", page_url: str = "", tool: str = "playwright",
                       tool_version: str = "", retention_days: int = 90, viewport: str = "",
                       ) -> EvidenceItem:
        eid = self._evidence_id(evidence_type)
        ref = self.store.save_bytes(["prospects", self.session_id, "evidence", f"{eid}.png"],
                                    png_bytes)
        return EvidenceItem(
            evidence_id=eid, finding_id=finding_id, company_id=self.company_id,
            campaign_id=self.campaign_id, session_id=self.session_id, page_url=page_url,
            evidence_type=evidence_type, captured_at=self.clock().isoformat(), tool=tool,
            tool_version=tool_version, viewport=viewport,
            sanitization_status="sanitized",  # a rendered screenshot carries no stored text
            content_hash=_sha256(png_bytes), storage_ref=ref,
            retention_deadline=(self.clock() + timedelta(days=retention_days)).isoformat())

    def _sanitize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact + bound a payload (no full DOM dump; no private field values)."""
        return _walk(payload, self._sanitizer, depth=0)


def _walk(value: Any, sanitizer: Sanitizer, depth: int) -> Any:
    if depth > 6:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, str):
        return sanitizer.redact(value[:_MAX_TEXT_CHARS])
    if isinstance(value, dict):
        return {str(k)[:120]: _walk(v, sanitizer, depth + 1) for k, v in list(value.items())[:200]}
    if isinstance(value, list):
        return [_walk(v, sanitizer, depth + 1) for v in value[:200]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitizer.redact(str(value)[:_MAX_TEXT_CHARS])


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_evidence_index(items: List[EvidenceItem]) -> Dict[str, Any]:
    return {it.evidence_id: {"finding_id": it.finding_id, "type": it.evidence_type,
                             "storage_ref": it.storage_ref, "hash": it.content_hash,
                             "sanitization_status": it.sanitization_status,
                             "client_safe": it.client_safe,
                             "retention_deadline": it.retention_deadline}
            for it in items}
