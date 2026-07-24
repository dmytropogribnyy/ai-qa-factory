"""Evidence sanitization for the Scout (Phase 8.3).

Reuses the Phase 8.1 content-safety layer (`ContentSecretScanner`, `redact_intake_text`) so
no secret / token / credential can enter a finding or its evidence. Evidence is a small
sanitized *fact sheet* about a public page — never a raw HTML dump, response body, cookie, or
header set. A finding is marked `sanitized=True` only when it and its evidence scan clean.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

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

    def safe_url(self, value: str) -> str:
        """Keep public routing identity while dropping credentials, query data, and fragments."""
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            parts = urlsplit(text)
            if parts.scheme.lower() in ("http", "https"):
                host = parts.hostname or ""
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"
                netloc = host
                try:
                    port = parts.port
                except ValueError:
                    port = None
                if port:
                    netloc = f"{host}:{port}"
                path = self.redact(parts.path)
                return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))
            if parts.scheme.lower() == "mailto":
                # Preserve only the contact intent. The address itself is PII in persisted evidence.
                return f"mailto:{self.redact(parts.path)}"
        except (TypeError, ValueError):
            pass
        if text.lower().startswith(("http://", "https://", "mailto:")):
            return "[REDACTED_URL]"
        return self.redact(text)

    def _sanitize_value(self, value: Any, *, depth: int = 0) -> Any:
        """Bounded recursive redaction for structured browser/axe/form metadata."""
        if depth > 5:
            return "[TRUNCATED]"
        if isinstance(value, str):
            if value.strip().lower().startswith(("http://", "https://", "mailto:")):
                return self.safe_url(value)
            return self.redact(value)
        if isinstance(value, dict):
            return {
                self.redact(str(k))[:80]: self._sanitize_value(v, depth=depth + 1)
                for k, v in list(value.items())[:100]
            }
        if isinstance(value, list):
            return [self._sanitize_value(v, depth=depth + 1) for v in value[:200]]
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return self.redact(str(value))

    def sanitize_observation(self, obs: PageObservation) -> Dict[str, Any]:
        """Persist the useful observation shape without credential-bearing URLs or raw free text."""
        data = obs.to_dict()
        for key in ("url", "final_url", "canonical"):
            data[key] = self.safe_url(data.get(key, ""))
        data["redirect_chain"] = [self.safe_url(v) for v in data.get("redirect_chain", [])[:10]]
        data["links"] = [self.safe_url(v) for v in data.get("links", [])[:200]]
        data["failed_resources"] = [
            self.safe_url(v) for v in data.get("failed_resources", [])[:200]
        ]
        data["blocked_requests"] = [
            self.safe_url(v) for v in data.get("blocked_requests", [])[:200]
        ]
        data["images"] = [
            {"src": self.safe_url(v.get("src", "")), "alt": self.redact(v.get("alt", ""))}
            for v in data.get("images", [])[:200] if isinstance(v, dict)
        ]
        forms = []
        for form in data.get("forms", [])[:50]:
            if not isinstance(form, dict):
                continue
            safe_form = self._sanitize_value(form)
            safe_form["action"] = self.safe_url(form.get("action", ""))
            forms.append(safe_form)
        data["forms"] = forms
        for key in (
            "fetch_error", "content_type", "title", "meta_description", "robots_meta",
            "x_robots_tag", "lang",
        ):
            data[key] = self.redact(str(data.get(key, "")))
        data["headings"] = [
            {"level": h.get("level"), "text": self.redact(str(h.get("text", "")))}
            for h in data.get("headings", [])[:100] if isinstance(h, dict)
        ]
        # Checks consume response headers in memory before this persistence boundary. Do not keep
        # arbitrary header names/values (cookies, auth, vendor metadata) in operator evidence.
        data["headers"] = {}
        data["raw_headers_stored"] = False
        data["structured_data"] = self._sanitize_value(data.get("structured_data", []))
        data["console_errors"] = [
            self.redact(str(v)) for v in data.get("console_errors", [])[:200]
        ]
        data["axe_violations"] = self._sanitize_value(data.get("axe_violations", []))
        data["screenshot_ref"] = PurePath(
            str(data.get("screenshot_ref", "")).replace("\\", "/")).name
        data["video_ref"] = PurePath(str(data.get("video_ref", "")).replace("\\", "/")).name
        data["redaction_applied"] = True
        return data

    def build_evidence(self, obs: PageObservation) -> Dict[str, Any]:
        """A sanitized public-fact sheet (no raw body, cookies, or unsafe headers)."""
        return {
            "url": self.safe_url(obs.url),
            "final_url": self.safe_url(obs.final_url),
            "status": obs.status,
            "backend": obs.backend,
            "title": self.redact(obs.title),
            "meta_description": self.redact(obs.meta_description),
            "canonical": self.safe_url(obs.canonical),
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
