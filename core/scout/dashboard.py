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
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _make_handler(service: ScoutService, launcher: CampaignLauncher, csrf_token: str):
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
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        # --- routing ---
        def do_GET(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            q = parse_qs(parsed.query)
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
                return self._html(200, self._tools_html())
            if path == "/api/projects":
                return self._json(200, self._projects_snapshot())
            if path == "/projects":
                return self._html(200, self._projects_html())
            if path == "/api/results":
                return self._json(200, self._results_snapshot())
            if path == "/results":
                return self._html(200, self._results_html())
            if path == "/company":
                return self._html(200, self._company_html((q.get("id") or [""])[0]))
            if path == "/artifact":
                return self._artifact((q.get("path") or [""])[0])
            if path == "/" or path == "/index.html":
                return self._html(200, self._overview_html())
            return self._json(404, {"error": "not found"})

        do_HEAD = do_GET

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/api/control":
                return self._control(parsed)
            if parsed.path == "/api/campaign/start":
                return self._campaign_start()
            return self._json(404, {"error": "not found"})

        def _control(self, parsed):
            """Apply a run control signal — behind the SAME guards as start: loopback Host +
            Origin + CSRF. Drain any body first so an early rejection never breaks the pipe."""
            self._read_json_body()   # optional body; also captures a body CSRF token
            if not self._host_is_loopback():
                return self._json(403, {"ok": False, "error": "non-loopback Host header refused"})
            if not self._origin_ok():
                return self._json(403, {"ok": False, "error": "cross-origin control requests are refused"})
            if not self._csrf_ok():
                return self._json(403, {"ok": False, "error": "missing or invalid CSRF token"})
            action = (parse_qs(parsed.query).get("action") or [""])[0]
            ok, status, message = service.control(action)
            return self._json(status, {"ok": ok, "action": action, "message": message,
                                       "status": service.status()})

        # --- guarded campaign start (v3.0.0 M4b) -----------------------------------------------
        def _campaign_start(self):
            """Start a bounded, read-only campaign — behind loopback + Host + Origin + CSRF guards."""
            # Drain the (bounded) request body first so an early rejection never leaves the client
            # writing into a half-closed socket (a broken pipe / connection abort).
            body = self._read_json_body()
            if not self._host_is_loopback():
                return self._json(403, {"ok": False, "error": "non-loopback Host header refused"})
            if not self._origin_ok():
                return self._json(403, {"ok": False, "error": "cross-origin start requests are refused"})
            if body is None:
                return self._json(400, {"ok": False, "error": "invalid or oversized JSON body"})
            if not self._csrf_ok():
                return self._json(403, {"ok": False, "error": "missing or invalid CSRF token"})
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
            if length <= 0 or length > _MAX_START_BODY_BYTES:
                return None
            try:
                raw = self.rfile.read(length)
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, OSError):
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
                    out.append({"company_id": cid, "name": c["canonical_name"],
                                "domain": c["primary_domain"], "findings": n,
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
                f"<tr><td>{_esc(t['id'])}</td><td>{_esc(t['domain'])}</td>"
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
<table><tr><th>tool</th><th>domain</th><th>readiness</th><th>auth</th><th>fallback</th><th>setup</th></tr>
{rows or '<tr><td colspan=6>none</td></tr>'}</table>
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


def _gmail_compose_url(to: str, subject: str, body: str) -> str:
    """A Gmail compose (draft) deep link — opens Gmail with the fields pre-filled. It NEVER sends;
    the operator reviews/edits and clicks Send manually."""
    from urllib.parse import quote
    return ("https://mail.google.com/mail/?view=cm&fs=1"
            f"&to={quote(to)}&su={quote(subject)}&body={quote(body)}")


def start_dashboard(service: ScoutService, host: str = "127.0.0.1", port: int = 0,
                    launcher: Optional[CampaignLauncher] = None,
                    csrf_token: Optional[str] = None) -> Tuple[ThreadingHTTPServer, str]:
    """Start the dashboard (localhost only) and return (server, base_url). Non-blocking.

    ``launcher`` (defaults to a live ``CampaignLauncher`` with an empty local-host allowlist, so
    localhost/private targets stay rejected) backs the guarded start endpoint; ``csrf_token``
    defaults to a fresh per-server secret. Both are attached to the returned server for the
    operator/tests (``server.scout_csrf_token`` / ``server.scout_launcher``).
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("dashboard binds to localhost only")
    launcher = launcher or CampaignLauncher(service)
    token = csrf_token or secrets.token_urlsafe(32)
    server = ThreadingHTTPServer((host, port), _make_handler(service, launcher, token))
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
