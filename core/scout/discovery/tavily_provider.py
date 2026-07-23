"""Tavily live discovery provider (v3.3) — the ONE real seedless discovery connector.

Implements the existing ``DiscoveryProvider`` protocol using the Tavily Search API. Turns a campaign
matrix cell (country / language / industry / business type / keywords / include+exclude domains) into
one bounded Tavily query, and returns company-website ``DiscoveryCandidate``s. It is observe-only:
GET-style search of public pages, no login/forms/CAPTCHA/scanning, no outreach.

Safety + fail-closed:
- the API key is fetched lazily via an injected ``key_provider`` and passed ONLY in the request
  Authorization header — never printed, logged, serialized, returned, or placed on a command line;
- fails closed when the key is absent, authentication fails (401), live approval is missing, budgets
  are exhausted, or the response is malformed;
- bounded timeout + retry/backoff for transient failures and HTTP 429;
- NEVER falls back to fixtures while claiming a live run;
- strict request / result / (optional) credit budgets;
- company-owned domains are preferred; directories, social networks, job boards, and aggregators are
  rejected with an explicit reason.

The HTTP transport is INJECTED so tests are deterministic with mocked responses and no network.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.scout.discovery.domain_intel import COMPANY, canonical_domain, classify_target
from core.scout.discovery.providers import (
    DiscoveryCandidate,
    DiscoveryError,
    ProviderMetadata,
)

TAVILY_ENDPOINT = "https://api.tavily.com/search"
_MAX_RESULTS_CAP = 20                    # hard per-request cap regardless of caller/limit
_QUERY_MAX_LEN = 380
# Tavily's `country` param (topic=general) accepts a country name; map ISO-ish inputs.
_COUNTRY_NAMES = {
    "us": "united states", "usa": "united states", "united states": "united states",
    "de": "germany", "ger": "germany", "germany": "germany", "gb": "united kingdom",
    "uk": "united kingdom", "fr": "france", "es": "spain", "it": "italy", "nl": "netherlands",
    "ca": "canada", "au": "australia",
}


class TavilyAuthError(DiscoveryError):
    """Authentication failed (e.g. HTTP 401) — fail closed, never retried into success."""


class TavilyUsageLimit(DiscoveryError):
    """Account credit exhaustion — HTTP 432 (plan limit) / 433 (PAYGO limit). NOT transient: retrying
    cannot help, so it is distinct from a 429 rate-limit and from a generic HTTP error. The operator
    must upgrade the plan / raise the PAYGO limit; existing results are preserved."""


class TavilyTransient(Exception):
    """A transient failure (HTTP 429/5xx/timeout) eligible for bounded retry/backoff. Distinct from a
    432/433 credit exhaustion, which is permanent until the operator raises the limit."""


def _raise_for_tavily_status(status_code: int) -> None:
    """Map a Tavily HTTP status to the right exception (testable without the network). 432/433 are
    honest, actionable credit-exhaustion errors — never lumped into a generic HTTP failure."""
    if status_code in (401, 403):
        raise TavilyAuthError("tavily authentication failed")
    if status_code == 429 or 500 <= status_code < 600:
        raise TavilyTransient(f"tavily transient http {status_code}")
    if status_code == 432:
        raise TavilyUsageLimit("tavily plan credit limit reached (HTTP 432) — upgrade your plan or "
                               "wait for the monthly reset; existing results are preserved")
    if status_code == 433:
        raise TavilyUsageLimit("tavily pay-as-you-go limit reached (HTTP 433) — raise your PAYGO "
                               "limit to continue; existing results are preserved")
    if status_code != 200:
        raise DiscoveryError(f"tavily http {status_code}")


@dataclass
class TavilyBudget:
    """Strict request / result / credit ceilings. Fails closed when any is exhausted."""
    max_requests: int = 8
    max_results: int = 10
    max_credits: float = 0.0                 # 0 => credit ceiling disabled (request/result still cap)
    cost_per_request: float = 0.0
    requests_made: int = 0
    results_returned: int = 0
    credits_used: float = 0.0

    def remaining_results(self) -> int:
        return max(0, self.max_results - self.results_returned)

    def check_can_request(self) -> None:
        if self.requests_made >= self.max_requests:
            raise DiscoveryError("tavily request budget exhausted")
        if self.remaining_results() <= 0:
            raise DiscoveryError("tavily result budget exhausted")
        if self.max_credits and self.credits_used + self.cost_per_request > self.max_credits + 1e-9:
            raise DiscoveryError("tavily credit ceiling reached")

    def record_request(self, n_results: int) -> None:
        self.requests_made += 1
        self.results_returned += max(0, int(n_results))
        self.credits_used += self.cost_per_request

    def to_dict(self) -> Dict[str, Any]:
        return {"max_requests": self.max_requests, "max_results": self.max_results,
                "max_credits": self.max_credits, "requests_made": self.requests_made,
                "results_returned": self.results_returned, "credits_used": round(self.credits_used, 4)}


@dataclass
class TavilyRequestConfig:
    topic: str = "general"
    search_depth: str = "basic"
    include_answer: bool = False
    include_raw_content: bool = False
    timeout_s: float = 12.0
    max_retries: int = 3
    backoff_base_s: float = 0.5
    backoff_cap_s: float = 4.0


def build_query(cell: Dict[str, Any]) -> str:
    """Build ONE bounded Tavily query from a matrix cell. Company-website oriented, not a directory
    search. Country is passed as the Tavily `country` param (not baked into the text)."""
    parts: List[str] = []
    industry = str(cell.get("industry") or "").strip()
    btype = str(cell.get("business_type") or "").strip()
    if industry:
        parts.append(f'"{industry}"')
    if btype and btype.lower() not in industry.lower():
        parts.append(btype)
    kws = cell.get("keywords") or []
    if isinstance(kws, str):
        kws = [kws]
    for kw in list(kws)[:4]:
        kw = str(kw).strip()
        if kw:
            parts.append(kw)
    parts.append("company official website")
    q = " ".join(parts).strip()
    return q[:_QUERY_MAX_LEN]


def tavily_country(cell: Dict[str, Any]) -> str:
    c = str(cell.get("country") or "").strip().lower()
    return _COUNTRY_NAMES.get(c, c if len(c) > 2 else "")


def real_tavily_transport(config: TavilyRequestConfig) -> Callable[[Dict[str, Any], str], Dict[str, Any]]:
    """Return a transport that POSTs to Tavily with the key in the Authorization header ONLY.
    Raises TavilyAuthError on 401/403, TavilyTransient on 429/5xx/timeout, TavilyUsageLimit on
    432/433 (credit exhaustion — upgrade/raise PAYGO), DiscoveryError otherwise. The key is never
    logged; errors carry only the status class."""
    def _transport(body: Dict[str, Any], api_key: str) -> Dict[str, Any]:
        import requests  # local import; the deterministic core/tests never touch the network
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(TAVILY_ENDPOINT, json=body, headers=headers, timeout=config.timeout_s)
        except requests.Timeout as exc:
            raise TavilyTransient("tavily read timeout") from exc
        except requests.RequestException as exc:
            raise TavilyTransient(f"tavily transport error: {type(exc).__name__}") from exc
        _raise_for_tavily_status(resp.status_code)     # 401/403 auth · 429/5xx transient · 432/433 usage
        try:
            return resp.json()
        except ValueError as exc:
            raise DiscoveryError("tavily response was not valid JSON") from exc
    return _transport


class TavilyDiscoveryProvider:
    """A real, budget-enforced, fail-closed Tavily discovery provider (DiscoveryProvider protocol)."""

    def __init__(self, metadata: ProviderMetadata, *,
                 key_provider: Callable[[], Optional[str]],
                 transport: Optional[Callable[[Dict[str, Any], str], Dict[str, Any]]] = None,
                 budget: Optional[TavilyBudget] = None,
                 request_config: Optional[TavilyRequestConfig] = None,
                 include_domains: Optional[List[str]] = None,
                 exclude_domains: Optional[List[str]] = None,
                 keywords: Optional[List[str]] = None,
                 live_approved: bool = False,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.metadata = metadata
        self._key_provider = key_provider
        self._config = request_config or TavilyRequestConfig()
        self._transport = transport or real_tavily_transport(self._config)
        self.budget = budget or TavilyBudget()
        self._include_domains = [d.strip().lower() for d in (include_domains or []) if d.strip()]
        self._exclude_domains = [d.strip().lower() for d in (exclude_domains or []) if d.strip()]
        # Campaign-level keywords are not a matrix dimension, so they are merged into every query.
        self._keywords = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        self._live_approved = live_approved
        self._sleep = sleep
        self.rejections: List[Dict[str, str]] = []   # bounded, redacted rejection log

    # -- readiness (no secret; presence only) ------------------------------------------------------
    def readiness(self) -> Dict[str, Any]:
        configured = bool(self._safe_key())
        allowed, reason = self.metadata.can_execute(live_approved=self._live_approved)
        return {"provider_id": self.metadata.provider_id, "provider": "tavily", "network": True,
                "configured": configured, "live_approved": self._live_approved,
                "readiness": ("live_ready" if configured and allowed else
                              "adapter_ready" if allowed else "adapter_ready_not_configured"),
                "reason": reason, "budget": self.budget.to_dict()}

    def _safe_key(self) -> Optional[str]:
        try:
            k = self._key_provider()
            return k if (k and str(k).strip()) else None
        except Exception:  # noqa: BLE001 - a broken provider is "not configured", never a crash-leak
            return None

    # -- discovery ---------------------------------------------------------------------------------
    def discover(self, cell: Dict[str, Any], limit: int) -> List[DiscoveryCandidate]:
        allowed, reason = self.metadata.can_execute(live_approved=self._live_approved)
        if not allowed:
            raise DiscoveryError(f"tavily discovery not allowed: {reason}")
        key = self._safe_key()
        if not key:
            raise DiscoveryError("tavily discovery unavailable: no configured credential (fail closed)")
        self.budget.check_can_request()

        want = max(0, min(int(limit), self.budget.remaining_results(), _MAX_RESULTS_CAP))
        if want == 0:
            raise DiscoveryError("tavily result budget exhausted")
        cell = {**cell, "keywords": cell.get("keywords") or self._keywords}
        body: Dict[str, Any] = {
            "query": build_query(cell), "topic": self._config.topic,
            "search_depth": self._config.search_depth, "include_answer": self._config.include_answer,
            "include_raw_content": self._config.include_raw_content, "max_results": want}
        country = tavily_country(cell)
        if country:
            body["country"] = country
        if self._include_domains:
            body["include_domains"] = self._include_domains
        if self._exclude_domains:
            body["exclude_domains"] = self._exclude_domains

        data = self._call_with_retry(body, key)
        results = data.get("results")
        if not isinstance(results, list):
            raise DiscoveryError("tavily response malformed: missing 'results' list")
        self.budget.record_request(len(results))
        return self._to_candidates(results, cell, body["query"])

    def _call_with_retry(self, body: Dict[str, Any], key: str) -> Dict[str, Any]:
        attempt = 0
        while True:
            try:
                out = self._transport(body, key)
                if not isinstance(out, dict):
                    raise DiscoveryError("tavily response malformed: not a JSON object")
                return out
            except TavilyTransient as exc:
                attempt += 1
                if attempt > self._config.max_retries:
                    raise DiscoveryError(f"tavily transient failure after retries: {exc}") from None
                delay = min(self._config.backoff_cap_s,
                            self._config.backoff_base_s * (2 ** (attempt - 1)))
                self._sleep(delay)
            # TavilyAuthError / DiscoveryError propagate immediately (fail closed, never retried).

    def _to_candidates(self, results: List[Any], cell: Dict[str, Any], query: str
                       ) -> List[DiscoveryCandidate]:
        out: List[DiscoveryCandidate] = []
        seen: set = set()
        for item in results:
            if not isinstance(item, dict):
                self._reject("", "malformed result item")
                continue
            url = str(item.get("url") or "").strip()
            kind, domain, why = classify_target(url)
            if kind != COMPANY:
                self._reject(domain or url, why)
                continue
            if domain in seen:                          # in-provider dedup (cross-campaign is the registry)
                self._reject(domain, "duplicate domain within query")
                continue
            if domain in self._exclude_domains:
                self._reject(domain, "excluded domain")
                continue
            seen.add(domain)
            title = str(item.get("title") or "").strip()[:200]
            out.append(DiscoveryCandidate(
                provider_id=self.metadata.provider_id,
                raw_candidate_id=domain,
                source_url=url[:500],
                source_query=query,
                business_name=title,
                website=f"https://{domain}",
                country_hint=str(cell.get("country") or "")[:40],
                language_hint=str(cell.get("language") or "")[:40],
                industry_hint=str(cell.get("industry") or "")[:60],
                business_type_hint=str(cell.get("business_type") or "")[:60],
                confidence="low",
                raw_sample=str(item.get("content") or "")[:160]))
        return out

    def _reject(self, domain: str, reason: str) -> None:
        if len(self.rejections) < 100:
            self.rejections.append({"domain": canonical_domain(domain) or domain, "reason": reason})
