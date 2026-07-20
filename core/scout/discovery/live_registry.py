"""Wiring for live (Tavily) discovery + cross-campaign registry reconciliation (v3.3).

Builds a ProviderRegistry containing the single real Tavily provider (fail-closed when the key is
absent or live approval is missing), and reconciles a run's candidates with the global analyzed-site
registry so the same company discovered again across campaigns/restarts is recorded once and skipped
("Already analyzed") instead of re-analyzed. No fixture fallback is ever used in live mode.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.discovery.providers import DiscoveryError, ProviderMetadata, ProviderRegistry
from core.scout.discovery.tavily_provider import (
    TavilyBudget,
    TavilyDiscoveryProvider,
)
from core.scout.discovery.tavily_secret import key_present, key_provider


def build_tavily_registry(*, live_approved: bool, max_results: int = 10, max_requests: int = 8,
                          cost_ceiling_usd: float = 0.0, cost_per_request: float = 0.0,
                          include_domains: Optional[List[str]] = None,
                          exclude_domains: Optional[List[str]] = None,
                          keywords: Optional[List[str]] = None,
                          key_provider_fn: Optional[Callable[[], Optional[str]]] = None,
                          transport=None) -> Tuple[TavilyDiscoveryProvider, ProviderRegistry]:
    """Construct the Tavily provider + a registry. Fails closed if live approval is missing or (for a
    real run) no credential is configured."""
    if not live_approved:
        raise DiscoveryError("live discovery not approved (pass --approve-live-discovery)")
    kp = key_provider_fn or key_provider()
    if transport is None and not key_present():
        raise DiscoveryError(
            "TAVILY_API_KEY is not configured (run `python tools/tavily_setup.py`). No fixture "
            "fallback is used for a live run.")
    meta = ProviderMetadata(
        provider_id="tavily", provider_type="api", display_name="Tavily Search",
        trust_status="trusted", enabled=True, source_category="discovered_public",
        terms_review_status="reviewed_approved", auth_ref="TAVILY_API_KEY",
        public_or_licensed="licensed", version="1.0.0", max_results_per_request=20,
        data_freshness="live")
    provider = TavilyDiscoveryProvider(
        meta, key_provider=kp, transport=transport,
        budget=TavilyBudget(max_requests=max_requests, max_results=max_results,
                            max_credits=cost_ceiling_usd, cost_per_request=cost_per_request),
        include_domains=include_domains, exclude_domains=exclude_domains, keywords=keywords,
        live_approved=live_approved)
    registry = ProviderRegistry()
    registry.register(provider)
    return provider, registry


def reconcile_with_registry(state: Dict[str, Any], *, campaign_id: str, provider_id: str,
                            output_dir: str) -> Dict[str, Any]:
    """Record a run's unique candidate domains in the global analyzed-site registry and mark those
    already analyzed as skipped. Returns a bounded, redacted reconciliation summary (no secrets)."""
    reg = AnalyzedSiteRegistry(output_dir)
    newly, skipped_already, in_progress = [], [], []
    for rec in state.get("candidates", []):
        url = rec.get("normalized_url") or rec.get("website") or ""
        if not url:
            continue
        try:
            _, is_new = reg.observe(url, campaign_id=campaign_id, provider=provider_id)
        except ValueError:
            continue
        do, reason = reg.should_analyze(url)
        entry = reg.get(url)
        dom = entry.domain if entry else url
        if not do and reason == "Already analyzed":
            skipped_already.append(dom)
        elif not do and "in progress" in reason.lower():
            in_progress.append(dom)
        elif is_new:
            newly.append(dom)
    return {"campaign_id": campaign_id, "provider": provider_id,
            "registry_total": reg.counts()["total"], "newly_discovered": sorted(set(newly)),
            "skipped_already_analyzed": sorted(set(skipped_already)),
            "in_progress_elsewhere": sorted(set(in_progress))}
