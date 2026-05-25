"""InputContextResolver — classifies raw inputs into typed InputSource objects.

Classify-only: no URL fetching, no browser execution, no credential use,
no external calls. Secret values are redacted before storage.
"""
from __future__ import annotations

import re
from typing import List
from urllib.parse import urlparse

from core.schemas.input_map import InputMap, InputSource

# --- Secret detection patterns -----------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, str]] = [
    # password=..., pass=..., pwd=...
    (r"(?i)(password|passwd|pass|pwd)\s*[=:]\s*\S+", "[REDACTED_PASSWORD]"),
    # token=..., api_token=..., access_token=...
    (r"(?i)(api_token|access_token|auth_token|token)\s*[=:]\s*\S+", "[REDACTED_TOKEN]"),
    # api_key=..., apikey=...
    (r"(?i)(api_key|apikey|x-api-key)\s*[=:]\s*\S+", "[REDACTED_TOKEN]"),
    # Authorization: Bearer ...
    (r"(?i)bearer\s+[A-Za-z0-9\-_\.]+", "[REDACTED_TOKEN]"),
    # cookie=...
    (r"(?i)(cookie|session_cookie|sessionid)\s*[=:]\s*\S+", "[REDACTED_COOKIE]"),
    # secret=..., client_secret=...
    (r"(?i)(client_secret|secret)\s*[=:]\s*\S+", "[REDACTED_SECRET]"),
    # sk-... (OpenAI keys), sk-ant-... (Anthropic keys)
    (r"sk-[A-Za-z0-9\-_]{20,}", "[REDACTED_TOKEN]"),
    # JWT: three base64url segments separated by dots
    (r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", "[REDACTED_TOKEN]"),
    # Basic auth in URL: https://user:pass@host
    (r"https?://[^@\s]+:[^@\s]+@[^\s]+", "[REDACTED_URL_WITH_CREDENTIALS]"),
    # webhook URLs with tokens (e.g. hooks.slack.com/services/T.../B.../...)
    (r"https?://[^\s]*hooks\.[^\s]*/[A-Za-z0-9]{8,}/[A-Za-z0-9\-_]+/[A-Za-z0-9\-_]+",
     "[REDACTED_WEBHOOK_URL]"),
]

_SECRET_DETECTED_NOTE = (
    "Credentials or secrets were detected and redacted. "
    "No credential use was performed. "
    "Credential use requires explicit approval in a later phase."
)


def _redact_secrets(text: str) -> tuple[str, bool]:
    """Return (redacted_text, secrets_were_found)."""
    redacted = text
    found = False
    for pattern, placeholder in _SECRET_PATTERNS:
        new, count = re.subn(pattern, placeholder, redacted)
        if count:
            found = True
            redacted = new
    return redacted, found


# --- URL classification helpers ----------------------------------------------------------

_TASK_URL_HOSTS = frozenset({
    "jira", "atlassian", "linear.app", "notion.so", "notion.site",
    "trello", "asana", "github.com", "gitlab.com", "basecamp",
    "clickup", "monday.com", "shortcut.com", "app.shortcut.com",
})

_REPO_URL_PATTERNS = [
    r"github\.com/[^/]+/[^/]+",
    r"gitlab\.com/[^/]+/[^/]+",
    r"bitbucket\.org/[^/]+/[^/]+",
    r"dev\.azure\.com",
]

_API_DOCS_PATTERNS = [
    r"swagger", r"openapi", r"apidoc", r"api-docs", r"postman",
    r"stoplight", r"readme\.io", r"apiary",
]

_DESIGN_URL_PATTERNS = [
    r"figma\.com", r"zeplin\.io", r"invisionapp\.com", r"canva\.com",
    r"miro\.com", r"lucidchart\.com",
]

_FILE_EXTENSION_MAP = {
    # Archives
    "zip": "uploaded_archive", "tar": "uploaded_archive", "gz": "uploaded_archive",
    "rar": "uploaded_archive", "7z": "uploaded_archive",
    # Screenshots / images
    "png": "screenshot", "jpg": "screenshot", "jpeg": "screenshot",
    "gif": "screenshot", "webp": "screenshot", "bmp": "screenshot",
    "tiff": "screenshot",
    # API specs
    "yaml": "api_docs_file", "yml": "api_docs_file", "json": "api_docs_file",
    # Test files
    "spec.ts": "test_file", "test.ts": "test_file", "spec.js": "test_file",
    "test.js": "test_file", "spec.py": "test_file", "test_": "test_file",
    # Config
    "env": "config_file", "toml": "config_file", "ini": "config_file",
    "cfg": "config_file",
}


