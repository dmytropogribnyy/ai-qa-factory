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

        def _overview_html(self) -> str:
            status = service.status()
            st = status.get("state", {})
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
