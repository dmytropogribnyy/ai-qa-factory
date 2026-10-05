"""Product Demos — the Dashboard read-projection and start path for the two implemented demos.

QA Evidence & Retest (``core.scout.qa_demo``) and LLM Output Evaluation (``core.llm_eval_demo``)
own their execution, persistence and verification. This module only:

- starts ONE run at a time per Dashboard (non-blocking lock -> 409 when busy), with a fresh
  server-chosen run id; the HTTP request selects a scenario and nothing else (no output root, URL,
  path, model or import file). The LLM web run is always FIXTURE mode.
- reads persisted runs through the engines' own ``load_*`` verification and renders escaped HTML
  fragments for ``core.scout.dashboard._page``. Grading is never recomputed here.
- serves the two canonical QA screenshots and a self-contained escaped export, only for a record
  that loaded as verified, path-confined and size-bounded before reading.

Runs live in the existing RunStore demo namespaces (``<output_dir>/scout/demo-qa-*``,
``demo-llm-*``); legacy ``demo-interview-*`` QA records stay readable and are never created.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import secrets
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from core import llm_eval_demo
from core.scout import qa_demo
from core.scout.store import RunStore, StoreError

SCENARIOS = {"qa": "demo-qa-", "llm": "demo-llm-"}
START_KEYS = frozenset({"scenario", "csrf_token"})
SIDES = ("before", "after")
MAX_RECENT = 20
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
MAX_CASES_BYTES = llm_eval_demo.MAX_IMPORT_BYTES
# Declared caps for the files a run folder holds, checked from metadata BEFORE any loader reads them.
MAX_STATE_BYTES = 64 * 1024               # state.json, config.json
MAX_REPORT_BYTES = 8 * 1024 * 1024        # qa_demo_report.json, llm_eval_report.json
MAX_RUN_ENTRIES = 64                      # a demo run holds about ten files and folders
_ID = re.compile(r"(demo-qa|demo-llm|demo-interview)-[A-Za-z0-9_-]{1,80}")
# Absolute filesystem paths (Windows drive, UNC or POSIX) must never reach an HTTP response.
_PATHISH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|(?<![\w.\-])/[^\s'\"<>|,;)/]+/)[^\s'\"<>|,;)]*")
# load_qa_demo marks a record it could not verify with this reason prefix (its ``_blocked``).
_QA_UNVERIFIED = "persisted run not usable"

_TONE = {"FIX_VERIFIED": "ok", "IMPROVED": "ok", "STABLE": "ok",
         "RETEST_FAILED": "attention", "BASELINE_NOT_REPRODUCED": "attention",
         "REGRESSION_DETECTED": "attention", "REVIEW_REQUIRED": "attention", "BLOCKED": "danger"}

_CSS = (
    "<style>"
    ".demo-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));"
    "gap:var(--gap)}.demo-grid .card{margin:0;display:flex;flex-direction:column;gap:6px}"
    ".demo-grid .card h2{margin:0}.demo-grid .card p{margin:0}.demo-grid .card .btn{align-self:flex-start;"
    "margin-top:6px}.demo-meta{font-size:13px}"
    ".demo-shots{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));"
    "gap:var(--gap);margin:0 0 var(--gap)}.demo-shots figure{margin:0;min-width:0}"
    ".demo-shots img{display:block;width:100%;height:auto;border:1px solid var(--border);"
    "border-radius:6px;background:#fff}.demo-shots figcaption{font-size:13px;margin-top:4px}"
    ".demo-wrap,.demo-wrap td,.demo-wrap th{overflow-wrap:anywhere}"
    ".demo-case{margin-bottom:8px}.demo-case>summary{color:var(--text)}"
    ".demo-case pre,.demo-advanced pre{max-height:360px}"
    "summary:focus-visible,button:focus-visible{outline:3px solid var(--focus);outline-offset:2px}"
    "</style>")

_HOME_SCRIPT = (
    "(function(){var ids=['run-qa','run-llm'],btns=ids.map(function(i){"
    "return document.getElementById(i);}).filter(Boolean);"
    "var st=document.getElementById('demo-status'),er=document.getElementById('demo-error');"
    "function busy(on){btns.forEach(function(b){b.disabled=on;"
    "b.setAttribute('aria-busy',on?'true':'false');});}"
    "function fail(msg){er.textContent=msg;er.hidden=false;st.textContent='';busy(false);}"
    "function run(b){var sc=b.getAttribute('data-scenario');busy(true);er.hidden=true;"
    "er.textContent='';st.textContent=(sc==='qa'?'Running the QA demo':'Running the evaluation')+"
    "' \\u2014 the result opens when it finishes.';"
    "fetch('/api/demos/start',{method:'POST',credentials:'same-origin',headers:{"
    "'Content-Type':'application/json','X-Scout-CSRF':CSRF},"
    "body:JSON.stringify({scenario:sc,csrf_token:CSRF})})"
    ".then(function(r){return r.json().catch(function(){return {};})"
    ".then(function(j){return {ok:r.ok,j:j};});})"
    ".then(function(x){var u=x.j&&x.j.url;"
    "if(x.ok&&typeof u==='string'&&/^\\/demos\\/run\\?id=[A-Za-z0-9_-]+$/.test(u)){"
    "st.textContent='Finished ('+String(x.j.status||'')+'). Opening the result\\u2026';"
    "location.assign(u);return;}"
    "fail(String((x.j&&x.j.error)||'The demo could not be started.'));})"
    ".catch(function(){fail('The Dashboard did not answer. Check that it is still running.');});}"
    "btns.forEach(function(b){b.addEventListener('click',function(){run(b);});});})();")


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _badge(text: Any) -> str:
    return f'<span class="badge {_TONE.get(str(text), "")}">{_e(text)}</span>'


def _hero(status: Any) -> str:
    """The existing ``status-hero`` modifier for an outcome (ok is the unmodified style)."""
    tone = _TONE.get(str(status), "")
    return "blocked" if tone == "danger" else "attention" if tone == "attention" else ""


def _fraction(side: Dict[str, Any]) -> str:
    """Show the engine's stored counts and rate; nothing is recomputed."""
    try:
        return f"{int(side['passed'])}/{int(side['total'])} ({float(side['pass_rate']) * 100:.0f}%)"
    except (KeyError, TypeError, ValueError):
        return "unavailable"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _kind(run_id: str) -> str:
    return "llm" if run_id.startswith("demo-llm-") else "qa"


