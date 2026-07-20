"""Domain intelligence for live discovery (v3.3) — canonical domains + target classification.

Bounded, dependency-light, public-suffix-AWARE (a curated common-suffix list, not the full Mozilla
PSL) so US/DE/EU domains dedup correctly, and shared-hosting platforms are handled so unrelated
tenants (``a.myshopify.com`` vs ``b.myshopify.com``) are never merged into one company. Also
classifies a result URL as a company site vs a directory / social network / job board / aggregator so
company-owned domains are preferred over duplicate-content pages. Reuses the Scout hostname
normalizer; adds only the multi-label-suffix + shared-hosting + aggregator knowledge.
"""
from __future__ import annotations

from typing import Tuple
from urllib.parse import urlsplit

from core.schemas.prospect_identity import normalize_hostname

# Common multi-label public suffixes (curated; not the full PSL). Enough for US/DE/UK/EU/APAC dedup.
_MULTI_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "ltd.uk", "plc.uk",
    "com.au", "net.au", "org.au", "co.nz", "co.jp", "or.jp", "ne.jp", "co.in", "co.kr",
    "com.br", "com.mx", "com.ar", "co.za", "com.sg", "com.tr", "com.cn", "com.hk", "com.tw",
    "co.il", "com.ua", "com.pl", "co.at",
})
# Platforms where the FIRST subdomain label is the tenant identity (never merge tenants).
_SHARED_HOSTING = frozenset({
    "herokuapp.com", "github.io", "gitlab.io", "vercel.app", "netlify.app", "web.app",
    "firebaseapp.com", "pages.dev", "workers.dev", "azurewebsites.net", "wixsite.com",
    "myshopify.com", "wordpress.com", "blogspot.com", "notion.site", "webflow.io",
    "onrender.com", "fly.dev", "surge.sh", "gitbook.io", "square.site", "weebly.com",
})
# Directories / social networks / job boards / review + content aggregators — NOT company-owned.
_AGGREGATORS = frozenset({
    # social
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "tiktok.com", "pinterest.com", "reddit.com", "threads.net", "mastodon.social",
    # directories / review / data
    "crunchbase.com", "g2.com", "capterra.com", "getapp.com", "softwareadvice.com",
    "trustpilot.com", "yelp.com", "glassdoor.com", "clutch.co", "goodfirms.co", "producthunt.com",
    "wikipedia.org", "bloomberg.com", "owler.com", "zoominfo.com", "apollo.io", "similarweb.com",
    "trustradius.com", "sourceforge.net", "slintel.com", "6sense.com",
    # job boards
    "indeed.com", "monster.com", "ziprecruiter.com", "dice.com", "lever.co", "greenhouse.io",
    "workable.com", "smartrecruiters.com", "stepstone.de", "xing.com", "kununu.com",
    # content / dev aggregators (not the company's own site)
    "medium.com", "substack.com", "dev.to", "hashnode.com", "github.com", "gitlab.com",
    "stackoverflow.com", "quora.com", "wordpress.org",
})
_JOB_BOARDS = frozenset({"indeed.com", "monster.com", "ziprecruiter.com", "dice.com", "lever.co",
                         "greenhouse.io", "workable.com", "smartrecruiters.com", "stepstone.de",
                         "kununu.com"})
_SOCIAL = frozenset({"linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
                     "youtube.com", "tiktok.com", "pinterest.com", "reddit.com", "threads.net",
                     "xing.com"})

COMPANY, AGGREGATOR, SOCIAL, JOB_BOARD, INVALID = (
    "company", "aggregator", "social", "job_board", "invalid")


def _registrable(host: str) -> str:
    """Public-suffix-aware registrable domain (curated list). Shared-hosting platforms keep the
    tenant subdomain so distinct tenants are not merged."""
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = [x for x in host.split(".") if x]
    if len(labels) < 2:
        return host
    last2 = ".".join(labels[-2:])
    last3 = ".".join(labels[-3:]) if len(labels) >= 3 else ""
    # A two-label public suffix (e.g. co.uk) -> registrable is the last 3 labels.
    if last2 in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        base = ".".join(labels[-3:])
    else:
        base = last2
    # Shared hosting: the tenant is the label in front of the platform suffix -> keep it.
    if base in _SHARED_HOSTING and len(labels) >= 3:
        return ".".join(labels[-3:])
    if last3 in _SHARED_HOSTING and len(labels) >= 4:  # e.g. tenant.pages.dev style depth
        return ".".join(labels[-4:])
    return base


def canonical_domain(url: str) -> str:
    """Return the canonical identity domain for a URL (scheme/case/www/fragment/params ignored).
    Empty string if no host can be extracted. Uses the Scout hostname validator first."""
    if not url:
        return ""
    raw = url.strip()
    if "://" not in raw:
        raw = "http://" + raw
    host = urlsplit(raw).hostname or ""
    try:
        host = normalize_hostname(host) or host
    except Exception:  # noqa: BLE001 - fall back to the raw host; classification still applies
        pass
    return _registrable(host)


def classify_target(url: str) -> Tuple[str, str, str]:
    """Classify a result URL. Returns (kind, canonical_domain, reason).

    kind in {company, aggregator, social, job_board, invalid}. Company-owned domains are preferred;
    directories/social/job boards/aggregators are rejected as not company-owned (duplicate content).
    """
    dom = canonical_domain(url)
    if not dom or "." not in dom:
        return INVALID, dom, "no valid public host"
    if dom in _SOCIAL:
        return SOCIAL, dom, f"social network ({dom})"
    if dom in _JOB_BOARDS:
        return JOB_BOARD, dom, f"job board ({dom})"
    if dom in _AGGREGATORS:
        return AGGREGATOR, dom, f"directory/aggregator ({dom})"
    return COMPANY, dom, "company-owned domain"


def is_company_domain(url: str) -> bool:
    return classify_target(url)[0] == COMPANY
