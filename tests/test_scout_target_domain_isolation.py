"""Scout — P1 Target-detail MUST be domain-scoped for multi-target manual/imported runs.

A single manual / imported (curated-list) run may analyze many domains. Each analyzed domain
registers the SAME run_id as its History campaign. Before this fix, ``CampaignService.target_detail``
resolved that shared run and then (a) aggregated verified findings across the WHOLE run
(``load_verified_findings``) and (b) read contacts / network / media from ``prospects.keys()[:1]`` —
the FIRST prospect. So ``/scout/target?domain=A`` could surface findings, screenshots, network
evidence or a reproduction video that actually belong to domains B–J from the same batch — a
client-evidence integrity break.

These deterministic regressions pin true per-domain isolation: the exact prospect is resolved by
canonical domain inside the selected run store, ONLY that prospect's artifacts are loaded, a domain
with no matching prospect fails honestly (``prospect_not_found``) instead of borrowing another
prospect, History registration stays idempotent, and the XLSX golden path opens the correct, isolated
Target card for every launched domain — all with no Tavily/discovery calls.
"""
from __future__ import annotations

import io
import urllib.error
import urllib.request

from core.scout.backends import PageObservation
from core.scout.campaign_service import CampaignService
from core.scout.config import ScoutRunConfig
from core.scout.curated_import import parse_curated_list
from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.discovery.tavily_provider import TavilyDiscoveryProvider
from core.scout.findings import ScoutFinding
from core.scout.service import ScoutService
from core.scout.store import RunStore


# -- fixtures: a real multi-target run with per-domain-distinct artifacts ---------------------------

_RUN = "batch-run-1"
_PROSPECTS = {"01-alpha": "alpha.example", "02-beta": "beta.example"}


def _finding(domain: str) -> dict:
    return ScoutFinding(signature="flow_entry_broken", category="business_flow",
                        check_family="business_flow", severity="high", confidence="high",
                        title=f"{domain}: primary flow entry is broken",
                        actual=f"Flow entry link failed: https://{domain}/checkout").to_dict()


def _seed_prospect(store: RunStore, pid: str, domain: str) -> None:
    store.save_prospect_artifact(pid, "findings.json",
                                 {"verified": [_finding(domain)], "rejected": []})
    store.save_prospect_artifact(pid, "observation.json", {
        "status": 200, "final_url": f"https://{domain}/",
        "console_errors": [f"{domain}-console-error"],
        "failed_resources": [f"https://{domain}/missing.png"],
        "blocked_requests": [f"https://{domain}/blocked.js"]})
    store.save_prospect_artifact(pid, "reproduction.json", {
        "signature": "flow_entry_broken", "reproduced": True,
        "reproduction_status": "reproduced", "start_url": f"https://{domain}/",
        "action_url": f"https://{domain}/checkout", "video_ref": "reproduction.webm"})
    pdir = store.prospect_dir(pid)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "shot.png").write_bytes(b"PNG-" + domain.encode())
    (pdir / "reproduction.webm").write_bytes(b"WEBM-" + domain.encode())


def _build_multi_target_run(out: str) -> CampaignService:
    """One completed run analyzing two distinct domains, each with its own findings / observation /
    reproduction / media, registered in History the way a real manual/imported run is."""
    store = RunStore(out, _RUN)
    state = {"status": "COMPLETED", "prospects": {
        pid: {"status": "DONE", "url": f"https://{dom}/"} for pid, dom in _PROSPECTS.items()}}
    store.save_state(state)
    for pid, dom in _PROSPECTS.items():
        _seed_prospect(store, pid, dom)
    ScoutService(out)._register_analyzed_run(store, state)   # realistic History registration
    return CampaignService(out)


# -- isolation: each domain's card carries ONLY its own artifacts -----------------------------------


def test_alpha_card_contains_only_alpha_artifacts(tmp_path, monkeypatch):
    _no_tavily(monkeypatch)
    cs = _build_multi_target_run(str(tmp_path))
    da = cs.target_detail("alpha.example")

    titles = {f["title"] for f in da["findings"]}
    assert titles == {"alpha.example: primary flow entry is broken"}     # never beta's finding
    assert da.get("prospect_id") == "01-alpha" and da.get("evidence_status") == "ok"
    assert da["network"]["console_errors"] == ["alpha.example-console-error"]
    assert da["network"]["failed_resources"] == ["https://alpha.example/missing.png"]
    assert da["media"] and all(m.startswith("prospects/01-alpha/") for m in da["media"])
    assert not any("02-beta" in m for m in da["media"])                  # beta's media never leaks
    assert da.get("reproduction", {}).get("action_url") == "https://alpha.example/checkout"


def test_beta_card_contains_only_beta_artifacts(tmp_path, monkeypatch):
    _no_tavily(monkeypatch)
    cs = _build_multi_target_run(str(tmp_path))
    db = cs.target_detail("beta.example")

    titles = {f["title"] for f in db["findings"]}
    assert titles == {"beta.example: primary flow entry is broken"}      # never alpha's finding
    assert db.get("prospect_id") == "02-beta" and db.get("evidence_status") == "ok"
    assert db["network"]["console_errors"] == ["beta.example-console-error"]
    assert db["media"] and all(m.startswith("prospects/02-beta/") for m in db["media"])
    assert not any("01-alpha" in m for m in db["media"])                 # alpha's media never leaks
    assert db.get("reproduction", {}).get("action_url") == "https://beta.example/checkout"


