"""Scout runtime configuration (Phase 8.3).

A bounded, fail-closed run configuration. Seeds are limited to 1..10 explicit public
URLs; every budget is bounded; the browser backend defaults to the offline-safe static
backend. A `ProspectCampaign` (Phase 8.2 contract) may be attached for provenance, but the
runtime only ever acts on the explicit `seeds`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List

from core.scout import SCOUT_VERSION
from core.scout.coverage import COVERAGE_MODES, OPERATOR_COVERAGE, derive_page_ceiling
from core.scout.evidence_policy import VIDEO_MANUAL, VIDEO_MODES, VIDEO_QUALIFIED_AUTO
from core.scout.run_purpose import KNOWN_PURPOSES, PURPOSE_PRODUCTION, PURPOSE_UNCLASSIFIED
from core.scout.url_safety import UrlPolicy

MAX_SEEDS = 10
MIN_SEEDS = 1

# The bounded, read-only check families available in v1.0.
CHECK_FAMILIES: FrozenSet[str] = frozenset({
    "links", "console_resources", "presubmit_validation", "accessibility",
    "performance", "seo", "structured_data", "mobile", "business_flow",
})

BROWSER_MODES: FrozenSet[str] = frozenset({"static", "playwright"})


class ScoutConfigError(ValueError):
    """Raised when a Scout run configuration is invalid."""


# How a run's target list arrived. "unknown" is only ever a READING of a config written before
# provenance existed — nothing new may enter it.
INTAKE_KINDS = frozenset({"paste", "upload", "discovery", "api", "unknown"})
# Every row read ends in exactly one of these. `rows_capped` exists because the operator's list may
# be longer than the run's site limit: without it, truncation looks like rows vanishing.
_INTAKE_COUNTS = ("rows_read", "rows_accepted", "rows_rejected", "duplicates", "rows_capped")
_MAX_INTAKE_TEXT = 200


def normalise_intake(value: Any) -> Dict[str, Any]:
    """Validate and bound an intake provenance record. Unknown keys are dropped, never stored.

    Free text from an untrusted request is the last thing that should end up in a client-facing
    artifact, so only a fixed set of keys survives and each is length- or type-bounded.
    """
    if not isinstance(value, dict) or not value:
        return {}
    kind = str(value.get("kind") or "").strip().lower()
    if kind not in INTAKE_KINDS:
        raise ScoutConfigError(f"unknown intake kind: {value.get('kind')!r}")
    out: Dict[str, Any] = {"kind": kind}
    for name in ("source_name", "query"):
        text = value.get(name)
        if isinstance(text, str) and text.strip():
            out[name] = text.strip()[:_MAX_INTAKE_TEXT]
    for name in _INTAKE_COUNTS:
        count = value.get(name)
        if isinstance(count, bool) or count is None:
            continue
        if not isinstance(count, int) or count < 0:
            raise ScoutConfigError(f"intake {name} must be a non-negative integer, got {count!r}")
        out[name] = count
    return out


@dataclass
class ScoutRunConfig:
    """Bounded configuration for one Scout run."""

    campaign_name: str = "adhoc"
    seeds: List[str] = field(default_factory=list)
    max_sites: int = MAX_SEEDS
    max_pages_per_site: int = 5
    request_timeout_s: float = 15.0
    max_response_bytes: int = 3_000_000
    # v1.0.x runs strictly sequentially. Parallel execution is deferred, so the only
    # honest value is 1; anything else fails closed rather than silently no-op.
    concurrency: int = 1
    check_families: List[str] = field(default_factory=lambda: sorted(CHECK_FAMILIES))
    browser_mode: str = "static"
    # Within-site coverage profile (depth per single site), independent of the campaign-budget axis.
    # "explicit" (default) preserves the serialized max_pages_per_site for back-compat; an operator
    # profile ("adaptive"/"deep") DERIVES the page ceiling and overrides a legacy max_pages_per_site.
    coverage: str = "explicit"
    # Reproduction-video policy. Default "manual" = behaviour unchanged (never auto-records);
    # "qualified_auto" opts into a short clip for a reproduced visual/interaction defect.
    # Scout decides for itself whether a clip is worth keeping (evidence_policy.video_qualified),
    # so a NEW run is automatic by default. "manual"/"off" remain accepted for an explicit opt-out
    # and for reading back runs made before this was automatic.
    video_mode: str = VIDEO_QUALIFIED_AUTO
    # Why this run exists: production work, or acceptance/diagnostic/manual-test data that must not
    # distort production counters and may later be cleaned up. NOT an operator-facing scan mode --
    # it is set by the harness or internal launch context. A new run is production unless something
    # deliberate says otherwise, so "unclassified" now means only "written before this field
    # existed" -- a reading of old data rather than a state anything new can enter.
    run_purpose: str = PURPOSE_PRODUCTION
    # WHERE this run's targets came from, recorded at intake. A finished run could say what it
    # scanned and never what it was handed: an uploaded list and a pasted one produced identical
    # config on disk, so "did we scan the file the client sent?" had no answer a person could check.
    # Bounded and arithmetic-checkable, never free text.
    intake: Dict[str, Any] = field(default_factory=dict)
    output_dir: str = "outputs"
    resume: bool = False
    run_id: str = ""
    # Explicit local hosts permitted for local fixtures (empty in live/public use).
    allowed_local_hosts: FrozenSet[str] = field(default_factory=frozenset)
    resolve_dns: bool = True

    def __post_init__(self) -> None:
        self.intake = normalise_intake(self.intake)
        if not isinstance(self.seeds, list) or not all(isinstance(s, str) for s in self.seeds):
            raise ScoutConfigError("seeds must be a list of URL strings")
        if not (MIN_SEEDS <= len(self.seeds) <= MAX_SEEDS):
            raise ScoutConfigError(f"seeds must contain {MIN_SEEDS}..{MAX_SEEDS} URLs, got {len(self.seeds)}")
        if self.coverage not in COVERAGE_MODES:
            raise ScoutConfigError(f"unknown coverage: {self.coverage!r}")
        # A selected coverage profile derives the per-site page ceiling and overrides any legacy
        # max_pages_per_site; "explicit" preserves the serialized value (historical/back-compat).
        if self.coverage in OPERATOR_COVERAGE:
            self.max_pages_per_site = derive_page_ceiling(self.coverage, self.max_pages_per_site)
        for name, value, lo, hi in (
            ("max_sites", self.max_sites, 1, MAX_SEEDS),
            ("max_pages_per_site", self.max_pages_per_site, 1, 50),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not (lo <= value <= hi):
                raise ScoutConfigError(f"{name} must be an int in [{lo},{hi}], got {value!r}")
        # Concurrency is honest about the runtime: v1.0.x is sequential only.
        if isinstance(self.concurrency, bool) or not isinstance(self.concurrency, int) \
                or self.concurrency != 1:
            raise ScoutConfigError(
                "concurrency must be 1 in v1.0.x; parallel execution is deferred "
                f"(got {self.concurrency!r})")
        if not isinstance(self.request_timeout_s, (int, float)) or not (1 <= self.request_timeout_s <= 120):
            raise ScoutConfigError("request_timeout_s must be within [1,120]")
        if isinstance(self.max_response_bytes, bool) or not isinstance(self.max_response_bytes, int) \
                or not (10_000 <= self.max_response_bytes <= 20_000_000):
            raise ScoutConfigError("max_response_bytes must be within [10_000, 20_000_000]")
        unknown = set(self.check_families) - CHECK_FAMILIES
        if unknown:
            raise ScoutConfigError(f"unknown check families: {sorted(unknown)}")
        if not self.check_families:
            raise ScoutConfigError("at least one check family is required")
        if self.browser_mode not in BROWSER_MODES:
            raise ScoutConfigError(f"unknown browser_mode: {self.browser_mode!r}")
        if self.video_mode not in VIDEO_MODES:
            raise ScoutConfigError(f"unknown video_mode: {self.video_mode!r}")
        if self.run_purpose not in KNOWN_PURPOSES:
            raise ScoutConfigError(f"unknown run_purpose: {self.run_purpose!r}")
        self.check_families = sorted(set(self.check_families))
        self.allowed_local_hosts = frozenset(self.allowed_local_hosts)

    def url_policy(self) -> UrlPolicy:
        return UrlPolicy(allowed_local_hosts=self.allowed_local_hosts, resolve_dns=self.resolve_dns)

    def material_signature(self) -> Dict[str, Any]:
        """The immutable subset that must match to resume a run.

        Excludes volatile/identity-only fields (``resume``, ``run_id``, ``output_dir``,
        ``scout_version``). Seed order is significant — prospect ids are index-based, so a
        reordered seed list is a different run and must not resume the old one.
        """
        return {
            "campaign_name": self.campaign_name,
            "seeds": list(self.seeds),
            "max_sites": self.max_sites,
            "max_pages_per_site": self.max_pages_per_site,
            "request_timeout_s": self.request_timeout_s,
            "max_response_bytes": self.max_response_bytes,
            "concurrency": self.concurrency,
            "check_families": list(self.check_families),
            "browser_mode": self.browser_mode,
            "coverage": self.coverage,
            "video_mode": self.video_mode,
            "run_purpose": self.run_purpose,
            "allowed_local_hosts": sorted(self.allowed_local_hosts),
            "resolve_dns": self.resolve_dns,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scout_version": SCOUT_VERSION,
            "campaign_name": self.campaign_name,
            "seeds": list(self.seeds),
            "max_sites": self.max_sites,
            "max_pages_per_site": self.max_pages_per_site,
            "request_timeout_s": self.request_timeout_s,
            "max_response_bytes": self.max_response_bytes,
            "concurrency": self.concurrency,
            "check_families": list(self.check_families),
            "browser_mode": self.browser_mode,
            "coverage": self.coverage,
            "video_mode": self.video_mode,
            "run_purpose": self.run_purpose,
            "intake": dict(self.intake),
            "output_dir": self.output_dir,
            "resume": self.resume,
            "run_id": self.run_id,
            "allowed_local_hosts": sorted(self.allowed_local_hosts),
            "resolve_dns": self.resolve_dns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoutRunConfig":
        known = {
            "campaign_name", "seeds", "max_sites", "max_pages_per_site", "request_timeout_s",
            "max_response_bytes", "concurrency", "check_families", "browser_mode", "coverage",
            "video_mode", "run_purpose", "intake", "output_dir", "resume", "run_id", "resolve_dns",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        if "allowed_local_hosts" in data:
            kwargs["allowed_local_hosts"] = frozenset(data["allowed_local_hosts"])
        # A config written before video capture became automatic recorded no video, whatever the
        # current default is. Reading it back as "automatic" would re-describe a finished run as
        # something it never was, so a missing key keeps the historical behaviour.
        kwargs.setdefault("video_mode", VIDEO_MANUAL)
        # Same reasoning for purpose: a run that recorded nothing genuinely declared nothing, and
        # reading it back as "production" would hand old test data protection it was never given
        # (or, worse, claim an unknown run was real work). Unclassified is the honest reading.
        if not str(kwargs.get("run_purpose") or "").strip():
            kwargs["run_purpose"] = PURPOSE_UNCLASSIFIED
        return cls(**kwargs)


def _campaign_slug(campaign_name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in campaign_name.lower()).strip("-")[:24] or "run"


def make_run_id(campaign_name: str, seeds: List[str], clock_iso: str) -> str:
    """Deterministic run id from campaign + normalized seeds + a provided timestamp.

    Deterministic by design (same inputs → same id); used only where a stable, explicit id is
    wanted (e.g. the bundled demo). Fresh scans must use :func:`fresh_run_id`, which is unique.
    """
    import hashlib
    payload = campaign_name + "\x00" + "\x00".join(sorted(seeds)) + "\x00" + clock_iso
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{_campaign_slug(campaign_name)}-{digest}"


def fresh_run_id(campaign_name: str) -> str:
    """A unique run id for a fresh scan: UTC timestamp + cryptographic entropy.

    Two fresh runs of the same campaign and seeds get distinct ids, so a normal run never
    reuses (and never silently mixes into) an existing run directory.
    """
    import secrets
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{_campaign_slug(campaign_name)}-{stamp}-{secrets.token_hex(4)}"
