"""Discovery CLI commands (Phase 8.4).

Extends the `scout` command family coherently:
  campaign-demo  — run the bundled deterministic discovery -> Scout pipeline (no network/browser).
  campaign-plan  — build + validate the campaign, matrix, and budgets (dry-run planning artifacts).
  campaign-run   — run discovery over a file import (and optional approved live provider).
  providers      — print the provider registry readiness snapshot.

Everything is read-only: no contact discovery, outreach, form submission, or external side effect.
"""
from __future__ import annotations

import json
import sys
from typing import List, Optional

from core.scout.discovery.config import DiscoveryCampaignConfig, DiscoveryConfigError
from core.scout.discovery.engine import DiscoveryEngine
from core.scout.discovery.providers import (
    DiscoveryError,
    FileImportDiscoveryProvider,
    ProviderMetadata,
    ProviderRegistry,
)
from core.scout.store import RunStore


def _split(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def _build_config(args, provider_allowlist, **overrides) -> DiscoveryCampaignConfig:
    kwargs = dict(
        campaign_name=getattr(args, "campaign", None) or "discovery",
        provider_allowlist=provider_allowlist,
        countries=_split(getattr(args, "countries", "")),
        languages=_split(getattr(args, "languages", "")),
        industries=_split(getattr(args, "industries", "")),
        business_types=_split(getattr(args, "business_types", "")),
        keywords=_split(getattr(args, "keywords", "")),
        min_commercial_threshold=getattr(args, "min_commercial", 40),
        max_promoted=getattr(args, "max_promoted", 5),
        matrix_hard_max=getattr(args, "matrix_max", 500),
        per_provider_result_budget=getattr(args, "per_provider_budget", 50),
        cost_ceiling_usd=getattr(args, "cost_ceiling", 0.0),
        output_dir=getattr(args, "output", "outputs"),
        approve_live_discovery=getattr(args, "approve_live_discovery", False),
        campaign_id=getattr(args, "campaign_id", "") or "",
    )
    kwargs.update(overrides)
    return DiscoveryCampaignConfig(**kwargs)


def cmd_campaign_demo(args) -> int:
    from core.scout.discovery.fixtures import (
        HostMappedStaticBackend, build_demo_registry, build_host_map,
        demo_suppression_policies, serve_discovery_site)
    from core.scout.url_safety import UrlPolicy
    with serve_discovery_site() as (_base, hostport):
        backend = HostMappedStaticBackend(UrlPolicy(resolve_dns=False), build_host_map(hostport))
        try:
            cfg = _build_config(
                args, ["p_directory", "p_maplisting", "p_blocked", "p_real_api"],
                campaign_name="discovery-demo", campaign_id="campaign-discovery-demo",
                countries=["US"], languages=["en"], min_commercial_threshold=40, max_promoted=3,
                resolve_dns=False, allow_readonly_profiling_when_no_outreach=True)
            store = RunStore(cfg.output_dir, cfg.campaign_id)
            store.reset()
            engine = DiscoveryEngine(cfg, build_demo_registry(), store,
                                     suppression_policies=demo_suppression_policies(),
                                     profiler=backend, scout_backend=backend)
            state = engine.run()
        except (DiscoveryError, DiscoveryConfigError) as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    _print_state(state)
    return 0


def cmd_campaign_plan(args) -> int:
    provider_id, registry = _discovery_registry(args)
    if registry is None:
        return 1
    try:
        cfg = _build_config(args, [provider_id])
        engine = DiscoveryEngine(cfg, registry, RunStore(cfg.output_dir, cfg.campaign_id),
                                 sample=getattr(args, "sample", None))
        plan = engine.plan()
    except (DiscoveryError, DiscoveryConfigError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    matrix = plan["CAMPAIGN_MATRIX.json"]
    print(f"Campaign: {plan['campaign_id']}")
    print(f"Matrix full size: {matrix['full_size']}  planned provider calls: "
          f"{matrix['planned_provider_calls']}  sampled: {matrix['sampled']}")
    print(f"Budgets: {json.dumps(plan['PROVIDER_BUDGET.json'])}")
    print("(dry-run - no provider was called, nothing was fetched or promoted)")
    return 0


def _discovery_registry(args, required: bool = True):
    """Choose the discovery provider registry: live Tavily (`--live-provider tavily`) or file import.
    The live provider fails closed without approval/credential; no fixture fallback is used."""
    if getattr(args, "live_provider", "") == "tavily":
        from core.scout.discovery.live_registry import build_tavily_registry
        try:
            _, registry = build_tavily_registry(
                live_approved=getattr(args, "approve_live_discovery", False),
                max_results=getattr(args, "tavily_max_results", 10),
                max_requests=getattr(args, "tavily_max_requests", 8),
                cost_ceiling_usd=getattr(args, "cost_ceiling", 0.0),
                include_domains=_split(getattr(args, "include_domains", "")),
                exclude_domains=_split(getattr(args, "exclude_domains", "")),
                keywords=_split(getattr(args, "keywords", "")))
        except DiscoveryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return "", None
        return "tavily", registry
    return _file_provider(args, required=required)


def cmd_campaign_run(args) -> int:
    provider_id, registry = _discovery_registry(args)
    if registry is None:
        return 1
    from core.scout.discovery.run_lock import CampaignBusy, CampaignRunLock
    try:
        cfg = _build_config(args, [provider_id])
        store = RunStore(cfg.output_dir, cfg.campaign_id)
        # Overlap guard: never start a second run of the SAME campaign (e.g. a scheduled run firing
        # while a manual one is in progress). Fresh-process resume is preserved.
        with CampaignRunLock(cfg.output_dir, cfg.campaign_id):
            engine = DiscoveryEngine(cfg, registry, store, sample=getattr(args, "sample", None))
            state = engine.run()
    except CampaignBusy as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except (DiscoveryError, DiscoveryConfigError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    _print_state(state)
    # Cross-campaign registry: record unique domains + skip anything already analyzed (no re-analysis).
    from core.scout.discovery.live_registry import reconcile_with_registry
    recon = reconcile_with_registry(state, campaign_id=cfg.campaign_id, provider_id=provider_id,
                                    output_dir=cfg.output_dir)
    (store.root / "REGISTRY_RECONCILIATION.json").write_text(
        json.dumps(recon, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Global registry: total={recon['registry_total']}  new={len(recon['newly_discovered'])}  "
          f"already_analyzed_skipped={len(recon['skipped_already_analyzed'])}")
    return 0


def cmd_discovery_providers(args) -> int:
    provider_id, registry = _file_provider(args, required=False)
    if registry is None:
        registry = ProviderRegistry()
    print(json.dumps(registry.snapshot(), indent=2))
    return 0


def _file_provider(args, required: bool = True):
    """Build a registry with a single file-import provider from --import. Returns (id, registry)."""
    path = getattr(args, "import_file", None)
    if not path:
        if required:
            print("ERROR: --import <file.csv|json|ndjson|txt> is required", file=sys.stderr)
            return "", None
        return "", None
    registry = ProviderRegistry()
    meta = ProviderMetadata(provider_id="file_import", provider_type="file_import",
                            display_name="Local file import", trust_status="semi_trusted",
                            enabled=True, source_category="manual_seed",
                            terms_review_status="reviewed_approved", version="1.0.0")
    import os
    registry.register(FileImportDiscoveryProvider(meta, path, base_dir=os.getcwd()))
    return "file_import", registry


def _print_state(state) -> None:
    c = state.get("counts", {})
    b = state.get("budget", {})
    print(f"Campaign: {state.get('campaign_id')}  status={state.get('status')}")
    print(f"Candidates: {c.get('candidates', 0)}  unique={c.get('unique', 0)}  "
          f"duplicates={c.get('duplicates', 0)}  uncertain={c.get('uncertain_identity', 0)}")
    print(f"Suppressed: {c.get('suppressed', 0)} (NO_SCAN {c.get('no_scan', 0)})  "
          f"technical_ok={c.get('technical_ok', 0)}  commercial_eligible={c.get('commercial_eligible', 0)}")
    print(f"Promoted to Scout QA: {c.get('promoted', 0)}  held_for_review={c.get('held_for_review', 0)}")
    print(f"Budget used: provider_calls={b.get('provider_calls', 0)} results={b.get('results', 0)} "
          f"cost=${b.get('cost_usd', 0)}")
    print("No contact was collected; no outreach/form/account/order/payment occurred.")


def run_discovery_cli(args) -> int:
    return {
        "campaign-demo": cmd_campaign_demo,
        "campaign-plan": cmd_campaign_plan,
        "campaign-run": cmd_campaign_run,
        "providers": cmd_discovery_providers,
    }[args.action](args)
