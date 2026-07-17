"""Discovery provider abstraction, provenance, and registry (Phase 8.4).

A provider turns a campaign matrix cell into bounded, untrusted `DiscoveryCandidate`s with
explicit provenance. Provider output is never treated as verified truth; it is normalized,
deduplicated, suppression-checked, and cheaply triaged before anything is fetched or promoted.

Built-in providers:
- `FixtureDiscoveryProvider`   — deterministic, committed, no network; drives the E2E.
- `FileImportDiscoveryProvider`— CSV / JSON / NDJSON / newline list; bounded, path-confined,
  secret-scanned, with an explicit malformed-row report.
- `UnconfiguredRealProvider`   — the real-adapter interface + a factual readiness report when
  no trusted live provider is configured (the default). Live discovery is opt-in only.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from core.orchestration.content_safety import ContentSecretScanner
from core.schemas.source_reference import SourceReference

PROVIDER_TYPES = frozenset({"fixture", "file_import", "api", "mcp"})
TRUST_STATUSES = frozenset({"untrusted", "semi_trusted", "trusted"})
# Aligned with the Phase 8.2 legal-review vocabulary.
TERMS_STATUSES = frozenset({"not_reviewed", "in_review", "reviewed_approved", "reviewed_blocked"})
_LOCAL_TYPES = frozenset({"fixture", "file_import"})

_MAX_FILE_BYTES = 5 * 1024 * 1024
# An auth reference must look like an environment-variable name, never a secret value.
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class DiscoveryError(Exception):
    """Raised for fail-closed discovery conditions (budget/terms/config/malformed input)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderMetadata:
    """Typed, declarative metadata for one discovery provider.

    `auth_ref` is always an environment-variable NAME, never a secret value. A provider whose
    terms are `reviewed_blocked` can never execute; live (api/mcp) providers additionally
    require explicit approval, trust, approved terms, and a configured auth reference.
    """

    provider_id: str = ""
    provider_type: str = "fixture"
    display_name: str = ""
    trust_status: str = "untrusted"
    enabled: bool = False
    source_category: str = "manual_seed"
    supported_markets: List[str] = field(default_factory=list)
    supported_languages: List[str] = field(default_factory=list)
    query_capabilities: List[str] = field(default_factory=list)
    auth_ref: str = ""                       # env var NAME only, never a value
    terms_review_status: str = "not_reviewed"
    rate_limit_per_min: int = 0
    cost_per_result_usd: float = 0.0
    max_results_per_request: int = 0
    data_freshness: str = "static"
    public_or_licensed: str = "public"
    version: str = "0.0.0"

    def __post_init__(self) -> None:
        if self.provider_type not in PROVIDER_TYPES:
            raise DiscoveryError(f"unknown provider_type: {self.provider_type!r}")
        if self.trust_status not in TRUST_STATUSES:
            raise DiscoveryError(f"unknown trust_status: {self.trust_status!r}")
        if self.terms_review_status not in TERMS_STATUSES:
            raise DiscoveryError(f"unknown terms_review_status: {self.terms_review_status!r}")
        if self.public_or_licensed not in ("public", "licensed"):
            raise DiscoveryError(f"unknown public_or_licensed: {self.public_or_licensed!r}")
        for name in ("rate_limit_per_min", "max_results_per_request"):
            if getattr(self, name) < 0:
                raise DiscoveryError(f"{name} cannot be negative")
        if self.cost_per_result_usd < 0:
            raise DiscoveryError("cost_per_result_usd cannot be negative")
        # An auth_ref must be an environment-variable NAME (UPPER_SNAKE), never a secret value.
        if self.auth_ref and not _ENV_NAME_RE.match(self.auth_ref):
            raise DiscoveryError("auth_ref must be an environment-variable name, not a value")

    @property
    def is_local(self) -> bool:
        return self.provider_type in _LOCAL_TYPES

    def can_execute(self, live_approved: bool) -> tuple[bool, str]:
        """Return (allowed, reason). Fail-closed on blocked terms / disabled / unapproved live."""
        if self.terms_review_status == "reviewed_blocked":
            return False, "provider terms are reviewed_blocked"
        if not self.enabled:
            return False, "provider disabled"
        if self.is_local:
            return True, "local provider"
        if not live_approved:
            return False, "live discovery not approved (pass --approve-live-discovery)"
        if self.trust_status != "trusted":
            return False, "live provider is not trusted"
        if self.terms_review_status != "reviewed_approved":
            return False, "live provider terms not reviewed_approved"
        if not self.auth_ref:
            return False, "live provider has no configured auth reference"
        return True, "approved live provider"

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class DiscoveryCandidate:
    """One untrusted provider result with explicit provenance (never verified truth)."""

    provider_id: str = ""
    raw_candidate_id: str = ""
    observed_at: str = field(default_factory=_now_iso)
    source_url: str = ""                     # public source URL when available
    source_query: str = ""                   # matrix cell / query descriptor
    business_name: str = ""
    website: str = ""                        # public website candidate URL
    country_hint: str = ""
    region_hint: str = ""
    language_hint: str = ""
    industry_hint: str = ""
    business_type_hint: str = ""
    confidence: str = "low"
    provider_warnings: List[str] = field(default_factory=list)
    raw_sample: str = ""                     # bounded, sanitized debug slice only

    def provenance(self) -> SourceReference:
        return SourceReference(url=self.source_url or self.website, platform="discovery_provider",
                               title=self.business_name, retrieved_at=self.observed_at,
                               notes=f"provider={self.provider_id};query={self.source_query}")

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveryCandidate":
        known = set(cls().__dict__.keys())
        return cls(**{k: v for k, v in data.items() if k in known})