def _detail_url(run_id: str) -> str:
    return "/demos/run?id=" + quote(run_id, safe="")


def _cap(rel: str) -> int:
    """The size limit for one file of a run folder (``rel`` is relative, '/'-separated). Read at
    call time so the module limits stay the single source."""
    if rel in ("state.json", "config.json"):
        return MAX_STATE_BYTES
    if rel in (qa_demo.REPORT_ARTIFACT, llm_eval_demo.REPORT_NAME):
        return MAX_REPORT_BYTES
    if rel.startswith("inputs/"):
        return MAX_CASES_BYTES
    return MAX_SCREENSHOT_BYTES   # screenshots and anything else a stored reference could name


def _raise(exc: OSError) -> None:
    raise exc


class DemoController:
    """Start/read projection for one Dashboard. ``runners``/``loaders`` are injectable for tests;
    production uses exactly the engines' run/load functions (LLM always in FIXTURE mode)."""

    def __init__(self, output_dir: str, *,
                 run_qa: Callable[[str, str], Dict[str, Any]] = qa_demo.run_qa_demo,
                 load_qa: Callable[[str, str], Dict[str, Any]] = qa_demo.load_qa_demo,
                 run_llm: Callable[[str, str], Dict[str, Any]] = llm_eval_demo.run_llm_eval_demo,
                 load_llm: Callable[[str, str], Dict[str, Any]] = llm_eval_demo.load_llm_eval_demo):
        self.output_dir = str(output_dir)
        self.runners = {"qa": run_qa, "llm": run_llm}
        self.loaders = {"qa": load_qa, "llm": load_llm}
        self._lock = threading.Lock()

    # --- helpers --------------------------------------------------------------------------------
    def _safe(self, text: Any, limit: int = 300) -> str:
        out = str(text or "")
        roots = {os.path.abspath(self.output_dir), os.path.realpath(self.output_dir)}
        roots |= {r.replace("\\", "\\\\") for r in roots}   # repr()-escaped form in OSError text
        for prefix in sorted(roots, key=len, reverse=True):
            out = out.replace(prefix, "<runs>")
        return _PATHISH.sub("<path>", out)[:limit]

    def _store(self, run_id: str) -> Optional[RunStore]:
        try:
            return RunStore(self.output_dir, run_id)
        except StoreError:
            return None

    @staticmethod
    def _preflight(store: RunStore) -> Tuple[str, str]:
        """Check the run folder from metadata only (lstat; no file content is read) before any core
        loader touches it: a bounded number of entries, no links, only regular files, each within
        its declared cap. Returns ('', '') when fine, else ('too_large' | 'unreadable', reason)."""
        count = 0
        try:
            for dirpath, dirnames, filenames in os.walk(store.root, onerror=_raise,
                                                        followlinks=False):
                for name in dirnames + filenames:
                    count += 1
                    if count > MAX_RUN_ENTRIES:
                        return "unreadable", "the run folder holds more entries than a demo run"
                    path = Path(dirpath, name)
                    info = path.lstat()
                    if stat.S_ISLNK(info.st_mode) or getattr(path, "is_junction", lambda: False)():
                        return "unreadable", "the run folder contains a link"
                    if name in filenames:
                        if not stat.S_ISREG(info.st_mode):
                            return "unreadable", "the run folder holds an entry that is not a file"
                        rel = path.relative_to(store.root).as_posix()
                        if info.st_size > _cap(rel):
                            return "too_large", f"stored file {rel} exceeds its size limit"
        except (OSError, ValueError):
            return "unreadable", "the run folder could not be inspected"
        return "", ""

    def _new_id(self, scenario: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{SCENARIOS[scenario]}{stamp}-{secrets.token_hex(3)}"

    # --- start ----------------------------------------------------------------------------------
    def start(self, body: Any) -> Tuple[int, Dict[str, Any]]:
        """Validate the request, then run one demo synchronously. The caller has already applied
        the Dashboard's loopback/Origin/CSRF guard."""
        if not isinstance(body, dict):
            return 400, {"ok": False, "error": "the request body must be a JSON object"}
        extra = sorted(str(k) for k in body if k not in START_KEYS)
        if extra:
            return 400, {"ok": False, "error": "unsupported field(s): " + ", ".join(extra)[:200]
                         + " — only 'scenario' is accepted"}
        scenario = body.get("scenario")
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            return 400, {"ok": False, "error": "scenario must be 'qa' or 'llm'"}
        if not self._lock.acquire(blocking=False):
            return 409, {"ok": False, "error": "Another demo run is in progress. Try again when it "
                                               "finishes."}
        try:
            run_id = self._new_id(scenario)
            try:
                result = self.runners[scenario](self.output_dir, run_id)
            except Exception as exc:   # noqa: BLE001 - report the failure type, never a traceback
                store = self._store(run_id)
                saved = bool(store and store.root.is_dir())
                payload = {"ok": False, "scenario": scenario,
                           "error": f"the demo run failed ({type(exc).__name__})"}
                if saved:
                    payload.update(run_id=run_id, url=_detail_url(run_id))
                return 500, payload
            result = result if isinstance(result, dict) else {}
            return 200, {"ok": True, "scenario": scenario, "run_id": run_id,
                         "url": _detail_url(run_id), "status": result.get("status"),
                         "verdict": result.get("verdict"), "mode": result.get("mode")}
        finally:
            self._lock.release()

    # --- read -----------------------------------------------------------------------------------
    def read(self, run_id: Any) -> Tuple[int, Dict[str, Any]]:
        """Return (http_status, view). view['record'] is verified | review_required | unverifiable
        for an existing run; 400 = invalid id, 404 = unknown run. Never executes anything."""
        if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
            return 400, {"ok": False, "error": "invalid demo run id"}
        store = self._store(run_id)
        if store is None:
            return 400, {"ok": False, "error": "invalid demo run id"}
        if not store.root.is_dir():
            return 404, {"ok": False, "error": "unknown demo run", "run_id": run_id}
        kind = _kind(run_id)
        problem, broken = self._preflight(store)   # before the core loader reads anything
        if not broken:
            try:
                result = self.loaders[kind](self.output_dir, run_id)
            except Exception as exc:   # noqa: BLE001 - a broken record is a view, not a 500
                broken = f"record could not be read ({type(exc).__name__})"
        if not broken and not isinstance(result, dict):
            broken = "record could not be read"
        if broken:
            result = {"status": "BLOCKED", "reason": broken}
        status = result.get("status")
        if broken:
            record = "unverifiable"
        elif kind == "qa":
            record = ("unverifiable" if status == "BLOCKED" and str(result.get("reason", ""))
                      .startswith(_QA_UNVERIFIED) else "verified")
        else:
            record = {"COMPLETED": "verified", "REVIEW_REQUIRED": "review_required"}.get(
                status, "unverifiable")
        view: Dict[str, Any] = {"ok": record == "verified", "run_id": run_id, "kind": kind,
                                "legacy": run_id.startswith("demo-interview-"), "record": record}
        if problem == "too_large":
            view["too_large"] = True
        if record == "verified":
            view["result"] = result
            if kind == "llm":
                view["cases"] = self._cases_snapshot(store, result)
        else:
            # Only the outcome and a path-free reason: a partial or damaged report is not shown.
            view["result"] = {"run_id": run_id, "status": status or "BLOCKED",
                              "reason": self._safe(result.get("reason") or "record not usable")}
        return (422 if record == "unverifiable" else 200), view

    def _cases_snapshot(self, store: RunStore, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The case inputs from the SAME persisted snapshot the run was graded on (hash-checked),
        never the current fixture. None when unavailable."""
        try:
            path = store._confine("inputs", "cases.json")
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CASES_BYTES:
                return None
            data = path.read_bytes()
            if _sha256(data) != report.get("dataset_sha256"):
                return None
            cases = json.loads(data.decode("utf-8")).get("cases")
            return {c["id"]: c for c in cases if isinstance(c, dict) and isinstance(c.get("id"), str)}
        except (StoreError, OSError, ValueError, AttributeError, TypeError):
            return None

    def _screenshot(self, run_id: str, result: Dict[str, Any], side: str) -> Tuple[int, Any]:
        """The canonical screenshot of one side of a verified QA record, re-checked against its
        evidence record. Returns (200, bytes) or (status, error dict)."""
        obs = result.get(side) if isinstance(result.get(side), dict) else {}
        ref = obs.get("screenshot_ref")
        if not ref:
            return 404, {"ok": False, "error": f"no {side} screenshot was captured in this run"}
        canonical = f"evidence/{side}.png"
        rec = next((r for r in result.get("evidence") or []
                    if isinstance(r, dict) and r.get("path") == canonical), None)
        if ref != canonical or rec is None:
            return 409, {"ok": False, "error": "the screenshot is not the canonical evidence file"}
        store = self._store(run_id)
        try:
            path = store._confine("evidence", f"{side}.png") if store else None
        except StoreError:
            path = None
        try:
            if path is None or path.is_symlink() or not path.is_file():
                return 404, {"ok": False, "error": "the screenshot file is missing"}
            if path.stat().st_size > MAX_SCREENSHOT_BYTES:
                return 413, {"ok": False, "error": "the screenshot is too large to serve"}
            data = path.read_bytes()
        except OSError:
            return 409, {"ok": False, "error": "the screenshot could not be read"}
        if not data.startswith(qa_demo.PNG_SIG) or \
                "sha256:" + _sha256(data) != rec.get("content_hash"):
            return 409, {"ok": False, "error": "the screenshot does not match its evidence record"}
        return 200, data

    def evidence(self, run_id: Any, side: Any) -> Tuple[int, Any]:
        """GET /demos/evidence: (200, png bytes) or (status, error dict)."""
        if side not in SIDES:
            return 400, {"ok": False, "error": "side must be 'before' or 'after'"}
        if not isinstance(run_id, str) or not _ID.fullmatch(run_id) or _kind(run_id) != "qa":
            return 400, {"ok": False, "error": "evidence is only available for QA demo runs"}
        status, view = self.read(run_id)
        if view.get("too_large"):
            return 413, {"ok": False, "error": "a stored file of this run exceeds its size limit"}
        if status != 200 or view["record"] != "verified":
            return (status if status in (400, 404) else 409), {
                "ok": False, "error": "evidence is only served for a verified run"}
        return self._screenshot(run_id, view["result"], side)

    def export(self, run_id: Any) -> Tuple[int, Any]:
        """GET /demos/export: (200, html bytes) generated from the verified loaded result."""
        status, view = self.read(run_id)
        if status != 200 or view["record"] != "verified":
            return (status if status in (400, 404) else 409), {
                "ok": False, "error": "an export is only produced for a verified run"}
        if view["kind"] == "qa":
            def img(side: str) -> Optional[str]:
                code, data = self._screenshot(run_id, view["result"], side)
                return ("data:image/png;base64," + base64.b64encode(data).decode("ascii")
                        if code == 200 else None)
            title, body = "QA Evidence & Retest", self._qa_body(view, img, export=True)
        else:
            title, body = "LLM Output Evaluation", self._llm_body(view, export=True)
        doc = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
               "<meta name='viewport' content='width=device-width, initial-scale=1'>"
               f"<title>{_e(title)} {_e(run_id)}</title><style>"
               ":root{--bg:#fff;--surface:#fff;--surface-2:#f2f2f2;--border:#ccc;--text:#111;"
               "--muted:#555;--focus:#1f4fd1;--gap:12px;--pad:16px;--ok:#1a7f37;--attention:#8a5a00;"
               "--error:#b42318;--code:#f4f4f4}body{font-family:system-ui,sans-serif;margin:1.5rem;"
               "color:var(--text);background:var(--bg)}table{border-collapse:collapse;width:100%}"
               "td,th{border:1px solid var(--border);padding:6px;text-align:left;vertical-align:top}"
               "pre{white-space:pre-wrap;background:var(--code);padding:8px}.badge{font-weight:600}"
               ".muted{color:var(--muted)}</style>"
               f"{_CSS}</head><body><main>{body}</main></body></html>")
        return 200, doc.encode("utf-8")

    # --- recent runs ----------------------------------------------------------------------------
    def recent(self) -> Tuple[List[Dict[str, Any]], int]:
        """Up to MAX_RECENT demo runs, newest first, and the total number of demo run folders."""
        root = os.path.join(self.output_dir, "scout")
        found = []
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if _ID.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False):
                        try:
                            found.append((entry.stat().st_mtime, entry.name))
                        except OSError:
                            continue
        except OSError:
            return [], 0
        found.sort(reverse=True)
        rows = []
        for _mtime, run_id in found[:MAX_RECENT]:
            status, view = self.read(run_id)
            if status in (400, 404):   # removed between listing and reading
                continue
            r = view.get("result") or {}
            outcome = r.get("verdict") if view["kind"] == "llm" and view["record"] == "verified" \
                else r.get("status")
            rows.append({"run_id": run_id, "kind": view["kind"], "legacy": view.get("legacy"),
                         "record": view.get("record"), "outcome": outcome or "BLOCKED",
                         "finished_at": r.get("finished_at"), "mode": r.get("mode")})
        return rows, len(found)

    # --- HTML fragments -------------------------------------------------------------------------
    def home_body(self) -> Tuple[str, str]:
        """(body, script) for GET /demos. The script expects a page-level ``CSRF`` constant."""
        rows, total = self.recent()
        names = {"qa": "QA Evidence & Retest", "llm": "LLM Output Evaluation"}
        trs = "".join(
            f'<tr><td data-label="Run"><a href="{_e(_detail_url(r["run_id"]))}">'
            f'<code>{_e(r["run_id"])}</code></a></td>'
            f'<td data-label="Demo">{_e(names[r["kind"]])}'
            f'{" (legacy record)" if r["legacy"] else ""}'
            f'{" &middot; " + _e(r["mode"]) if r["mode"] else ""}</td>'
            f'<td data-label="Result">{_badge(r["outcome"])}'
            f'{" <span class=muted>record not verified</span>" if r["record"] == "unverifiable" else ""}'
            f'</td><td data-label="Finished">{_e(r["finished_at"] or "—")}</td></tr>'
            for r in rows)
        note = (f'Showing the {len(rows)} most recent of {total} demo runs.' if total > len(rows)
                else f'{total} demo run{"" if total == 1 else "s"}.')
        recent = (f'<p class="muted">{_e(note)}</p><div class="scrollx demo-wrap">'
                  f'<table class="responsive-table"><thead><tr><th>Run</th><th>Demo</th>'
                  f'<th>Result</th><th>Finished (UTC)</th></tr></thead><tbody>{trs}</tbody>'
                  f'</table></div>' if rows else
                  '<p class="quiet-state">No demo has been run yet. Each run is kept and listed '
                  'here; running again always creates a new run.</p>')
        qa_limits = "".join(f"<li>{_e(x)}</li>" for x in qa_demo.LIMITATIONS)
        llm_limits = "".join(f"<li>{_e(x)}</li>" for x in llm_eval_demo._COMMON_LIMITS
                             + [llm_eval_demo._MODE_LIMITS["FIXTURE"]])
        body = (
            f'{_CSS}<h1>Demos</h1>'
            '<p class="page-intro muted">Two self-contained product demonstrations. Each button runs '
            'once, saves the run with its evidence, and opens the result. Opening or reloading a '
            'result never runs anything again.</p>'
            '<div class="demo-grid">'
            '<section class="card" aria-labelledby="demo-qa-title">'
            '<h2 id="demo-qa-title">QA Evidence &amp; Retest</h2>'
            '<p>Real local Chromium and axe-core check an owned synthetic page with two planted '
            'defects, apply a <strong>predefined</strong> repair at the same URL, and retest.</p>'
            '<p class="muted demo-meta">Mode: real local browser &middot; Duration: usually under a '
            'minute &middot; Proves: before/after screenshots and a scoped verdict for two axe rules '
            '(image-alt, label).</p>'
            '<button type="button" class="btn primary" id="run-qa" data-scenario="qa">'
            'Run QA demo</button></section>'
            '<section class="card" aria-labelledby="demo-llm-title">'
            '<h2 id="demo-llm-title">LLM Output Evaluation</h2>'
            '<p>Grades a baseline and a candidate set of raw outputs against gold cases '
            '(schema, abstention, reference match, citations, canary) and flags per-case '
            'regressions.</p>'
            '<p class="muted demo-meta">Mode: <strong>FIXTURE</strong> &mdash; constructed outputs, '
            'no model or API call &middot; Duration: a few seconds &middot; Proves: deterministic '
            'grading and the comparison policy, not model quality.</p>'
            '<button type="button" class="btn primary" id="run-llm" data-scenario="llm">'
            'Run evaluation</button></section></div>'
            '<p id="demo-status" class="muted" role="status" aria-live="polite"></p>'
            '<p id="demo-error" class="form-error" role="alert" hidden></p>'
            f'<h2>Recent demo runs</h2>{recent}'
            '<details class="advanced compact-details"><summary>What these demos do not show'
            '</summary><h3>QA Evidence &amp; Retest</h3><ul>' + qa_limits + '</ul>'
            '<h3>LLM Output Evaluation</h3><ul>' + llm_limits + '</ul></details>')
        return body, _HOME_SCRIPT

    def detail(self, run_id: Any) -> Tuple[int, str, str]:
        """(http_status, title, body) for GET /demos/run."""
        status, view = self.read(run_id)
        back = '<p><a href="/demos">&larr; All demos</a></p>'
        if status in (400, 404):
            msg = ("This is not a valid demo run id." if status == 400 else
                   "No demo run with this id exists. Runs are listed on the Demos page.")
            return status, "Demo run", f'{back}<h1>Demo run</h1><p class="quiet-state">{_e(msg)}</p>'
        if view["record"] != "verified":
            r = view["result"]
            label = ("The stored result was recorded by a different evaluator version and is not "
                     "re-interpreted automatically." if view["record"] == "review_required" else
                     "This run's saved record could not be verified, so no result is shown.")
            return status, "Demo run", (
                f'{_CSS}{back}<h1>Demo run <code class="demo-wrap">{_e(run_id)}</code></h1>'
                f'<div class="card status-hero blocked demo-wrap">{_badge(r.get("status"))} '
                f'<p>{_e(label)}</p><p class="muted">Reason: {_e(r.get("reason"))}</p></div>')
        if view["kind"] == "qa":
            def img(side: str) -> str:
                return f"/demos/evidence?id={quote(run_id, safe='')}&side={side}"
            return 200, "QA Evidence & Retest", _CSS + back + self._qa_body(view, img)
        return 200, "LLM Output Evaluation", _CSS + back + self._llm_body(view)

    def _qa_body(self, view: Dict[str, Any], img: Callable[[str], Optional[str]],
                 export: bool = False) -> str:
        r = view["result"]
        status = r.get("status")
        run_id = view["run_id"]
        before_ids = {v.get("id") for v in (r.get("before") or {}).get("axe_violations") or []
                      if isinstance(v, dict)}
        after_ids = {v.get("id") for v in (r.get("after") or {}).get("axe_violations") or []
                     if isinstance(v, dict)}
        # A side without a successful axe observation says nothing about the rule: "not observed",
        # never "absent".
        observed = {side: (r.get(side) or {}).get("axe_status") == "ok" for side in SIDES}

        def cell(side: str, rule: str, ids: set) -> str:
            return ("present" if rule in ids else "absent") if observed[side] else "not observed"

        rows = ""
        for rule in r.get("targeted_rules") or qa_demo.TARGETS:
            outcome = ("resolved" if rule in (r.get("resolved") or []) else
                       "still present" if rule in (r.get("remaining") or []) else "not decided")
            rows += (f'<tr><td data-label="Target rule"><code>{_e(rule)}</code></td>'
                     f'<td data-label="Before">{_e(cell("before", rule, before_ids))}</td>'
                     f'<td data-label="After">{_e(cell("after", rule, after_ids))}</td>'
                     f'<td data-label="Result">{_e(outcome)}</td></tr>')
        figs = ""
        for side in SIDES:
            obs = r.get(side) or {}
            src = img(side) if obs.get("screenshot_ref") else None
            caption = ("Before: the synthetic page with both planted defects" if side == "before"
                       else "After: the same URL serving the predefined repair")
            shot = (f'<img src="{_e(src)}" alt="{_e(caption)} (screenshot)" width="640" height="400"'
                    f' style="height:auto">' if src else
                    f'<p class="quiet-state">No screenshot was captured for this side'
                    f'{": " + _e(self._safe(obs.get("error"))) if obs.get("error") else "."}</p>')
            figs += f'<figure>{shot}<figcaption class="muted">{_e(caption)}</figcaption></figure>'
        errors = "".join(f'<li>{_e(side.capitalize())}: {_e(self._safe((r.get(side) or {}).get("error")))}</li>'
                         for side in SIDES if (r.get(side) or {}).get("error"))
        oos = r.get("out_of_scope") or {}
        evidence = "".join(f'<li><code>{_e(x.get("path"))}</code> &mdash; {_e(x.get("content_hash"))}</li>'
                           for x in r.get("evidence") or [] if isinstance(x, dict))
        limits = "".join(f"<li>{_e(x)}</li>" for x in r.get("limitations") or [])
        legacy = (' <span class="muted">(legacy record, read-only)</span>' if view.get("legacy")
                  else "")
        export_link = ("" if export else
                       f' &middot; <a href="/demos/export?id={_e(quote(run_id, safe=""))}">'
                       f'Download report</a>')
        raw = json.dumps(r, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        return (
            f'<h1>QA Evidence &amp; Retest {_badge(status)}</h1>'
            f'<div class="card status-hero {_hero(status)} demo-wrap">'
            f'<p><strong>Scoped verdict: {_e(status)}</strong> for the two target rules '
            f'(image-alt, label) on an owned synthetic page &mdash; not a general accessibility '
            f'certification.</p><p>{_e(self._safe(r.get("reason")))}</p>'
            f'<p class="muted">Run <code>{_e(run_id)}</code>{legacy} &middot; started '
            f'{_e(r.get("started_at"))} &middot; finished {_e(r.get("finished_at"))}{export_link}</p>'
            f'</div>'
            f'<h2>Before and after</h2><div class="demo-shots">{figs}</div>'
            f'<h2>Targeted rules</h2><div class="scrollx demo-wrap"><table class="responsive-table">'
            f'<thead><tr><th>Target rule</th><th>Before</th><th>After</th><th>Result</th></tr>'
            f'</thead><tbody>{rows}</tbody></table></div>'
            + (f'<h2>Observation problems</h2><ul>{errors}</ul>' if errors else "")
            + f'<p class="muted">Repair: {_e(r.get("repair"))}</p>'
            f'<details class="advanced compact-details demo-advanced demo-wrap"><summary>Evidence, '
            f'provenance and limitations</summary>'
            f'<p>Other axe rules (out of scope, never counted as resolved) &mdash; before: '
            f'{_e(", ".join(oos.get("before") or []) or "none")}; after: '
            f'{_e(", ".join(oos.get("after") or []) or "none")}</p>'
            f'<h3>Evidence records</h3><ul>{evidence or "<li>none</li>"}</ul>'
            f'<h3>Tools</h3><p>{_e(r.get("tool"))}</p><h3>Fixture</h3><p>{_e(r.get("fixture"))}</p>'
            f'<h3>Limitations</h3><ul>{limits}</ul>'
            f'<h3>Stored record (JSON)</h3><pre>{_e(raw)}</pre></details>')

    def _llm_body(self, view: Dict[str, Any], export: bool = False) -> str:
        r = view["result"]
        run_id = view["run_id"]
        cmp = r.get("comparison") or {}
        cases = view.get("cases")
        verdict = r.get("verdict")
        meaning = {
            "REGRESSION_DETECTED": "The evaluation completed. At least one case passed on the "
                                   "baseline and fails on the candidate, so the candidate fails the "
                                   "demo regression policy even if its average is higher.",
            "IMPROVED": "The evaluation completed. No case regressed and at least one improved.",
            "STABLE": "The evaluation completed. No case changed outcome.",
        }.get(str(verdict), "")
        summary = "".join(
            f'<tr><td data-label="Side">{_e(side)}</td>'
            f'<td data-label="Passed / total">{_e(_fraction(cmp.get(side) or {}))}</td></tr>'
            for side in ("baseline", "candidate"))

        def ids(key: str) -> str:
            return ", ".join(cmp.get(key) or []) or "none"

        def side_html(ev: Dict[str, Any], label: str) -> str:
            checks = "".join(
                f'<li><code>{_e(name)}</code> {_badge(c.get("status"))} {_e(c.get("reason"))}</li>'
                for name, c in (ev.get("checks") or {}).items() if isinstance(c, dict))
            return (f'<h4>{_e(label)}: {_badge(ev.get("status"))}</h4>'
                    f'<p class="muted">Raw output</p><pre>{_e(ev.get("raw_output"))}</pre>'
                    f'<ul>{checks}</ul>')

        details = ""
        for p in cmp.get("per_case") or []:
            if not isinstance(p, dict):
                continue
            case = (cases or {}).get(p.get("case_id"))
            if case:
                context = "".join(f'<li><code>{_e(k)}</code>: {_e(v)}</li>'
                                  for k, v in (case.get("context") or {}).items())
                inputs = (f'<p><strong>Prompt:</strong> {_e(case.get("prompt"))}</p>'
                          f'<p><strong>Context</strong></p><ul>{context}</ul>'
                          f'<p><strong>Expected</strong></p>'
                          f'<pre>{_e(json.dumps(case.get("expected"), ensure_ascii=False))}</pre>')
            else:
                inputs = '<p class="muted">Case inputs are unavailable from this run\'s snapshot.</p>'
            base, cand = p.get("baseline") or {}, p.get("candidate") or {}
            details += (
                f'<details class="demo-case card"><summary><code>{_e(p.get("case_id"))}</code> '
                f'&middot; {_e(p.get("category"))} &middot; baseline {_e(base.get("status"))} '
                f'&rarr; candidate {_e(cand.get("status"))} &middot; <strong>{_e(p.get("change"))}'
                f'</strong></summary>{inputs}{side_html(base, "Baseline")}'
                f'{side_html(cand, "Candidate")}</details>')
        limits = "".join(f"<li>{_e(x)}</li>" for x in r.get("limitations") or [])
        provenance = (json.dumps(r.get("provenance"), sort_keys=True, ensure_ascii=False)
                      if r.get("provenance") else "none (fixture)")
        origin = ("constructed test examples, no model or API call &mdash; not a measured model "
                  "benchmark" if r.get("mode") == "FIXTURE" else
                  "imported outputs; provider, model and timing are user-declared and not verified")
        export_link = ("" if export else
                       f' &middot; <a href="/demos/export?id={_e(quote(run_id, safe=""))}">'
                       f'Download report</a>')
        raw = json.dumps(r, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        return (
            f'<h1>LLM Output Evaluation {_badge(verdict)}</h1>'
            f'<div class="card status-hero {_hero(verdict)} demo-wrap">'
            f'<p><strong>Mode: {_e(r.get("mode"))}</strong> &mdash; {origin}.</p>'
            f'<p><strong>Verdict: {_e(verdict)}</strong>. {_e(meaning)}</p>'
            f'<p class="muted">Run <code>{_e(run_id)}</code> &middot; started '
            f'{_e(r.get("started_at"))} &middot; finished {_e(r.get("finished_at"))}{export_link}</p>'
            f'</div>'
            f'<h2>Baseline and candidate</h2><div class="scrollx demo-wrap">'
            f'<table class="responsive-table"><thead><tr><th>Side</th><th>Passed / total</th></tr>'
            f'</thead><tbody>{summary}</tbody></table></div>'
            f'<p><strong>Regressed:</strong> {_e(ids("regressed"))} &middot; '
            f'<strong>Improved:</strong> {_e(ids("improved"))}</p>'
            f'<p class="muted">Comparison policy: a case is regressed when it passes on the baseline '
            f'and fails on the candidate; any regression yields REGRESSION_DETECTED. This is a demo '
            f'comparison policy, not release authorization.</p>'
            f'<h2>Cases</h2><div class="demo-wrap">{details}</div>'
            f'<details class="advanced compact-details demo-advanced demo-wrap"><summary>Provenance '
            f'and limitations</summary>'
            f'<p>Provenance: {_e(provenance)} &middot; provider called: '
            f'{_e(r.get("provider_called"))} &middot; model, cost, latency: unknown</p>'
            f'<p>Dataset {_e(r.get("dataset_id"))} v{_e(r.get("dataset_version"))} &middot; sha256 '
            f'{_e(r.get("dataset_sha256"))}<br>Responses sha256 {_e(r.get("responses_sha256"))}<br>'
            f'Evaluator {_e(r.get("evaluator_version"))} &middot; sha256 '
            f'{_e(r.get("evaluator_sha256"))}</p>'
            f'<h3>Limitations</h3><ul>{limits}</ul>'
            f'<h3>Stored record (JSON)</h3><pre>{_e(raw)}</pre></details>')
