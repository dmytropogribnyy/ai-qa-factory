"""Interview QA demo — a targeted before/after accessibility retest on an owned synthetic page.

One command observes a local service-desk page carrying two deliberate defects (axe ``image-alt``
and ``label``) in real Chromium + axe-core, applies a PREDEFINED repair to the SAME document at the
SAME URL, and retests. Only those two rules decide the verdict; every other axe rule is kept
visible as out-of-scope. This is not AI-generated remediation and not an accessibility audit.

Reuses PlaywrightBackend.observe(deep_qa=True), serve_demo_site (isolated fixture_pages),
RunStore and EvidenceRecord. Fails closed: a missing browser/axe/navigation/screenshot is BLOCKED,
never a substituted image or a success. ``load_qa_demo`` re-verifies the persisted run (paths,
hashes, verdict); that detects accidental damage in a same-user file store, it is not tamper-proof.
"""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core.schemas.evidence import EvidenceRecord
from core.scout.backends import PageObservation, PlaywrightBackend
from core.scout.demo_site import _page, serve_demo_site
from core.scout.store import RunStore, StoreError
from core.scout.url_safety import UrlPolicy

SCHEMA = "interview_qa_demo/v1"
FIXTURE_REVISION = "service-desk-v1"
TARGETS = ("image-alt", "label")
REPORT_ARTIFACT = "qa_demo_report.json"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
_RUN_ID = re.compile(r"demo-interview-[a-zA-Z0-9_-]+")
_PAGE_PATH = "/interview/service-desk.html"
_LOGO_PATH = "/interview/logo.svg"
LIMITATIONS = [
    "Targeted retest of two axe rules only (image-alt, label); other rules are listed as out-of-scope.",
    "Real local Chromium + axe-core on an owned synthetic page; not a client or production site.",
    "The repair is predefined fixture markup, not generated or applied by a model.",
    "A clean targeted result does not establish WCAG conformance or overall accessibility.",
    "Integrity checks detect damage in a same-user local file store; they are not tamper-proof.",
]

_STYLE = ("<style>body{font-family:system-ui,sans-serif;margin:0;background:#f4f6fb;color:#1b2333}"
          "header{display:flex;gap:12px;align-items:center;background:#1f4fd1;color:#fff;"
          "padding:16px 24px}main{max-width:720px;margin:24px auto;background:#fff;padding:24px;"
          "border-radius:8px}.search{display:flex;flex-direction:column;gap:8px;margin-top:16px}"
          "label{font-weight:600}input{padding:10px;border:1px solid #6b7488;border-radius:4px}"
          "</style>")


def _service_desk(repaired: bool) -> str:
    logo_alt = " alt='Northwind Service Desk logo'" if repaired else ""
    label = "<label for='help-q'>Search help articles</label>" if repaired else ""
    return _page(
        "<title>Northwind Service Desk</title>",
        f"<header><img src='{_LOGO_PATH}' width='48' height='48'{logo_alt}>"
        "<strong>Northwind Service Desk</strong></header>"
        "<main><h1>How can we help?</h1><p>Find answers about accounts, billing and devices.</p>"
        f"<div class='search' role='search'>{label}"
        "<input type='search' id='help-q' name='q'></div></main>",
        _STYLE)


DEFECTIVE_PAGE = _service_desk(repaired=False)
REPAIRED_PAGE = _service_desk(repaired=True)
_LOGO_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
             "<rect width='48' height='48' rx='10' fill='#fff'/>"
             "<path d='M12 24h24M24 12v24' stroke='#1f4fd1' stroke-width='6'/></svg>")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _validate_id(run_id: Any) -> str:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError(f"refused run id {run_id!r}: must match demo-interview-[a-zA-Z0-9_-]+")
    return run_id


# --- comparison ----------------------------------------------------------------------------------

def _problem(obs: Any) -> str:
    """Why an observation cannot be trusted as evidence ('' when it can)."""
    if not isinstance(obs, dict):
        return "observation missing or not an object"
    if obs.get("ok") is not True:
        return "navigation did not succeed"
    status = obs.get("status")
    if not isinstance(status, int) or isinstance(status, bool) or not 200 <= status < 300:
        return f"HTTP status not a success: {status!r}"
    if obs.get("axe_status") != "ok":
        return f"axe did not run: {obs.get('axe_status')!r}"
    violations = obs.get("axe_violations")
    if not isinstance(violations, list):
        return "axe violation list missing or malformed"
    for v in violations:
        rid = v.get("id") if isinstance(v, dict) else None
        if not isinstance(rid, str) or not rid.strip() or rid == "unknown":
            return "axe violation without a proven rule id"
    if not isinstance(obs.get("screenshot_ref"), str) or not obs["screenshot_ref"]:
        return "no captured screenshot"
    if obs.get("truncated") is True:
        return "page content was truncated"
    return ""