class DiscoveryProvider(Protocol):
    metadata: ProviderMetadata

    def discover(self, cell: Dict[str, Any], limit: int) -> List[DiscoveryCandidate]: ...

    def readiness(self) -> Dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Fixture provider (deterministic, no network)
# ---------------------------------------------------------------------------

class FixtureDiscoveryProvider:
    """Returns a fixed, committed list of candidates. Deterministic; no network."""

    def __init__(self, metadata: ProviderMetadata, candidates: List[DiscoveryCandidate]) -> None:
        self.metadata = metadata
        self._candidates = list(candidates)

    def discover(self, cell: Dict[str, Any], limit: int) -> List[DiscoveryCandidate]:
        # Deterministic: the fixture ignores the cell content but honours the per-call limit.
        out = [c for c in self._candidates if c.provider_id == self.metadata.provider_id]
        return out[: max(0, int(limit))]

    def readiness(self) -> Dict[str, Any]:
        return {"provider_id": self.metadata.provider_id, "readiness": "fixture_tested",
                "configured": True, "network": False}


# ---------------------------------------------------------------------------
# File-import provider (CSV / JSON / NDJSON / newline list)
# ---------------------------------------------------------------------------

@dataclass
class FileImportReport:
    path: str = ""
    format: str = ""
    rows_total: int = 0
    rows_ok: int = 0
    rows_malformed: int = 0
    malformed_samples: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class FileImportDiscoveryProvider:
    """Imports candidates from a bounded, path-confined local file.

    Supports CSV, JSON (list), NDJSON, and a newline-separated URL/domain list. The file size
    is bounded, the path is confined under an allowed base, content is secret-scanned, and
    malformed rows are reported (not silently dropped) via `last_report`.
    """

    def __init__(self, metadata: ProviderMetadata, path: str, *, base_dir: Optional[str] = None,
                 max_bytes: int = _MAX_FILE_BYTES) -> None:
        self.metadata = metadata
        self.max_bytes = max_bytes
        self._scanner = ContentSecretScanner()
        self._path = self._confine(path, base_dir)
        self.last_report = FileImportReport(path=str(self._path))

    @staticmethod
    def _confine(path: str, base_dir: Optional[str]) -> Path:
        """Confine a RELATIVE import path under `base_dir` (blocks '..' traversal). An explicit
        absolute path is trusted (chosen directly by the CLI user, not by provider output)."""
        p = Path(path)
        if p.is_absolute() or base_dir is None:
            return p.resolve()
        base = Path(base_dir).resolve()
        target = (base / p).resolve()
        if base != target and base not in target.parents:
            raise DiscoveryError(f"import path escapes the allowed base: {path!r}")
        return target

    def discover(self, cell: Dict[str, Any], limit: int) -> List[DiscoveryCandidate]:
        report = FileImportReport(path=str(self._path))
        self.last_report = report
        if not self._path.exists() or not self._path.is_file():
            report.errors.append("file not found")
            raise DiscoveryError(f"import file not found: {self._path}")
        size = self._path.stat().st_size
        if size > self.max_bytes:
            report.errors.append(f"file too large: {size} > {self.max_bytes}")
            raise DiscoveryError(f"import file too large: {size} bytes")
        raw = self._path.read_bytes().decode("utf-8", errors="replace")
        # Secret scan the whole file — a credential-bearing import fails closed.
        if self._scanner.scan_text("import", raw):
            report.errors.append("import file appears to contain a secret; refused")
            raise DiscoveryError("import file contains a secret and was refused")
        suffix = self._path.suffix.lower()
        if suffix == ".json":
            rows = self._parse_json(raw, report)
        elif suffix in (".ndjson", ".jsonl"):
            rows = self._parse_ndjson(raw, report)
        elif suffix == ".csv":
            rows = self._parse_csv(raw, report)
        else:
            rows = self._parse_lines(raw, report)
        report.format = suffix.lstrip(".") or "lines"
        out: List[DiscoveryCandidate] = []
        for row in rows:
            cand = self._row_to_candidate(row, report)
            if cand is not None:
                out.append(cand)
            if len(out) >= max(0, int(limit)):
                break
        report.rows_ok = len(out)
        return out

    def _row_to_candidate(self, row: Dict[str, Any], report: FileImportReport
                          ) -> Optional[DiscoveryCandidate]:
        website = str(row.get("website") or row.get("url") or "").strip()
        name = str(row.get("business_name") or row.get("name") or "").strip()
        if not website and not name:
            report.rows_malformed += 1
            if len(report.malformed_samples) < 5:
                report.malformed_samples.append(str(row)[:120])
            return None
        return DiscoveryCandidate(
            provider_id=self.metadata.provider_id,
            raw_candidate_id=str(row.get("id") or website or name)[:120],
            source_query="file_import",
            business_name=name[:200],
            website=website[:500],
            country_hint=str(row.get("country") or "")[:40],
            language_hint=str(row.get("language") or "")[:40],
            industry_hint=str(row.get("industry") or "")[:60],
            business_type_hint=str(row.get("business_type") or "")[:60],
            confidence="low",
        )

    def _parse_json(self, raw: str, report: FileImportReport) -> List[Dict[str, Any]]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            report.errors.append(f"invalid JSON: {exc}")
            raise DiscoveryError(f"invalid JSON import: {exc}") from exc
        if isinstance(data, dict):
            data = data.get("candidates") or data.get("rows") or []
        if not isinstance(data, list):
            raise DiscoveryError("JSON import must be a list (or {candidates:[...]})")
        rows: List[Dict[str, Any]] = []
        for item in data:
            report.rows_total += 1
            if isinstance(item, dict):
                rows.append(item)
            else:
                report.rows_malformed += 1
        return rows

    def _parse_ndjson(self, raw: str, report: FileImportReport) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            report.rows_total += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                report.rows_malformed += 1
                if len(report.malformed_samples) < 5:
                    report.malformed_samples.append(line[:120])
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                report.rows_malformed += 1
        return rows

    def _parse_csv(self, raw: str, report: FileImportReport) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            report.rows_total += 1
            rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items()})
        return rows

    def _parse_lines(self, raw: str, report: FileImportReport) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            report.rows_total += 1
            rows.append({"website": line})
        return rows

    def readiness(self) -> Dict[str, Any]:
        return {"provider_id": self.metadata.provider_id, "readiness": "locally_configured",
                "configured": self._path.exists(), "path": str(self._path)}