def test_domain_with_no_matching_prospect_fails_honestly(tmp_path, monkeypatch):
    _no_tavily(monkeypatch)
    cs = _build_multi_target_run(str(tmp_path))
    # gamma points at the same run (drift) but the run has NO gamma prospect.
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis(
        "gamma.example", status=ANALYZED, campaign_id=_RUN)
    dg = cs.target_detail("gamma.example")

    assert dg.get("evidence_status") == "prospect_not_found"
    assert dg.get("prospect_id") in (None, "")
    assert dg["findings"] == [] and dg["media"] == []                    # never borrows another prospect
    assert dg.get("reproduction") in (None, {})
    assert dg["network"] == {}


def test_history_registration_of_the_run_is_idempotent(tmp_path, monkeypatch):
    _no_tavily(monkeypatch)
    _build_multi_target_run(str(tmp_path))
    store = RunStore(str(tmp_path), _RUN)
    ScoutService(str(tmp_path))._register_analyzed_run(store, store.load_state())   # replay
    for dom in _PROSPECTS.values():
        rows = [e for e in AnalyzedSiteRegistry(str(tmp_path)).all() if e.domain == dom]
        assert len(rows) == 1                                            # no duplicate History rows


# -- XLSX golden path: a curated batch opens the correct isolated card per launched domain ----------


class _PerDomainBackend:
    """No-network backend: each seed reaches P_DONE so its domain is registered and resolvable."""
    name = "static"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                               title="T", meta_description="d", html_bytes=1000,
                               headings=[{"level": 1, "text": "h"}], landmarks={"main": 1},
                               headers={"content-type": "text/html", "cache-control": "max-age=60"})


def _xlsx_bytes(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_xlsx_batch_opens_the_correct_isolated_card_per_domain(tmp_path, monkeypatch):
    _no_tavily(monkeypatch)
    rows = [["URL", "Recommended action", "Product"],
            ["alpha-shop.example", "Scout now", "A"],
            ["beta-shop.example", "Scout now", "B"]]
    res = parse_curated_list(_xlsx_bytes(rows), "curated.xlsx")
    selected = [r.seed_url for r in res.rows if r.preselect]
    assert len(selected) == 2

    svc = ScoutService(str(tmp_path))
    svc.start(ScoutRunConfig(campaign_name="curated", seeds=selected, browser_mode="static",
                             resolve_dns=False, output_dir=str(tmp_path)), backend=_PerDomainBackend())
    svc.join(timeout=60)

    cs = CampaignService(str(tmp_path))
    hist = {r["domain"] for r in cs.history()}
    assert {"alpha-shop.example", "beta-shop.example"} <= hist

    da = cs.target_detail("alpha-shop.example")
    db = cs.target_detail("beta-shop.example")
    assert da.get("evidence_status") == "ok" and db.get("evidence_status") == "ok"
    # each card binds to its OWN prospect in the shared run — never the same one
    assert da.get("prospect_id") and db.get("prospect_id")
    assert da.get("prospect_id") != db.get("prospect_id")
    assert da.get("scout_run") == db.get("scout_run")                    # same run, different prospect


# -- UI regression: the Target PAGE is isolated and fails honestly over real HTTP -----------------


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_target_page_is_domain_isolated_and_fails_honestly(tmp_path, monkeypatch):
    _no_tavily(monkeypatch)
    out = str(tmp_path)
    _build_multi_target_run(out)
    # A ghost domain points at the same shared run but has no prospect of its own.
    AnalyzedSiteRegistry(out).record_analysis("ghost.example", status=ANALYZED, campaign_id=_RUN)

    server, url = start_dashboard(ScoutService(out), operator_home=True)
    try:
        s_alpha, alpha_html = _get(url + "/scout/target?domain=alpha.example")
        s_ghost, ghost_html = _get(url + "/scout/target?domain=ghost.example")
    finally:
        server.shutdown()

    assert s_alpha == 200 and s_ghost == 200
    # alpha's page shows alpha's finding and never beta's; no honest-unavailable banner.
    assert "alpha.example: primary flow entry is broken" in alpha_html
    assert "beta.example: primary flow entry is broken" not in alpha_html
    assert "could not be bound to its own analyzed page" not in alpha_html
    # ghost's page shows the honest banner and NONE of alpha's/beta's evidence.
    assert "could not be bound to its own analyzed page" in ghost_html
    assert "alpha.example: primary flow entry is broken" not in ghost_html
    assert "beta.example: primary flow entry is broken" not in ghost_html


# -- guard: none of the above may touch Tavily / discovery -----------------------------------------


def _no_tavily(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("Tavily discovery must never be constructed on the manual/target path")
    monkeypatch.setattr(TavilyDiscoveryProvider, "__init__", _boom)
