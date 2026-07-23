"""Unified within-site COVERAGE policy (PR-1 core).

Coverage is the *depth within one target site* axis: how many genuinely distinct, meaningful pages of
a single site to test. It is INDEPENDENT of the portfolio campaign-budget axis (SESSION_PRESETS +
AdaptiveAllocator decide how many domains and for how long — unchanged here).

Two operator-facing profiles derive an internal per-site page ceiling (a CEILING, never a quota to
fill):

    adaptive  -> 12 additional same-site pages   (product default)
    deep      -> 20 additional same-site pages

A third mode, ``explicit``, is internal only (never offered to an operator): it preserves a run's
serialized ``max_pages_per_site`` exactly, for backward compatibility with historical runs and
programmatic callers. A selected profile derives the ceiling and a legacy ``max_pages_per_site`` must
not silently override it.

Classification is deliberately conservative:

  * Only OBVIOUS pagination / blog / news / legal / language-copy noise is skipped BEFORE fetch.
  * A page is never suppressed as a near-duplicate from its URL alone — suppression requires observed
    STRUCTURAL/template evidence (landmark set + heading-level skeleton + form presence), and only
    after the same template has already been seen.

The planner stops early when no new meaningful coverage appears and records an honest stop reason. It
carries NO multi-step flow ceiling — flow exploration is single-step today, and honest flow metadata
is recorded by the engine, not invented here.
"""
from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urlsplit

OPERATOR_COVERAGE = ("adaptive", "deep")          # the only two operator-facing choices
COVERAGE_MODES = ("adaptive", "deep", "explicit")  # + internal back-compat mode

_PAGE_CEILING = {"adaptive": 12, "deep": 20}

# Consecutive structural near-duplicates that together mean "further pages add no new coverage".
_NEAR_DUP_RUN = 3

# Conservative pre-fetch noise. Language codes are matched ONLY as a leading path segment so a real
# path like "/design" is never mistaken for a language copy.
_LANG = frozenset({"de", "fr", "es", "it", "pt", "nl", "ru", "zh", "ja", "ko", "pl", "tr", "ar",
                   "sv", "da", "fi", "no", "cs", "el", "he", "hi", "th", "uk", "ro", "hu"})
_NOISE_PATH_SUBSTR = ("/blog/", "/news/", "/tag/", "/tags/", "/category/", "/categories/",
                      "/author/", "/archive/", "/page/", "/feed")
_NOISE_PATH_EXACT_PREFIX = ("/privacy", "/terms", "/cookie", "/legal", "/gdpr", "/imprint",
                            "/disclaimer", "/eula", "/refund", "/blog", "/news")
_NOISE_SUFFIX = (".rss", ".xml", ".atom")
_PAGE_QS = re.compile(r"(^|&)p(age)?=\d", re.IGNORECASE)


def derive_page_ceiling(coverage: str, explicit_max_pages: int) -> int:
    """Additional-page ceiling for a coverage mode. ``explicit`` preserves the serialized value."""
    return _PAGE_CEILING.get(coverage, explicit_max_pages)