# ---------------------------------------------------------------------------
# Real provider adapter (interface + factual readiness when not configured)
# ---------------------------------------------------------------------------

class UnconfiguredRealProvider:
    """The real-adapter interface with a factual readiness report.

    When no trusted live provider is configured (the default — `config/mcp_servers.yaml` is a
    references-only manifest with everything disabled), this reports an honest readiness state
    and refuses to `discover`. It never scrapes or invents a fallback.
    """

    def __init__(self, metadata: ProviderMetadata, *, resolver: Optional[Callable[[str], bool]] = None
                 ) -> None:
        self.metadata = metadata
        # resolver(env_name) -> bool: whether the referenced credential is present. Default:
        # treat as unconfigured (never reads the value; presence check only).
        self._resolver = resolver or (lambda _name: False)

    @property
    def configured(self) -> bool:
        return bool(self.metadata.auth_ref) and self._resolver(self.metadata.auth_ref)

    def discover(self, cell: Dict[str, Any], limit: int) -> List[DiscoveryCandidate]:
        allowed, reason = self.metadata.can_execute(live_approved=True)
        if not self.configured or not allowed:
            raise DiscoveryError(
                f"real provider {self.metadata.provider_id!r} is not available: "
                f"{'unconfigured credentials' if not self.configured else reason}. "
                "No scraping fallback is used.")
        # A genuinely configured adapter would call its API here. With no live credentials in
        # this environment there is nothing to call, and fabricating results is not allowed.
        raise DiscoveryError("live provider adapter has no configured backend to call")

    def readiness(self) -> Dict[str, Any]:
        allowed, reason = self.metadata.can_execute(live_approved=True)
        if self.configured and allowed:
            level = "live_accepted_ready"
        elif allowed:
            level = "adapter_ready"          # approved/trusted but credential not present
        else:
            level = "adapter_ready_not_configured"
        return {"provider_id": self.metadata.provider_id, "readiness": level,
                "configured": self.configured, "reason": reason, "network": True}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ProviderRegistry:
    """A small in-process registry of discovery providers keyed by provider_id."""

    def __init__(self) -> None:
        self._providers: Dict[str, DiscoveryProvider] = {}

    def register(self, provider: DiscoveryProvider) -> None:
        pid = provider.metadata.provider_id
        if not pid:
            raise DiscoveryError("provider has no provider_id")
        if pid in self._providers:
            raise DiscoveryError(f"duplicate provider_id: {pid!r}")
        self._providers[pid] = provider

    def get(self, provider_id: str) -> DiscoveryProvider:
        if provider_id not in self._providers:
            raise DiscoveryError(f"unknown provider_id: {provider_id!r}")
        return self._providers[provider_id]

    def ids(self) -> List[str]:
        return sorted(self._providers)

    def snapshot(self) -> List[Dict[str, Any]]:
        """A serializable registry snapshot (metadata + readiness) with no secrets."""
        out = []
        for pid in self.ids():
            p = self._providers[pid]
            out.append({"metadata": p.metadata.to_dict(), "readiness": p.readiness()})
        return out