def compare_retest(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Scoped verdict over TARGETS. Untrustworthy evidence on either side is BLOCKED."""
    base = {"targeted_rules": list(TARGETS), "limitations": list(LIMITATIONS),
            "resolved": [], "remaining": [], "out_of_scope": {"before": [], "after": []}}
    for side, obs in (("before", before), ("after", after)):
        problem = _problem(obs)
        if problem:
            return {**base, "status": "BLOCKED", "reason": f"{side}: {problem}"}
    before_ids = {v["id"] for v in before["axe_violations"]}
    after_ids = {v["id"] for v in after["axe_violations"]}
    base["out_of_scope"] = {"before": sorted(before_ids - set(TARGETS)),
                            "after": sorted(after_ids - set(TARGETS))}
    missing = [t for t in TARGETS if t not in before_ids]
    if missing:
        return {**base, "status": "BASELINE_NOT_REPRODUCED",
                "reason": f"target defect(s) not present before the fix: {', '.join(missing)}"}
    resolved = [t for t in TARGETS if t not in after_ids]
    remaining = [t for t in TARGETS if t in after_ids]
    if remaining:
        return {**base, "status": "RETEST_FAILED", "resolved": resolved, "remaining": remaining,
                "reason": f"still present after the fix: {', '.join(remaining)}"}
    return {**base, "status": "FIX_VERIFIED", "resolved": resolved,
            "reason": "both target defects reproduced before the fix and absent on retest"}


# --- capture -------------------------------------------------------------------------------------

def _not_run(reason: str) -> Dict[str, Any]:
    return {"ok": False, "status": 0, "axe_status": "", "axe_violations": [], "screenshot_ref": "",
            "truncated": False, "url": "", "final_url": "", "error": reason}


def _normalize_violations(raw: Any) -> tuple:
    """Map the backend's ``rule`` key onto a stable ``id``, validating the SOURCE shape first.
    Missing is not empty: None / non-list / malformed item / unproven rule id => ([], error)."""
    if not isinstance(raw, list):
        return [], f"axe violation list missing or malformed: {type(raw).__name__}"
    out = []
    for v in raw:
        rid = v.get("rule", v.get("id")) if isinstance(v, dict) else None
        if not isinstance(rid, str) or not rid.strip() or rid == "unknown":
            return [], "axe violation without a proven rule id"
        out.append({"id": rid, "impact": str(v.get("impact", "")), "help": str(v.get("help", "")),
                    "selector": str(v.get("selector", ""))})
    return out, ""


def _observe(backend: PlaywrightBackend, url: str, side: str, store: RunStore,
             run_id: str) -> tuple:
    filename = f"{side}.png"
    backend.screenshot_filename = filename
    try:
        obs = backend.observe(url, 20.0, 2_000_000, deep_qa=True)
    except Exception as exc:
        obs = PageObservation(url=url, backend="playwright",
                              fetch_error=f"browser error: {type(exc).__name__}")
    violations, shape_error = _normalize_violations(obs.axe_violations)
    out = {"ok": obs.ok is True, "status": obs.status,
           "axe_status": "error" if shape_error else (obs.axe_status or ""),
           "axe_violations": violations, "screenshot_ref": "", "truncated": bool(obs.truncated),
           "url": url, "final_url": obs.final_url,
           "error": (shape_error or str(obs.fetch_error or ""))[:200], "observed_at": _now()}
    record = None
    shot = store.root / "evidence" / filename
    if obs.screenshot_ref == filename and shot.is_file():
        data = shot.read_bytes()
        if data.startswith(PNG_SIG):
            out["screenshot_ref"] = f"evidence/{filename}"
            record = EvidenceRecord(
                id=f"{run_id}:{side}-screenshot", evidence_type="screenshot",
                path=out["screenshot_ref"], title=f"{side.capitalize()} screenshot",
                description=f"Real Chromium capture of the synthetic fixture, {side} the "
                            "predefined repair.",
                source_phase="interview_qa_demo", content_hash=_sha256(data),
                notes=[f"url={url}", "synthetic owned target", "internal only"])
    if not out["screenshot_ref"] and not out["error"]:
        out["error"] = "no real screenshot was captured"
    return out, record


def _source_hashes() -> Dict[str, str]:
    here = Path(__file__).resolve()
    return {p.name: _sha256(p.read_bytes()) for p in (here, here.with_name("demo_site.py"))}


def _tool_identity() -> Dict[str, str]:
    try:
        from importlib.metadata import version
        pw = version("playwright")
    except Exception:
        pw = "unknown"
    return {"browser": "chromium (headless, via PlaywrightBackend)", "playwright": pw,
            "axe": "axe-core via collect_axe_on_page (deep_qa)"}


def run_qa_demo(output_dir: str, run_id: str) -> Dict[str, Any]:
    _validate_id(run_id)
    store = RunStore(output_dir, run_id)
    store.root.mkdir(parents=True, exist_ok=False)  # atomic reservation; any existing dir refused
    started = _now()
    fixture = {"path": _PAGE_PATH, "revision": FIXTURE_REVISION,
               "defective_sha256": _sha256(DEFECTIVE_PAGE.encode("utf-8")),
               "repaired_sha256": _sha256(REPAIRED_PAGE.encode("utf-8"))}
    meta = {"schema": SCHEMA, "run_id": run_id, "started_at": started, "fixture": fixture,
            "source_hashes": _source_hashes(), "tool": _tool_identity(),
            "targeted_rules": list(TARGETS), "limitations": list(LIMITATIONS),
            "repair": "predefined fixture markup (image alt + visible label), same URL"}
    store.write_config(meta)
    store.save_state({"status": "RUNNING", "run_id": run_id, "started_at": started})

    before = after = _not_run("not observed")
    records: List[EvidenceRecord] = []
    pages = {_PAGE_PATH: (200, "text/html", DEFECTIVE_PAGE),
             _LOGO_PATH: (200, "image/svg+xml", _LOGO_SVG)}
    try:
        with serve_demo_site(fixture_pages=pages) as (base_url, allowed_host):
            backend = PlaywrightBackend(
                policy=UrlPolicy(allowed_local_hosts=frozenset({allowed_host})),
                screenshot_dir=str(store.root / "evidence"))
            url = base_url + _PAGE_PATH
            before, rec = _observe(backend, url, "before", store, run_id)
            records += [rec] if rec else []
            if _problem(before):
                after = _not_run("skipped: the baseline observation was not usable")
            else:
                pages[_PAGE_PATH] = (200, "text/html", REPAIRED_PAGE)  # predefined repair
                after, rec = _observe(backend, url, "after", store, run_id)
                records += [rec] if rec else []
    except Exception as exc:  # keep whatever real evidence was captured; record the failure
        after = after if after.get("screenshot_ref") else _not_run(f"harness: {type(exc).__name__}")

    report = {**meta, **compare_retest(before, after), "before": before, "after": after,
              "evidence": [r.to_dict() for r in records], "finished_at": _now(),
              "report_html": "report/index.html"}
    store.save_artifact(REPORT_ARTIFACT, report)
    store.save_bytes(["report", "index.html"], _render_html(report).encode("utf-8"))
    store.save_state({"status": report["status"], "run_id": run_id, "started_at": started,
                      "finished_at": report["finished_at"]})
    return report


# --- load ----------------------------------------------------------------------------------------

def _blocked(run_id: str, reason: str, report: Any = None) -> Dict[str, Any]:
    base = report if isinstance(report, dict) else {}
    return {**base, "run_id": run_id, "status": "BLOCKED", "resolved": [], "remaining": [],
            "reason": f"persisted run not usable: {reason}"}


def _verify_screenshot(store: RunStore, obs: Dict[str, Any], records: Dict[str, Any]) -> str:
    ref = obs.get("screenshot_ref")
    if not ref:
        return ""   # nothing claimed; the recomputed verdict already handles that
    rec = records.get(ref) if isinstance(ref, str) else None
    if rec is None:
        return f"no evidence record for {ref!r}"
    try:
        path = store._confine(*ref.split("/"))
    except StoreError:
        return f"screenshot path escapes the run: {ref!r}"
    if not path.is_file():
        return f"screenshot missing: {ref}"
    data = path.read_bytes()
    if not data.startswith(PNG_SIG) or _sha256(data) != rec.get("content_hash"):
        return f"screenshot bytes do not match the evidence record: {ref}"
    return ""


_TERMINAL = ("FIX_VERIFIED", "RETEST_FAILED", "BASELINE_NOT_REPRODUCED", "BLOCKED")


def _parse_utc(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _lifecycle_problem(store: RunStore, run_id: str, report: Dict[str, Any]) -> str:
    """The terminal state.json is the commit marker: it is written LAST, so a report without a
    matching terminal state belongs to a run that never finished and must not be accepted."""
    try:
        state = store.load_state()
    except StoreError as exc:
        return f"run state unreadable ({exc}); the run may not have finished"
    if not isinstance(state, dict):
        return "run state is not an object; the run may not have finished"
    if state.get("run_id") != run_id:
        return "run state belongs to a different run id"
    status = state.get("status")
    if status not in _TERMINAL:
        return f"run state is not terminal ({status!r}); the run did not finish"
    if status != report.get("status"):
        return f"run state status {status!r} disagrees with the report"
    finished, started = state.get("finished_at"), state.get("started_at")
    if not _parse_utc(finished) or finished != report.get("finished_at"):
        return "run state finished_at missing or disagrees with the report"
    if not _parse_utc(started) or started != report.get("started_at"):
        return "run state started_at missing or disagrees with the report"
    try:
        if _parse_utc(started) > _parse_utc(finished):
            return "run state started_at is after finished_at"
    except TypeError:
        return "run state timestamps are not comparable"
    return ""


def load_qa_demo(output_dir: str, run_id: str) -> Dict[str, Any]:
    _validate_id(run_id)
    store = RunStore(output_dir, run_id)
    if not store.root.is_dir():
        return _blocked(run_id, "run not found")
    try:
        report = store.load_artifact(REPORT_ARTIFACT)
    except StoreError as exc:
        return _blocked(run_id, str(exc))
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        return _blocked(run_id, "report missing or not this schema")
    if report.get("run_id") != run_id or report.get("targeted_rules") != list(TARGETS):
        return _blocked(run_id, "report identity or scope mismatch", report)
    problem = _lifecycle_problem(store, run_id, report)
    if problem:
        return _blocked(run_id, problem, report)
    before, after, evidence = report.get("before"), report.get("after"), report.get("evidence")
    if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(evidence, list):
        return _blocked(run_id, "report structure incomplete", report)
    records: Dict[str, Any] = {}
    for rec in evidence:
        path = rec.get("path") if isinstance(rec, dict) else None
        if not isinstance(path, str) or not path.strip() or path.startswith(("/", "\\")):
            return _blocked(run_id, "malformed evidence record", report)
        if path in records:
            return _blocked(run_id, f"duplicate evidence records for {path!r}", report)
        records[path] = rec
    for obs in (before, after):
        problem = _verify_screenshot(store, obs, records)
        if problem:
            return _blocked(run_id, problem, report)
    verdict = compare_retest(before, after)
    if verdict["status"] != report.get("status"):
        return _blocked(run_id, "stored verdict disagrees with the persisted observations", report)
    return {**report, **verdict}


# --- offline HTML export (not a Dashboard) -------------------------------------------------------

def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_html(r: Dict[str, Any]) -> str:
    sides = []
    for side in ("before", "after"):
        obs = r[side]
        ids = ", ".join(v.get("id", "") for v in obs.get("axe_violations", [])) or "(none)"
        shot = (f"<img src='../{_e(obs['screenshot_ref'])}' alt='{_e(side)} screenshot' width='480'>"
                if obs.get("screenshot_ref") else "<p><strong>No screenshot captured.</strong></p>")
        error = f"<p>Error: {_e(obs['error'])}</p>" if obs.get("error") else ""
        sides.append(f"<section><h2>{_e(side.capitalize())}</h2><p>HTTP {_e(obs.get('status'))}, "
                     f"axe {_e(obs.get('axe_status') or 'not run')}</p><p>axe rule ids: {_e(ids)}</p>"
                     f"{error}{shot}</section>")
    rows = ""
    for t in TARGETS:
        outcome = ("resolved" if t in r["resolved"] else "remaining" if t in r["remaining"]
                   else "not decided")
        rows += f"<tr><td>{_e(t)}</td><td>{_e(outcome)}</td></tr>"
    evidence = "".join(f"<li>{_e(x.get('path'))} — {_e(x.get('content_hash'))} "
                       f"(internal_only={_e(x.get('internal_only'))})</li>" for x in r["evidence"])
    oos = r.get("out_of_scope", {})
    limits = "".join(f"<li>{_e(x)}</li>" for x in r["limitations"])
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>Interview QA demo {_e(r['run_id'])}</title></head><body>"
            f"<h1>Targeted accessibility retest: {_e(r['status'])}</h1>"
            f"<p>Run {_e(r['run_id'])} · {_e(r['started_at'])} → {_e(r['finished_at'])}</p>"
            f"<p>{_e(r['reason'])}</p><p>Repair: {_e(r['repair'])}</p>"
            f"<table><tr><th>Target rule</th><th>Result</th></tr>{rows}</table>"
            f"<p>Out-of-scope rules — before: {_e(', '.join(oos.get('before', [])) or '(none)')}; "
            f"after: {_e(', '.join(oos.get('after', [])) or '(none)')}</p>"
            f"{''.join(sides)}<h2>Evidence</h2><ul>{evidence}</ul>"
            f"<h2>Provenance</h2><p>{_e(r['tool'])}</p><p>Fixture {_e(r['fixture'])}</p>"
            f"<p>Sources {_e(r['source_hashes'])}</p><h2>Limitations</h2><ul>{limits}</ul>"
            "</body></html>")