def is_obvious_noise(url: str) -> bool:
    """True only for CLEARLY low-value pages (pagination/blog/news/legal/language copy/feeds).

    Conservative by design — a false negative (fetching a low-value page) is far cheaper than a false
    positive (silently skipping a real page)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    path = (parts.path or "/").lower()
    query = (parts.query or "").lower()
    if _PAGE_QS.search(query):
        return True
    if any(s in path for s in _NOISE_PATH_SUBSTR):
        return True
    if any(path == p or path.startswith(p + "/") or path.startswith(p + "-") or path.startswith(p + ".")
           for p in _NOISE_PATH_EXACT_PREFIX):
        return True
    if path.endswith(_NOISE_SUFFIX):
        return True
    first = path.lstrip("/").split("/", 1)[0]
    if first in _LANG:                       # leading language-copy segment, e.g. /de/, /fr/pricing
        return True
    return False


def page_signature(observation: Any) -> str:
    """A structural/template fingerprint of an observed page (never its URL or text content).

    Two pages sharing landmark set + heading-LEVEL skeleton + form presence are the same template."""
    landmarks = getattr(observation, "landmarks", {}) or {}
    headings = getattr(observation, "headings", []) or []
    forms = getattr(observation, "forms", []) or []
    landmark_key = ",".join(sorted(str(k) for k in landmarks))
    level_skeleton = ",".join(str(h.get("level", "")) for h in headings if isinstance(h, dict))
    return f"L[{landmark_key}]|H[{level_skeleton}]|F[{int(bool(forms))}]"


class CoveragePlanner:
    """Per-target within-site coverage planner. Stateful over one site's pages; pure/in-memory.

    ``active`` (an operator profile) enables noise-skipping, structural near-duplicate suppression and
    early stop. ``explicit`` is passive: no filtering, stopping only at the preserved ceiling — so a
    legacy run behaves exactly as before while still reporting honest metadata."""

    def __init__(self, *, coverage: str, page_ceiling: int, near_dup_run: int = _NEAR_DUP_RUN) -> None:
        self.coverage = coverage
        self.page_ceiling = int(page_ceiling)
        self._near_dup_run = int(near_dup_run)
        self.active = coverage in OPERATOR_COVERAGE
        self._seen_sigs: set = set()
        self._meaningful = 0
        self._seeded = False
        self._skipped_noise = 0
        self._skipped_dup = 0
        self._consec_dup = 0
        self._stop_reason = ""

    def seed(self, observation: Any) -> None:
        """Count the landing page as meaningful page #1 and register its template, so a link that
        merely re-renders it is a near-duplicate and the ceiling counts the landing honestly."""
        self._seen_sigs.add(page_signature(observation))
        self._meaningful = 1
        self._seeded = True

    def pre_fetch_skip(self, url: str) -> str:
        """Return ``"noise"`` if this URL should be skipped BEFORE fetching (operator profiles only)."""
        if self.active and is_obvious_noise(url):
            self._skipped_noise += 1
            return "noise"
        return ""

    def record(self, url: str, observation: Any) -> str:
        """Classify a fetched page as ``"meaningful"`` or ``"near_duplicate"`` (structural evidence)."""
        sig = page_signature(observation)
        if self.active and sig in self._seen_sigs:
            self._skipped_dup += 1
            self._consec_dup += 1
            return "near_duplicate"
        self._meaningful += 1
        self._consec_dup = 0
        self._seen_sigs.add(sig)
        return "meaningful"

    def should_stop(self) -> str:
        """Non-empty stop reason once the ceiling is hit or coverage is exhausted."""
        if self._stop_reason:
            return self._stop_reason
        if self._meaningful >= self.page_ceiling:
            self._stop_reason = "page_ceiling_reached"
        elif self.active and self._consec_dup >= self._near_dup_run:
            self._stop_reason = "no_new_meaningful_coverage"
        return self._stop_reason

    def stop(self, reason: str) -> None:
        """Record an externally-imposed stop (e.g. operator control) if none is set yet."""
        if not self._stop_reason:
            self._stop_reason = reason

    def finalize_links_exhausted(self) -> None:
        if not self._stop_reason:
            self._stop_reason = "links_exhausted"

    def summary(self) -> Dict[str, Any]:
        # meaningful_pages_tested counts the landing (once seeded) plus meaningful additional pages,
        # and is bounded by page_ceiling — it is never reported above the ceiling it was capped at.
        return {
            "coverage": self.coverage,
            "page_ceiling": self.page_ceiling,
            "meaningful_pages_tested": self._meaningful,
            "pages_skipped_noise": self._skipped_noise,
            "pages_skipped_near_duplicate": self._skipped_dup,
            "page_stop_reason": self._stop_reason,
        }


def make_planner(coverage: str, explicit_max_pages: int) -> "CoveragePlanner":
    """Build the planner for a run's coverage mode. The ceiling is landing-inclusive (total meaningful
    pages): an operator profile derives 12/20; ``explicit`` allows the landing plus its legacy
    ``max_pages_per_site`` links, preserving prior behaviour exactly."""
    if coverage in OPERATOR_COVERAGE:
        ceiling = _PAGE_CEILING[coverage]
    else:
        ceiling = int(explicit_max_pages) + 1          # landing + legacy per-site link cap
    return CoveragePlanner(coverage=coverage, page_ceiling=ceiling)
