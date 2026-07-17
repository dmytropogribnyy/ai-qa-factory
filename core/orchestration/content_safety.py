"""Content secret scanning + safe atomic artifact publication — Phase 8.1.

The existing `core.client_delivery_pack.SecretScanner` only inspects FILE NAMES, not
file contents. Phase 8.1 needs real content scanning before any artifact is written,
so this module provides:

- ContentSecretScanner: regex scan of JSON/Markdown *content* for secret patterns.
- ArtifactSafeWriter: render in memory → scan content → write to a temp dir inside the
  project output root → validate the full set → atomically publish → roll back on failure.

No network, no external calls.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# Secret patterns scanned in artifact CONTENT (not filenames).
_SECRET_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("stripe_secret_key", re.compile(r"\b(sk|rk)_(live|test)_[0-9A-Za-z]{16,}")),
    ("stripe_publishable_key", re.compile(r"\bpk_(live|test)_[0-9A-Za-z]{16,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}")),
    ("basic_auth_url", re.compile(r"https?://[^\s/@]+:[^\s/@]+@")),
    ("password_assignment", re.compile(r"(?i)\bpass(?:word|wd)?\s*[:=]\s*['\"]?[^\s'\"]{4,}")),
    ("cookie_header", re.compile(r"(?i)\b(?:set-)?cookie\s*[:=]\s*\S+=\S+")),
]

# Redaction placeholders that are allowed (already-safe) and must not trigger a block.
_ALLOWED_PLACEHOLDERS = ("[REDACTED", "ref:", "${", "<pin", "env-var", "<redacted")


# Credential-bearing URL: strip only the userinfo, keep scheme + host + path so
# classification and fingerprint identity are preserved (distinct hosts stay distinct).
_CRED_URL = re.compile(r"(https?://)[^\s/@:]+:[^\s/@]+@")


@dataclass
class RedactionResult:
    text: str
    secrets_found: bool = False


def redact_intake_text(text: str) -> RedactionResult:
    """Single public intake-boundary redactor.

    Removes secrets while preserving non-secret structure:
    - credential URLs -> `scheme://[REDACTED_CREDENTIALS]@host/path` (host/path kept);
    - bearer/api-key/JWT/cookie/password/etc. -> `[REDACTED_<label>]`.

    Used for the generated project-id seed, intake, the input fingerprint, and all
    persisted content, so no raw secret can reach a path, log, stdout, or artifact.
    Output passes the ContentSecretScanner (placeholders are allowed).
    """
    found = False
    redacted, n = _CRED_URL.subn(lambda m: f"{m.group(1)}[REDACTED_CREDENTIALS]@", text or "")
    if n:
        found = True
    for label, pat in _SECRET_PATTERNS:
        if label == "basic_auth_url":
            continue  # handled above, preserving host/path
        def _sub(m: "re.Match[str]", _label: str = label) -> str:
            snippet = m.group(0)
            if any(ph in snippet for ph in _ALLOWED_PLACEHOLDERS):
                return snippet
            return f"[REDACTED_{_label}]"
        redacted, k = pat.subn(_sub, redacted)
        if k:
            found = True
    return RedactionResult(text=redacted, secrets_found=found)


@dataclass
class ContentScanResult:
    clean: bool = True
    findings: List[str] = field(default_factory=list)   # "artifact:pattern" entries


class ContentSecretScanner:
    """Scans artifact content strings for secret patterns."""

    def scan_text(self, name: str, text: str) -> List[str]:
        findings: List[str] = []
        for label, pat in _SECRET_PATTERNS:
            for m in pat.finditer(text):
                snippet = m.group(0)
                # Skip matches that are actually redaction placeholders.
                if any(ph in snippet for ph in _ALLOWED_PLACEHOLDERS):
                    continue
                findings.append(f"{name}:{label}")
        return findings

    def scan_all(self, artifacts: Dict[str, str]) -> ContentScanResult:
        all_findings: List[str] = []
        for name, text in artifacts.items():
            all_findings.extend(self.scan_text(name, text))
        return ContentScanResult(clean=not all_findings, findings=sorted(set(all_findings)))


class ArtifactPublishError(Exception):
    """Raised when artifacts cannot be safely published (e.g. content secret found)."""


class ArtifactSafeWriter:
    """Renders, scans, and atomically publishes a set of artifacts to a target dir."""

    def __init__(self, target_dir: Path, scanner: ContentSecretScanner | None = None) -> None:
        self.target_dir = Path(target_dir)
        self.scanner = scanner or ContentSecretScanner()

    @staticmethod
    def _validate_names(artifacts: Dict[str, str]) -> None:
        """Permit flat filenames only — reject separators, traversal, absolute paths."""
        for name in artifacts:
            if (
                not name
                or "/" in name or "\\" in name
                or ".." in name
                or os.path.isabs(name)
                or Path(name).name != name
            ):
                raise ArtifactPublishError(f"unsafe artifact name: {name!r}")

    def _recover_crash_state(self, tmp_dir: Path, bak_dir: Path) -> None:
        """Resolve leftover state from a previous crash BEFORE touching anything.

        A `.bak_publish` is the last known-good output, never disposable temp:
        - backup present + target missing  -> restore backup to target (recover);
        - backup present + target present  -> fail closed (manual review required);
        - stale temp (no ambiguous backup)  -> safe to remove.
        """
        if bak_dir.exists():
            if not self.target_dir.exists():
                os.replace(bak_dir, self.target_dir)  # restore last good output
            else:
                raise ArtifactPublishError(
                    f"both {self.target_dir.name} and its backup exist "
                    f"({bak_dir.name}); manual recovery required, refusing to proceed"
                )
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)

    def publish(self, artifacts: Dict[str, str]) -> ContentScanResult:
        """Scan content, then publish safely. Raise ArtifactPublishError on secrets.

        `artifacts` maps filename -> already-serialized content (JSON/Markdown strings).

        Windows-safe strategy (no reliance on overwriting a non-empty directory):
        1. Validate artifact names (flat only); scan all content IN MEMORY — a secret
           is never written to disk; recover any prior crash state (backup is sacred).
        2. Write the full set into a sibling temp dir; validate completeness.
        3. Move any existing valid output aside to a backup name (os.replace to a
           non-existing path — atomic rename on the same filesystem).
        4. Move the temp dir into the target name.
        5. On success remove the backup; on failure restore it. The previous valid
           output is preserved until the new set is fully staged, so a failure can
           never leave a mixed old/new set.
        """
        self._validate_names(artifacts)
        result = self.scanner.scan_all(artifacts)
        if not result.clean:
            raise ArtifactPublishError(
                "Content secret scan blocked publication: " + ", ".join(result.findings)
            )

        parent = self.target_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = parent / (self.target_dir.name + ".tmp_publish")
        bak_dir = parent / (self.target_dir.name + ".bak_publish")
        self._recover_crash_state(tmp_dir, bak_dir)

        # Stage the complete new set in the temp dir.
        tmp_dir.mkdir(parents=True)
        try:
            for name, text in artifacts.items():
                (tmp_dir / name).write_text(text, encoding="utf-8")
            missing = [n for n in artifacts if not (tmp_dir / n).exists()]
            if missing:
                raise ArtifactPublishError(f"incomplete artifact set: {missing}")
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise  # existing target untouched

        # Swap: old aside, new into place, then drop old.
        moved_backup = False
        try:
            if self.target_dir.exists():
                os.replace(self.target_dir, bak_dir)   # rename to non-existing name
                moved_backup = True
            os.replace(tmp_dir, self.target_dir)
        except Exception as exc:
            # Restore the previous output if the swap failed after the backup rename.
            if moved_backup and bak_dir.exists() and not self.target_dir.exists():
                os.replace(bak_dir, self.target_dir)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if bak_dir.exists():
                shutil.rmtree(bak_dir, ignore_errors=True)
            raise ArtifactPublishError(f"publication swap failed and was rolled back: {exc}") from exc
        # Success: drop the old backup.
        if bak_dir.exists():
            shutil.rmtree(bak_dir, ignore_errors=True)
        return result
