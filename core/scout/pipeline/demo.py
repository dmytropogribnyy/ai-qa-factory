"""Bundled deterministic complete pre-send demo (Final Phase I).

Runs the full pipeline (deep QA -> findings -> evidence -> memory -> fingerprint -> contacts ->
governance -> offer -> disclosure -> draft -> review) against bundled local fixtures, with no
external network, no browser, and nothing sent. Used by `scout presend-demo` and the dashboard.
"""
from __future__ import annotations

import itertools
from typing import Any, Callable, Dict, List, Optional

from core.scout.demo_site import serve_demo_site
from core.scout.discovery.fixtures import HostMappedStaticBackend
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository
from core.scout.outreach.contacts import inferred_contact, public_contact
from core.scout.pipeline.presend import PreSendPipeline
from core.scout.store import RunStore
from core.scout.url_safety import UrlPolicy

_NOW = "2026-07-17T11:00:00+00:00"


def _candidates(hostport: str) -> List[Dict[str, Any]]:
    return [
        {"candidate_id": "c1", "url": "http://acme.example/accessibility/index.html",
         "registrable_domain": "acme.example", "company_name": "Acme",
         "hints": {"business_type_hint": "agency"}},
        {"candidate_id": "c2", "url": "http://shopmart.example/seo/index.html",
         "registrable_domain": "shopmart.example", "company_name": "ShopMart",
         "hints": {"business_type_hint": "ecommerce"}},
        {"candidate_id": "c3", "url": "http://noout.example/mobile/index.html",
         "registrable_domain": "noout.example", "company_name": "NoOut",
         "suppression_status": "NO_OUTREACH", "hints": {"business_type_hint": "agency"}},
    ]


def _contact_source(cand: Dict[str, Any]) -> List[Any]:
    dom = cand["registrable_domain"]
    return [
        public_contact(f"co-{dom}", dom, "email", f"hello@{dom}", evidence_ref="ev-1",
                       observed_at=_NOW, verify=True, suppression_check_ref="supp-1"),
        public_contact(f"co-{dom}", dom, "email", f"jane@{dom}", evidence_ref="ev-2",
                       observed_at=_NOW, data_subject="named_person", verify=True,
                       suppression_check_ref="supp-1"),
        inferred_contact(f"co-{dom}", dom, "email", f"guess@{dom}", observed_at=_NOW),
    ]


def run_presend_demo(output_dir: str, *, campaign_id: str = "campaign-presend-demo",
                     clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    counter = itertools.count()
    clk = clock or (lambda: f"2026-07-17T11:00:{next(counter):02d}+00:00")
    store = RunStore(output_dir, campaign_id)
    store.reset()                                  # deterministic re-run
    db = MemoryDB(str(store.root / "memory.db"))
    repo = MemoryRepository(db)
    with serve_discovery_context() as (backend, hostport):
        pipe = PreSendPipeline(store, repo, campaign_id=campaign_id,
                               policy=UrlPolicy(resolve_dns=False), backend=backend, clock=clk,
                               contact_source=_contact_source)
        summary = pipe.run(_candidates(hostport))
    summary["memory_db"] = str(store.root / "memory.db")
    summary["companies_in_memory"] = repo.count("companies")
    summary["drafts_in_memory"] = repo.count("drafts")
    db.close()
    return summary


class serve_discovery_context:  # noqa: N801 - context-manager helper
    """Serve the demo site and yield a host-mapped backend + host:port."""

    def __enter__(self):
        self._cm = serve_demo_site()
        _base, hostport = self._cm.__enter__()
        host_map = {"acme.example": hostport, "shopmart.example": hostport,
                    "noout.example": hostport}
        backend = HostMappedStaticBackend(UrlPolicy(resolve_dns=False), host_map)
        return backend, hostport

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)
