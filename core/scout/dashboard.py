"""Localhost Scout dashboard (Phase 8.3; v3.0.0 M4b guarded start).

A dependency-light stdlib HTTP dashboard bound to 127.0.0.1 only. It reads the run store and
exposes control (pause/resume/cancel/global-kill). Artifact serving is path-confined to the
active run directory — no arbitrary filesystem access, no traversal.

v3.0.0 adds ONE state-changing endpoint — ``POST /api/campaign/start`` — for the local operator.
It is fenced by four independent guards: the server binds loopback only; the ``Host`` header must
be loopback (blocks DNS-rebinding); ``Origin`` (when present) must match; and a per-server CSRF
token is required. It can only launch the existing bounded, read-only Scout engine (see
``campaign_start.CampaignLauncher``) — it never sends email, submits forms, or runs commands.
"""
from __future__ import annotations

import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from core.scout import SCOUT_PRODUCT_NAME, SCOUT_VERSION
from core.scout.campaign_start import CampaignLauncher
from core.scout.service import ScoutService
from core.scout.store import StoreError

_CONTENT_TYPES = {".json": "application/json", ".png": "image/png", ".md": "text/markdown"}
# Defensive cap on how much a single artifact response may return (our artifacts are small).
_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
# The largest JSON body accepted by the start endpoint (requests are tiny).
_MAX_START_BODY_BYTES = 64 * 1024
# The largest pasted client brief accepted by the dashboard intake (also bounded by the body cap).
_MAX_BRIEF_BYTES = 60 * 1024
# Hard cap on how many body bytes we will drain before giving up (prevents a huge-Content-Length
# read while still fully draining ordinary oversized requests so the socket is not half-closed).
_DRAIN_CAP_BYTES = 2 * 1024 * 1024
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# Per-project mutation locks so concurrent double-submits are serialized (v3.1 P1). Shared across
# the per-request WorkExecutionService instances in this process.
import threading as _threading  # noqa: E402

_WORK_LOCKS: dict = {}
_WORK_LOCKS_GUARD = _threading.Lock()


def _work_lock(key: str):
    with _WORK_LOCKS_GUARD:
        lk = _WORK_LOCKS.get(key)
        if lk is None:
            lk = _threading.Lock()
            _WORK_LOCKS[key] = lk
        return lk


