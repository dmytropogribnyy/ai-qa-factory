"""One ingestion path for every way an operator can name a site.

Pasted text, an uploaded CSV/XLSX and discovery results all end up here, because "where the list came
from" must not change what happens to the list. After this module every source has produced the same
thing: canonical targets, a duplicate account, and rejections that say WHY in words an operator can
act on.

Two rules this module exists to enforce:

- **Identity is the canonical domain, not the URL.** ``https://www.nolt.io/`` and ``https://nolt.io``
  are one site; ``https://plausible.io/pricing?utm_source=x`` is the same site as ``https://plausible.io/``.
  Deduplicating by URL let the same company appear several times in History and in Needs attention.
- **A rejected line is not a site.** ``0.1`` and ``http://localhost/`` must never reach the queue,
  the history or a counter as though they were companies; they are reported as what they are.

A target the operator typed or uploaded is **pinned**: it was chosen deliberately, so commercial
triage may score it but must not silently drop it. Discovery targets carry no such promise.

Nothing here fetches anything. It is pure parsing, canonicalization and policy, so the preview an
operator sees before pressing Start is produced by exactly the code that will run afterwards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from core.scout.discovery.domain_intel import canonical_domain
from core.scout.url_safety import Resolver, UrlPolicy, check_url

# Query parameters that identify a campaign, not a page. Keeping them would make the same page look
# like two different targets and would leak our own tracking into stored evidence.
_TRACKING_PREFIXES = ("utm_", "mc_", "pk_", "hsa_", "vero_")
_TRACKING_KEYS = frozenset({
    "gclid", "fbclid", "msclkid", "yclid", "dclid", "igshid", "mkt_tok", "ref", "referrer",
    "source", "campaign_id", "at_medium", "at_campaign", "_hsenc", "_hsmi",
})

# Why a line was refused, in the operator's terms rather than the validator's.
KIND_MALFORMED = "malformed"
KIND_NON_PUBLIC = "non_public"
KIND_UNSUPPORTED = "unsupported"
KIND_UNREACHABLE = "unreachable"

_REASON_KINDS = (
    (KIND_NON_PUBLIC, ("localhost", "prohibited ip", "prohibited address", "private", "loopback",
                       "link-local", "reserved")),
    (KIND_UNSUPPORTED, ("scheme not allowed", "port not allowed", "credentials in url")),
    (KIND_UNREACHABLE, ("does not resolve",)),
    (KIND_MALFORMED, ("malformed", "no host", "empty url", "single-label")),
)

_HUMAN_REASON = {
    KIND_MALFORMED: "not a website address",
    KIND_NON_PUBLIC: "not a public website (private, local or reserved address)",
    KIND_UNSUPPORTED: "unsupported address",
    KIND_UNREACHABLE: "the host could not be resolved",
}

_SPLIT = re.compile(r"[\s,;]+")


@dataclass
class IntakeTarget:
    """One site the queue will actually visit."""
    raw: str
    url: str                    # canonical entry URL
    domain: str                 # canonical identity used for dedup, History and evidence
    pinned: bool = True         # named by the operator, so triage may score but not silently drop

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class IntakeRejection:
    value: str
    kind: str
    reason: str                 # operator-facing
    detail: str = ""            # the validator's own words, kept for diagnostics

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class IntakeDuplicate:
    value: str
    domain: str
    duplicate_of: str           # the raw line already accepted for this domain
    already_analyzed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class IntakeResult:
    targets: List[IntakeTarget] = field(default_factory=list)
    duplicates: List[IntakeDuplicate] = field(default_factory=list)
    rejected: List[IntakeRejection] = field(default_factory=list)
    lines_read: int = 0

    def counts(self) -> Dict[str, int]:
        """The four numbers the operator is shown before pressing Start.

        ``unique_sites`` is deliberately separate from ``lines_read``: a file with ten rows for one
        company is one site, and reporting ten would promise work that will not happen.
        """
        return {
            "lines_read": self.lines_read,
            "unique_sites": len(self.targets),
            "duplicates": len(self.duplicates),
            "rejected": len(self.rejected),
            "already_analyzed": sum(1 for d in self.duplicates if d.already_analyzed),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counts": self.counts(),
            "targets": [t.to_dict() for t in self.targets],
            "duplicates": [d.to_dict() for d in self.duplicates],
            "rejected": [r.to_dict() for r in self.rejected],
        }

    def seeds(self) -> List[str]:
        return [t.url for t in self.targets]


def _classify(reason: str) -> str:
    low = (reason or "").lower()
    for kind, needles in _REASON_KINDS:
        if any(n in low for n in needles):
            return kind
    return KIND_MALFORMED


def _structurally_invalid(url: str) -> bool:
    """Is this not an address at all, before anyone asks DNS about it?

    ``0.1`` is the case from the acceptance file. Left to the resolver it comes back as "host does
    not resolve", which is both slower and the wrong story: the operator did not type a site that
    happens to be down, they typed something that is not a website address. A host with no dot, or
    one made only of digits and dots that is not a valid IPv4, is refused here on shape alone.
    """
    import ipaddress

    host = urlsplit(url).hostname or ""
    if not host:
        return True
    # A real address that simply is not public — localhost, a private IP — is NOT malformed. The
    # safety validator names it precisely, and its wording is the one the operator should read.
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    if "." not in host:
        return True
    if all(label.isdigit() for label in host.split(".") if label):
        return True                     # digits and dots, but not a valid IP: not an address
    return False


def canonical_entry_url(raw: str) -> str:
    """The URL Scout will actually open for a target: scheme normalised, tracking stripped.

    The path is kept — an operator who pasted a pricing page meant that page — but campaign tracking
    is removed so the same page cannot enter the queue twice under two names.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    query = "&".join(
        piece for piece in parts.query.split("&")
        if piece and not _is_tracking(piece.split("=", 1)[0].lower()))
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def _is_tracking(key: str) -> bool:
    return key in _TRACKING_KEYS or any(key.startswith(p) for p in _TRACKING_PREFIXES)