def _classify_url(url: str) -> str:
    """Classify a URL into an input_type. Order matters (most-specific first)."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    full = url.lower()

    # Task / issue URLs (Jira, Linear, GitHub issues, etc.)
    for h in _TASK_URL_HOSTS:
        if h in host:
            # Distinguish repo vs issue by path depth and segments
            if "github.com" in host or "gitlab.com" in host:
                # github.com/org/repo = repo; /issues/, /pull/ = task
                if any(seg in path for seg in ["/issues/", "/pull/", "/merge_requests/"]):
                    return "task_url"
                if len([p for p in path.split("/") if p]) >= 2:
                    return "repo_url"
            return "task_url"

    # Repo URLs without issue paths
    for pattern in _REPO_URL_PATTERNS:
        if re.search(pattern, full):
            return "repo_url"

    # API docs
    for pattern in _API_DOCS_PATTERNS:
        if re.search(pattern, full):
            return "api_docs_url"

    # Design tools
    for pattern in _DESIGN_URL_PATTERNS:
        if re.search(pattern, full):
            return "design_url"

    # Everything else is a target URL (the app under test)
    return "target_url"


def _classify_file(path: str) -> str:
    """Classify a file by extension."""
    lower = path.lower()
    # Multi-part extensions first
    for ext in ["spec.ts", "test.ts", "spec.js", "test.js", "spec.py"]:
        if lower.endswith(ext):
            return "test_file"
    suffix = lower.rsplit(".", 1)[-1] if "." in lower else ""
    return _FILE_EXTENSION_MAP.get(suffix, "unknown_file")


def _looks_like_url(text: str) -> bool:
    return bool(re.match(r"https?://\S+", text.strip()))


def _looks_like_file_path(text: str) -> bool:
    t = text.strip()
    # Multi-line text is always a brief, never a file path
    if "\n" in t:
        return False
    return bool(
        re.match(r"[A-Za-z]:\\", t)        # Windows absolute
        or t.startswith("/")                # POSIX absolute
        or re.match(r"\./|\.\.\/", t)       # relative ./
        or re.search(r"\.\w{1,5}$", t)     # has an extension
    )


# --- Resolver ---------------------------------------------------------------------------

class InputContextResolver:
    """Classifies raw inputs into typed InputSource objects.

    Rules:
    - classify-only: no URL fetching, no browser execution, no external calls
    - secrets in raw_value are redacted before storage
    - approved=False on all sources (approval is a later gate)
    """

    def resolve(self, raw_inputs: List[str], project_id: str) -> InputMap:
        """Classify each raw input string and return an InputMap."""
        sources: List[InputSource] = []
        for raw in raw_inputs:
            source = self._classify_one(raw.strip())
            sources.append(source)
        return InputMap(project_id=project_id, sources=sources)

    def _classify_one(self, raw: str) -> InputSource:
        redacted, had_secrets = _redact_secrets(raw)

        notes_parts: list[str] = []
        if had_secrets:
            notes_parts.append(_SECRET_DETECTED_NOTE)

        if _looks_like_url(raw):
            input_type = _classify_url(raw.split()[0])
            # Any input containing secrets is treated as a credential reference
            if had_secrets:
                input_type = "credentials_reference"
            raw_to_store = redacted
        elif _looks_like_file_path(raw):
            input_type = _classify_file(raw)
            raw_to_store = redacted  # path itself unlikely to hold secrets, but redact anyway
        else:
            # Text / brief — largest category
            if had_secrets:
                input_type = "credentials_reference"
            else:
                input_type = "pasted_brief"
            raw_to_store = redacted

        # Execution-blocked types get an extra note
        blocked_types = {
            "target_url", "unknown_url", "credentials_reference",
            "api_docs_url", "repo_url", "design_url",
        }
        if input_type in blocked_types and input_type != "credentials_reference":
            notes_parts.append(
                f"Input classified as '{input_type}'. "
                "No automatic fetch or execution. Requires approval in a later phase."
            )
        if input_type == "credentials_reference":
            notes_parts.append(
                "Credential reference detected. "
                "No credential use performed. "
                "Use requires explicit approval (Phase 2+)."
            )

        return InputSource(
            input_type=input_type,
            label=self._make_label(raw_to_store, input_type),
            raw_value=raw_to_store,
            classification_notes=" | ".join(notes_parts) if notes_parts else "",
            approved=False,
        )

    @staticmethod
    def _make_label(value: str, input_type: str) -> str:
        truncated = value[:60].replace("\n", " ").strip()
        if len(value) > 60:
            truncated += "..."
        return f"[{input_type}] {truncated}"