def _make_handler(service: ScoutService, launcher: CampaignLauncher, csrf_token: str,
                  operator_home: bool = False):
    class _Handler(BaseHTTPRequestHandler):
        server_version = f"ScoutDashboard/{SCOUT_VERSION}"

        def log_message(self, *args):
            return

        # --- helpers ---
        def _json(self, status: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _html(self, status: int, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            # Local-only CSP: no external scripts/styles/fonts/frames; images may be inline data URIs.
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                             "form-action 'self'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        # --- routing ---
        def do_GET(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            q = parse_qs(parsed.query)
            # DNS-rebinding defense for READS too: a request whose Host is not loopback must never
            # receive CSRF tokens, project data, evidence, contacts, or artifacts (v3.1 P0-3).
            if not self._host_is_loopback():
                return self._json(403, {"error": "non-loopback Host header refused"})
            if path == "/health":
                return self._json(200, {"status": "ok", "product": SCOUT_PRODUCT_NAME,
                                        "version": SCOUT_VERSION, "run_id": service.run_id,
                                        "running": service.is_running()})
            if path == "/api/status":
                return self._json(200, service.status())
            if path == "/api/csrf":
                # Same-origin pages can read this; a cross-origin page cannot (no CORS header),
                # so the token stays secret to foreign origins — the point of the guard.
                return self._json(200, {"csrf_token": csrf_token})
            if path == "/api/prospects":
                st = service.status().get("state", {})
                return self._json(200, {"prospects": st.get("prospects", {})})
            if path == "/api/prospect":
                pid = (q.get("id") or [""])[0]
                return self._json(200, self._prospect(pid))
            if path == "/api/events":
                return self._json(200, {"events": service.recent_events(200)})
            if path == "/api/campaign":
                return self._json(200, self._campaign_summary())
            if path == "/api/candidates":
                st = service.status().get("state", {})
                return self._json(200, {"candidates": st.get("candidates", [])})
            if path == "/api/providers":
                return self._json(200, {"providers": self._read_report(
                    "PROVIDER_REGISTRY_SNAPSHOT.json") or []})
            if path == "/api/presend":
                return self._json(200, self._presend_summary())
            if path == "/api/comms":
                return self._json(200, self._comms_summary())
            if path == "/api/tools":
                return self._json(200, self._tools_snapshot())
            if path == "/tools":
                return self._html(200, self._tools_page())
            if path == "/api/projects":
                return self._json(200, self._projects_snapshot())
            if path == "/projects":
                return self._html(200, self._projects_page())
            # v3.1 operator dashboard read-model routes
            if path == "/api/overview":
                return self._json(200, self._read_model().overview().to_dict())
            if path == "/api/work":
                view = (q.get("view") or ["all"])[0]
                return self._json(200, self._read_model().project_list(view=view))
            if path.startswith("/api/work/"):
                return self._json(200, self._work_detail_json(path[len("/api/work/"):]))
            if path == "/work" or path == "/work/":
                return self._html(200, self._work_list_page(q))
            if path.startswith("/work/"):
                return self._html(200, self._work_detail_page(path[len("/work/"):], q))
            if path == "/scout":
                return self._html(200, self._scout_home_page())
            if path == "/scout/campaigns":
                return self._html(200, self._scout_campaigns_page())
            if path == "/activity":
                return self._html(200, self._activity_page(q))
            if path == "/api/activity":
                return self._json(200, self._activity_json((q.get("project") or [""])[0]))
            if path == "/settings":
                return self._html(200, self._settings_page())
            if path == "/docs":
                return self._html(200, self._docs_page())
            if path == "/api/results":
                return self._json(200, self._results_snapshot())
            if path == "/results":
                return self._html(200, self._results_page(q))
            if path == "/company":
                return self._html(200, self._company_page((q.get("id") or [""])[0]))
            if path == "/artifact":
                return self._artifact((q.get("path") or [""])[0])
            if path == "/work-evidence":
                return self._work_evidence((q.get("project") or [""])[0], (q.get("path") or [""])[0])
            if path == "/" or path == "/index.html":
                # Operator home = the new Overview inbox; a Scout-run-bound dashboard keeps its
                # existing run view at "/" (regression-preserved). Both link to each other.
                if operator_home and not service.is_running() and not self._has_active_run():
                    return self._html(200, self._operator_overview_page())
                return self._html(200, self._overview_html())
            return self._json(404, {"error": "not found"})

        def _has_active_run(self) -> bool:
            try:
                st = service.status().get("state", {})
                return bool(st.get("candidates") or st.get("prospects") or st.get("status"))
            except Exception:
                return False

        def _read_model(self):
            from core.dashboard.read_model import DashboardReadModel
            from datetime import datetime, timezone
            return DashboardReadModel(service.output_dir,
                                      clock=lambda: datetime.now(timezone.utc).isoformat())

        do_HEAD = do_GET

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/api/control":
                return self._control(parsed)
            if parsed.path == "/api/campaign/start":
                return self._campaign_start()
            if parsed.path.startswith("/api/work/"):
                return self._work_action(parsed.path[len("/api/work/"):])
            return self._json(404, {"error": "not found"})

        def _guard_mutation(self, body):
            """One shared guard for every state-changing endpoint (v3.1 M10): loopback bind (server)
            + loopback Host (anti DNS-rebinding) + Origin + per-server CSRF. Returns an error dict on
            refusal, else None. The caller must have already drained the body."""
            if not self._host_is_loopback():
                return (403, {"ok": False, "error": "non-loopback Host header refused"})
            if not self._origin_ok():
                return (403, {"ok": False, "error": "cross-origin requests are refused"})
            if not self._csrf_ok():
                return (403, {"ok": False, "error": "missing or invalid CSRF token"})
            return None

        def _control(self, parsed):
            """Apply a run control signal — behind the shared mutation guard. Drain any body first so
            an early rejection never breaks the pipe."""
            body = self._read_json_body()   # optional body; also captures a body CSRF token
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            action = (parse_qs(parsed.query).get("action") or [""])[0]
            ok, status, message = service.control(action)
            return self._json(status, {"ok": ok, "action": action, "message": message,
                                       "status": service.status()})

        # --- guarded client-work mutations (v3.1) — NEVER a command/argv over HTTP -------------
        def _work_action(self, action: str):
            """Guarded client-work lifecycle mutations that call WorkExecutionService (the same
            service the CLI uses). Only reviewer/note/reason are accepted — never a command."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            if body is None:
                return self._json(400, {"ok": False, "error": "invalid or oversized JSON body"})
            pid = str(body.get("project_id") or "")
            reviewer = str(body.get("reviewer") or "")[:120]
            note = str(body.get("note") or "")[:500]
            reason = str(body.get("reason") or "")[:500]
            from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
            from core.orchestration.work_state_manager import InvalidTransitionError
            if action == "analyze":
                # Read-only intake (analysis only; nothing is executed). Uses the SAME project-id
                # contract as the CLI: generate a safe id when omitted, else validate strictly.
                from core.orchestration.client_work import ClientWorkService
                from core.orchestration.content_safety import redact_intake_text
                from core.orchestration.providers import (
                    ClockProvider,
                    IdProvider,
                    generate_project_id,
                    validate_project_id,
                )
                brief = str(body.get("text") or "").strip()
                if not brief:
                    return self._json(400, {"ok": False, "error": "a client brief is required"})
                if len(brief.encode("utf-8")) > _MAX_BRIEF_BYTES:
                    return self._json(400, {"ok": False,
                                            "error": f"brief exceeds {_MAX_BRIEF_BYTES} bytes"})
                generated = not pid.strip()
                project_id = (generate_project_id(redact_intake_text(brief).text, IdProvider())
                              if generated else pid.strip())
                if not validate_project_id(project_id):
                    return self._json(400, {"ok": False, "error": "invalid project id (use "
                                            "[A-Za-z0-9._-], max 64, no separators/traversal)"})
                try:
                    res = ClientWorkService(ClockProvider(), IdProvider(),
                                            output_dir=service.output_dir).analyze(
                        brief, project_id=project_id,
                        source_platform=str(body.get("source_platform") or "manual"),
                        fresh_only=generated)
                except Exception as exc:
                    return self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                return self._json(200, {"ok": True, "action": action,
                                        "project_id": res.project_id})
            # Serialize conflicting lifecycle mutations per project so a double-submit cannot race
            # (the state machine already prevents duplicate history / an incorrect transition).
            with _work_lock(f"{service.output_dir}::{pid}"):
                svc = WorkExecutionService(output_dir=service.output_dir)
                try:
                    if action == "approve":
                        svc.approve(pid, reviewer=reviewer or "operator", note=note)
                    elif action == "review":
                        svc.review(pid, reviewer=reviewer or "operator", approved=True, note=note)
                    elif action == "review-reject":
                        svc.review(pid, reviewer=reviewer or "operator", approved=False, note=note)
                    elif action == "prepare-delivery":
                        svc.prepare_delivery(pid)
                        return self._json(200, {"ok": True, "action": action, "project_id": pid,
                                                "status": svc.status(pid).status})
                    elif action == "reopen-delivery":
                        if not reason.strip():
                            return self._json(400, {"ok": False, "error": "reason is required"})
                        entry = svc.reopen_delivery(pid, reviewer=reviewer or "operator", reason=reason)
                        return self._json(200, {"ok": True, "action": action, "project_id": pid,
                                                "status": svc.status(pid).status,
                                                "outcome": entry["outcome"]})
                    elif action == "mark-delivered":
                        svc.mark_delivered(pid, note=note)
                    else:
                        return self._json(404, {"ok": False, "error": "unknown work action"})
                except (WorkExecutionError, InvalidTransitionError) as exc:
                    return self._json(409, {"ok": False, "action": action, "project_id": pid,
                                            "error": str(exc)})
                v = svc.status(pid)
                return self._json(200, {"ok": True, "action": action, "project_id": pid,
                                        "status": v.status, "next_action": v.next_action})

        # --- guarded campaign start (v3.0.0 M4b) -----------------------------------------------
        def _campaign_start(self):
            """Start a bounded, read-only campaign — behind loopback + Host + Origin + CSRF guards."""
            # Drain the (bounded) request body first so an early rejection never leaves the client
            # writing into a half-closed socket (a broken pipe / connection abort).
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            if body is None:
                return self._json(400, {"ok": False, "error": "invalid or oversized JSON body"})
            result = launcher.start(body)
            payload = result.to_dict()
            payload["status_snapshot"] = service.status()
            return self._json(result.status, payload)

        def _host_is_loopback(self) -> bool:
            host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0].strip().lower()
            host = host[1:-1] if host.startswith("[") and host.endswith("]") else host
            return host in _LOOPBACK_HOSTS

        def _csrf_ok(self) -> bool:
            supplied = self.headers.get("X-Scout-CSRF") or self._body_csrf
            return bool(supplied) and secrets.compare_digest(str(supplied), csrf_token)

        def _read_json_body(self) -> Optional[dict]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length <= 0:
                return None
            # Always DRAIN the declared body (bounded) before any rejection so an oversized/invalid
            # request never leaves the client writing into a half-closed socket (Windows WinError
            # 10053). Beyond a hard drain cap we stop reading (a huge Content-Length is abusive).
            try:
                raw = self.rfile.read(min(length, _DRAIN_CAP_BYTES))
            except OSError:
                return None
            if length > _MAX_START_BODY_BYTES:
                return None            # oversized (drained what we safely could)
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError:
                return None
            if not isinstance(data, dict):
                return None
            self._body_csrf = data.get("csrf_token")   # allow CSRF via body too (no header needed)
            return data

        _body_csrf = None

        def _origin_ok(self) -> bool:
            """Reject browser-originated cross-origin POSTs (lightweight CSRF guard).

            Browsers always attach Origin on cross-origin fetch; the CLI control command sends
            none, so a missing Origin is allowed while a foreign one is refused. The start endpoint
            layers a required CSRF token on top, so a missing Origin alone never suffices there.
            """
            origin = self.headers.get("Origin")
            if not origin:
                return True
            host = self.headers.get("Host", "")
            allowed = {f"http://{host}", f"https://{host}"}
            return origin in allowed

        # --- data ---
        def _prospect(self, pid: str):
            store = service.store
            if store is None or not pid:
                return {"error": "no prospect"}
            out = {"prospect_id": pid}
            for name in ("observation.json", "findings.json", "evidence.json", "scorecard.json"):
                try:
                    out[name.split(".")[0]] = store.load_prospect_artifact(pid, name)
                except StoreError:
                    out[name.split(".")[0]] = None
            return out

        def _artifact(self, rel: str):
            store = service.store
            if store is None or not rel:
                return self._json(404, {"error": "no artifact"})
            parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
            try:
                target = store._confine(*parts)
            except StoreError:
                return self._json(403, {"error": "path not allowed"})
            if not target.exists() or not target.is_file():
                return self._json(404, {"error": "not found"})
            if target.stat().st_size > _MAX_ARTIFACT_BYTES:
                return self._json(413, {"error": "artifact too large to serve"})
            ctype = next((v for k, v in _CONTENT_TYPES.items() if target.name.endswith(k)),
                         "application/octet-stream")
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _campaign_summary(self):
            st = service.status().get("state", {})
            matrix = st.get("matrix", {})
            return {"campaign_id": st.get("campaign_id"), "status": st.get("status"),
                    "counts": st.get("counts", {}), "budget": st.get("budget", {}),
                    "matrix": {k: matrix.get(k) for k in
                               ("full_size", "planned_provider_calls", "sampled")}}

        def _read_report(self, name: str):
            store = service.store
            if store is None:
                return None
            try:
                target = store._confine("report", name)
            except StoreError:
                return None
            if not target.exists():
                return None
            try:
                return json.loads(target.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return None

        def _campaign_html(self, status, st) -> str:
            counts = st.get("counts", {})
            budget = st.get("budget", {})
            rows = []
            for c in st.get("candidates", []):
                rows.append(
                    "<tr>"
                    f"<td>{_esc(c.get('business_name', ''))}</td>"
                    f"<td>{_esc(c.get('normalized_url') or c.get('public_url', ''))}</td>"
                    f"<td>{_esc(c.get('duplicate_status', ''))}</td>"
                    f"<td>{_esc(c.get('suppression_status', ''))}</td>"
                    f"<td>{_esc(c.get('eligibility_status', ''))}</td>"
                    f"<td>{_esc(c.get('commercial_status', ''))}</td>"
                    f"<td>{_esc(c.get('commercial_score', 0))}</td>"
                    f"<td>{_esc(c.get('promotion_decision', ''))}</td>"
                    f"<td>{_esc(c.get('promoted_scout_run', ''))}</td></tr>")
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} — Discovery</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:1200px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:5px;text-align:left;font-size:13px}}
code{{background:#f4f4f4;padding:2px 4px}}</style></head>
<body><h1>{SCOUT_PRODUCT_NAME} <small>discovery</small></h1>
<p>Campaign <code>{_esc(st.get('campaign_id', ''))}</code> — status
<strong>{_esc(st.get('status', 'n/a'))}</strong> (read-only view)</p>
<p>Candidates: {_esc(counts.get('candidates', 0))} · unique {_esc(counts.get('unique', 0))} ·
duplicates {_esc(counts.get('duplicates', 0))} · uncertain {_esc(counts.get('uncertain_identity', 0))} ·
suppressed {_esc(counts.get('suppressed', 0))} (NO_SCAN {_esc(counts.get('no_scan', 0))}) ·
technical_ok {_esc(counts.get('technical_ok', 0))} · eligible {_esc(counts.get('commercial_eligible', 0))} ·
promoted {_esc(counts.get('promoted', 0))} · held {_esc(counts.get('held_for_review', 0))}</p>
<p>Budget: provider_calls {_esc(budget.get('provider_calls', 0))} · results {_esc(budget.get('results', 0))} ·
cost ${_esc(budget.get('cost_usd', 0))} — APIs: <a href="/api/campaign">campaign</a>,
<a href="/api/candidates">candidates</a>, <a href="/api/providers">providers</a></p>
<h2>Discovered candidates</h2><table><tr><th>business</th><th>url</th><th>dedup</th>
<th>suppression</th><th>technical</th><th>commercial</th><th>score</th><th>promotion</th>
<th>scout run</th></tr>{''.join(rows) or '<tr><td colspan=9>none</td></tr>'}</table>
<p><em>Read-only discovery. No contact was collected; no outreach/form/order/payment occurred.</em></p>
</body></html>"""

        def _presend_summary(self):
            findings = self._read_report("NORMALIZED_FINDINGS.json") or []
            contacts = self._read_report("CONTACT_VERIFICATION.json") or []
            offers = self._read_report("AUDIT_OFFER.json") or []
            review = self._read_report("REVIEW_QUEUE.json") or []
            suppression = self._read_report("SUPPRESSION_CHECK.json") or []
            return {"findings": len(findings), "contacts": len(contacts), "offers": len(offers),
                    "review_items": len(review), "suppression": suppression,
                    "any_send_control": False}  # there is no send control in Final Phase I

        def _presend_html(self) -> str:
            s = self._presend_summary()
            findings = self._read_report("NORMALIZED_FINDINGS.json") or []
            review = self._read_report("REVIEW_QUEUE.json") or []
            frows = "".join(
                f"<tr><td>{_esc(f.get('capability'))}</td><td>{_esc(f.get('severity'))}</td>"
                f"<td>{_esc(f.get('title'))}</td><td>{_esc(f.get('is_client_safe'))}</td></tr>"
                for f in findings[:200])
            rrows = "".join(
                f"<tr><td>{_esc(r.get('queue'))}</td><td>{_esc(r.get('draft') or r.get('contact') or r.get('company'))}</td></tr>"
                for r in review[:200])
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} — Pre-Send</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:1100px}}
table{{border-collapse:collapse;width:100%;margin-bottom:1.5rem}}td,th{{border:1px solid #ccc;padding:5px;font-size:13px;text-align:left}}
.banner{{background:#efe;border:1px solid #7a7;padding:.6rem;border-radius:4px}}</style></head>
<body><h1>{SCOUT_PRODUCT_NAME} <small>pre-send review</small></h1>
<p class=banner><strong>Nothing is sent.</strong> This is a human review view for the Final
Phase II sending workflow. There is no send button.</p>
<p>Findings: {s['findings']} · Contacts: {s['contacts']} · Offers: {s['offers']} ·
Review items: {s['review_items']} — APIs: <a href="/api/presend">presend</a>,
<a href="/artifact?path=report/OUTREACH_DRAFTS.md">drafts</a>,
<a href="/artifact?path=report/CAMPAIGN_SUMMARY.md">summary</a></p>
<h2>Verified findings</h2><table><tr><th>capability</th><th>severity</th><th>title</th>
<th>client-safe</th></tr>{frows or '<tr><td colspan=4>none</td></tr>'}</table>
<h2>Review queue</h2><table><tr><th>queue</th><th>subject</th></tr>
{rrows or '<tr><td colspan=2>none</td></tr>'}</table>
</body></html>"""

        def _memory_db_path(self):
            store = service.store
            if store is None:
                return None
            p = store.root / "memory.db"
            return p if p.exists() else None

        def _results_snapshot(self):
            path = self._memory_db_path()
            if path is None:
                return {"companies": [], "count": 0, "note": "no memory database for this run"}
            from core.scout.memory.db import MemoryDB
            db = MemoryDB(str(path))
            try:
                out = []
                for c in db.query("SELECT company_id, canonical_name, primary_domain FROM companies "
                                  "ORDER BY company_id"):
                    cid = c["company_id"]
                    contacts = db.query("SELECT normalized_value, status FROM contacts WHERE company_id=?",
                                        (cid,))
                    n = db.query("SELECT COUNT(*) AS n FROM findings WHERE company_id=?", (cid,))[0]["n"]
                    sevs = [r["severity"] for r in db.query(
                        "SELECT severity FROM findings WHERE company_id=?", (cid,)) if r["severity"]]
                    out.append({"company_id": cid, "name": c["canonical_name"],
                                "domain": c["primary_domain"], "findings": n,
                                "max_severity": _max_severity(sevs),
                                "contact": (contacts[0]["normalized_value"] if contacts else ""),
                                "contact_status": (contacts[0]["status"] if contacts else "")})
                return {"companies": out, "count": len(out)}
            finally:
                db.close()

        def _company_detail(self, cid: str):
            path = self._memory_db_path()
            if path is None or not cid:
                return None
            from core.scout.memory.db import MemoryDB
            db = MemoryDB(str(path))
            try:
                crow = db.query("SELECT * FROM companies WHERE company_id=?", (cid,))
                if not crow:
                    return None
                findings = [dict(r) for r in db.query(
                    "SELECT finding_id, capability, severity, title, verification_state, "
                    "lifecycle_state, client_safe FROM findings WHERE company_id=?", (cid,))]
                contacts = db.query("SELECT * FROM contacts WHERE company_id=?", (cid,))
                contact = dict(contacts[0]) if contacts else {}
                prov = {}
                if contact:
                    prow = db.query("SELECT source_category, source_url, publicly_published_for_contact, "
                                    "terms_review_status, last_verified_at FROM contact_provenance "
                                    "WHERE contact_id=? AND state='ACTIVE' ORDER BY created_at DESC "
                                    "LIMIT 1", (contact["contact_id"],))
                    prov = dict(prow[0]) if prow else {}
                drow = db.query("SELECT subject, body FROM draft_revisions WHERE company_id=? "
                                "ORDER BY revision_number DESC LIMIT 1", (cid,))
                draft = dict(drow[0]) if drow else {}
                return {"company": dict(crow[0]), "findings": findings, "contact": contact,
                        "provenance": prov, "draft": draft}
            finally:
                db.close()

        def _results_html(self) -> str:
            snap = self._results_snapshot()
            rows = "".join(
                f"<tr><td><a href='/company?id={_esc(c['company_id'])}'>{_esc(c['name'] or c['company_id'])}</a></td>"
                f"<td>{_esc(c['domain'])}</td><td>{_esc(c['contact'])}</td>"
                f"<td>{_esc(c['contact_status'])}</td><td>{_esc(c['findings'])}</td></tr>"
                for c in snap.get("companies", []))
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} — Results</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:1100px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;font-size:13px;text-align:left}}</style></head>
<body><h1>{SCOUT_PRODUCT_NAME} <small>results</small></h1>
<p><a href="/">&larr; Home</a> · <a href="/projects">projects</a></p>
<table><tr><th>company</th><th>domain</th><th>public contact</th><th>contact state</th>
<th>findings</th></tr>{rows or '<tr><td colspan=5>no companies yet</td></tr>'}</table>
<p><em>Read-only. No outreach is sent from here.</em> API: <a href="/api/results">/api/results</a></p>
</body></html>"""

        def _company_html(self, cid: str) -> str:
            d = self._company_detail(cid)
            if d is None:
                return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
                        f"<title>{SCOUT_PRODUCT_NAME} — company not found</title></head>"
                        "<body><main><h1>Company not found</h1>"
                        "<p>Unknown company id, or no company data for this run yet.</p>"
                        "<p><a href='/results'>&larr; Back to results</a></p></main></body></html>")
            frows = "".join(
                f"<tr><td>{_esc(f['capability'])}</td><td>{_esc(f['severity'])}</td>"
                f"<td>{_esc(f['title'])}</td><td>{_esc(f['verification_state'])}</td>"
                f"<td>{_esc(f['client_safe'])}</td></tr>" for f in d["findings"])
            contact = d["contact"]
            prov = d["provenance"]
            draft = d["draft"]
            recip = contact.get("normalized_value", "")
            compose = _gmail_compose_url(recip, draft.get("subject", ""), draft.get("body", ""))
            gmail_action = (f"<a href='{_esc(compose)}' target='_blank' rel='noopener'>Open in Gmail</a>"
                            if recip and draft else "<em>no draft/contact yet</em>")
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} — {_esc(cid)}</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:900px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;font-size:13px;text-align:left}}
pre{{background:#f6f6f6;padding:.6rem;white-space:pre-wrap}}</style></head>
<body><h1>{_esc(d['company'].get('canonical_name') or cid)}</h1>
<p><a href="/results">&larr; Results</a> — domain {_esc(d['company'].get('primary_domain'))}</p>
<h2>Findings</h2><table><tr><th>capability</th><th>severity</th><th>title</th>
<th>verification</th><th>client-safe</th></tr>{frows or '<tr><td colspan=5>none</td></tr>'}</table>
<h2>Public contact + provenance</h2>
<p>Contact: <code>{_esc(recip)}</code> ({_esc(contact.get('status'))}) ·
source: {_esc(prov.get('source_category'))} · published:
{_esc(prov.get('publicly_published_for_contact'))} · terms: {_esc(prov.get('terms_review_status'))} ·
verified: {_esc(prov.get('last_verified_at'))}<br>source URL: {_esc(prov.get('source_url'))}</p>
<h2>Draft (editable in Gmail; nothing is sent from here)</h2>
<p><strong>Subject:</strong> {_esc(draft.get('subject', '(none)'))}</p>
<pre>{_esc(draft.get('body', '(no draft)'))}</pre>
<p>Action: {gmail_action} — then send manually in Gmail and mark the company contacted.
Live API send stays the optional, one-at-a-time <code>scout send</code> CLI path.</p>
</body></html>"""

        def _projects_snapshot(self):
            from core.orchestration.project_index import ProjectIndex
            return ProjectIndex(service.output_dir).snapshot()

        def _projects_html(self) -> str:
            snap = self._projects_snapshot()
            rows = "".join(
                f"<tr><td>{_esc(p['project_id'])}</td><td>{_esc(p['type'])}</td>"
                f"<td>{_esc(p['title'])}</td><td>{_esc(p['lifecycle_state'])}</td>"
                f"<td>{_esc(p['progress'])}%</td><td>{_esc(len(p['blockers']))}</td>"
                f"<td>{_esc(p['evidence_count'])}</td><td>{_esc(p['operator_next_action'])}</td></tr>"
                for p in snap.get("projects", []))
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} — Projects</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:1200px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;font-size:13px;text-align:left}}</style></head>
<body><h1>{SCOUT_PRODUCT_NAME} <small>projects</small></h1>
<p><a href="/">&larr; Home</a> · <a href="/tools">tool readiness</a></p>
<p>Client-work projects and Scout campaigns, from the existing project state (read-only;
{_esc(snap.get('project_count', 0))} total).</p>
<table><tr><th>project</th><th>type</th><th>title</th><th>state</th><th>progress</th>
<th>blockers</th><th>evidence</th><th>operator next action</th></tr>
{rows or '<tr><td colspan=8>none yet</td></tr>'}</table>
<p>API: <a href="/api/projects">/api/projects</a></p>
</body></html>"""

        def _tools_snapshot(self):
            from core.orchestration.tool_broker import ToolBroker
            return ToolBroker(clock=lambda: "").snapshot()

        def _tools_html(self) -> str:
            snap = self._tools_snapshot()
            rows = "".join(
                f"<tr><td>{_esc(t['id'])}</td><td>{_esc(t.get('ui_level', ''))}</td>"
                f"<td>{_esc(t['domain'])}</td>"
                f"<td>{_esc(t['readiness'])}</td><td>{_esc(t['auth_requirement'])}</td>"
                f"<td>{_esc(t['fallback'])}</td><td>{_esc(t.get('setup_instruction', ''))}</td></tr>"
                for t in snap.get("tools", []))
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} — Tool Readiness</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:1100px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;font-size:13px;text-align:left}}
.banner{{background:#eef;border:1px solid #99c;padding:.6rem;border-radius:4px}}</style></head>
<body><h1>{SCOUT_PRODUCT_NAME} <small>tool readiness</small></h1>
<p><a href="/">&larr; Home</a></p>
<p class=banner>Honest readiness (no live MCP/network call). None is live-accepted
(any_live_accepted={_esc(snap.get('any_live_accepted'))}). Session-only MCP tools show
<code>declared</code>; connect them in Claude Code (/mcp) to use. No secret values are shown.</p>
<table><tr><th>tool</th><th>level</th><th>domain</th><th>readiness</th><th>auth</th><th>fallback</th><th>setup</th></tr>
{rows or '<tr><td colspan=7>none</td></tr>'}</table>
<p>API: <a href="/api/tools">/api/tools</a></p>
</body></html>"""

        def _comms_summary(self):
            health = self._read_report("FINAL_PRODUCT_HEALTH.json") or {}
            metrics = self._read_report("COMMERCIAL_METRICS.json") or {}
            controls = self._read_report("OUTREACH_CONTROL_STATE.json") or {}
            return {"outreach_global": controls.get("global", "DISABLED"),
                    "outreach_kill": controls.get("kill", "RUNNING"),
                    "send_status": health.get("send_status"), "metrics": metrics,
                    "any_real_send": health.get("any_real_send", False),
                    "has_send_button": False}  # sending is CLI-gated; no dashboard send button

        def _comms_html(self) -> str:
            s = self._comms_summary()
            m = s.get("metrics", {})
            enabled = s["outreach_global"] == "ENABLED" and s["outreach_kill"] != "KILLED"
            banner = ("<span style='color:#a00'>OUTREACH ENABLED</span>" if enabled
                      else "<span style='color:#070'>OUTREACH DISABLED (default)</span>")
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} — Communication</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:1000px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:6px}}
.banner{{padding:.6rem;border:1px solid #999;border-radius:4px;font-weight:bold}}</style></head>
<body><h1>{SCOUT_PRODUCT_NAME} <small>communication</small></h1>
<p class=banner>Global outreach: {banner} · kill: {_esc(s['outreach_kill'])}</p>
<p><strong>There is no send button here.</strong> Sending is performed only via the gated
<code>scout send</code> CLI (dry-run by default; live requires explicit approval, a reviewer, and
an exact recipient confirmation). Nothing is sent from this dashboard, and no real external message
was sent (any_real_send={_esc(s['any_real_send'])}).</p>
<h2>Commercial funnel</h2><table>
<tr><th>verified</th><th>approved</th><th>accepted</th><th>delivered</th><th>replies</th>
<th>revenue</th><th>dup-sends</th></tr>
<tr><td>{_esc(m.get('verified_prospects', 0))}</td><td>{_esc(m.get('approved_drafts', 0))}</td>
<td>{_esc(m.get('sends_accepted', 0))}</td><td>{_esc(m.get('delivered', 0))}</td>
<td>{_esc(m.get('replies', 0))}</td><td>{_esc(m.get('revenue', 0))}</td>
<td>{_esc(m.get('duplicate_send_incidents', 0))}</td></tr></table>
<p>APIs: <a href="/api/comms">comms</a>,
<a href="/artifact?path=report/FINAL_E2E_REPORT.md">final report</a></p>
</body></html>"""

        def _overview_html(self) -> str:
            status = service.status()
            st = status.get("state", {})
            if self._read_report("FINAL_PRODUCT_HEALTH.json") is not None:
                return self._comms_html()
            if self._read_report("NORMALIZED_FINDINGS.json") is not None:
                return self._presend_html()
            if isinstance(st.get("candidates"), list):
                return self._campaign_html(status, st)
            prospects = st.get("prospects", {})
            controllable = bool(status.get("controllable"))
            mode = status.get("mode", "IDLE")
            rows = []
            for pid, p in sorted(prospects.items()):
                epid = _esc(pid)
                rows.append(
                    f"<tr><td>{epid}</td><td>{_esc(p.get('url', ''))}</td>"
                    f"<td>{_esc(p.get('status', ''))}</td><td>{_esc(p.get('priority', ''))}</td>"
                    f"<td>{_esc(p.get('verified_defects', 0))}</td>"
                    f"<td><a href='/api/prospect?id={_esc(pid)}'>details</a></td></tr>"
                )
            manual = [pid for pid, p in prospects.items() if p.get("status") == "MANUAL_ACTION_REQUIRED"]
            running = bool(status.get("running"))
            if controllable:
                # Stop Safely = graceful cancel (finish the current unit, stop future work);
                # Cancel = global kill (interrupt the active safe loop promptly). No forced kill.
                controls = (
                    '<button onclick="ctl(\'pause\')">Pause</button>'
                    '<button onclick="ctl(\'resume\')">Resume</button>'
                    '<button onclick="ctl(\'cancel\')">Stop Safely</button>'
                    '<button onclick="ctl(\'kill\')" style="color:#a00">Cancel (kill)</button>'
                )
            else:
                controls = ("<em>Controls unavailable — this run is "
                            f"<strong>{_esc(mode)}</strong> (read-only).</em>")
            # The guarded start panel is offered only when nothing is running (idle / finished).
            start_panel = "" if running else _START_PANEL_HTML
            return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{SCOUT_PRODUCT_NAME} v{SCOUT_VERSION}</title>
<style>body{{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:1000px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;text-align:left}}
button{{margin-right:.5rem;padding:.4rem .8rem}}code{{background:#f4f4f4;padding:2px 4px}}
.mode{{padding:2px 8px;border-radius:4px;background:#eef;font-weight:bold}}</style></head>
<body><h1>{SCOUT_PRODUCT_NAME} <small>v{SCOUT_VERSION}</small></h1>
<p>Run <code>{_esc(status.get('run_id', ''))}</code> — mode <span class=mode>{_esc(mode)}</span>
— status <strong>{_esc(st.get('status', 'n/a'))}</strong> — running: {_esc(status.get('running'))}</p>
<p>Controls: {controls}</p>
<p>Manual-action prospects: {len(manual)} — Live: <a href="/api/events">events</a>,
<a href="/api/status">status</a>, <a href="/health">health</a> · Operator:
<a href="/results">results</a>, <a href="/projects">projects</a>, <a href="/tools">tool readiness</a></p>
<h2>Prospects</h2><table><tr><th>id</th><th>url</th><th>status</th><th>priority</th>
<th>defects</th><th></th></tr>{''.join(rows) or '<tr><td colspan=6>none yet</td></tr>'}</table>
{start_panel}
<script>const CSRF={json.dumps(csrf_token)};
function ctl(a){{fetch('/api/control?action='+a,{{method:'POST',headers:{{'X-Scout-CSRF':CSRF}}}})
.then(r=>r.json()).then(j=>{{if(!j.ok)alert('control refused: '+(j.message||j.error));location.reload()}})}}
function startCampaign(){{
 var seeds=(document.getElementById('seeds').value||'').split(/[\\n,]+/).map(s=>s.trim()).filter(Boolean);
 if(!seeds.length){{alert('enter at least one public https URL');return;}}
 if(!document.getElementById('confirm').checked){{alert('please confirm the bounded read-only scan');return;}}
 var key=(crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+Math.random();
 fetch('/api/campaign/start',{{method:'POST',headers:{{'Content-Type':'application/json','X-Scout-CSRF':CSRF}},
  body:JSON.stringify({{confirm:true,idempotency_key:key,seeds:seeds,
   campaign:document.getElementById('campaign').value||'adhoc',
   max_pages:parseInt(document.getElementById('maxpages').value||'5',10)}})}})
 .then(r=>r.json()).then(j=>{{if(j.ok){{location.reload();}}
  else{{alert('start refused: '+(j.message||j.error)+(j.rejected&&j.rejected.length?'\\n'+j.rejected.map(x=>x.url+': '+x.reason).join('\\n'):''));}}}})
 .catch(e=>alert('start failed: '+e));}}
</script>
</body></html>"""

        # --- v3.1 operator dashboard pages (Overview / Work / Activity / Settings) -------------
        def _work_actions_script(self) -> str:
            return (
                "const CSRF=" + json.dumps(csrf_token) + ";\n"
                "function setStatus(m,ok){var s=document.getElementById('copystatus');"
                "if(s){s.textContent=m;s.className=ok?'copyok':'muted';}}\n"
                # Double-submit safe: the initiating button is disabled while the mutation is in
                # flight and only re-enabled on failure (success reloads).
                "function wact(btn,action,extra){if(btn){if(btn.dataset.busy)return;"
                "btn.dataset.busy='1';btn.disabled=true;}var b=Object.assign({},extra||{});"
                "fetch('/api/work/'+action,{method:'POST',headers:{'Content-Type':'application/json',"
                "'X-Scout-CSRF':CSRF},body:JSON.stringify(b)}).then(r=>r.json()).then(function(j){"
                "if(j.ok){location.reload();}else{alert(j.error||'refused');"
                "if(btn){btn.disabled=false;delete btn.dataset.busy;}}}).catch(function(e){"
                "alert(''+e);if(btn){btn.disabled=false;delete btn.dataset.busy;}});}\n"
                "function copyText(id){var el=document.getElementById(id);var t=el?el.textContent:'';"
                "if(navigator.clipboard&&navigator.clipboard.writeText){"
                "navigator.clipboard.writeText(t).then(function(){setStatus('Copied \\u2713',true);},"
                "function(){setStatus('Copy failed \\u2014 select the text manually',false);});}"
                "else{setStatus('Copy not supported \\u2014 select the text manually',false);}}\n")

        def _poll_html(self) -> str:
            return ('<div class="row" style="font-size:12px"><span id="pollstate" class="muted" '
                    'aria-live="polite">Live</span><span class="muted">·</span>'
                    '<span class="muted">Last updated <span id="lastupd">just now</span></span>'
                    '<span id="pollbanner" hidden> · <a href="#" '
                    'onclick="location.reload();return false">Updates available — Refresh</a></span></div>')

        def _poll_script(self, endpoint: str, sig_keys: str) -> str:
            # Bounded same-origin polling: refresh a freshness indicator and flag when the persisted
            # state changed; it NEVER auto-reloads (so typing / confirm dialogs are never interrupted)
            # - the operator clicks Refresh. Pauses when the tab is hidden.
            return (
                "(function(){var base=null;var url=" + json.dumps(endpoint) + ";"
                "function sig(j){try{return JSON.stringify((" + sig_keys + ")(j));}catch(e){return '';}}"
                "function tick(){if(document.hidden)return;"
                "fetch(url,{headers:{'X-Scout-CSRF':CSRF}}).then(r=>r.json()).then(function(j){"
                "var s=sig(j);if(base===null)base=s;"
                "var d=new Date();var lu=document.getElementById('lastupd');"
                "if(lu)lu.textContent=d.toLocaleTimeString();"
                "var ps=document.getElementById('pollstate');if(ps)ps.textContent='Live';"
                "if(s!==base){var b=document.getElementById('pollbanner');if(b)b.hidden=false;}"
                "}).catch(function(){var p=document.getElementById('pollstate');"
                "if(p)p.textContent='offline (retrying)';});}"
                "setInterval(tick,10000);tick();})();\n")

        def _operator_overview_page(self) -> str:
            ov = self._read_model().overview()
            def _att(a):
                return (f'<div class="card"><div class="row" style="justify-content:space-between">'
                        f'<div><strong>{_esc(a["title"])}</strong> {_badge(a["status"], "attention")}<br>'
                        f'<span class="muted">{_esc(a["project_id"])} — {_esc(a["reason"])}</span></div>'
                        f'<a class="btn primary" href="{_esc(a["href"])}">Open</a></div></div>')
            att = "".join(_att(a) for a in ov.attention) or (
                '<div class="card empty"><strong>You\'re all caught up</strong>'
                '<div class="muted">No projects require your attention.</div></div>')
            def _wrow(p):
                return (f'<tr><td><a href="{_esc(p["href"])}">{_esc(p["title"])}</a></td>'
                        f'<td>{_badge(p["stage"])}</td><td>{_badge(p["health"], p["health"])}</td>'
                        f'<td>{_esc(p["next_action"])}</td></tr>')
            work = "".join(_wrow(p) for p in ov.active_work)
            work_tbl = (f'<table><caption>Active work</caption><tr><th>Project</th><th>Stage</th>'
                        f'<th>Health</th><th>Next action</th></tr>{work}</table>'
                        if work else '<div class="card empty muted">No active work.</div>')
            def _crow(c):
                return (f'<tr><td>{_esc(c["title"])}</td><td>{_badge(c["status"])}</td>'
                        f'<td>{_esc(c["next_action"])}</td></tr>')
            camps = "".join(_crow(c) for c in ov.active_campaigns)
            camp_tbl = (f'<table><caption>Active Scout campaigns</caption><tr><th>Campaign</th>'
                        f'<th>Status</th><th>Next action</th></tr>{camps}</table>'
                        if camps else '<div class="card empty muted">No active Scout campaigns. '
                        '<a href="/scout">Open Scout</a></div>')
            body = (f'<h1>Overview</h1>'
                    f'<div class="row"><span class="chip">Projects {ov.counts.get("projects", 0)}</span>'
                    f'<span class="chip">Needs attention {ov.counts.get("attention", 0)}</span>'
                    f'<span class="chip">Campaigns {ov.counts.get("campaigns", 0)}</span>'
                    f'<button class="btn" onclick="location.reload()">Refresh</button></div>'
                    f'{self._poll_html()}'
                    f'<h2>Needs your attention</h2>{att}'
                    f'<h2>Active work</h2><div class="scrollx">{work_tbl}</div>'
                    f'<h2>Scout</h2><div class="scrollx">{camp_tbl}</div>')
            script = ("const CSRF=" + json.dumps(csrf_token) + ";\n"
                      + self._poll_script("/api/overview",
                                          "function(j){return [(j.counts||{}).attention,"
                                          "(j.attention||[]).map(function(a){return a.project_id+a.status})]}"))
            return _page("AI QA Factory — Overview", "/", body, script)

        _WORK_VIEWS = (("all", "All Work"), ("needs_attention", "Needs Attention"),
                       ("ready_to_execute", "Ready to Execute"), ("in_progress", "In Progress"),
                       ("blocked", "Blocked"), ("ready_for_review", "Ready for Review"),
                       ("ready_for_delivery", "Ready for Delivery"),
                       ("delivery_prepared", "Delivery Prepared"), ("completed", "Completed"))

        def _work_list_page(self, q) -> str:
            view = (q.get("view") or ["all"])[0]
            data = self._read_model().project_list(view=view)
            views = "".join(
                f'<a class="chip" href="/work?view={v}" '
                f'{"style=font-weight:600" if v == view else ""}>{_esc(lbl)}</a>'
                for v, lbl in self._WORK_VIEWS)
            def _row(p):
                return (f'<tr><td><a href="{_esc(p["href"])}">{_esc(p["title"])}</a>'
                        f'<div class="muted">{_esc(p["project_id"])}</div></td>'
                        f'<td>{_badge(p["stage"])}</td><td>{_badge(p["health"], p["health"])}</td>'
                        f'<td>{_esc(p["next_action"])}</td><td class="muted">{_esc(p["updated"])}</td></tr>')
            rows = "".join(_row(p) for p in data["projects"])
            table = (f'<table><caption>{data["total"]} project(s) — view: {_esc(view)}</caption>'
                     f'<tr><th>Project</th><th>Stage</th><th>Health</th><th>Next action</th>'
                     f'<th>Updated</th></tr>{rows}</table>' if rows
                     else '<div class="card empty">No projects in this view. '
                          '<a href="/work?view=all">Clear filter</a></div>')
            create = (
                '<details class="card"><summary>Create work from a pasted client brief</summary>'
                '<p class="muted">Analysis only — nothing is executed. This reuses analyze-job.</p>'
                '<p><label>Project name (optional)<br><input id="cw_pid" placeholder="my-project"></label></p>'
                '<p><label>Source platform (optional)<br><input id="cw_src" placeholder="upwork / direct"></label></p>'
                '<p><label>Client brief<br><textarea id="cw_brief" rows="5" style="width:100%"></textarea></label></p>'
                '<p><button class="btn primary" onclick="createWork()">Analyze brief</button></p>'
                '<p class="muted">No Upwork API — paste the brief and (optionally) a source reference.</p>'
                '</details>')
            script = (self._work_actions_script() +
                      "function createWork(){var b=document.getElementById('cw_brief').value.trim();"
                      "if(!b){alert('paste a client brief');return;}"
                      "fetch('/api/work/analyze',{method:'POST',headers:{'Content-Type':'application/json',"
                      "'X-Scout-CSRF':CSRF},body:JSON.stringify({text:b,"
                      "project_id:document.getElementById('cw_pid').value.trim(),"
                      "source_platform:document.getElementById('cw_src').value.trim()})})"
                      ".then(r=>r.json()).then(j=>{if(j.ok){location.href='/work/'+j.project_id;}"
                      "else{alert(j.error||'refused');}}).catch(e=>alert(''+e));}")
            body = (f'<h1>Work</h1><div class="row">{views}'
                    f'<button class="btn" onclick="location.reload()">Refresh</button></div>'
                    f'{self._poll_html()}'
                    f'<div class="scrollx">{table}</div>{create}')
            # Poll the current view; the banner never auto-reloads, so the Create-work form is safe.
            script = (script + self._poll_script(
                "/api/work?view=" + view,
                "function(j){return (j.projects||[]).map(function(p){return p.project_id+p.status})}"))
            return _page("AI QA Factory — Work", "/work", body, script)

        def _work_detail_json(self, pid):
            from core.dashboard.actions import ProjectDetailBuilder
            d = ProjectDetailBuilder(service.output_dir).detail(pid)
            return d or {"error": "not found", "project_id": pid}

        _DETAIL_TABS = (("summary", "Summary"), ("plan", "Plan"), ("results", "Results"),
                        ("delivery", "Delivery"))

        def _work_detail_page(self, pid, q=None) -> str:
            from core.dashboard.actions import ProjectDetailBuilder
            b = ProjectDetailBuilder(service.output_dir)
            d = b.detail(pid)
            if d is None:
                return _page("Project not found", "/work",
                             '<h1>Project not found</h1><p><a href="/work">&larr; Work</a></p>')
            q = q or {}
            sel = (q.get("tab") or ["summary"])[0]
            if sel not in [t[0] for t in self._DETAIL_TABS]:
                sel = "summary"
            h = d["header"]
            safe_pid = "".join(c for c in pid if c.isalnum() or c in "._-")
            actbtns = []
            for a in d["allowed_actions"]:
                cls = "btn primary" if a.get("primary") else "btn"
                if a["kind"] == "http_mutation":
                    act = a["endpoint"].split("/")[-1]
                    if a.get("fields"):
                        fields_js = "[" + ",".join("'" + f + "'" for f in a["fields"]) + "]"
                        extra = ("Object.assign({project_id:'" + safe_pid + "'},promptFields("
                                 + fields_js + "))")
                    else:
                        extra = "{project_id:'" + safe_pid + "'}"
                    conf = ("if(!confirm('" + _esc(a["label"]) + "?'))return;" if a.get("confirm") else "")
                    onclick = conf + "wact(this,'" + act + "'," + extra + ")"
                    actbtns.append(f'<button class="{cls}" onclick="{onclick}">{_esc(a["label"])}</button>')
                elif a["id"] == "open_vscode":
                    actbtns.append(f'<a class="{cls}" href="{_esc(_vscode_file_uri(d["workspace_path"]))}">'
                                   f'{_esc(a["label"])}</a>')
                elif a["id"] == "copy_work_order":
                    actbtns.append('<button class="btn" onclick="copyText(\'workorder\')">'
                                   'Copy Work Order</button>')
                elif a["id"] == "copy_workspace":
                    actbtns.append('<button class="btn" onclick="copyText(\'wspath\')">'
                                   'Copy Workspace Path</button>')
                elif a["id"] == "refresh":
                    actbtns.append('<button class="btn" onclick="location.reload()">Refresh</button>')
            header = (f'<p><a href="/work">&larr; Work</a></p><h1>{_esc(h["title"])}</h1>'
                      f'<div class="row">{_badge(h["stage"])} {_badge(h["health"], h["health"])} '
                      f'<span class="muted">{_esc(h["source"])} · {h["progress"]}%</span></div>'
                      f'{self._poll_html()}'
                      f'<div class="row" style="margin:.6rem 0">{"".join(actbtns)}'
                      f'<span id="copystatus" class="muted" aria-live="polite"></span></div>')
            summary = d["summary"]
            blockers = "".join(f"<li>{_esc(x)}</li>" for x in summary["blockers"]) or "<li class=muted>none</li>"
            panel = {
                "summary": (
                    '<div class="card">'
                    f'<p><strong>Next:</strong> {_esc(summary["next_action"])}</p>'
                    f'<p><strong>Validation:</strong> {summary["tests_passed"]}/{summary["tests_run"]} · '
                    f'evidence {summary["evidence_count"]}</p>'
                    f'<p><strong>Blockers:</strong></p><ul>{blockers}</ul></div>'),
                "plan": (
                    '<div class="card">'
                    f'<p><strong>Intent:</strong> {_esc(d["plan"]["client_intent"])}</p>'
                    f'<p><strong>Verdict:</strong> {_badge(d["plan"]["verdict"] or "n/a")}</p>'
                    f'<details><summary>Requirements &amp; questions</summary>'
                    f'<ul>{"".join(f"<li>{_esc(r)}</li>" for r in d["plan"]["requirements"]) or "<li class=muted>none</li>"}</ul>'
                    f'</details></div>'),
                "results": (
                    '<div class="card">'
                    f'<p>Validation: {_badge("PASS" if d["results"]["validation_passed"] else "pending", "ok" if d["results"]["validation_passed"] else "")}</p>'
                    f'<p class="muted">Artifacts: {_esc(", ".join(str(a) for a in d["results"]["artifacts"]) or "none")}</p>'
                    f'<details open><summary>Evidence ({len(d["results"]["evidence"])})</summary>'
                    f'<ul>{"".join(self._evidence_li(e) for e in d["results"]["evidence"]) or "<li class=muted>none</li>"}</ul>'
                    f'</details></div>'),
                "delivery": (
                    '<div class="card">'
                    f'<p>State: {_badge(d["delivery"]["status"], "attention" if d["delivery"]["status"] == "DELIVERY_PREPARED" else "")}</p>'
                    f'<p class="muted">Reviewed by {_esc(d["delivery"]["reviewed_by"] or "—")} · '
                    f'digest {_esc((d["delivery"]["manifest_digest"] or "—")[:23])}</p>'
                    f'<details><summary>Included files ({len(d["delivery"]["included_files"])})</summary>'
                    f'<ul>{"".join(f"<li>{_esc(x)}</li>" for x in d["delivery"]["included_files"]) or "<li class=muted>not prepared</li>"}</ul>'
                    f'</details>'
                    '<p class="muted">mark-delivered records your manual send; the Dashboard sends nothing.</p></div>'),
            }
            tablist = ('<div class="tabs" role="tablist" aria-label="Project sections">' + "".join(
                f'<button role="tab" id="tab-{tid}" aria-controls="panel-{tid}" '
                f'aria-selected="{"true" if tid == sel else "false"}" '
                f'tabindex="{"0" if tid == sel else "-1"}" onclick="selTab(\'{tid}\')">{label}</button>'
                for tid, label in self._DETAIL_TABS) + '</div>')
            panels = "".join(
                f'<div role="tabpanel" id="panel-{tid}" aria-labelledby="tab-{tid}" '
                f'{"" if tid == sel else "hidden"}>{panel[tid]}</div>' for tid, _l in self._DETAIL_TABS)
            hidden = (f'<div style="display:none"><pre id="wspath">{_esc(d["workspace_path"])}</pre>'
                      f'<pre id="workorder">{_esc(b.work_order(pid) or "")}</pre></div>')
            script = (
                self._work_actions_script() +
                "function promptFields(names){var o={};for(var i=0;i<names.length;i++){"
                "var v=prompt(names[i]);if(v===null)throw 'cancelled';o[names[i]]=v;}return o;}\n"
                "function selTab(id){document.querySelectorAll('[role=tab]').forEach(function(t){"
                "var on=t.id==='tab-'+id;t.setAttribute('aria-selected',on?'true':'false');"
                "t.tabIndex=on?0:-1;});document.querySelectorAll('[role=tabpanel]').forEach(function(p){"
                "p.hidden=p.id!=='panel-'+id;});var u=new URL(location);u.searchParams.set('tab',id);"
                "history.replaceState(null,'',u);}\n"
                "var tl=document.querySelector('[role=tablist]');if(tl){tl.addEventListener('keydown',"
                "function(e){var ts=[].slice.call(document.querySelectorAll('[role=tab]'));"
                "var i=ts.findIndex(function(t){return t.getAttribute('aria-selected')==='true';});"
                "if(e.key==='ArrowRight'||e.key==='ArrowLeft'){var n=(i+(e.key==='ArrowRight'?1:"
                "ts.length-1))%ts.length;var id=ts[n].id.replace('tab-','');selTab(id);ts[n].focus();"
                "e.preventDefault();}});}\n" +
                self._poll_script("/api/work/" + safe_pid, "function(j){return [j.header&&j.header.status]}"))
            return _page(f"AI QA Factory — {pid}", "/work", header + tablist + panels + hidden, script)

        def _scout_home_page(self) -> str:
            # The operator Scout home in the shared layout, reusing the SAME ScoutService status and
            # the SAME guarded /api/control + /api/campaign/start endpoints (no second service/state).
            status = service.status()
            st = status.get("state", {})
            mode = status.get("mode", "IDLE")
            controllable = bool(status.get("controllable"))
            running = bool(status.get("running"))
            prospects = st.get("prospects", {})
            if controllable:
                controls = ('<button class="btn" onclick="ctl(\'pause\')">Pause</button>'
                            '<button class="btn" onclick="ctl(\'resume\')">Resume</button>'
                            '<button class="btn" onclick="ctl(\'cancel\')">Stop Safely</button>'
                            '<button class="btn danger" onclick="ctl(\'kill\')">Cancel (kill)</button>')
            else:
                controls = (f'<em class="muted">Controls unavailable — this run is '
                            f'<strong>{_esc(mode)}</strong> (read-only).</em>')
            prows = "".join(
                f'<tr><td>{_esc(pid)}</td><td class="muted">{_esc(p.get("url", ""))}</td>'
                f'<td>{_badge(p.get("status", ""))}</td><td>{_esc(p.get("priority", ""))}</td>'
                f'<td>{_esc(p.get("verified_defects", 0))}</td></tr>'
                for pid, p in sorted(prospects.items()))
            table = (f'<table><caption>Prospects in this run</caption><tr><th>ID</th><th>URL</th>'
                     f'<th>Status</th><th>Priority</th><th>Defects</th></tr>{prows}</table>'
                     if prows else '<div class="card empty muted">No prospects in this run.</div>')
            start_panel = "" if running else _START_PANEL_HTML
            body = (f'<h1>Scout</h1><p class="muted">{_esc(SCOUT_PRODUCT_NAME)} — bounded, read-only '
                    f'discovery + QA. Nothing is scanned or sent without your explicit action.</p>'
                    f'<div class="card"><p>Run <code>{_esc(status.get("run_id", ""))}</code> · mode '
                    f'{_badge(mode)} · status {_badge(st.get("status", "n/a"))}</p>'
                    f'<div class="row">{controls}</div></div>'
                    f'<div class="row"><a class="chip" href="/scout/campaigns">Campaigns</a>'
                    f'<a class="chip" href="/results">Results</a></div>'
                    f'<div class="scrollx">{table}</div>{start_panel}')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";\n"
                "function ctl(a){fetch('/api/control?action='+a,{method:'POST',"
                "headers:{'X-Scout-CSRF':CSRF}}).then(r=>r.json()).then(function(j){"
                "if(!j.ok)alert('control refused: '+(j.message||j.error));location.reload();});}\n"
                "function startCampaign(){var seeds=(document.getElementById('seeds').value||'')"
                ".split(/[\\n,]+/).map(function(s){return s.trim();}).filter(Boolean);"
                "if(!seeds.length){alert('enter at least one public https URL');return;}"
                "if(!document.getElementById('confirm').checked){alert('please confirm the bounded "
                "read-only scan');return;}var key=(crypto&&crypto.randomUUID)?crypto.randomUUID():"
                "String(Date.now())+Math.random();"
                "fetch('/api/campaign/start',{method:'POST',headers:{'Content-Type':'application/json',"
                "'X-Scout-CSRF':CSRF},body:JSON.stringify({confirm:true,idempotency_key:key,seeds:seeds,"
                "campaign:document.getElementById('campaign').value||'adhoc',"
                "max_pages:parseInt(document.getElementById('maxpages').value||'5',10)})})"
                ".then(r=>r.json()).then(function(j){if(j.ok){location.reload();}else{"
                "alert('start refused: '+(j.message||j.error));}}).catch(function(e){"
                "alert('start failed: '+e);});}\n")
            return _page("AI QA Factory — Scout", "/scout", body, script)

        def _scout_campaigns_page(self) -> str:
            ov = self._read_model().overview()
            # Reuse the unified project index for scout campaigns (no second store).
            from core.orchestration.project_index import ProjectIndex
            camps = [p for p in ProjectIndex(service.output_dir).list_projects()
                     if p.type == "scout_campaign"]
            rows = "".join(
                f'<tr><td>{_esc(c.title)}</td><td>{_badge(c.lifecycle_state)}</td>'
                f'<td>{c.progress}%</td><td>{c.evidence_count}</td>'
                f'<td class="muted">{_esc(c.operator_next_action)}</td></tr>' for c in camps)
            table = (f'<table><caption>Scout campaigns</caption><tr><th>Campaign</th><th>Status</th>'
                     f'<th>Progress</th><th>Evidence</th><th>Next action</th></tr>{rows}</table>'
                     if rows else '<div class="card empty muted">No campaigns yet. '
                     '<a href="/scout">Open Scout to start one</a>.</div>')
            body = (f'<h1>Scout campaigns</h1><div class="row">'
                    f'<a class="chip" href="/scout">Scout home</a>'
                    f'<a class="chip" href="/results">Results</a>'
                    f'<span class="chip">Active {len(ov.active_campaigns)}</span></div>'
                    f'<div class="scrollx">{table}</div>'
                    f'<p class="muted">Campaign start + Pause/Resume/Stop Safely/Cancel controls are '
                    f'on <a href="/scout">Scout home</a> (bounded, read-only; nothing is sent).</p>')
            return _page("AI QA Factory — Scout campaigns", "/scout", body)

        # --- Scout data pages, unified into the shared layout (reuse existing data) -----------
        def _results_page(self, q) -> str:
            snap = self._results_snapshot()
            companies = snap.get("companies", [])
            qtext = (q.get("q") or [""])[0].strip().lower()
            fcontact = (q.get("contact") or [""])[0].strip()
            fsev = (q.get("sev") or [""])[0].strip().lower()
            sev_min = _SEV_RANK.get(fsev, 0)

            def _keep(c):
                if qtext and qtext not in (str(c["name"]) + " " + str(c["domain"])).lower():
                    return False
                if fcontact and str(c.get("contact_status", "")) != fcontact:
                    return False
                if sev_min and _SEV_RANK.get(str(c.get("max_severity", "")).lower(), 0) < sev_min:
                    return False
                return True

            filtered = [c for c in companies if _keep(c)]
            contact_states = sorted({str(c.get("contact_status", "")) for c in companies if c.get("contact_status")})
            rows = "".join(
                f'<tr><td><a href="/company?id={_esc(c["company_id"])}">{_esc(c["name"] or c["company_id"])}</a></td>'
                f'<td class="muted">{_esc(c["domain"])}</td>'
                f'<td>{_badge(c.get("max_severity") or "none", _sev_badge_kind(c.get("max_severity", "")))}</td>'
                f'<td>{_esc(c["findings"])}</td><td class="muted">{_esc(c["contact"])}</td>'
                f'<td>{_badge(c["contact_status"] or "—")}</td></tr>' for c in filtered)
            table = (f'<table><caption>{len(filtered)} of {len(companies)} companies</caption>'
                     f'<tr><th>Company</th><th>Domain</th><th>Max severity</th><th>Findings</th>'
                     f'<th>Public contact</th><th>Contact state</th></tr>{rows}</table>' if rows
                     else '<div class="card empty muted">No companies match these filters. '
                          '<a href="/results">Clear filters</a>.</div>')
            sev_opts = "".join(
                f'<option value="{s}"{" selected" if fsev == s else ""}>{s.title()}</option>'
                for s in ("", "low", "medium", "high", "critical"))
            con_opts = '<option value="">Any contact state</option>' + "".join(
                f'<option value="{_esc(s)}"{" selected" if fcontact == s else ""}>{_esc(s)}</option>'
                for s in contact_states)
            active = []
            if qtext:
                active.append(f'<span class="chip">search: {_esc(qtext)}</span>')
            if fcontact:
                active.append(f'<span class="chip">contact: {_esc(fcontact)}</span>')
            if fsev:
                active.append(f'<span class="chip">severity ≥ {_esc(fsev)}</span>')
            chips = (f'<div class="row">{"".join(active)}<a class="chip" href="/results">Clear all</a></div>'
                     if active else "")
            form = (
                '<form class="card" method="get" action="/results" role="search">'
                '<div class="row">'
                f'<label>Search<br><input name="q" value="{_esc((q.get("q") or [""])[0])}" '
                'placeholder="company or domain"></label>'
                f'<label>Contact state<br><select name="contact">{con_opts}</select></label>'
                f'<label>Min severity<br><select name="sev">{sev_opts}</select></label>'
                '<span style="align-self:end"><button class="btn primary" type="submit">Filter</button> '
                '<a class="btn" href="/results">Reset</a></span></div></form>')
            body = (f'<h1>Results</h1><div class="row"><a class="chip" href="/scout">Scout home</a>'
                    f'<a class="chip" href="/scout/campaigns">Campaigns</a></div>'
                    f'{form}{chips}<div class="scrollx">{table}</div>'
                    '<p class="muted">Read-only. No outreach is sent from here.</p>')
            return _page("AI QA Factory — Results", "/scout", body)

        def _company_page(self, cid: str) -> str:
            d = self._company_detail(cid)
            if d is None:
                return _page("Company not found", "/scout",
                             '<h1>Company not found</h1><p>Unknown company id, or no data for this run '
                             'yet.</p><p><a href="/results">&larr; Results</a></p>')
            frows = "".join(
                f'<tr><td>{_esc(f["capability"])}</td>'
                f'<td>{_badge(f["severity"], _sev_badge_kind(f.get("severity", "")))}</td>'
                f'<td>{_esc(f["title"])}</td><td class="muted">{_esc(f["verification_state"])}</td>'
                f'<td>{_esc(f["client_safe"])}</td></tr>' for f in d["findings"])
            contact, prov, draft = d["contact"], d["provenance"], d["draft"]
            recip = contact.get("normalized_value", "")
            compose = _gmail_compose_url(recip, draft.get("subject", ""), draft.get("body", ""))
            gmail_action = (f'<a class="btn" href="{_esc(compose)}" target="_blank" rel="noopener">'
                            "Open in Gmail</a>" if recip and draft else "<em>no draft/contact yet</em>")
            body = (
                f'<p><a href="/results">&larr; Results</a></p>'
                f'<h1>{_esc(d["company"].get("canonical_name") or cid)}</h1>'
                f'<p class="muted">domain {_esc(d["company"].get("primary_domain"))}</p>'
                f'<h2>Findings</h2><div class="scrollx"><table><caption>{len(d["findings"])} finding(s)</caption>'
                f'<tr><th>Capability</th><th>Severity</th><th>Title</th><th>Verification</th>'
                f'<th>Client-safe</th></tr>{frows or "<tr><td colspan=5 class=muted>none</td></tr>"}</table></div>'
                '<h2>Public contact + provenance</h2><div class="card">'
                f'<p>Contact: <code>{_esc(recip)}</code> ({_esc(contact.get("status"))}) · '
                f'source {_esc(prov.get("source_category"))} · published '
                f'{_esc(prov.get("publicly_published_for_contact"))} · verified '
                f'{_esc(prov.get("last_verified_at"))}</p>'
                f'<p class="muted">source URL: {_esc(prov.get("source_url"))}</p></div>'
                '<h2>Draft (edit in Gmail; nothing is sent from here)</h2><div class="card">'
                f'<p><strong>Subject:</strong> {_esc(draft.get("subject", "(none)"))}</p>'
                f'<pre>{_esc(draft.get("body", "(no draft)"))}</pre>'
                f'<p>{gmail_action} <span class="muted">— then send manually in Gmail and mark the '
                'company contacted. Live API send stays the optional, one-at-a-time scout send CLI '
                'path.</span></p></div>')
            return _page(f"AI QA Factory — {cid}", "/scout", body)

        def _projects_page(self) -> str:
            snap = self._projects_snapshot()
            rows = "".join(
                f'<tr><td>{_esc(p["project_id"])}</td><td>{_badge(p["type"])}</td>'
                f'<td>{_esc(p["title"])}</td><td>{_badge(p["lifecycle_state"])}</td>'
                f'<td>{_esc(p["progress"])}%</td><td>{_esc(len(p["blockers"]))}</td>'
                f'<td>{_esc(p["evidence_count"])}</td>'
                f'<td class="muted">{_esc(p["operator_next_action"])}</td></tr>'
                for p in snap.get("projects", []))
            table = (f'<table><caption>{snap.get("project_count", 0)} projects + campaigns</caption>'
                     f'<tr><th>Project</th><th>Type</th><th>Title</th><th>State</th><th>Progress</th>'
                     f'<th>Blockers</th><th>Evidence</th><th>Next action</th></tr>{rows}</table>'
                     if rows else '<div class="card empty muted">None yet.</div>')
            body = (f'<h1>Projects</h1><p class="muted">Client-work projects and Scout campaigns from '
                    f'the existing project state (read-only). See also <a href="/work">Work</a>.</p>'
                    f'<div class="scrollx">{table}</div>')
            return _page("AI QA Factory — Projects", "/work", body)

        def _evidence_li(self, e) -> str:
            rel = e.get("relative_path", "")
            integ = e.get("integrity", "unverified")
            kind = {"verified": "ok", "stale": "blocked"}.get(integ, "")
            label = {"verified": "Verified", "stale": "Stale", "unverified": "Unverified"}.get(integ, "")
            link = (f' — <a href="{_esc(e["href"])}">Preview</a>' if e.get("href") else "")
            return (f'<li>{_esc(rel)} <span class="muted">{_esc(e.get("kind", ""))}</span> '
                    f'{_badge(label, kind)}{link}</li>')

        def _activity_json(self, project):
            events = []
            from core.orchestration.work_execution import WorkExecutionService
            wx = WorkExecutionService(output_dir=service.output_dir)
            index = self._read_model().project_list(view="all")["projects"]
            targets = [project] if project else [p["project_id"] for p in index]
            for pid in targets:
                try:
                    st = wx._load_state(pid)
                except Exception:
                    continue
                for h in st.history[-50:]:
                    hd = h.to_dict() if hasattr(h, "to_dict") else dict(h)
                    events.append({"time": hd.get("at", ""), "actor": hd.get("actor", ""),
                                   "action": f'{hd.get("from_state")} -> {hd.get("to_state")}',
                                   "object": pid, "result": hd.get("reason", "")})
            events.sort(key=lambda e: e["time"], reverse=True)
            return {"schema": "dashboard-read-model/v1", "events": events[:200]}

        def _activity_page(self, q) -> str:
            data = self._activity_json((q.get("project") or [""])[0])
            rows = "".join(
                f'<tr><td class="muted">{_esc(e["time"])}</td><td>{_esc(e["actor"])}</td>'
                f'<td>{_esc(e["action"])}</td><td>{_esc(e["object"])}</td>'
                f'<td class="muted">{_esc(e["result"])}</td></tr>' for e in data["events"])
            table = (f'<table><caption>Recent state transitions</caption><tr><th>Time</th><th>Actor</th>'
                     f'<th>Action</th><th>Project</th><th>Result</th></tr>{rows}</table>' if rows
                     else '<div class="card empty muted">No activity yet.</div>')
            return _page("AI QA Factory — Activity", "/activity",
                         f'<h1>Activity</h1><div class="scrollx">{table}</div>')

        def _settings_page(self) -> str:
            from core.orchestration.tool_broker import ToolBroker
            gmail = next((t for t in ToolBroker(clock=lambda: "").discover()
                         if t.id == "gmail_personal"), None)
            gmail_state = gmail.ui_level if gmail else "Unknown"
            body = (
                '<h1>Settings</h1>'
                f'<div class="card"><h2>Workspace</h2>'
                f'<p>Output workspace: <code>{_esc(str(service.output_dir))}</code></p></div>'
                '<div class="card"><h2>Display density</h2>'
                '<div class="row"><button class="btn" onclick="setDensity(\'comfortable\')">Comfortable</button>'
                '<button class="btn" onclick="setDensity(\'compact\')">Compact</button></div>'
                '<p class="muted">Saved in this browser only (no server preference database).</p></div>'
                '<div class="card"><h2>Scout defaults (bounded, read-only)</h2>'
                '<p class="muted">1–10 public https seeds · static browser · concurrency 1 · read-only.</p></div>'
                f'<div class="card"><h2>Gmail</h2><p>Setup status: {_badge(gmail_state)} '
                '<span class="muted">(no secret is shown; live send is a separate opt-in CLI path)</span></p></div>')
            script = ("function setDensity(d){document.documentElement.setAttribute('data-density',d);"
                      "try{localStorage.setItem('qa_density',d);}catch(e){}}"
                      "try{var d=localStorage.getItem('qa_density');if(d)document.documentElement.setAttribute('data-density',d);}catch(e){}")
            return _page("AI QA Factory — Settings", "/settings", body, script)

        # Safe evidence preview/download for client-work projects (v3.1 M7). Path-confined, size-
        # bounded, correct MIME; ACTIVE content (html/svg/js/xml) is NEVER served inline - it is
        # returned as text/plain attachment so the browser cannot execute it. Images preview inline.
        _EV_IMG = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".gif": "image/gif", ".webp": "image/webp"}
        _EV_TEXT = {".txt", ".log", ".json", ".md", ".csv", ".ts", ".py"}
        _EV_ACTIVE = {".html", ".htm", ".svg", ".xml", ".js", ".mjs", ".xhtml"}
        _EV_MAX = 5 * 1024 * 1024

        def _work_evidence(self, project: str, rel: str):
            from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
            wx = WorkExecutionService(output_dir=service.output_dir)
            if not project or not rel:
                return self._json(400, {"error": "project and path are required"})
            try:
                ws = wx._ws(project)                       # validates the project id
                target = wx._confine(ws, rel)              # refuses traversal
            except WorkExecutionError:
                return self._json(403, {"error": "path not allowed"})
            if not target.is_file():
                return self._json(404, {"error": "not found"})
            if target.stat().st_size > self._EV_MAX:
                return self._json(413, {"error": "evidence too large to preview"})
            ext = target.suffix.lower()
            data = target.read_bytes()
            if ext in self._EV_IMG:
                ctype, disp = self._EV_IMG[ext], "inline"
            elif ext in self._EV_ACTIVE:
                ctype, disp = "text/plain; charset=utf-8", "attachment"   # never execute active content
            elif ext in self._EV_TEXT or ext == "":
                ctype, disp = "text/plain; charset=utf-8", "inline"
            else:
                ctype, disp = "application/octet-stream", "attachment"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            safe_name = Path(rel).name.replace('"', "")
            self.send_header("Content-Disposition", f'{disp}; filename="{safe_name}"')
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _tools_page(self) -> str:
            data = self._read_model().tools()
            def _lvl_kind(level):
                return {"Runtime Available": "ok", "Fixture Verified": "ok", "Live Verified": "ok",
                        "Blocked": "blocked", "Unavailable": "blocked"}.get(level, "")
            rows = "".join(
                f'<tr><td>{_esc(t["name"])}<div class="muted">{_esc(t["id"])}</div></td>'
                f'<td>{_esc(t["capability"])}</td><td>{_badge(t["ui_level"], _lvl_kind(t["ui_level"]))}</td>'
                f'<td class="muted">{_esc(t["readiness"])}</td>'
                f'<td class="muted">{_esc(t["reason"])}</td>'
                f'<td class="muted">{_esc(t["setup_action"])}</td></tr>' for t in data["tools"])
            table = (f'<table><caption>Honest readiness (no live MCP/network call; '
                     f'any_live_accepted={data["any_live_accepted"]})</caption>'
                     f'<tr><th>Tool</th><th>Capability</th><th>Level</th><th>Readiness</th>'
                     f'<th>Reason</th><th>Setup action</th></tr>{rows}</table>')
            body = (f'<h1>Tools</h1><p class="muted">Honest tool readiness (no live MCP/network call). '
                    f'A test file is never a runtime binding; a binding present is "Binding Available"; '
                    f'a checked runtime is "Runtime Available"; nothing is "Live Verified" without a '
                    f'real live acceptance.</p><div class="scrollx">{table}</div>')
            return _page("AI QA Factory — Tools · Tool readiness", "/tools", body)

        def _docs_page(self) -> str:
            docs = [("Product contract", "PRODUCT_CONTRACT_V3.md"),
                    ("Client work operator guide", "CLIENT_WORK_OPERATOR_GUIDE.md"),
                    ("Scout operator guide", "SCOUT_OPERATOR_GUIDE.md"),
                    ("Dashboard guide", "DASHBOARD_OPERATOR_GUIDE.md"),
                    ("Tool readiness guide", "TOOL_READINESS_GUIDE.md"),
                    ("Troubleshooting", "TROUBLESHOOTING_OPERATOR.md")]
            items = "".join(f"<li>{_esc(lbl)} — <code>docs/{_esc(f)}</code></li>" for lbl, f in docs)
            body = (f'<h1>Documentation</h1><div class="card"><p class="muted">Local documentation '
                    f'(open in your editor):</p><ul>{items}</ul></div>')
            return _page("AI QA Factory — Documentation", "/docs", body)

    return _Handler


_START_PANEL_HTML = """<h2>Start a bounded read-only campaign</h2>
<div style="border:1px solid #ccc;padding:1rem;border-radius:6px;max-width:640px">
<p>Runs the existing bounded, read-only Scout engine over 1&ndash;10 <strong>public https</strong>
seeds. It never sends email, submits forms, solves CAPTCHAs, or runs commands. Non-public / private
/ loopback targets are rejected.</p>
<p><label>Public seed URLs (one per line):<br>
<textarea id="seeds" rows="4" style="width:100%" placeholder="https://example.com/"></textarea></label></p>
<p><label>Campaign name: <input id="campaign" value="adhoc"></label>
&nbsp;<label>Max pages/site: <input id="maxpages" type="number" value="5" min="1" max="50" style="width:5rem"></label></p>
<p><label><input type="checkbox" id="confirm"> I confirm this is an authorized, bounded, read-only scan.</label></p>
<p><button onclick="startCampaign()">Start campaign</button></p>
</div>"""


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# --- v3.1 design system (local CSS tokens; no external assets) ---------------------------------
_TOKENS_CSS = """
:root{
 --bg:#f6f7f9; --surface:#fff; --surface-2:#eef1f4; --border:#d7dbe0; --text:#1a1d21;
 --muted:#4d565f; --primary:#1257c9; --primary-ink:#fff; --ok:#136c33; --attention:#7a5000;
 --danger:#a11208; --focus:#1257c9;
 --radius:8px; --pad:16px; --gap:12px; --maxw:1200px; --row:40px;
 --font:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
}
:root[data-density="compact"]{ --pad:10px; --gap:8px; --row:32px; }
*{box-sizing:border-box}
body{font-family:var(--font);margin:0;background:var(--bg);color:var(--text);line-height:1.5}
a{color:var(--primary);text-decoration:none} a:hover{text-decoration:underline}
header.top{background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5}
header.top .wrap{max-width:var(--maxw);margin:0 auto;display:flex;align-items:center;gap:var(--gap);padding:10px var(--pad)}
header.top .brand{font-weight:700} header.top nav{display:flex;gap:4px;margin-left:8px}
header.top nav a{padding:6px 12px;border-radius:6px;color:var(--muted)}
header.top nav a[aria-current="page"]{background:var(--surface-2);color:var(--text);font-weight:600}
main{max-width:var(--maxw);margin:0 auto;padding:var(--pad)}
html,body{max-width:100%;overflow-x:hidden}
header.top .wrap{flex-wrap:wrap} header.top nav{flex-wrap:wrap}
.scrollx{overflow-x:auto;max-width:100%;margin-bottom:var(--gap)}
h1{font-size:22px;margin:.2rem 0 1rem} h2{font-size:16px;margin:1.4rem 0 .6rem}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:var(--pad);margin-bottom:var(--gap)}
.muted{color:var(--muted)} .row{display:flex;gap:var(--gap);flex-wrap:wrap;align-items:center}
table{border-collapse:collapse;width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)}
caption{text-align:left;color:var(--muted);padding:6px 2px;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);font-size:13px;height:var(--row)}
th{background:var(--surface-2);color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--border);background:var(--surface-2)}
.badge.ok{color:var(--ok);border-color:#a6e3b8} .badge.attention{color:var(--attention);border-color:#e6cf7a}
.badge.blocked,.badge.danger{color:var(--danger);border-color:#f2b8b1} .badge.done{color:var(--muted)}
.btn{display:inline-block;padding:8px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:14px}
.btn.primary{background:var(--primary);border-color:var(--primary);color:var(--primary-ink)}
.btn.danger{border-color:#f2b8b1;color:var(--danger)}
.btn:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.chip{display:inline-flex;gap:6px;align-items:center;padding:2px 10px;background:var(--surface-2);border:1px solid var(--border);border-radius:999px;font-size:12px}
.empty{padding:2rem;text-align:center;color:var(--muted)}
input,select{padding:6px 8px;border:1px solid var(--border);border-radius:6px;font-size:14px;background:var(--surface);color:var(--text)}
pre{background:var(--surface-2);padding:.7rem;border-radius:6px;overflow:auto;white-space:pre-wrap;font-size:12px}
details>summary{cursor:pointer;color:var(--muted)}
.skeleton{background:linear-gradient(90deg,var(--surface-2),#e9edf1,var(--surface-2));border-radius:6px;height:14px}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin:1rem 0 0;flex-wrap:wrap}
.tabs [role=tab]{padding:8px 14px;border:1px solid transparent;border-bottom:none;background:none;cursor:pointer;color:var(--muted);border-radius:6px 6px 0 0;font-size:14px}
.tabs [role=tab][aria-selected=true]{background:var(--surface);border-color:var(--border);color:var(--text);font-weight:600;margin-bottom:-1px}
[role=tabpanel]{padding-top:.8rem} [role=tabpanel][hidden]{display:none}
.copyok{color:var(--ok)}
"""

_NAV = (("Overview", "/"), ("Scout", "/scout"), ("Work", "/work"))
_MORE = (("Tools", "/tools"), ("Activity", "/activity"), ("Settings", "/settings"),
         ("Documentation", "/docs"))


def _nav_html(active: str) -> str:
    links = []
    for label, href in _NAV:
        cur = ' aria-current="page"' if href == active else ""
        links.append(f'<a href="{href}"{cur}>{label}</a>')
    more = "".join(f'<a href="{h}">{lbl}</a>' for lbl, h in _MORE)
    return (f'<header class="top"><div class="wrap"><span class="brand">AI QA Factory</span>'
            f'<nav aria-label="Primary">{"".join(links)}'
            f'<details style="position:relative"><summary class="btn" style="padding:6px 12px">More</summary>'
            f'<div class="card" style="position:absolute;right:0;min-width:180px;z-index:10">{more}</div>'
            f'</details></nav></div></header>')


def _page(title: str, active: str, body: str, script: str = "") -> str:
    scr = f"<script>{script}</script>" if script else ""
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_esc(title)}</title><style>{_TOKENS_CSS}</style></head><body>"
            f"{_nav_html(active)}<main>{body}</main>{scr}</body></html>")


def _badge(text: str, kind: str = "") -> str:
    return f'<span class="badge {kind}">{_esc(text)}</span>'


_SEV_RANK = {"critical": 5, "high": 4, "medium": 3, "moderate": 3, "low": 2, "info": 1,
             "informational": 1}


def _max_severity(severities) -> str:
    best, best_rank = "", 0
    for s in severities:
        r = _SEV_RANK.get(str(s).strip().lower(), 0)
        if r > best_rank:
            best, best_rank = str(s), r
    return best


def _sev_badge_kind(sev: str) -> str:
    r = _SEV_RANK.get(str(sev).strip().lower(), 0)
    return "blocked" if r >= 4 else ("attention" if r == 3 else "")


def _vscode_file_uri(path: str) -> str:
    """A correctly-encoded cross-platform ``vscode://file/`` URI (v3.1 P1).

    Normalizes Windows separators to ``/`` and percent-encodes the path (spaces -> %20), keeping
    ``/`` and the drive-letter ``:``. Windows ``D:\\1QA AI\\proj`` -> ``vscode://file/D:/1QA%20AI/proj``;
    POSIX ``/home/u/proj`` -> ``vscode://file/home/u/proj``.
    """
    from urllib.parse import quote
    p = str(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "vscode://file" + quote(p, safe="/:@")


def _gmail_compose_url(to: str, subject: str, body: str) -> str:
    """A Gmail compose (draft) deep link — opens Gmail with the fields pre-filled. It NEVER sends;
    the operator reviews/edits and clicks Send manually."""
    from urllib.parse import quote
    return ("https://mail.google.com/mail/?view=cm&fs=1"
            f"&to={quote(to)}&su={quote(subject)}&body={quote(body)}")


def start_dashboard(service: ScoutService, host: str = "127.0.0.1", port: int = 0,
                    launcher: Optional[CampaignLauncher] = None,
                    csrf_token: Optional[str] = None,
                    operator_home: bool = False) -> Tuple[ThreadingHTTPServer, str]:
    """Start the dashboard (localhost only) and return (server, base_url). Non-blocking.

    ``launcher`` (defaults to a live ``CampaignLauncher`` with an empty local-host allowlist, so
    localhost/private targets stay rejected) backs the guarded start endpoint; ``csrf_token``
    defaults to a fresh per-server secret. Both are attached to the returned server for the
    operator/tests (``server.scout_csrf_token`` / ``server.scout_launcher``). ``operator_home``
    makes ``/`` the v3.1 Overview inbox when no Scout run is bound (the Scout run view is preserved
    at ``/`` for a run-bound dashboard, and always available at ``/scout``).
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("dashboard binds to localhost only")
    launcher = launcher or CampaignLauncher(service)
    token = secrets.token_urlsafe(32) if csrf_token is None else csrf_token
    server = ThreadingHTTPServer((host, port),
                                 _make_handler(service, launcher, token, operator_home))
    server.scout_csrf_token = token          # type: ignore[attr-defined]
    server.scout_launcher = launcher         # type: ignore[attr-defined]
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    out_dir = getattr(service, "output_dir", "outputs")
    # Publish the CSRF token to a local, per-port file so the loopback CLI control command can
    # authenticate. It lives under the (gitignored) output dir; a cross-origin page cannot read it.
    _publish_csrf_token(out_dir, bound_port, token)
    # Write an ownership record so `stop-local` can prove a process is THIS dashboard invocation
    # (PID + start time + command identity + port + repo) before ever stopping it (v3.0.2 M7).
    write_ownership_record(out_dir, bound_port, token)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{bound_host}:{bound_port}"


def csrf_token_path(output_dir: str, port: int) -> Path:
    return Path(output_dir) / "scout" / "_dashboard" / f"csrf-{int(port)}.token"


def _publish_csrf_token(output_dir: str, port: int, token: str) -> None:
    try:
        path = csrf_token_path(output_dir, port)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        try:                                   # best-effort restrictive perms (POSIX; no-op on Windows)
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        pass   # publishing is best-effort; the dashboard UI still works via the in-page token


def read_csrf_token(output_dir: str, port: int) -> Optional[str]:
    try:
        return csrf_token_path(output_dir, port).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# --- ownership record (v3.0.2 M7): lets `stop-local` prove a process is THIS dashboard -----------
_OWNERSHIP_MARKER = "main.py scout dashboard"


def ownership_path(output_dir: str, port: int) -> Path:
    return Path(output_dir) / "scout" / "_dashboard" / f"ownership-{int(port)}.json"


def write_ownership_record(output_dir: str, port: int, token: str) -> Optional[dict]:
    """Atomically write who owns the dashboard on ``port``: PID, process start time (anti PID
    reuse), the expected command identity, the workspace/repo, and a random owner token. Returns
    the record (or None if it could not be written)."""
    import sys
    from datetime import datetime, timezone
    record = {
        "schema": "dashboard-ownership/v1",
        "pid": os.getpid(),
        "port": int(port),
        "python_executable": sys.executable,
        "command_marker": _OWNERSHIP_MARKER,
        "argv": list(sys.argv),
        "repo": str(Path.cwd()),
        "workspace": str(Path(output_dir).resolve()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "owner_token": secrets.token_urlsafe(16),
    }
    try:
        path = ownership_path(output_dir, port)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)             # best-effort (POSIX; no-op on Windows)
        except OSError:
            pass
        return record
    except OSError:
        return None   # best-effort; the dashboard still works, stop-local just won't find a record


def remove_ownership_record(output_dir: str, port: int) -> None:
    try:
        ownership_path(output_dir, port).unlink()
    except OSError:
        pass
