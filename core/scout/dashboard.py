"""Localhost Scout dashboard (Phase 8.3).

A dependency-light stdlib HTTP dashboard bound to 127.0.0.1 only. It reads the run store and
exposes control (pause/resume/cancel/global-kill). Artifact serving is path-confined to the
active run directory — no arbitrary filesystem access, no traversal. It performs no external
side effect.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Tuple
from urllib.parse import parse_qs, urlsplit

from core.scout import SCOUT_PRODUCT_NAME, SCOUT_VERSION
from core.scout.service import ScoutService
from core.scout.store import StoreError

_CONTENT_TYPES = {".json": "application/json", ".png": "image/png", ".md": "text/markdown"}
# Defensive cap on how much a single artifact response may return (our artifacts are small).
_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024


def _make_handler(service: ScoutService):
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
            if path == "/artifact":
                return self._artifact((q.get("path") or [""])[0])
            if path == "/" or path == "/index.html":
                return self._html(200, self._overview_html())
            return self._json(404, {"error": "not found"})

        do_HEAD = do_GET

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path != "/api/control":
                return self._json(404, {"error": "not found"})
            if not self._origin_ok():
                return self._json(403, {"error": "cross-origin control requests are refused"})
            action = (parse_qs(parsed.query).get("action") or [""])[0]
            ok, status, message = service.control(action)
            return self._json(status, {"ok": ok, "action": action, "message": message,
                                       "status": service.status()})

        def _origin_ok(self) -> bool:
            """Reject browser-originated cross-origin control POSTs (lightweight CSRF guard).

            Browsers always attach Origin on cross-origin fetch; the CLI control command sends
            none, so a missing Origin is allowed while a foreign one is refused. The dashboard
            is localhost-only and never exposes an HTTP start/scan endpoint.
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

        def _overview_html(self) -> str:
            status = service.status()
            st = status.get("state", {})
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
            if controllable:
                controls = (
                    '<button onclick="ctl(\'pause\')">Pause</button>'
                    '<button onclick="ctl(\'resume\')">Resume</button>'
                    '<button onclick="ctl(\'cancel\')">Cancel</button>'
                    '<button onclick="ctl(\'kill\')" style="color:#a00">GLOBAL KILL</button>'
                )
            else:
                controls = ("<em>Controls unavailable — this run is "
                            f"<strong>{_esc(mode)}</strong> (read-only).</em>")
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
<a href="/api/status">status</a>, <a href="/health">health</a></p>
<h2>Prospects</h2><table><tr><th>id</th><th>url</th><th>status</th><th>priority</th>
<th>defects</th><th></th></tr>{''.join(rows) or '<tr><td colspan=6>none yet</td></tr>'}</table>
<script>function ctl(a){{fetch('/api/control?action='+a,{{method:'POST'}})
.then(r=>r.json()).then(j=>{{if(!j.ok)alert('control refused: '+j.message);location.reload()}})}}</script>
</body></html>"""

    return _Handler


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def start_dashboard(service: ScoutService, host: str = "127.0.0.1", port: int = 0
                    ) -> Tuple[ThreadingHTTPServer, str]:
    """Start the dashboard (localhost only) and return (server, base_url). Non-blocking."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("dashboard binds to localhost only")
    server = ThreadingHTTPServer((host, port), _make_handler(service))
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{bound_host}:{bound_port}"
