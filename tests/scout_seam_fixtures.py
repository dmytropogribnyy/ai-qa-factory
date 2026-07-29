"""Seeded stand for the Scout detail seam inspection (spec 2026-07-26).

One run holding every state where the compact prospect state and findings.json can disagree, a
second run over the same domain with different numbers so run pinning is falsifiable, and an
archived run. No network, no discovery, no browser.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.discovery.tavily_provider import TavilyDiscoveryProvider
from core.scout.findings import ScoutFinding
from core.scout.operator_state import OperatorStateStore
from core.scout.service import ScoutService
from core.scout.store import RunStore

RUN_A = "seam-run-A"
RUN_B = "seam-run-B"
RUN_ARCHIVED = "seam-run-archived"


def _finding(domain: str, tag: str, severity: str, index: int) -> dict:
    # The index is what makes two same-severity findings two findings. Building the signature from
    # tag+severity alone gave the second "medium" the same identity as the first, so the canonical
    # split suppressed it as a duplicate and a stand advertising "3 defects" quietly held 2.
    return ScoutFinding(signature=f"{tag}_{severity}_{index}", category="seo", check_family="seo",
                        severity=severity, confidence="high",
                        title=f"{domain}: {tag} {index} ({severity})",
                        actual=f"observed on https://{domain}/").to_dict()


def _save_findings(store: RunStore, pid: str, domain: str, tag: str,
                   severities: list[str]) -> tuple[int, int]:
    from core.scout.actionable import actionable_set
    verified = [_finding(domain, tag, sev, i) for i, sev in enumerate(severities, 1)]
    store.save_prospect_artifact(pid, "findings.json", {"verified": verified, "rejected": []})
    store.save_prospect_artifact(pid, "observation.json",
                                 {"status": 200, "final_url": f"https://{domain}/"})
    # Counted the way the engine counts, so the stand cannot pass a seam the product would fail.
    canonical = actionable_set(verified)
    return canonical.total, canonical.confirmed_issue_count


def _build_primary_run(out: str) -> None:
    store = RunStore(out, RUN_A)
    prospects: dict[str, dict] = {}

    # alpha — DONE, 3 defects + 2 informational, coverage written.
    total, defects = _save_findings(store, "01-alpha", "alpha.example", "alpha",
                                    ["high", "medium", "medium", "info", "info"])
    prospects["01-alpha"] = {"status": "DONE", "url": "https://alpha.example/",
                             "verified_findings": total, "verified_defects": defects,
                             "coverage": "adaptive", "meaningful_pages_tested": 7,
                             "page_stop_reason": "no_new_meaningful_coverage"}

    # beta — MANUAL_ACTION_REQUIRED with a persisted challenge record.
    store.save_prospect_artifact("02-beta", "observation.json",
                                 {"status": 200, "final_url": "https://beta.example/",
                                  "backend": "playwright"})
    store.save_prospect_artifact("02-beta", "manual_action.json", {
        "reason": "captcha_detected", "stage": "post_landing_precheck",
        "stop_boundary": "stopped_before_interaction", "chromium_started": True,
        "landing_loaded": True, "analysis_complete": False,
        "recommended_action": "Solve the CAPTCHA yourself, then rescan."})
    prospects["02-beta"] = {"status": "MANUAL_ACTION_REQUIRED", "url": "https://beta.example/",
                            "reason": "captcha_detected", "analysis_complete": False}

    # gamma — FAILED, no manual-action record.
    store.save_prospect_artifact("03-gamma", "observation.json",
                                 {"status": 503, "final_url": "https://gamma.example/"})
    prospects["03-gamma"] = {"status": "FAILED", "url": "https://gamma.example/",
                             "error": "RuntimeError: backend gave up"}

    # delta — the interrupted state: findings.json on disk, compact state never advanced past PENDING.
    _save_findings(store, "04-delta", "delta.example", "delta", ["high", "medium"])
    prospects["04-delta"] = {"status": "PENDING", "url": "https://delta.example/"}

    # epsilon — DONE from a legacy run: no "coverage" key at all.
    total, defects = _save_findings(store, "05-epsilon", "epsilon.example", "epsilon",
                                    ["medium", "info"])
    prospects["05-epsilon"] = {"status": "DONE", "url": "https://epsilon.example/",
                               "verified_findings": total, "verified_defects": defects}

    # theta — DONE and honestly clean: zero findings, coverage present.
    store.save_prospect_artifact("06-theta", "findings.json", {"verified": [], "rejected": []})
    store.save_prospect_artifact("06-theta", "observation.json",
                                 {"status": 200, "final_url": "https://theta.example/"})
    prospects["06-theta"] = {"status": "DONE", "url": "https://theta.example/",
                             "verified_findings": 0, "verified_defects": 0,
                             "coverage": "adaptive", "meaningful_pages_tested": 5,
                             "page_stop_reason": "no_new_meaningful_coverage"}

    # eta — SKIPPED: no findings, no challenge record.
    prospects["07-eta"] = {"status": "SKIPPED", "url": "https://eta.example/",
                           "reason": "skipped_by_operator"}

    state = {"status": "COMPLETED", "prospects": prospects}
    store.save_state(state)
    ScoutService(out)._register_analyzed_run(store, state)

    # zeta drifted into History pointing at this run, but the run has no zeta prospect.
    AnalyzedSiteRegistry(out).record_analysis("zeta.example", status=ANALYZED, campaign_id=RUN_A)


def _build_second_alpha_run(out: str) -> None:
    """A LATER run over alpha with different counts and non-overlapping titles, so a page that
    ignores ?run= is caught by the numbers rather than by luck."""
    store = RunStore(out, RUN_B)
    total, defects = _save_findings(store, "01-alpha", "alpha.example", "alpha-rescan",
                                    ["high", "info"])
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-alpha": {"status": "DONE", "url": "https://alpha.example/",
                     "verified_findings": total, "verified_defects": defects,
                     "coverage": "deep", "meaningful_pages_tested": 14,
                     "page_stop_reason": "page_cap_reached"}}})


def _build_archived_run(out: str) -> None:
    store = RunStore(out, RUN_ARCHIVED)
    _save_findings(store, "01-alpha", "archived.example", "archived", ["medium"])
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-alpha": {"status": "DONE", "url": "https://archived.example/",
                     "verified_findings": 1, "verified_defects": 1}}})
    OperatorStateStore(out).archive_run(RUN_ARCHIVED)


def build_seam_stand(out: str) -> dict:
    _build_primary_run(out)
    _build_second_alpha_run(out)
    _build_archived_run(out)
    return {"run_a": RUN_A, "run_b": RUN_B, "archived": RUN_ARCHIVED}


def no_tavily(monkeypatch) -> None:
    def _boom(*a, **k):
        raise AssertionError("discovery must never be constructed on the seam inspection path")
    monkeypatch.setattr(TavilyDiscoveryProvider, "__init__", _boom)


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
