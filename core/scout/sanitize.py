"""Evidence sanitization for the Scout (Phase 8.3).

Reuses the Phase 8.1 content-safety layer (`ContentSecretScanner`, `redact_intake_text`) so
no secret / token / credential can enter a finding or its evidence. Evidence is a small
sanitized *fact sheet* about a public page — never a raw HTML dump, response body, cookie, or
header set. A finding is marked `sanitized=True` only when it and its evidence scan clean.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from core.orchestration.content_safety import ContentSecretScanner, redact_intake_text
from core.scout.backends import PageObservation
from core.scout.findings import ScoutFinding

# Obvious PII patterns to drop from evidence text (emails / long digit runs).
import re

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{7,}\b")
_MAX_TEXT = 400


@dataclass
class Sanitizer:
    def __post_init__(self) -> None:
        self._scanner = ContentSecretScanner()

    def redact(self, text: str) -> str:
        if not text:
            return ""
        redacted = redact_intake_text(text).text
        redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
        redacted = _LONG_DIGITS_RE.sub("[REDACTED_NUMBER]", redacted)
        return redacted[:_MAX_TEXT]

    def is_clean(self, text: str) -> bool:
        return not self._scanner.scan_text("x", text or "")

    def build_evidence(self, obs: PageObservation) -> Dict[str, Any]:
        """A sanitized public-fact sheet (no raw body, cookies, or unsafe headers)."""
        return {
            "url": obs.url,
            "final_url": obs.final_url,
            "status": obs.status,
            "backend": obs.backend,
            "title": self.redact(obs.title),
            "meta_description": self.redact(obs.meta_description),
            "canonical": obs.canonical,
            "robots": self.redact((obs.robots_meta + " " + obs.x_robots_tag).strip()),
            "has_viewport_meta": obs.has_viewport_meta,
            "headings": [self.redact(h["text"]) for h in obs.headings[:8]],
            "safe_headers": dict(obs.headers),   # already reduced to a safe allowlist
            "screenshot_ref": obs.screenshot_ref,
            "note": "Sanitized public fact sheet; no response body, cookies, or credentials stored.",
        }

    def sanitize_finding(self, finding: ScoutFinding) -> ScoutFinding:
        """Redact every free-text field; mark sanitized only if it scans clean."""
        finding.title = self.redact(finding.title)
        finding.expected = self.redact(finding.expected)
        finding.actual = self.redact(finding.actual)
        finding.business_impact = self.redact(finding.business_impact)
        finding.coverage_limitation = self.redact(finding.coverage_limitation)
        finding.reproduction_steps = [self.redact(s) for s in finding.reproduction_steps]
        finding.notes = [self.redact(n) for n in finding.notes]
        blob = " ".join([
            finding.title, finding.expected, finding.actual, finding.business_impact,
            finding.coverage_limitation, *finding.reproduction_steps, *finding.notes,
        ])
        finding.sanitized = self.is_clean(blob)
        return finding

    def scan_artifacts(self, artifacts: Dict[str, str]) -> List[str]:
        """Return content-secret findings across serialized artifacts (empty = clean)."""
        return self._scanner.scan_all(artifacts).findings