def split_lines(text: str) -> List[str]:
    """Split pasted text into candidate values. Commas and whitespace both separate."""
    return [piece for piece in _SPLIT.split(text or "") if piece.strip()]


def parse_targets(values: Iterable[str], *, policy: Optional[UrlPolicy] = None,
                  resolver: Optional[Resolver] = None,
                  known_domains: FrozenSet[str] = frozenset(),
                  pinned: bool = True) -> IntakeResult:
    """Turn raw operator input into targets, duplicates and explained rejections.

    ``known_domains`` are canonical domains already present in history: they are reported as
    duplicates rather than refused, because re-scanning a site is legitimate — what must not happen
    is a SECOND current row appearing for it.
    """
    result = IntakeResult()
    seen: Dict[str, str] = {}
    for raw in values:
        value = (raw or "").strip()
        if not value:
            continue
        result.lines_read += 1
        url = canonical_entry_url(value)
        if _structurally_invalid(url):
            result.rejected.append(IntakeRejection(
                value=value, kind=KIND_MALFORMED, reason=_HUMAN_REASON[KIND_MALFORMED],
                detail="not a hostname"))
            continue
        verdict = check_url(url, policy=policy, resolver=resolver)
        if not verdict.eligible:
            kind = _classify(verdict.reason)
            result.rejected.append(IntakeRejection(
                value=value, kind=kind, reason=_HUMAN_REASON[kind], detail=verdict.reason))
            continue
        domain = canonical_domain(url)
        if not domain:
            result.rejected.append(IntakeRejection(
                value=value, kind=KIND_MALFORMED, reason=_HUMAN_REASON[KIND_MALFORMED],
                detail="no canonical domain"))
            continue
        if domain in seen:
            result.duplicates.append(IntakeDuplicate(
                value=value, domain=domain, duplicate_of=seen[domain]))
            continue
        seen[domain] = value
        if domain in known_domains:
            result.duplicates.append(IntakeDuplicate(
                value=value, domain=domain, duplicate_of=domain, already_analyzed=True))
        result.targets.append(IntakeTarget(raw=value, url=url, domain=domain, pinned=pinned))
    return result


def parse_text(text: str, **kwargs: Any) -> IntakeResult:
    """Parse a pasted block of URLs."""
    return parse_targets(split_lines(text), **kwargs)


def parse_rows(rows: Sequence[Sequence[Any]], **kwargs: Any) -> IntakeResult:
    """Parse spreadsheet rows: the first cell that looks like an address wins.

    A curated list carries product names, scores and notes beside the URL; picking the first
    address-like cell keeps the same intake for a bare list and a rich one, with no per-file mode.
    """
    values: List[str] = []
    for row in rows or []:
        cells = [str(cell or "").strip() for cell in (row or [])]
        if not any(cells):
            continue                        # a blank spacer row is not something to report
        picked = next((c for c in cells if "://" in c or "." in c.split("/")[0]), "")
        # A non-empty row with no address at all is still reported — usually the header, sometimes a
        # note the operator expected to be scanned. Silently dropping it would make the file look
        # fully understood when part of it was ignored.
        values.append(picked or cells[0])
    return parse_targets(values, **kwargs)
