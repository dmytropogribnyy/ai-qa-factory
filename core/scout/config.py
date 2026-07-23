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
from core.scout.evidence_policy import VIDEO_MANUAL, VIDEO_MODES
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
    video_mode: str = VIDEO_MANUAL
    output_dir: str = "outputs"
    resume: bool = False
    run_id: str = ""
    # Explicit local hosts permitted for local fixtures (empty in live/public use).
    allowed_local_hosts: FrozenSet[str] = field(default_factory=frozenset)
    resolve_dns: bool = True

    def __post_init__(self) -> None:
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
            "video_mode", "output_dir", "resume", "run_id", "resolve_dns",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        if "allowed_local_hosts" in data:
            kwargs["allowed_local_hosts"] = frozenset(data["allowed_local_hosts"])
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
