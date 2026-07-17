"""Scout report export (Phase 8.3).

Assembles a client-facing report from a completed run and publishes it atomically via the
Phase 8.1 `ArtifactSafeWriter` (temp -> content secret scan -> atomic swap). Only VERIFIED +
sanitized findings are included, and the evidence index references only approved run
artifacts. Nothing is sent; this only writes local files under the run's report/ directory.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from core.orchestration.content_safety import ArtifactSafeWriter
from core.scout import SCOUT_PRODUCT_NAME, SCOUT_VERSION
from core.scout.store import RunStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verified(store: RunStore, pid: str) -> List[Dict[str, Any]]:
    data = store.load_prospect_artifact(pid, "findings.json") or {}
    return [f for f in data.get("verified", []) if f.get("is_client_safe")]


def build_report(store: RunStore, clock: Callable[[], str] = _now) -> Dict[str, Any]:
    state = store.load_state()
    prospects = state.get("prospects", {})
    generated_at = clock()

    all_verified: List[Dict[str, Any]] = []
    scorecards: Dict[str, Any] = {}
    evidence_index: Dict[str, Any] = {}
    coverage: List[Dict[str, Any]] = []
    shortlist: List[Dict[str, Any]] = []
    manual: List[Dict[str, Any]] = []

    for pid, p in sorted(prospects.items()):
        status = p.get("status")
        if status == "MANUAL_ACTION_REQUIRED":
            manual.append({"prospect": pid, "url": p.get("url"), "reason": p.get("reason")})
            continue
        if status != "DONE":
            continue
        verified = _verified(store, pid)
        defects = [f for f in verified if f.get("severity") != "info"]
        limitations = [f for f in verified if f.get("category") == "coverage"]
        for f in verified:
            f2 = dict(f)
            f2["prospect"] = pid
            (coverage if f.get("category") == "coverage" else all_verified).append(f2)
        sc = store.load_prospect_artifact(pid, "scorecard.json")
        if sc:
            scorecards[pid] = sc
        ev = p.get("evidence_ref")
        if ev:
            evidence_index[pid] = {"evidence_ref": ev, "verified_findings": len(verified)}
        shortlist.append({
            "prospect": pid, "url": p.get("url"), "priority": p.get("priority", "D"),
            "verified_defects": len(defects), "limitations": len(limitations),
        })

    shortlist.sort(key=lambda r: ("ABCD".index(r["priority"]) if r["priority"] in "ABCD" else 9,
                                  -r["verified_defects"]))

    report_json = {
        "product": SCOUT_PRODUCT_NAME,
        "version": SCOUT_VERSION,
        "run_id": state.get("run_id"),
        "run_status": state.get("status"),
        "generated_at": generated_at,
        "shortlist": shortlist,
        "verified_findings": all_verified,
        "coverage_limitations": coverage,
        "manual_action_required": manual,
        "scorecards": scorecards,
        "evidence_index": evidence_index,
        "note": "Local, read-only QA. No outreach was sent; no forms/accounts/orders/payments.",
    }

    artifacts = {
        "REPORT.json": json.dumps(report_json, indent=2, ensure_ascii=False, sort_keys=True),
        "EVIDENCE_INDEX.json": json.dumps(evidence_index, indent=2, ensure_ascii=False, sort_keys=True),
        "CAMPAIGN_SUMMARY.md": _campaign_md(state, shortlist, all_verified, manual),
        "PROSPECT_SHORTLIST.md": _shortlist_md(shortlist),
        "VERIFIED_FINDINGS.md": _findings_md(all_verified),
        "COVERAGE_AND_LIMITATIONS.md": _coverage_md(coverage),
        "SCORECARD_SUMMARY.md": _scorecard_md(scorecards),
    }

    # Atomic + content-secret-scanned publish (rejects any secret-bearing content).
    ArtifactSafeWriter(store.report_dir()).publish(artifacts)
    return {
        "report_dir": str(store.report_dir()),
        "artifacts": sorted(artifacts.keys()),
        "verified_findings": len(all_verified),
        "manual_action_required": len(manual),
        "shortlist": shortlist,
    }


def _campaign_md(state, shortlist, verified, manual) -> str:
    return (
        "# Campaign Summary — Prospect QA Scout (local)\n\n"
        f"- Run: `{state.get('run_id')}` — status **{state.get('status')}**\n"
        f"- Prospects analyzed: {len(shortlist)}\n"
        f"- Verified findings (defects): {len(verified)}\n"
        f"- Manual-action-required prospects: {len(manual)}\n\n"
        "_Local, read-only QA. No outreach, form submission, account, order, or payment occurred._\n"
    )


def _shortlist_md(shortlist) -> str:
    lines = ["# Prospect Shortlist\n", "| Prospect | URL | Priority | Verified defects |",
             "|---|---|---|---|"]
    for r in shortlist:
        lines.append(f"| {r['prospect']} | {r['url']} | {r['priority']} | {r['verified_defects']} |")
    return "\n".join(lines) + "\n"


def _findings_md(verified) -> str:
    lines = ["# Verified Findings\n"]
    if not verified:
        return lines[0] + "\n_No verified defects._\n"
    for f in verified:
        lines.append(f"## [{f['severity'].upper()}] {f['title']} — `{f.get('prospect')}`")
        lines.append(f"- URL: {f['url']}")
        lines.append(f"- Category: {f['category']} · Confidence: {f['confidence']}")
        if f.get("business_impact"):
            lines.append(f"- Business impact: {f['business_impact']}")
        if f.get("reproduction_steps"):
            lines.append("- Reproduction: " + " → ".join(f["reproduction_steps"]))
        lines.append("")
    return "\n".join(lines) + "\n"


def _coverage_md(coverage) -> str:
    lines = ["# Coverage & Limitations\n"]
    for f in coverage:
        lines.append(f"- `{f.get('prospect')}` — {f['title']}: {f.get('coverage_limitation', '')}")
    return "\n".join(lines) + ("\n" if coverage else "\n_No limitations recorded._\n")


def _scorecard_md(scorecards) -> str:
    lines = ["# Scorecard Summary\n", "_Scores are advisory only and do not authorize outreach._\n"]
    for pid, sc in sorted(scorecards.items()):
        dims = ", ".join(f"{d['name']}={d['value']}" for d in sc.get("dimensions", []))
        lines.append(f"- `{pid}` — priority **{sc.get('priority')}** · {dims}")
    return "\n".join(lines) + "\n"
