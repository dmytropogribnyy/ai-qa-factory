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
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from core.dashboard.read_model import health_label, stage_label
from core.orchestration.project_index import _INTAKE_STATES
from core.scout import SCOUT_PRODUCT_NAME, SCOUT_VERSION
from core.scout.campaign_start import CampaignLauncher
from core.scout.service import ScoutService
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.store import RunStore, StoreError

_CONTENT_TYPES = {".json": "application/json", ".png": "image/png", ".md": "text/markdown",
                  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                  ".gif": "image/gif", ".webm": "video/webm", ".mp4": "video/mp4",
                  # Captured artifacts are UNTRUSTED third-party content. Never serve HTML as
                  # text/html on our own origin (stored XSS -> CSRF-token/API theft): render as
                  # source text. Do not add executable types (.svg/.xml/.xhtml) here.
                  ".har": "application/json", ".txt": "text/plain", ".html": "text/plain"}
# Defensive cap on how much a single artifact response may return (our artifacts are small).
_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
# The largest JSON body accepted by the start endpoint (requests are tiny).
_MAX_START_BODY_BYTES = 64 * 1024
# The largest pasted client brief accepted by the dashboard intake (also bounded by the body cap).
_MAX_BRIEF_BYTES = 60 * 1024
# The client-work workspace subdirectory (matches core.orchestration.work_execution._ARK).
_ARK_DIR = "40_ark_work"
# Hard cap on how many body bytes we will drain before giving up (prevents a huge-Content-Length
# read while still fully draining ordinary oversized requests so the socket is not half-closed).
_DRAIN_CAP_BYTES = 2 * 1024 * 1024
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _project_scout_activity_events(run_id: str, raw_events: list[dict]
                                   ) -> list[tuple[int, dict]]:
    """Project raw Scout audit events without rewriting the append-only source.

    ``actionable_target_reached`` is the one unique milestone: legacy writers could append it
    once per remaining candidate, so Activity keeps the first occurrence per campaign + target.
    Every other event remains repeatable and is preserved exactly as recorded.
    """
    projected: list[tuple[int, dict]] = []
    seen_actionable_targets: set[tuple[str, object]] = set()
    for event_index, event in enumerate(raw_events):
        if event.get("event") == "actionable_target_reached":
            identity = (run_id, event.get("target"))
            if identity in seen_actionable_targets:
                continue
            seen_actionable_targets.add(identity)
        projected.append((event_index, event))
    return projected[-100:]


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


# In-process registry of running background workers, keyed by "<output_dir>::<pid>". It enforces
# "one active worker per project" and carries the cancel Event for a still-running worker. A durable
# WORKER_ACTIVE.json marker on disk lets a status call after a restart detect an interrupted run
# (the marker exists but no live thread here -> the process died mid-run). The Work Order itself is
# always rebuilt from persisted project state by ClaudeWorkerExecutor; NOTHING about the command,
# prompt, argv, tools, model, or budget ever comes from the HTTP request.
_ACTIVE_WORKERS: dict = {}
_ACTIVE_WORKERS_GUARD = _threading.Lock()
_WORKER_TIMEOUT_S = 300           # fixed server-side bound; never taken from the request


def _default_worker_executor(*, resume: bool, cancel):
    """The production factory: a bounded ClaudeWorkerExecutor built from persisted state only.
    Tests replace this module attribute to inject a deterministic FixtureClaudeWorker."""
    from core.orchestration.claude_worker import ClaudeWorkerExecutor
    return ClaudeWorkerExecutor(resume=resume, timeout_s=_WORKER_TIMEOUT_S, cancel=cancel)


_worker_executor_factory = _default_worker_executor


# Bounded cache for the Access & Identity snapshot so a page/API request never blocks on the sum of
# several subprocess version probes (the readiness rarely changes within a session). An explicit
# refresh recomputes it. Computed at most once per _ACCESS_TTL_S, guarded for thread safety.
_ACCESS_CACHE: dict = {"snap": None, "at": 0.0}
_ACCESS_CACHE_GUARD = _threading.Lock()
_ACCESS_TTL_S = 120.0


def cached_access_snapshot(refresh: bool = False) -> dict:
    import time as _time
    now = _time.time()
    with _ACCESS_CACHE_GUARD:
        fresh = _ACCESS_CACHE["snap"] is not None and (now - _ACCESS_CACHE["at"]) < _ACCESS_TTL_S
        if fresh and not refresh:
            return _ACCESS_CACHE["snap"]
    from core.orchestration.access_bootstrap import AccessBootstrap
    snap = AccessBootstrap().snapshot()
    with _ACCESS_CACHE_GUARD:
        _ACCESS_CACHE["snap"] = snap
        _ACCESS_CACHE["at"] = now
    return snap


def _make_handler(service: ScoutService, launcher: CampaignLauncher, csrf_token: str,
                  operator_home: bool = False, challenge_manager=None):
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
            body = _theme_legacy(html).encode("utf-8")
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

        def _redirect(self, location: str, status: int = 303) -> None:
            """Redirect legacy duplicate routes to their canonical operator surface."""
            self.send_response(status)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

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
                return self._json(200, self._prospect(pid, (q.get("run") or [""])[0]))
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
            if path == "/api/services":
                from core.orchestration.service_capability import snapshot as _svc_snap
                return self._json(200, _svc_snap())
            if path == "/api/toolgap":
                from core.orchestration.tool_gap import plan_tools, snapshot as _gap_snap
                sid = (q.get("service") or [""])[0]
                return self._json(200, plan_tools(sid).to_dict() if sid else _gap_snap())
            if path == "/tools":
                return self._html(200, self._tools_page())
            if path == "/api/projects":
                return self._json(200, self._projects_snapshot())
            if path == "/projects":
                return self._redirect("/work")
            # v3.1 operator dashboard read-model routes
            if path == "/api/overview":
                return self._json(200, self._read_model().overview(
                    include_diagnostics=self._want_diagnostics(q)).to_dict())
            if path == "/api/work":
                view = (q.get("view") or ["active"])[0]
                return self._json(200, self._read_model().project_list(
                    view=view, include_diagnostics=self._want_diagnostics(q)))
            if path.startswith("/api/work/"):
                return self._json(200, self._work_detail_json(path[len("/api/work/"):]))
            if path == "/work" or path == "/work/":
                return self._html(200, self._work_list_page(q))
            if path.startswith("/work/"):
                return self._html(200, self._work_detail_page(path[len("/work/"):], q))
            if path == "/scout":
                return self._html(200, self._scout_home_page())
            if path == "/scout/campaigns":
                return self._html(200, self._scout_campaigns_page(q))
            if path == "/activity":
                return self._html(200, self._activity_page(q))
            if path == "/api/activity":
                return self._json(200, self._activity_json((q.get("project") or [""])[0],
                                                           self._want_diagnostics(q)))
            if path == "/data":
                return self._html(200, self._data_page(q))
            if path == "/settings":
                if (q.get("refresh") or [""])[0]:
                    cached_access_snapshot(refresh=True)   # explicit operator refresh
                return self._html(200, self._settings_page(q))
            if path == "/api/access":
                return self._json(200, cached_access_snapshot(
                    refresh=bool((q.get("refresh") or [""])[0])))
            if path == "/api/build":
                # Running-build identity + stale-process detection (read-only, no secrets/paths).
                from core.build_identity import current_identity
                return self._json(200, current_identity())
            if path == "/api/collab":
                # Direct Collaboration Driver monitor (Issue #14.D) — read-only over the canonical store.
                return self._json(200, self._collab_snapshot())
            if path == "/collab":
                return self._html(200, self._collab_page(q))
            if path == "/api/discovery":
                # v3.3 read-only live-discovery + analyzed-site history (no secret; loopback-only).
                from core.scout.discovery.discovery_status import discovery_status
                out_dir = getattr(service, "output_dir", "outputs")
                return self._json(200, discovery_status(out_dir))
            # v3.3 adaptive Scout operator workflow (read models + pages)
            if path == "/api/scout/catalog":
                return self._json(200, self._campaign_service().catalog())
            if path == "/api/scout/progress":
                return self._json(200, self._campaign_service().progress((q.get("id") or [""])[0]))
            if path == "/api/scout/history":
                return self._json(200, {"rows": self._campaign_service().history(
                    filters={"text": (q.get("text") or [""])[0],
                             "status": (q.get("status") or [""])[0],
                             "purpose": (q.get("purpose") or [""])[0],
                             "archived": (q.get("archived") or [""])[0]})})
            if path == "/api/scout/target":
                return self._json(200, self._campaign_service().target_detail(
                    (q.get("domain") or [""])[0], run=(q.get("run") or [""])[0]))
            if path == "/api/scout/attention":
                return self._json(200, challenge_manager.snapshot())
            if path == "/scout/new":
                return self._html(200, self._scout_new_page(q))
            if path == "/scout/progress":
                return self._html(200, self._scout_progress_page((q.get("id") or [""])[0]))
            if path == "/scout/history":
                return self._html(200, self._scout_history_page(q))
            if path == "/scout/target":
                return self._html(200, self._scout_target_page(
                    (q.get("domain") or [""])[0], run=(q.get("run") or [""])[0]))
            if path == "/scout/run":
                return self._html(200, self._scout_run_results_page((q.get("id") or [""])[0]))
            if path == "/scout/attention":
                return self._html(200, self._scout_attention_page())
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
            if path == "/scout/artifact":
                return self._scout_artifact(
                    (q.get("run") or [""])[0], (q.get("rel") or [""])[0],
                    download=(q.get("download") or [""])[0] in ("1", "true", "yes"))
            if path == "/scout/client-evidence":
                return self._scout_client_evidence(
                    (q.get("domain") or [""])[0], (q.get("run") or [""])[0])
            if path == "/scout/client-report":
                return self._html(200, self._scout_client_report_page(
                    (q.get("domain") or [""])[0], (q.get("run") or [""])[0]))
            if path == "/work-evidence":
                return self._work_evidence((q.get("project") or [""])[0], (q.get("path") or [""])[0])
            if path == "/" or path == "/index.html":
                # The operator front door is stable: an active Scout run never replaces Overview.
                # Run controls and results stay on the explicit Scout surfaces.
                if operator_home:
                    return self._html(200, self._operator_overview_page(q))
                return self._html(200, self._overview_html())
            return self._json(404, {"error": "not found"})

        @staticmethod
        def _want_diagnostics(q) -> bool:
            """Read the 'Show diagnostics' toggle (?diagnostics=1). Production views are the default;
            diagnostics are only ever shown when the operator explicitly opts in."""
            return (q.get("diagnostics") or [""])[0].strip().lower() in ("1", "true", "yes", "on")

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

        def _collab_snapshot(self):
            from core.collaboration.monitor import CollaborationMonitor
            from core.collaboration.service import resolve_branch_head
            out = getattr(service, "output_dir", "outputs")
            # Truly branch-aware: match each thread against ITS branch head (read-only), not one HEAD.
            return CollaborationMonitor(
                out, head_resolver=lambda branch="": resolve_branch_head(".", branch)).snapshot()

        def _collab_page(self, q=None) -> str:
            try:
                snap = self._collab_snapshot()
            except Exception as exc:
                return _page("Collaboration", "/collab",
                             f'<h1>Collaboration</h1><p class="muted">Monitor unavailable: '
                             f'{_esc(type(exc).__name__)}</p>')
            show_completed = ((q or {}).get("completed") or [""])[0] in ("1", "true", "yes")
            return _page("Collaboration", "/collab", _collab_body(
                snap, show_completed=show_completed),
                         script="setTimeout(function(){location.reload();},15000);")

        do_HEAD = do_GET

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/api/control":
                return self._control(parsed)
            if parsed.path == "/api/campaign/start":
                return self._campaign_start()
            if parsed.path == "/api/scout/preflight":
                return self._scout_preflight()
            if parsed.path == "/api/scout/launch":
                return self._scout_launch()
            if parsed.path == "/api/scout/import":
                return self._scout_import()
            if parsed.path == "/api/scout/intake/preview":
                return self._scout_intake_preview()
            if parsed.path in ("/api/scout/data/preview", "/api/scout/data/trash",
                               "/api/scout/data/restore", "/api/scout/data/delete",
                               "/api/scout/data/classify"):
                return self._scout_data_action(parsed.path.rsplit("/", 1)[-1])
            if parsed.path == "/api/scout/control":
                return self._scout_control(parsed)
            if parsed.path == "/api/scout/export":
                return self._scout_export(parsed)
            if parsed.path == "/api/scout/rescan":
                return self._scout_rescan(parsed)
            if parsed.path == "/api/scout/replay":
                return self._scout_replay(parsed)
            if parsed.path == "/api/scout/challenge/start":
                return self._scout_challenge_start(parsed)
            if parsed.path == "/api/scout/challenge/action":
                return self._scout_challenge_action(parsed)
            if parsed.path == "/api/scout/operator":
                return self._scout_operator_action(parsed)
            if parsed.path == "/api/scout/engagement":
                return self._scout_engagement(parsed)
            if parsed.path == "/api/scout/polish-draft":
                return self._scout_polish_draft(parsed)
            if parsed.path == "/api/scout/start-client-work":
                return self._scout_start_client_work(parsed)
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

        def _scout_import(self):
            """Parse an uploaded curated .xlsx/.csv into canonical seed rows for Manual Scan — behind
            the shared mutation guard. A base64 file rides in a bounded JSON body (larger than the
            control cap, still bounded). The workbook is NEVER persisted; only the parsed manifest is.
            This produces seeds only — launch reuses /api/campaign/start."""
            import base64
            _cap = 8 * 1024 * 1024                         # ~5MB file base64-encoded + JSON overhead
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json(400, {"ok": False, "error": "bad Content-Length"})
            raw = b""
            if length > _cap:
                try:
                    self.rfile.read(min(length, _cap))     # drain bounded, then refuse
                except OSError:
                    pass
                return self._json(413, {"ok": False, "error": "import body too large"})
            if length > 0:
                try:
                    raw = self.rfile.read(length)
                except OSError:
                    return self._json(400, {"ok": False, "error": "read error"})
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                return self._json(400, {"ok": False, "error": "invalid JSON body"})
            if not isinstance(body, dict):
                return self._json(400, {"ok": False, "error": "invalid JSON body"})
            self._body_csrf = body.get("csrf_token")
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            filename = str(body.get("filename") or "")[:200]
            try:
                data = base64.b64decode(str(body.get("content_b64") or ""), validate=True)
            except Exception:  # noqa: BLE001 - any decode failure is a bad request, never a crash
                return self._json(400, {"ok": False, "error": "invalid base64 content"})
            from core.scout.curated_import import CuratedImportError, parse_curated_list
            from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
            try:
                res = parse_curated_list(data, filename,
                                         registry=AnalyzedSiteRegistry(service.output_dir))
            except CuratedImportError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            manifest_saved = True
            try:                                           # persist the MANIFEST only — never the workbook
                imp_dir = Path(service.output_dir) / "scout" / "_imports"
                imp_dir.mkdir(parents=True, exist_ok=True)
                (imp_dir / f"{res.import_id}.json").write_text(
                    json.dumps(res.to_dict(), indent=2), encoding="utf-8")
            except OSError:
                manifest_saved = False                     # reported honestly, never a false success
            return self._json(200, {"ok": True, "result": res.to_dict(),
                                    "manifest_saved": manifest_saved})

        def _scout_intake_preview(self):
            """What the queue will actually contain, computed by the code that will build it.

            The operator presses Start on the strength of these numbers, so they must not come from a
            second, friendlier parser: this calls the same ``core.scout.intake`` the launch path uses.
            It is read-only — nothing is queued, fetched or persisted — but it still sits behind the
            shared mutation guard because it accepts an operator-supplied body.
            """
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
            from core.scout.intake import parse_rows, parse_text
            text = str(body.get("text") or "")[:200_000]
            rows = body.get("rows")
            try:
                known = frozenset(e.domain for e in AnalyzedSiteRegistry(service.output_dir).all()
                                  if getattr(e, "domain", ""))
            except Exception:  # noqa: BLE001 - history is advisory here; never block a preview
                known = frozenset()
            # DNS is deliberately not consulted here: a preview must be instant and deterministic,
            # and skipping resolution is safe because the LAUNCHER re-validates every seed with
            # resolution (the anti-rebinding guard) before anything is queued. The structural and
            # private/reserved checks still run, so localhost and 0.1 are refused in the preview.
            from core.scout.url_safety import UrlPolicy
            common = {"known_domains": known, "pinned": True,
                      "policy": UrlPolicy(resolve_dns=False)}
            if isinstance(rows, list):
                result = parse_rows([r if isinstance(r, list) else [r] for r in rows[:5000]],
                                    **common)
            else:
                result = parse_text(text, **common)
            return self._json(200, {"ok": True, **result.to_dict()})

        def _data_store(self):
            from core.scout.data_management import DataManagementStore
            # ``service.run_id`` survives the run that set it, so it names the LAST run, not a
            # running one. Pass whether a run is actually in flight as well, or the most recent
            # finished run stays permanently unmanageable behind a "still running" refusal.
            running = False
            try:
                running = bool(service.is_running())
            except Exception:      # noqa: BLE001 - an unavailable probe must fail SAFE (protect)
                running = True
            return DataManagementStore(service.output_dir,
                                       active_run_id=str(getattr(service, "run_id", "") or ""),
                                       run_active=running)

        def _scout_data_action(self, action: str):
            """Preview / Trash / Restore / permanent delete, each behind the shared mutation guard.

            The four are separate endpoints rather than one with a mode, so an accidental replay of
            a preview request can never turn into a deletion.
            """
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            raw = body.get("run_ids")
            # Exact ids only, bounded. A selection that could expand after it was previewed is not
            # the selection that was previewed.
            run_ids = [str(item) for item in raw[:500]] if isinstance(raw, list) else []
            store = self._data_store()
            if action == "preview":
                return self._json(200, {"ok": True, "preview": store.preview(run_ids).to_dict()})
            if action == "trash":
                return self._json(200, {"ok": True, **store.move_to_trash(run_ids)})
            if action == "restore":
                return self._json(200, {"ok": True, **store.restore(run_ids)})
            if action == "classify":
                return self._json(200, {"ok": True, **store.classify(
                    run_ids, purpose=str(body.get("purpose") or ""))})
            return self._json(200, {"ok": True, **store.permanently_delete(
                run_ids, confirm=body.get("confirm") is True)})

        def _data_page(self, q=None) -> str:
            """Everything that takes up space, what it is for, and a staged way to let it go."""
            query = q or {}
            view = (query.get("view") or [""])[0].strip().lower()
            in_trash = view == "trash"

            def _one(name: str) -> str:
                return (query.get(name) or [""])[0].strip()[:120]

            # The filters an operator can combine. Each one only ever NARROWS, so a preview built
            # from the visible selection can never reach a run the table was not showing.
            filters = {"purpose": _one("purpose"), "text": _one("q"),
                       "since": _one("since"), "until": _one("until"),
                       "trash": "only" if in_trash else "exclude"}
            inv = self._data_store().inventory(filters=filters)
            rows_source = list(inv.runs)
            from core.scout.data_management import (PURPOSE_ACCEPTANCE, PURPOSE_DIAGNOSTIC,
                                                    PURPOSE_LABELS, PURPOSE_MANUAL_TEST,
                                                    PURPOSE_PRODUCTION, PURPOSE_UNCLASSIFIED)
            tiles = "".join(
                f'<div class="summary-item"><span class="muted">{_esc(PURPOSE_LABELS[key])}</span>'
                f'<strong>{inv.counts.get(key, 0)}</strong></div>'
                for key in (PURPOSE_PRODUCTION, PURPOSE_ACCEPTANCE, PURPOSE_DIAGNOSTIC,
                            PURPOSE_MANUAL_TEST, PURPOSE_UNCLASSIFIED))
            tiles += (f'<div class="summary-item"><span class="muted">Storage</span>'
                      f'<strong>{_esc(_human_bytes(inv.bytes_total))}</strong></div>'
                      f'<div class="summary-item"><span class="muted">In Trash</span>'
                      f'<strong>{inv.counts.get("in_trash", 0)}</strong></div>')
            rows = "".join(
                f'<tr><td class="select-cell"><input type="checkbox" class="pick" '
                f'value="{_esc(r.run_id)}" aria-label="Select {_esc(r.run_id)}"></td>'
                f'<td data-label="Run"><code>{_esc(r.run_id)}</code></td>'
                f'<td data-label="Purpose">{_badge(r.purpose_label)}</td>'
                f'<td data-label="Sites" class="muted">'
                f'{_esc(", ".join(r.domains) or "none recorded")}</td>'
                f'<td data-label="Evidence" class="muted">{r.screenshots} screenshot(s) · '
                f'{r.videos} video(s) · {r.findings} finding(s)</td>'
                f'<td data-label="Size" class="muted">{_esc(_human_bytes(r.bytes))}</td>'
                f'<td data-label="When" class="muted">{_fmt_ts(r.trashed_at or r.created_at)}</td>'
                f'</tr>' for r in rows_source)
            table = (f'<table class="responsive-table"><thead><tr>'
                     f'<th><input type="checkbox" id="pickall" aria-label="Select all"></th>'
                     f'<th>Run</th><th>Purpose</th><th>Sites</th><th>Evidence</th><th>Size</th>'
                     f'<th>{"Moved to Trash" if in_trash else "Recorded"}</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table>'
                     if rows else
                     f'<div class="card empty muted">{_esc(_data_empty_note(filters, in_trash))}</div>')
            active_purpose = filters["purpose"].lower()
            options = "".join(
                f'<option value="{_esc(key)}"'
                f'{" selected" if active_purpose == key else ""}>{_esc(label)}</option>'
                for key, label in (("", "Any purpose"),
                                   (PURPOSE_PRODUCTION, PURPOSE_LABELS[PURPOSE_PRODUCTION]),
                                   (PURPOSE_ACCEPTANCE, PURPOSE_LABELS[PURPOSE_ACCEPTANCE]),
                                   (PURPOSE_DIAGNOSTIC, PURPOSE_LABELS[PURPOSE_DIAGNOSTIC]),
                                   (PURPOSE_MANUAL_TEST, PURPOSE_LABELS[PURPOSE_MANUAL_TEST]),
                                   (PURPOSE_UNCLASSIFIED, PURPOSE_LABELS[PURPOSE_UNCLASSIFIED])))
            filter_bar = (
                f'<form class="row filters" method="get" action="/data">'
                f'{"<input type=hidden name=view value=trash>" if in_trash else ""}'
                f'<label class="sr-only" for="f_purpose">Purpose</label>'
                f'<select id="f_purpose" name="purpose">{options}</select>'
                f'<label class="sr-only" for="f_q">Run or site</label>'
                f'<input id="f_q" name="q" value="{_esc(filters["text"])}" '
                f'placeholder="run id or site" maxlength="120">'
                f'<label class="sr-only" for="f_since">Recorded from</label>'
                f'<input id="f_since" name="since" type="date" value="{_esc(filters["since"][:10])}">'
                f'<label class="sr-only" for="f_until">Recorded to</label>'
                f'<input id="f_until" name="until" type="date" value="{_esc(filters["until"][:10])}">'
                f'<button class="chip" type="submit">Filter</button>'
                f'<a class="chip" href="/data{"?view=trash" if in_trash else ""}">Clear</a>'
                f'</form>')
            actions = (
                '<button class="chip" onclick="act(\'restore\')">Restore selected</button>'
                '<button class="chip danger" onclick="destroy()">Delete permanently…</button>'
                if in_trash else
                '<button class="chip" onclick="preview()">Preview what would be removed</button>'
                # An Unclassified run is required to demand an explicit choice, so the operator has
                # to be able to make one. Production is deliberately not offered: a label that buys
                # sweep-protection must not be handed out from the sweep screen.
                '<label class="sr-only" for="setpurpose">Record what these runs were</label>'
                '<select id="setpurpose"><option value="">Record what these were&hellip;</option>'
                '<option value="acceptance">Acceptance</option>'
                '<option value="diagnostic">Diagnostic</option>'
                '<option value="manual_test">Manual test</option></select>'
                '<button class="chip" onclick="classify()">Save purpose</button>'
                '<button class="chip" onclick="act(\'trash\')" id="tobin" disabled>'
                'Move selected to Trash</button>')
            tabs = (('<a class="chip" href="/data">Stored runs</a>'
                     '<span class="chip active">Trash</span>') if in_trash else
                    ('<span class="chip active">Stored runs</span>'
                     '<a class="chip" href="/data?view=trash">Trash</a>'))
            body = (
                '<h1>Data management</h1>'
                '<p class="page-intro muted">What Scout has stored, what each run was for, and a '
                'staged way to let test data go. Production runs and runs whose purpose was never '
                'recorded are never swept automatically.</p>'
                f'<div class="row">{tabs}</div>'
                f'<div class="summary-grid">{tiles}</div>'
                f'{filter_bar}'
                f'<p class="muted">The tiles above count everything stored. The table below shows '
                f'what your filters selected — and a removal can only ever reach what is in it.</p>'
                f'<div class="scrollx">{table}</div>'
                '<div class="card" id="previewout" role="status" aria-live="polite" hidden></div>'
                f'<div class="card bulkbar" id="bulkbar" hidden><b><span id="selected">0</span> '
                f'selected</b><div class="row">{actions}'
                '<span id="datamsg" class="muted" aria-live="polite"></span></div></div>'
                '<p class="muted">Moving to Trash removes nothing from disk. Permanent deletion is '
                'available only from Trash, only for the runs you select there, and only after a '
                'separate confirmation naming the exact counts.</p>')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";"
                "function picks(){return Array.from(document.querySelectorAll('.pick:checked'))"
                ".map(function(x){return x.value;});}"
                "function refreshBulk(){var n=picks().length;"
                "document.getElementById('selected').textContent=n;"
                "document.getElementById('bulkbar').hidden=!n;"
                "var t=document.getElementById('tobin');if(t)t.disabled=true;}"
                "document.querySelectorAll('.pick').forEach(function(x){x.onchange=refreshBulk;});"
                "var pa=document.getElementById('pickall');if(pa)pa.onchange=function(){"
                "document.querySelectorAll('.pick').forEach(function(x){x.checked=pa.checked;});"
                "refreshBulk();};"
                "function J(u,b){return fetch(u,{method:'POST',headers:{'X-Scout-CSRF':CSRF,"
                "'Content-Type':'application/json'},body:JSON.stringify(b)})"
                ".then(function(r){return r.json();});}"
                "function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(c){"
                "return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}"
                "function preview(){var d=picks();if(!d.length)return;"
                "J('/api/scout/data/preview',{run_ids:d}).then(function(j){"
                "var p=j.preview||{},o=document.getElementById('previewout');o.hidden=false;"
                "var h='<h2>This would be removed</h2><ul>'+"
                "'<li>'+(p.runs||[]).length+' run(s)</li>'+"
                "'<li>'+(p.unique_domains||[]).length+' site(s): '+esc((p.unique_domains||[])"
                ".join(', '))+'</li>'+"
                "'<li>'+p.screenshots+' screenshot(s), '+p.videos+' video(s), '+p.findings+"
                "' finding(s)</li>'+"
                "'<li>'+Math.round((p.bytes_to_reclaim||0)/1024)+' KiB reclaimed</li></ul>';"
                "if((p.shared_with_production||[]).length){h+='<p class=\"banner warn\">These '+"
                "'sites are also part of production runs and keep their history: '+"
                "esc(p.shared_with_production.join(', '))+'</p>';}"
                "if((p.protected||[]).length){h+='<h3>Not included</h3><ul>'+p.protected.map("
                "function(x){return '<li><code>'+esc(x.run_id)+'</code> — '+esc(x.reason)+"
                "'</li>';}).join('')+'</ul>';}"
                "o.innerHTML=h;var t=document.getElementById('tobin');"
                "if(t)t.disabled=!(p.runs||[]).length;});}"
                "function classify(){var d=picks(),s=document.getElementById('setpurpose');"
                "if(!d.length||!s||!s.value)return;"
                "J('/api/scout/data/classify',{run_ids:d,purpose:s.value}).then(function(j){"
                "if((j.classified||[]).length)location.reload();"
                "else document.getElementById('datamsg').textContent="
                "(((j.refused||[])[0]||{}).reason||'Nothing was changed.');});}"
                "function act(a){var d=picks();if(!d.length)return;"
                "J('/api/scout/data/'+a,{run_ids:d}).then(function(j){"
                "if(j.ok)location.reload();else document.getElementById('datamsg').textContent="
                "(j.error||'Action failed');});}"
                "function destroy(){var d=picks();if(!d.length)return;"
                "J('/api/scout/data/preview',{run_ids:d}).then(function(j){var p=j.preview||{};"
                "return qaConfirm('Permanently delete '+d.length+' run(s) and '+"
                "Math.round((p.bytes_to_reclaim||0)/1024)+' KiB of evidence? This cannot be undone.',"
                "'Delete permanently','DELETE');}).then(function(ok){if(!ok)return;"
                "J('/api/scout/data/delete',{run_ids:d,confirm:true}).then(function(j){"
                "if((j.deleted||[]).length)location.reload();"
                "else document.getElementById('datamsg').textContent='Nothing was deleted.';});});}")
            return _page("AI QA Factory — Data management", "/data", body, script)

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
                                            "[A-Za-z0-9._-], max 64, no separators/traversal, "
                                            "no Windows reserved names)"})
                source_platform = str(body.get("source_platform") or "manual")
                import hashlib
                fingerprint = hashlib.sha256(
                    (redact_intake_text(brief).text + "\x00" + source_platform).encode("utf-8")
                ).hexdigest()
                # Serialize + idempotency per project (v3.2 5.2): a double-submit or a concurrent
                # identical request never creates two analyses or overwrites progressed state.
                with _work_lock(f"{service.output_dir}::{project_id}"):
                    ws = Path(service.output_dir) / project_id / _ARK_DIR
                    fp_path = ws / "INTAKE_FINGERPRINT.json"
                    if (ws / "WORK_RUN_STATE.json").exists():
                        prior = {}
                        try:
                            prior = json.loads(fp_path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            prior = {}
                        if prior.get("fingerprint") == fingerprint:
                            return self._json(200, {"ok": True, "action": action,
                                                    "project_id": project_id, "idempotent": True})
                        return self._json(409, {"ok": False, "action": action,
                                                "project_id": project_id,
                                                "error": "a different project already exists with "
                                                "this id (input fingerprint differs)"})
                    try:
                        res = ClientWorkService(ClockProvider(), IdProvider(),
                                                output_dir=service.output_dir).analyze(
                            brief, project_id=project_id, source_platform=source_platform,
                            fresh_only=generated)
                    except Exception as exc:
                        return self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                    try:
                        ws.mkdir(parents=True, exist_ok=True)
                        from datetime import datetime, timezone
                        fp_path.write_text(json.dumps(
                            {"fingerprint": fingerprint, "at": datetime.now(timezone.utc).isoformat()},
                            indent=2, sort_keys=True), encoding="utf-8")
                    except OSError:
                        pass
                    return self._json(200, {"ok": True, "action": action,
                                            "project_id": res.project_id})
            if action in ("worker-start", "worker-resume", "worker-cancel", "worker-status"):
                return self._worker_action(action, pid, body)
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

        # --- guarded autonomous worker (v3.2) — project-id only, background, one-active ---------
        def _worker_action(self, action: str, pid: str, body: dict):
            """Start/resume/cancel/inspect a BOUNDED background Claude worker. Only a validated
            project id is accepted (never a prompt/command/argv/workspace/tools/model/budget); the
            Work Order is rebuilt from persisted state by ClaudeWorkerExecutor. Enforces one active
            worker per project, persists before start, reconciles an interrupted run, and returns
            immediately (the run proceeds in a daemon thread)."""
            from datetime import datetime, timezone

            from core.orchestration.providers import validate_project_id
            from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
            if not validate_project_id(pid):
                return self._json(400, {"ok": False, "error": "a valid project id is required"})
            key = f"{service.output_dir}::{pid}"
            ws = Path(service.output_dir) / pid / _ARK_DIR

            if action == "worker-status":
                info = self._worker_live(key)
                session = {}
                sp = ws / "EXECUTION_SESSION.json"
                if sp.exists():
                    try:
                        session = json.loads(sp.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        session = {}
                try:
                    st = WorkExecutionService(output_dir=service.output_dir).status(pid)
                    lifecycle = {"status": st.status, "progress": st.progress,
                                 "blockers": st.blockers, "next_action": st.next_action}
                except WorkExecutionError as exc:
                    lifecycle = {"error": str(exc)}
                return self._json(200, {"ok": True, "action": action, "project_id": pid,
                                        "running": info is not None,
                                        "started_at": (info or {}).get("started_at"),
                                        "lifecycle": lifecycle,
                                        "session": {k: session.get(k) for k in
                                                    ("executor", "session_id", "stop_reason", "ok",
                                                     "files_changed", "cost_usd", "blockers")}})

            if action == "worker-cancel":
                # A running worker stops safely (process tree terminated); a not-yet-started worker
                # will not launch. Both the durable marker and the in-process Event are set.
                ws.mkdir(parents=True, exist_ok=True)
                (ws / "WORKER_CANCEL.json").write_text(json.dumps(
                    {"requested_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
                info = self._worker_live(key)
                if info is not None:
                    info["cancel"].set()
                return self._json(200, {"ok": True, "action": action, "project_id": pid,
                                        "was_running": info is not None})

            # worker-start / worker-resume: an explicit confirmation is required, and the request may
            # carry ONLY the project id + confirm (any command/prompt/argv field is ignored).
            if body.get("confirm") is not True:
                return self._json(400, {"ok": False, "error": "autonomous worker execution requires "
                                        "an explicit confirm=true"})
            with _work_lock(key):
                if self._worker_live(key) is not None:
                    return self._json(409, {"ok": False, "action": action, "project_id": pid,
                                            "error": "a worker is already running for this project"})
                svc = WorkExecutionService(output_dir=service.output_dir)
                # Restart recovery: no live worker in THIS process but state stuck at EXECUTING means
                # a prior process died mid-run -> reconcile to BLOCKED so it can be resumed.
                try:
                    svc.recover_interrupted(pid)
                    cur = svc.status(pid).status
                except WorkExecutionError as exc:
                    return self._json(404, {"ok": False, "error": str(exc)})
                if cur not in ("READY_TO_EXECUTE", "REPAIR_REQUIRED", "BLOCKED"):
                    return self._json(409, {"ok": False, "action": action, "project_id": pid,
                                            "error": f"cannot start a worker from state {cur} "
                                            "(approve the plan first)"})
                # Client-repo trust + private-work-dir preflight (P0-E): refuse untrusted execution
                # and refuse a non-private work directory. Never simulate isolation.
                from core.orchestration.execution_trust import (
                    assess_execution_trust,
                    preflight_work_isolation,
                )
                trust = assess_execution_trust(str(ws))
                if not trust.trusted:
                    return self._json(409, {"ok": False, "action": action, "project_id": pid,
                                            "error": f"untrusted repository: {trust.reason}",
                                            "action_required": trust.action})
                pf = preflight_work_isolation(str(ws))
                if not pf.ok:
                    return self._json(409, {"ok": False, "action": action, "project_id": pid,
                                            "error": f"work-isolation preflight failed: {pf.reason}",
                                            "action_required": pf.action})
                # Persist-before-start: clear any stale cancel marker and register the active worker
                # + a durable marker BEFORE the daemon thread launches.
                try:
                    (ws / "WORKER_CANCEL.json").unlink()
                except OSError:
                    pass
                cancel = _threading.Event()
                started_at = datetime.now(timezone.utc).isoformat()
                with _ACTIVE_WORKERS_GUARD:
                    _ACTIVE_WORKERS[key] = {"cancel": cancel, "started_at": started_at, "done": False}
                try:
                    ws.mkdir(parents=True, exist_ok=True)
                    (ws / "WORKER_ACTIVE.json").write_text(json.dumps(
                        {"started_at": started_at, "action": action}, indent=2, sort_keys=True),
                        encoding="utf-8")
                except OSError:
                    pass

                def _run():
                    try:
                        executor = _worker_executor_factory(
                            resume=(action == "worker-resume"), cancel=cancel)
                        WorkExecutionService(output_dir=service.output_dir).execute(pid, executor)
                    except Exception as exc:       # never crash the server; NEVER silently swallow
                        # Surface a bounded, secret-redacted error (type + message, no traceback) as an
                        # actionable lifecycle blocker so worker-status shows why, not a silent state.
                        try:
                            from core.orchestration.content_safety import redact_intake_text
                            red = redact_intake_text(f"{type(exc).__name__}: {exc}").text[:300]
                            WorkExecutionService(output_dir=service.output_dir) \
                                .record_background_failure(pid, red)
                        except Exception:
                            pass
                    finally:
                        with _ACTIVE_WORKERS_GUARD:
                            cur_info = _ACTIVE_WORKERS.get(key)
                            if cur_info is not None:
                                cur_info["done"] = True
                        try:
                            (ws / "WORKER_ACTIVE.json").unlink()
                        except OSError:
                            pass

                _threading.Thread(target=_run, name=f"worker:{pid}", daemon=True).start()
                return self._json(202, {"ok": True, "action": action, "project_id": pid,
                                        "status": "EXECUTING", "started_at": started_at,
                                        "message": "bounded worker started; poll worker-status"})

        @staticmethod
        def _worker_live(key: str):
            with _ACTIVE_WORKERS_GUARD:
                info = _ACTIVE_WORKERS.get(key)
                return info if (info is not None and not info["done"]) else None

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
        def _prospect(self, pid: str, run: str = ""):
            # Optional EXACT-run scoping: a raw-JSON diagnostic opened from a historical run page must
            # read that exact confined RunStore and NEVER fall back to the active/attached run.
            run = str(run or "").strip()
            if run:
                try:
                    store = RunStore(service.output_dir, run)
                except StoreError:
                    return {"error": "invalid run", "run": run}
                if not store.exists():
                    return {"error": "run not found", "run": run}
                try:
                    state = store.load_state() or {}
                except StoreError:
                    state = {}
                if not pid or pid not in (state.get("prospects", {}) or {}):
                    return {"error": "prospect not found in run", "run": run, "prospect_id": pid}
            else:
                store = service.store
                # No run-membership check on this legacy unpinned path, so the persisted status is
                # resolved the SAME way: load this store's state if one is attached. Any failure or
                # absence leaves it genuinely unknown (the legacy exemption below then applies).
                try:
                    state = (store.load_state() or {}) if store is not None else {}
                except StoreError:
                    state = {}
            if store is None or not pid:
                return {"error": "no prospect"}
            # Same completeness predicate the read model (target_detail) applies, so this diagnostic
            # endpoint cannot drift from it — see campaign_service.analysis_incomplete.
            from core.scout.campaign_service import analysis_incomplete
            pstate = (state.get("prospects", {}) or {}).get(pid, {}) or {}
            prospect_status = str(pstate.get("status", "") or "")
            analysis_complete = (prospect_status == "DONE") if prospect_status else None
            out = {"prospect_id": pid, "prospect_status": prospect_status,
                   "analysis_complete": analysis_complete}
            if run:
                out["run"] = run
            for name in ("observation.json", "findings.json", "evidence.json", "scorecard.json"):
                try:
                    out[name.split(".")[0]] = store.load_prospect_artifact(pid, name)
                except StoreError:
                    out[name.split(".")[0]] = None
            if analysis_incomplete(prospect_status):
                # Confirmed findings and their derived scorecard exist only for a completed analysis
                # (core/scout/engine.py writes scorecard.json only on the DONE path). Withhold both
                # by name -- no `verified` key anywhere in this payload -- while distinguishing
                # "withheld because incomplete" from "artifact genuinely absent on disk". observation
                # and evidence stay: they are page-level diagnostics, not confirmed findings.
                out["findings"] = {"withheld": "analysis_incomplete",
                                   "artifact_present": out.get("findings") is not None}
                out["scorecard"] = {"withheld": "analysis_incomplete",
                                    "artifact_present": out.get("scorecard") is not None}
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

        def _scout_artifact(self, run_id: str, rel: str, *, download: bool = False):
            """Serve one captured evidence file from a specific Scout run, path-confined.

            The RunStore constructor rejects an unsafe run_id; `_confine` blocks traversal out of the
            run dir. Captured content is untrusted, so HTML is served as source text (see
            _CONTENT_TYPES) and nosniff is set."""
            if not run_id or not rel:
                return self._json(404, {"error": "no artifact"})
            try:
                st = RunStore(service.output_dir, run_id)
            except StoreError:
                return self._json(403, {"error": "bad run id"})
            parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
            try:
                target = st._confine(*parts)
            except StoreError:
                return self._json(403, {"error": "path not allowed"})
            if not target.exists() or not target.is_file():
                return self._json(404, {"error": "not found"})
            # A result-bearing artifact (finding records, the scorecard derived from them, the
            # reproduction record and its video clip) belongs to a COMPLETED analysis only. This URL
            # is user-facing and guessable, so the same completeness predicate the read model and
            # /api/prospect apply must gate it here too — withholding it from the page alone would
            # leave the result one hand-typed URL away. Page-level capture (screenshots, observation,
            # trace, the stop-reason record) stays available: it explains why the run stopped.
            from core.scout.campaign_service import analysis_incomplete, is_result_bearing_artifact
            if len(parts) >= 3 and parts[0] == "prospects" and is_result_bearing_artifact(parts[-1]):
                try:
                    pstate = ((st.load_state() or {}).get("prospects", {}) or {}).get(parts[1], {})
                except StoreError:
                    pstate = {}
                if analysis_incomplete(str((pstate or {}).get("status", "") or "")):
                    return self._json(409, {"error": "analysis incomplete",
                                            "detail": "this artifact carries a QA result and is "
                                                      "available only for a completed analysis"})
            if target.stat().st_size > _MAX_ARTIFACT_BYTES:
                return self._json(413, {"error": "artifact too large to serve"})
            name = target.name.lower()
            ctype = next((v for k, v in _CONTENT_TYPES.items() if name.endswith(k)),
                         "application/octet-stream")
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if download:
                # The filename is the store's own already-validated component, never caller text, so
                # it cannot carry a quote, a path separator or a header-splitting newline.
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{target.name}"')
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _scout_client_report_page(self, domain: str, run_id: str) -> str:
            """A preview of what the client would receive, rendered by us rather than served as HTML.

            The package's own report is a standalone HTML file built partly from text captured on a
            third-party site. Serving those bytes inline would run untrusted markup on the
            Dashboard's own origin, so this renders the SAME content through the app's escaping
            instead. What the operator checks here is the content; the packaged file is the same
            content in a portable wrapper.
            """
            det = self._campaign_service().target_detail(domain, run=run_id)
            if det.get("analysis_complete") is not True:
                return _page("AI QA Factory — Client report", "/scout",
                             f'<h1>{_esc(domain)}</h1><div class="card"><p>No client report can be '
                             f'previewed: this target has no completed analysis.</p>'
                             f'<p><a class="btn" href="/scout/target?domain={_esc(domain)}">'
                             f'Back to the target</a></p></div>')
            findings = [f for f in (det.get("findings") or [])
                        if str(f.get("severity") or "").strip().lower() != "info"]
            run = det.get("run") or run_id

            def _art(rel: str) -> str:
                return f'/scout/artifact?run={_esc(run)}&rel={_esc(rel)}'

            media = [str(m) for m in (det.get("media") or [])]
            frames = {str(s.get("file") or ""): s for s in (det.get("screenshots") or [])
                      if isinstance(s, dict)}
            shots = "".join(
                f'<figure class="report-shot"><a href="{_art(m)}" target="_blank" rel="noopener">'
                f'<img src="{_art(m)}" alt="{_esc(frames.get(m.rsplit("/", 1)[-1], {}).get("role") or domain)}">'
                f'</a><figcaption class="muted">'
                f'{_esc(frames.get(m.rsplit("/", 1)[-1], {}).get("role") or m.rsplit("/", 1)[-1])}'
                f'</figcaption></figure>'
                for m in media if m.lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "webp"))
            vids = "".join(
                f'<video src="{_art(m)}" controls preload="metadata" style="max-width:420px"></video>'
                for m in media if m.lower().rsplit(".", 1)[-1] in ("webm", "mp4"))
            rows = "".join(
                f'<tr><td>{_badge(str(f.get("severity") or "unknown").upper())}</td>'
                f'<td><strong>{_esc(f.get("title") or "Untitled finding")}</strong>'
                f'<div class="muted">{_esc(f.get("business_impact") or "Impact not recorded.")}</div>'
                f'</td><td class="muted">{_esc(f.get("url") or "")}</td></tr>'
                for f in findings)
            body = (
                f'<h1>Client report preview — {_esc(domain)}</h1>'
                f'<div class="row"><a class="chip" href="/scout/target?domain={_esc(domain)}'
                f'&amp;run={_esc(run)}">Back to the target</a>'
                f'<a class="btn primary" href="/scout/client-evidence?run={_esc(run)}'
                f'&amp;domain={_esc(domain)}">Download client evidence (.zip)</a></div>'
                f'<div class="banner">This is exactly what the packaged report covers. Your talking '
                f'points, the email draft and the contact\'s provenance are deliberately not here — '
                f'they are operator notes, not client deliverables.</div>'
                f'<div class="card"><h2>Findings the client will see</h2><div class="scrollx">'
                f'<table class="responsive-table"><thead><tr><th>Severity</th>'
                f'<th>Issue and impact</th><th>Page</th></tr></thead><tbody>'
                f'{rows or "<tr><td colspan=3>No confirmed issue was recorded.</td></tr>"}'
                f'</tbody></table></div></div>'
                f'<div class="card"><h2>Screenshots</h2><div class="media-grid">'
                f'{shots or "<p class=muted>No screenshot was captured for this target.</p>"}'
                f'</div></div>'
                + (f'<div class="card"><h2>Reproduction video</h2>{vids}</div>' if vids else ''))
            return _page("AI QA Factory — Client report", "/scout", body)

        def _scout_client_evidence(self, domain: str, run_id: str):
            """Generate and download one exact-target, bounded, client-ready evidence ZIP."""
            if not domain or not run_id:
                return self._json(400, {"error": "exact domain and run are required"})
            try:
                bundle = self._campaign_service().export_client_evidence(
                    domain, run=run_id)
                target = Path(bundle["path"]).resolve()
                if (not target.is_file() or target.is_symlink()
                        or target.suffix.lower() != ".zip"
                        or target.stat().st_size > _MAX_ARTIFACT_BYTES):
                    raise StoreError("client evidence package is unavailable")
                data = target.read_bytes()
            except StoreError as exc:
                return self._json(409, {"error": str(exc)})
            except OSError:
                return self._json(500, {"error": "client evidence package could not be read"})
            filename = str(bundle.get("filename") or "qa-evidence.zip")
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _scout_rescan(self, parsed):
            """One-button human-in-the-loop resume for a target Scout could not analyze unattended
            (e.g. blocked by a CAPTCHA). Marks it eligible again; the next campaign re-analyzes it.
            Never solves/bypasses a challenge — the operator handles that in their own session."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            domain = ((parse_qs(parsed.query).get("domain") or [""])[0]
                      or str((body or {}).get("domain", ""))).strip()
            ok = AnalyzedSiteRegistry(service.output_dir).request_rescan(domain) if domain else False
            return self._json(200 if ok else 404, {
                "ok": ok, "domain": domain,
                "message": ("Marked for re-analysis. Solve the challenge in your own browser, then "
                            "run a campaign including this target — Scout will continue.") if ok
                else "no such target"})

        def _scout_replay(self, parsed):
            """Watch a single target replayed in a VISIBLE (headed) browser. Runs one bounded,
            isolated ScoutEngine pass (own run store, no discovery, no other run disturbed) with a
            forced-headful Playwright backend, so a window opens and fresh evidence is captured.
            CSRF-guarded. Never solves challenges; never sends anything."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            domain = ((parse_qs(parsed.query).get("domain") or [""])[0]
                      or str((body or {}).get("domain", ""))).strip()
            if not domain:
                return self._json(400, {"ok": False, "error": "no domain"})
            import time as _time

            from core.scout.backends import PlaywrightBackend
            from core.scout.config import ScoutRunConfig
            from core.scout.discovery.domain_intel import canonical_domain
            from core.scout.engine import ScoutEngine
            dom = canonical_domain(domain) or domain
            run_id = f"replay-{dom}-{int(_time.time())}".replace("/", "-").replace("\\", "-")
            try:
                cfg = ScoutRunConfig(campaign_name="headed-replay", seeds=[f"https://{dom}/"],
                                     max_sites=1, browser_mode="playwright",
                                     output_dir=service.output_dir, run_id=run_id)
                store = RunStore(service.output_dir, run_id)
                backend = PlaywrightBackend(policy=cfg.url_policy(), headful=True)
                engine = ScoutEngine(cfg, store, backend=backend)
            except Exception as exc:
                return self._json(400, {"ok": False,
                                        "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            _threading.Thread(target=engine.run, name=f"replay-{run_id}", daemon=True).start()
            return self._json(200, {"ok": True, "run_id": run_id,
                "message": ("Headed replay started — a browser window will open. Watch it, then "
                            "reload this page for the fresh screenshots and evidence.")})

        def _scout_challenge_start(self, parsed):
            """Start an explicit, visible, waiting human-in-the-loop browser session."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            q = parse_qs(parsed.query)
            domain = ((q.get("domain") or [""])[0]
                      or str((body or {}).get("domain") or "")).strip()
            source_run = ((q.get("run") or [""])[0]
                          or str((body or {}).get("run") or "")).strip()
            try:
                item = challenge_manager.start(domain, source_run=source_run)
            except ValueError:
                return self._json(400, {"ok": False, "error": "Enter a valid public domain."})
            except Exception as exc:
                return self._json(400, {"ok": False,
                    "error": ("Could not open the manual browser check "
                              f"({type(exc).__name__}). Check system readiness and try again.")})
            return self._json(202, {"ok": True, "session": item})

        def _scout_challenge_action(self, parsed):
            """Continue, defer, or skip a waiting manual browser session."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            q = parse_qs(parsed.query)
            sid = ((q.get("id") or [""])[0] or str((body or {}).get("id") or "")).strip()
            action = ((q.get("action") or [""])[0]
                      or str((body or {}).get("action") or "")).strip()
            try:
                item = challenge_manager.signal(sid, action)
            except (KeyError, ValueError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            return self._json(200, {"ok": True, "session": item})

        def _scout_operator_action(self, parsed):
            """Archive/restore/skip/cleanup actions from History and exact Run results."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            body = body or {}
            action = str(body.get("action") or "").strip()
            domains = body.get("domains") if isinstance(body.get("domains"), list) else []
            prospect_ids = (body.get("prospect_ids")
                            if isinstance(body.get("prospect_ids"), list) else [])
            run_id = str(body.get("run_id") or "").strip()
            confirm = bool(body.get("confirm"))
            from core.scout.operator_state import OperatorStateStore
            ops = OperatorStateStore(service.output_dir)
            try:
                if action == "archive_targets":
                    result = ops.archive_targets(domains)
                elif action == "restore_targets":
                    result = ops.restore_targets(domains)
                elif action == "forget_targets":
                    if not confirm:
                        raise StoreError("forget requires explicit confirmation")
                    forgotten = [d for d in domains if AnalyzedSiteRegistry(
                        service.output_dir).forget(d, confirm=True)]
                    ops.restore_targets(forgotten)
                    result = {"ok": True, "forgotten": forgotten,
                              "message": "History removed; exact-run evidence was preserved."}
                elif action == "skip_queued":
                    result = ops.request_skip(run_id, prospect_ids)
                elif action == "delete_evidence":
                    result = ops.delete_heavy_evidence(
                        run_id, prospect_ids, confirm=confirm)
                elif action == "archive_run":
                    result = ops.archive_run(run_id)
                elif action == "restore_run":
                    result = ops.restore_run(run_id)
                elif action == "delete_run":
                    result = ops.delete_run(
                        run_id, confirm=confirm, active_run_id=service.run_id,
                        active=service.is_running())
                else:
                    return self._json(400, {"ok": False, "error": "unknown operator action"})
            except (OSError, StoreError, ValueError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            return self._json(200, result)

        def _scout_engagement(self, parsed):
            """Advance a prospect's sales-funnel status (contacted/replied/won/delivered/lost).
            CSRF-guarded. The registry validates the status and refuses an unknown target."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            q = parse_qs(parsed.query)
            domain = ((q.get("domain") or [""])[0] or str((body or {}).get("domain", ""))).strip()
            status = ((q.get("status") or [""])[0]
                      or str((body or {}).get("status", ""))).strip().lower()
            work_id = ((q.get("work_id") or [""])[0] or str((body or {}).get("work_id", ""))).strip()
            # Won/Delivered are commitments — the registry refuses them unless the operator explicitly
            # confirmed a real client agreement / completed delivery (never a casual one-click change).
            confirm = str((q.get("confirm") or [""])[0]
                          or (body or {}).get("confirm", "")).strip().lower() in ("1", "true", "yes")
            ok = (AnalyzedSiteRegistry(service.output_dir).set_engagement(
                domain, status, work_id=work_id, confirm=confirm) if (domain and status) else False)
            return self._json(200 if ok else 400,
                              {"ok": ok, "domain": domain, "status": status,
                               "needs_confirmation": bool(status in ("won", "delivered")
                                                          and not confirm)})

        def _scout_polish_draft(self, parsed):
            """Explicit, operator-triggered AI polish of the outreach draft (the ONLY draft path that
            may make a paid model call, and only when a live LLM is configured). CSRF-guarded. Reads
            are $0; this mutation is strictly opt-in. Budget controls / no-repeat cache land in Slice 3."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            domain = ((parse_qs(parsed.query).get("domain") or [""])[0]
                      or str((body or {}).get("domain", ""))).strip()
            if not domain:
                return self._json(400, {"ok": False, "error": "no domain"})
            try:
                current = self._campaign_service().target_detail(domain)
                actionable = [f for f in (current.get("findings") or [])
                              if str(f.get("severity") or "").lower() != "info"]
                if not actionable:
                    return self._json(409, {"ok": False,
                        "error": "AI polish is unavailable until a confirmed actionable finding exists"})
                draft = self._campaign_service().polish_draft(domain)
            except Exception as exc:
                return self._json(400, {"ok": False,
                                        "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            return self._json(200, {"ok": True, "domain": domain, "draft": draft})

        def _scout_start_client_work(self, parsed):
            """Bridge a prospect into the client-work lifecycle: build a job brief from the domain +
            Scout findings, run the read-only analyze-job planning/feasibility, and LINK the resulting
            work item. It does NOT mark the prospect Won — that is a proposal/preparation step; Won
            needs a real, owner-confirmed client agreement. Planning only (human approves execution)."""
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            domain = ((parse_qs(parsed.query).get("domain") or [""])[0]
                      or str((body or {}).get("domain", ""))).strip()
            if not domain:
                return self._json(400, {"ok": False, "error": "no domain"})
            import time as _time

            from core.orchestration.client_work import ClientWorkService
            from core.scout.discovery.domain_intel import canonical_domain
            dom = canonical_domain(domain) or domain
            det = self._campaign_service().target_detail(domain)
            actionable = [f for f in (det.get("findings") or [])
                          if str(f.get("severity") or "").lower() != "info"]
            if det.get("analysis_complete") is not True or not actionable:
                return self._json(409, {"ok": False,
                    "error": ("Client work requires a completed analysis with at least one "
                              "confirmed actionable finding")})
            brief = _client_work_brief(dom, det.get("findings") or [])
            pid = f"scout-{dom.replace('.', '-')}-{int(_time.time())}"[:64].rstrip("-.")
            try:
                res = ClientWorkService(output_dir=service.output_dir).analyze(
                    brief, pid, source_platform="scout")
            except Exception as exc:
                return self._json(400, {"ok": False,
                                        "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            # Link the work item WITHOUT advancing the sales stage. The prospect stays where it is;
            # Won requires a real, owner-confirmed client agreement (explicit, confirmed action).
            AnalyzedSiteRegistry(service.output_dir).link_work(domain, pid)
            return self._json(200, {"ok": True, "project_id": pid, "verdict": res.verdict,
                "message": (f"Client-work analysis started ({res.verdict}) and linked as a proposal. "
                            "The prospect's sales stage is unchanged — mark Won only after a real, "
                            "confirmed client agreement. Review feasibility + proposal, then approve "
                            "execution.")})

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
            banner = ("<span class='danger-ctl'>OUTREACH ENABLED</span>" if enabled
                      else "<span class='ok-ctl'>OUTREACH DISABLED (default)</span>")
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
            legacy_run_id = status.get("run_id", "")
            rows = []
            for pid, p in sorted(prospects.items()):
                epid = _esc(pid)
                rows.append(
                    f"<tr><td>{epid}</td><td>{_esc(p.get('url', ''))}</td>"
                    f"<td>{_esc(p.get('status', ''))}</td><td>{_esc(p.get('priority', ''))}</td>"
                    f"<td>{_esc(p.get('verified_defects', 0))}</td>"
                    f"<td>{_scout_details_cell(legacy_run_id, pid, p)}</td></tr>"
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
                    '<button onclick="ctl(\'kill\')" class="danger-ctl">Cancel (kill)</button>'
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
   coverage:(document.getElementById('coverage')||{{}}).value||'adaptive'}})}})
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
            # Refresh re-renders the current page; it is an action, not a destination, so it is a
            # real button (a link with href="#" is announced as a link and moves focus to the top).
            return ('<div class="row" style="font-size:12px"><span id="pollstate" class="muted" '
                    'aria-live="polite">Live</span><span class="muted">·</span>'
                    '<span class="muted">Last updated <span id="lastupd">just now</span></span>'
                    '<span class="muted">·</span><button type="button" class="linklike" '
                    'onclick="location.reload()">Refresh now</button>'
                    '<span id="pollbanner" hidden> · <button type="button" class="linklike" '
                    'onclick="location.reload()">Updates available — Refresh</button></span></div>')

        def _poll_script(self, endpoint: str, sig_keys: str) -> str:
            # Bounded same-origin polling: refresh a freshness indicator and flag when the persisted
            # state changed; it NEVER auto-reloads (so typing / confirm dialogs are never interrupted)
            # - the operator clicks Refresh. Pauses when the tab is hidden.
            return (
                "(function(){var base=null;var url=" + json.dumps(endpoint) + ";"
                "function sig(j){try{return JSON.stringify((" + sig_keys + ")(j));}catch(e){return 'sig-error:'+String(e);}}"
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

        def _operator_overview_page(self, q=None) -> str:
            diag = self._want_diagnostics(q or {})
            ov = self._read_model().overview(include_diagnostics=diag)
            def _att(a):
                # Several projects can need attention for the SAME reason, so each card has to name
                # the project it is about - otherwise the cards are indistinguishable.
                project = _esc(a.get("project_title") or a.get("project_id", ""))
                return (f'<div class="card"><div class="row" style="justify-content:space-between">'
                        f'<div><strong>{_esc(a["title"])}</strong> '
                        f'{_badge(stage_label(a["status"]), "attention")}<br>'
                        f'<span class="attention-project">{project}</span><br>'
                        f'<span class="muted">{_esc(a["reason"])}</span></div>'
                        f'<a class="btn primary" href="{_esc(a["href"])}">'
                        f'Open<span class="sr-only"> {project}</span></a></div></div>')
            # Nothing to do is one line. As a full-height card it competed for attention with the
            # blocks that DID have something in them, and three such cards on one screen taught the
            # operator to skim past the region where real blockers appear.
            att = "".join(_att(a) for a in ov.attention) or (
                '<p class="quiet-state attention-clear">Nothing needs your attention. '
                '<span class="muted">Blocked or review-ready work appears here.</span></p>')
            def _wrow(p):
                return (f'<tr><td><a href="{_esc(p["href"])}">{_esc(p["title"])}</a></td>'
                        f'<td>{_badge(p["stage"])}</td><td>{_badge(health_label(p["health"]), p["health"])}</td>'
                        f'<td>{_esc(p["next_action"])}</td></tr>')
            def _wcard(p):
                # Same responsive treatment the Work queue already uses: a four-column table is
                # unreadable on a phone, so narrow viewports get cards instead.
                return (f'<li><div class="card"><h3><a href="{_esc(p["href"])}">'
                        f'{_esc(p["title"])}</a></h3>'
                        f'<div class="muted meta">{_esc(p["project_id"])}</div>'
                        f'<div class="row" style="margin:.4rem 0">{_badge(p["stage"])} '
                        f'{_badge(health_label(p["health"]), p["health"])}</div>'
                        f'<div><strong>Next:</strong> {_esc(p["next_action"])}</div></div></li>')
            work = "".join(_wrow(p) for p in ov.active_work)
            open_work = ov.counts.get("open_work", 0)
            more_open = (f'<p class="muted"><a href="/work?view=active">View all {open_work} open '
                         f'project(s)</a></p>' if open_work > len(ov.active_work) else '')
            work_tbl = (f'<div class="scrollx only-desktop"><table>'
                        f'<caption>Approved and running now</caption><tr><th>Project</th>'
                        f'<th>Stage</th><th>Health</th><th>Next action</th></tr>{work}</table></div>'
                        f'<ul class="cards only-mobile" aria-label="Active work">'
                        f'{"".join(_wcard(p) for p in ov.active_work)}</ul>'
                        f'{more_open}'
                        if work else
                        '<p class="quiet-state">No client work is running. '
                        '<a href="/work?create=1#client-brief">Analyze a client brief</a> to create '
                        'a reviewable plan.</p>')
            def _crow(c):
                return (f'<tr><td>{_esc(c["title"])}</td><td>{_badge(c["status"])}</td>'
                        f'<td>{_esc(c["next_action"])}</td></tr>')
            # Failed campaigns need the operator too, but they live on a different surface, so they
            # get their own honest block instead of being counted into the work-attention tile.
            def _srow(s):
                return (f'<li><strong>{_esc(s["project_title"])}</strong> — '
                        f'{_esc(s["reason"])}</li>')
            failed_scout = ("".join(_srow(s) for s in ov.scout_attention))
            scout_failed_block = (
                f'<div class="card" style="border-color:var(--attention)">'
                f'<strong>&#9888; {len(ov.scout_attention)} Scout campaign(s) ended in a failed '
                f'state</strong><ul>{failed_scout}</ul>'
                f'<p><a class="btn" href="/scout/campaigns">Review Scout campaigns</a></p></div>'
                if failed_scout else '')
            camps = "".join(_crow(c) for c in ov.active_campaigns)
            camp_tbl = (f'<div class="scrollx"><table><caption>Active Scout campaigns</caption>'
                        f'<tr><th>Campaign</th><th>Status</th><th>Next action</th></tr>{camps}'
                        f'</table></div>'
                        if camps else
                        '<p class="quiet-state">No campaign is running.</p>')
            # Scout is the primary thing this page starts, so its two actions are always offered —
            # not only when the campaign list happens to be empty.
            scout_actions = ('<div class="row scout-actions">'
                             '<a class="btn primary" href="/scout/new">Start Scout</a>'
                             '<a class="btn" href="/results">View Scout results</a>'
                             '<a class="btn" href="/scout/attention">Needs attention</a></div>')
            hidden = ov.counts.get("diagnostics_hidden", 0)
            # The diagnostics switch is a view preference, not a status, so it belongs with the rest
            # of the diagnostics under More. Only the banner stays here — while the view IS filtered
            # the operator has to be told, or the counts silently mean something else.
            diag_banner = ('<div class="banner warn">Showing diagnostic data (smoke/acceptance/'
                           'replay/demo). These are not production work. '
                           '<a href="/">Show production only</a></div>' if diag else '')
            body = (f'<h1>Overview</h1>{diag_banner}'
                    f'<div class="summary-grid overview-summary">'
                    f'<a class="summary-item" href="/work?view=active">'
                    f'<span class="muted">Open work</span>'
                    f'<strong>{ov.counts.get("open_work", 0)}</strong></a>'
                    f'<a class="summary-item" href="/work?view=needs_attention">'
                    f'<span class="muted">Needs attention</span>'
                    f'<strong>{ov.counts.get("attention", 0)}</strong>'
                    f'<span class="tile-note">client work</span></a>'
                    f'<a class="summary-item" href="/scout/campaigns">'
                    f'<span class="muted">Active Scout campaigns</span>'
                    f'<strong>{ov.counts.get("active_campaigns", 0)}</strong></a></div>'
                    f'{self._poll_html()}'
                    f'<h2>Scout</h2>{scout_actions}{scout_failed_block}{camp_tbl}'
                    f'<h2>Needs your attention</h2>{att}'
                    f'<h2>Client work</h2>'
                    f'<p class="muted">Approved projects that are ready to run, running, or being '
                    f'validated. Everything not yet finished lives in Open work.</p>'
                    f'{work_tbl}'
                    f'{_system_ready_html(service.output_dir, hidden)}')
            script = ("const CSRF=" + json.dumps(csrf_token) + ";\n"
                      + self._poll_script(
                          "/api/overview",
                          "function(j){return [(j.attention||[]).map(function(a){return a.project_id"
                          "+'|'+a.status+'|'+a.next_action}),(j.active_work||[]).map(function(p){"
                          "return p.project_id+'|'+p.status+'|'+p.progress+'|'+p.next_action}),"
                          "(j.active_campaigns||[]).map(function(c){return c.campaign_id+'|'+c.status"
                          "+'|'+c.progress})]}"))
            return _page("AI QA Factory — Overview", "/", body, script)

        _WORK_PRIMARY_VIEWS = (("active", "Active"), ("needs_attention", "Needs attention"),
                               ("completed", "Completed"), ("all", "All"))
        _WORK_STATUS_VIEWS = (("ready_to_execute", "Ready to execute"),
                              ("in_progress", "In progress"), ("blocked", "Blocked"),
                              ("ready_for_review", "Ready for review"),
                              ("ready_for_delivery", "Ready for delivery"),
                              ("delivery_prepared", "Delivery prepared"))

        def _work_list_page(self, q) -> str:
            view = (q.get("view") or ["active"])[0]
            allowed_views = {v for v, _ in self._WORK_PRIMARY_VIEWS + self._WORK_STATUS_VIEWS}
            if view not in allowed_views:
                view = "active"
            diag = self._want_diagnostics(q)
            data = self._read_model().project_list(view=view, include_diagnostics=diag)
            _dsuffix = "&diagnostics=1" if diag else ""
            views = "".join(
                f'<a class="chip" href="/work?view={v}{_dsuffix}"'
                f'{" aria-current=\"page\"" if v == view else ""}>{_esc(lbl)}</a>'
                for v, lbl in self._WORK_PRIMARY_VIEWS)
            status_options = ['<option value="" disabled'
                              + (' selected' if view not in dict(self._WORK_STATUS_VIEWS) else '')
                              + '>Choose a stage</option>']
            status_options.extend(
                f'<option value="{v}"{" selected" if v == view else ""}>{_esc(lbl)}</option>'
                for v, lbl in self._WORK_STATUS_VIEWS)
            diag_hidden = (
                '<input type="hidden" name="diagnostics" value="1">' if diag else '')
            status_filter = (
                '<form class="work-status-filter" action="/work" method="get">'
                '<label for="work_status">Status</label>'
                f'<select id="work_status" name="view" onchange="document.getElementById('
                f'\'work_status_apply\').disabled=!this.value">{"".join(status_options)}</select>'
                f'{diag_hidden}<button id="work_status_apply" class="btn" type="submit"'
                f'{" disabled" if view not in dict(self._WORK_STATUS_VIEWS) else ""}>Apply</button>'
                '</form>')
            hidden = self._read_model().overview(
                include_diagnostics=False).counts.get("diagnostics_hidden", 0)
            diag_toggle = (
                f'<a class="chip" href="/work?view={view}">&#10003; Production only — hide '
                'diagnostics</a>' if diag else
                f'<a class="chip" href="/work?view={view}&diagnostics=1">Show diagnostics'
                f'{f" ({hidden})" if hidden else ""}</a>')
            diag_description = (
                f'{hidden} test, replay, or diagnostic record'
                f'{" is" if hidden == 1 else "s are"} hidden from production views.'
                if not diag else
                'Diagnostic work is visible in this view and remains excluded from production '
                'counts on Overview.')
            diag_options = (
                '<details class="advanced compact-details work-view-options">'
                '<summary>Advanced view options</summary>'
                f'<p class="muted">{diag_description}</p><div class="row">{diag_toggle}</div>'
                '</details>')
            def _row(p):
                # Two briefs can share a title; the project name is what makes a row identifiable.
                return (f'<tr><td><a href="{_esc(p["href"])}">{_esc(p["title"])}</a>'
                        f'<div class="muted meta">{_esc(p["project_id"])}</div></td>'
                        f'<td>{_badge(p["stage"])}</td><td>{_badge(health_label(p["health"]), p["health"])}</td>'
                        f'<td>{_esc(p["next_action"])}</td>'
                        f'<td class="muted">{_esc(_fmt_ts(p["updated"]))}</td></tr>')

            def _card(p):
                return (f'<li><div class="card"><h3><a href="{_esc(p["href"])}">{_esc(p["title"])}</a></h3>'
                        f'<div class="muted meta">{_esc(p["project_id"])}</div>'
                        f'<div class="row" style="margin:.4rem 0">{_badge(p["stage"])} '
                        f'{_badge(health_label(p["health"]), p["health"])}</div>'
                        f'<div><strong>Next:</strong> {_esc(p["next_action"])}</div>'
                        f'<div class="muted meta">Updated {_esc(_fmt_ts(p["updated"]))}</div></div></li>')

            if data["projects"]:
                rows = "".join(_row(p) for p in data["projects"])
                # The caption names the view the way the operator selected it, not by its URL key.
                view_label = dict(self._WORK_PRIMARY_VIEWS + self._WORK_STATUS_VIEWS).get(view, view)
                # The result region gets its own heading so the page never jumps h1 -> h3 (the
                # mobile cards are h3) and screen-reader users can navigate straight to it.
                heading = '<h2 class="sr-only">Projects</h2>'
                desktop = (f'{heading}<div class="scrollx only-desktop"><table>'
                           f'<caption>{data["total"]} project(s) — {_esc(view_label)}</caption>'
                           f'<tr><th>Project</th><th>Stage</th>'
                           f'<th>Health</th><th>Next action</th><th>Updated</th></tr>{rows}</table></div>')
                cards = ('<ul class="cards only-mobile" aria-label="Projects">'
                         + "".join(_card(p) for p in data["projects"]) + "</ul>")
                table = desktop + cards
            else:
                empty_states = {
                    "active": (
                        "No active client work",
                        "Analyze a brief to create a feasibility assessment and reviewable plan.",
                        '<a class="btn primary" href="/work?create=1#client-brief">'
                        'Analyze a client brief</a>',
                    ),
                    "needs_attention": (
                        "Nothing needs your attention",
                        "Blocked, approval-ready, and review-ready work will appear here.",
                        '<a class="btn" href="/work?view=active">View active work</a>',
                    ),
                    "completed": (
                        "No completed client work",
                        "Finished and manually delivered projects will remain available here.",
                        '<a class="btn" href="/work?view=active">View active work</a>',
                    ),
                    "all": (
                        "No client work yet",
                        "Paste a client brief to create the first reviewable work plan.",
                        '<a class="btn primary" href="/work?create=1#client-brief">'
                        'Analyze a client brief</a>',
                    ),
                }
                title, description, action = empty_states.get(
                    view,
                    ("No work at this stage",
                     "Projects will appear here when they reach the selected lifecycle stage.",
                     '<a class="btn" href="/work?view=active">View active work</a>'))
                table = (f'<div class="card empty compact"><strong>{title}</strong>'
                         f'<div class="muted">{description}</div>'
                         f'<p class="row empty-actions">{action}</p></div>')
            open_intake = " open" if (q.get("create") or [""])[0] in ("1", "true", "yes") else ""
            create = (
                f'<details id="client-brief" class="card work-intake"{open_intake}>'
                '<summary>Analyze a client brief</summary>'
                '<p class="muted work-intake-intro">Create a reviewable feasibility assessment and '
                'work plan. Nothing will execute until you approve the plan.</p>'
                '<div class="work-intake-grid">'
                '<label for="cw_pid">Project name <span class="label-note">(optional)</span></label>'
                # The '-' is escaped on purpose: `pattern` is compiled with the RegExp `v` flag, and
                # an unescaped trailing '-' makes the browser throw, silently disabling validation.
                r'<input id="cw_pid" maxlength="64" pattern="[A-Za-z0-9._\-]+" '
                'aria-describedby="cw_pid_help" placeholder="checkout-regression">'
                '<small id="cw_pid_help" class="field-help">Letters, numbers, dots, underscores, and '
                'hyphens. Leave blank to generate a safe name.</small>'
                '<label for="cw_src">Source platform <span class="label-note">(optional)</span></label>'
                '<select id="cw_src"><option value="manual">Not specified</option>'
                '<option value="upwork">Upwork</option><option value="direct">Direct client</option>'
                '<option value="other">Other</option></select>'
                '<label for="cw_brief">Client brief</label>'
                '<textarea id="cw_brief" rows="7" required aria-describedby="cw_brief_help cw_error" '
                'placeholder="Paste the client request, scope, deliverables, deadline, budget, and '
                'available access."></textarea>'
                '<small id="cw_brief_help" class="field-help">Include enough detail to assess fit, '
                'risks, missing access, validation, and expected deliverables.</small></div>'
                '<div id="cw_error" class="form-error" role="alert" aria-live="assertive" '
                'tabindex="-1" hidden></div>'
                '<div class="row work-intake-actions"><button class="btn primary" type="button" '
                'onclick="createWork(this)">Analyze and create plan</button>'
                '<span id="cw_status" class="muted" role="status" aria-live="polite"></span></div>'
                '</details>')
            script = (self._work_actions_script() +
                      "function clearWorkError(){var e=document.getElementById('cw_error');"
                      "var b=document.getElementById('cw_brief'),p=document.getElementById('cw_pid');"
                      "if(e){e.hidden=true;e.textContent='';}if(b)b.removeAttribute('aria-invalid');"
                      "if(p)p.removeAttribute('aria-invalid');}\n"
                      "function showWorkError(message,field){var e=document.getElementById('cw_error');"
                      "var s=document.getElementById('cw_status');if(s)s.textContent='';"
                      "if(e){e.textContent=message;e.hidden=false;}if(field){"
                      "field.setAttribute('aria-invalid','true');field.focus();}else if(e)e.focus();}\n"
                      "function setWorkBusy(btn,busy){if(!btn)return;if(busy){"
                      "btn.dataset.busy='1';btn.disabled=true;}else{btn.disabled=false;"
                      "delete btn.dataset.busy;}}\n"
                      "function createWork(btn){var brief=document.getElementById('cw_brief');"
                      "var pid=document.getElementById('cw_pid');var b=brief.value.trim();"
                      "clearWorkError();if(!b){showWorkError('Paste a client brief to continue.',brief);"
                      "return;}var p=pid.value.trim();if(p&&!/^[A-Za-z0-9._-]{1,64}$/.test(p)){"
                      "showWorkError('Use only letters, numbers, dots, underscores, or hyphens in "
                      "the project name.',pid);return;}if(btn&&btn.dataset.busy)return;"
                      "setWorkBusy(btn,true);var status=document.getElementById('cw_status');"
                      "if(status)status.textContent='Analyzing the brief and creating a plan…';"
                      "fetch('/api/work/analyze',{method:'POST',headers:{'Content-Type':'application/json',"
                      "'X-Scout-CSRF':CSRF},body:JSON.stringify({text:b,"
                      "project_id:p,source_platform:document.getElementById('cw_src').value})})"
                      ".then(r=>r.json()).then(function(j){if(j.ok){location.href='/work/'+j.project_id;}"
                      "else{setWorkBusy(btn,false);showWorkError(j.error||"
                      "'Could not analyze this brief. Review the fields and try again.');}})"
                      ".catch(function(){setWorkBusy(btn,false);showWorkError("
                      "'The analysis could not start. Check that the Dashboard is running and try "
                      "again.');});}"
                      "var cwb=document.getElementById('cw_brief');if(cwb)cwb.addEventListener("
                      "'input',clearWorkError);var cwp=document.getElementById('cw_pid');"
                      "if(cwp)cwp.addEventListener('input',clearWorkError);")
            body = (f'<h1>Work</h1><p class="muted">Active client work is shown by default. '
                    f'Completed items remain available in the Completed view.</p>'
                    f'<div class="work-filter-bar"><nav class="work-primary-views" '
                    f'aria-label="Work views">{views}</nav>{status_filter}</div>'
                    f'{self._poll_html()}'
                    f'{table}{diag_options}{create}')
            # Poll the current view; the banner never auto-reloads, so the Create-work form is safe.
            # The signature notices same-status changes (progress/updated/blockers/evidence/next).
            script = (script + self._poll_script(
                "/api/work?view=" + view,
                "function(j){return (j.projects||[]).map(function(p){return p.project_id+'|'+p.status"
                "+'|'+p.progress+'|'+p.updated+'|'+p.blockers+'|'+p.evidence_count+'|'+p.next_action})}"))
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
                    fixed = "Object.assign({project_id:'" + safe_pid + "'}," + json.dumps(
                        a.get("body") or {}) + ")"
                    if a.get("fields"):
                        fields_js = "[" + ",".join("'" + f + "'" for f in a["fields"]) + "]"
                        extra = "Object.assign(" + fixed + ",promptFields(" + fields_js + "))"
                    else:
                        extra = fixed
                    action_js = "wact(this,'" + act + "'," + extra + ")"
                    if a.get("confirm"):
                        onclick = ("var btn=this;qaConfirm(" + json.dumps(a["label"] + "?")
                                   + "," + json.dumps(a["label"])
                                   + ").then(function(ok){if(ok)wact(btn,'" + act + "',"
                                   + extra + ");})")
                    else:
                        onclick = action_js
                    # The handler is JS placed inside a double-quoted HTML attribute, and
                    # json.dumps() emits double quotes: without escaping, the attribute ends at the
                    # first one and the whole handler is truncated to `qaConfirm(` - which silently
                    # turned every confirm-guarded action (Mark Delivered, Reopen Delivery) into a
                    # dead button. Entities are decoded before the JS is evaluated, so _esc is safe.
                    actbtns.append(f'<button class="{cls}" onclick="{_esc(onclick)}">'
                                   f'{_esc(a["label"])}</button>')
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
                      f'<div class="row">{_badge(h["stage"])} {_badge(health_label(h["health"]), h["health"])} '
                      f'<span class="muted">{_esc(_source_label(h["source"]))} · '
                      f'{h["progress"]}% complete</span></div>'
                      f'{self._poll_html()}'
                      f'<div class="row" style="margin:.6rem 0">{"".join(actbtns)}'
                      f'<span id="copystatus" class="muted" aria-live="polite"></span></div>')
            summary = d["summary"]
            blockers = "".join(f"<li>{_esc(x)}</li>" for x in summary["blockers"]) or "<li class=muted>none</li>"
            # Intake questions are a different thing from execution blockers, and the Work list
            # counts them - so the detail has to show them instead of reporting "none".
            missing = summary.get("missing_information") or []
            still_blocking = summary["status"] in _INTAKE_STATES
            missing_block = (
                f'<p><strong>Information needed from the client:</strong>'
                f'{"" if still_blocking else " <span class=\'muted\'>(recorded at intake; no longer blocking)</span>"}'
                f'</p><ul>{"".join(f"<li>{_esc(x)}</li>" for x in missing)}</ul>') if missing else ''
            panel = {
                "summary": (
                    '<div class="card">'
                    f'<p><strong>Next:</strong> {_esc(summary["next_action"])}</p>'
                    f'<p><strong>Validation:</strong> {summary["tests_passed"]}/{summary["tests_run"]} · '
                    f'evidence {summary["evidence_count"]}</p>'
                    f'{missing_block}'
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
                    f'<p>State: {_badge(stage_label(d["delivery"]["status"]), "attention" if d["delivery"]["status"] == "DELIVERY_PREPARED" else "")}</p>'
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
                self._poll_script(
                    "/api/work/" + safe_pid,
                    "function(j){var h=j.header||{},s=j.summary||{},d=j.delivery||{},r=j.results||{};"
                    "return [h.status,h.progress,h.updated_at,h.activity_count,s.next_action,"
                    "(s.blockers||[]).length,s.tests_passed,s.tests_run,s.evidence_count,"
                    "r.validation_passed,d.status,d.manifest_digest]}"))
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
                primary_control = (
                    '<button class="btn primary" onclick="ctl(\'resume\')">Resume</button>'
                    if str(mode).upper() == "PAUSED" else
                    '<button class="btn primary" onclick="ctl(\'pause\')">Pause</button>')
                controls = (primary_control
                            + '<button class="btn" onclick="ctl(\'cancel\')">Stop &amp; save</button>'
                            + '<details class="advanced"><summary>Emergency action</summary>'
                            + '<button class="btn danger" onclick="ctl(\'kill\')">'
                            + 'Cancel immediately</button></details>')
            else:
                controls = (f'<em class="muted">Controls unavailable — this run is '
                            f'<strong>{_esc(mode)}</strong> (read-only).</em>')
            run_id = status.get("run_id", "")
            from core.scout.discovery.domain_intel import canonical_domain
            prows = "".join(
                f'<tr><td data-label="Target">{_esc(canonical_domain(p.get("url","")) or p.get("url",""))}</td>'
                f'<td data-label="Status">{_badge(_run_prospect_label(p))}</td>'
                f'<td data-label="Priority">{_esc(p.get("priority", "") or "—")}</td>'
                f'<td data-label="Actionable">{_esc(p.get("verified_defects", 0))}</td>'
                f'<td data-label="Open">{_scout_details_primary(run_id, p)}</td></tr>'
                for pid, p in sorted(prospects.items()))
            if prows:
                table = (f'<table class="responsive-table"><caption>Targets in this run</caption>'
                         f'<thead><tr><th>Target</th><th>Status</th><th>Priority</th>'
                         f'<th>Actionable</th><th>Open</th></tr></thead><tbody>{prows}</tbody></table>')
            elif running:
                # An ACTIVE run whose prospect map is still empty is NOT an empty run: the engine
                # persists the run and its config before it populates that map, and the populated map
                # only reaches disk once the first target finishes. Saying "no prospects" here while
                # a browser is working on one contradicts the ACTIVE badge next to it. The run's own
                # config carries the seeds, so the queued targets can be named from persisted data —
                # and when no config is readable we say what is happening without inventing a list.
                seeds = []
                try:
                    cfg = service.store.load_config() if service.store is not None else {}
                    seeds = list((cfg or {}).get("seeds") or [])
                except (StoreError, AttributeError, TypeError):
                    seeds = []
                # These are the SEEDS as submitted, not the targets the engine will end up with: it
                # drops policy-rejected ones, collapses duplicates by normalized URL and truncates to
                # the campaign's site limit. Call them seeds, collapse the obvious repeats so one
                # domain is not printed twice, and cap the list so a large import cannot fill the
                # card.
                shown, seen = [], set()
                for raw in seeds:
                    dom = canonical_domain(raw) or str(raw)
                    if dom not in seen:
                        seen.add(dom)
                        shown.append(dom)
                extra = max(len(shown) - 10, 0)
                listed = ", ".join(shown[:10]) + (f" and {extra} more" if extra else "")
                queued_html = (f'<b>{len(shown)} '
                               f'{"seed" if len(shown) == 1 else "seeds"} submitted:</b> '
                               f'{_esc(listed)}. ' if shown else '')
                # Say the same thing the status badge above says. The engine persists the run as
                # PENDING first and only flips it to RUNNING once it actually begins, so while the
                # worker is starting and the browser is launching the badge reads "Queued" — claiming
                # "analysis in progress" beside it would be the contradiction this notice exists to
                # remove, in the other direction.
                # A paused or stopping run writes no status of its own — the engine blocks inside its
                # control gate and the persisted status stays RUNNING — so reading the status alone
                # would announce analysis that is not happening. The control flags are on this very
                # page; consult them first.
                control = status.get("control") or {}
                if control.get("paused"):
                    phase, tail = "Paused", "no target will start until you resume"
                elif control.get("cancelled") or control.get("killed"):
                    phase, tail = "Stopping", "the current target finishes and no new target starts"
                elif str(st.get("status", "") or "").strip().upper() == "RUNNING":
                    phase, tail = ("Analysis in progress",
                                   "no target has finished yet. Each one appears here as it completes")
                else:
                    phase, tail = ("The run is starting",
                                   "no target has finished yet. Each one appears here as it completes")
                table = (f'<div class="card empty muted">{queued_html}{phase} — {tail}.</div>')
            else:
                table = '<div class="card empty muted">No prospects in this run.</div>'
            start_panel = "" if running else _START_PANEL_HTML
            results_link = (f'<a class="chip" href="/scout/run?id={_esc(run_id)}">Run results</a>'
                            if run_id else '')
            body = (f'<h1>Manual URL Scan</h1><p class="muted">{_esc(SCOUT_PRODUCT_NAME)} — bounded, '
                    f'read-only scan of URLs you paste. For automatic prospect discovery use '
                    f'<a href="/scout/new">Discover Prospects</a>. Nothing is sent without your action.</p>'
                    f'<div class="row"><a class="chip" href="/scout/new">Discover Prospects (adaptive)</a>'
                    f'<a class="chip" href="/scout/history">History</a>'
                    f'<a class="chip" href="/scout/attention">Needs attention</a>'
                    f'<a class="chip" href="/results">Companies &amp; outreach</a></div>'
                    f'<div class="card"><p>Scan mode {_badge(mode)} · status '
                    f'{_badge(_prospect_status_label(st.get("status", "n/a")))}</p>'
                    # This card states what a live process is doing, so it must also say whether the
                    # statement is still current. Without it the page froze at the moment it was
                    # opened and a finished run kept reading as a starting one. Same freshness row
                    # and same polling helper the sibling operator screens already use; it never
                    # auto-reloads, so a confirm dialog or a half-typed URL is never interrupted.
                    + (self._poll_html() if running else '')
                    + f'<div class="row">{controls}</div></div>'
                    f'<div class="row"><a class="chip" href="/scout/campaigns">Campaigns</a>'
                    f'{results_link}</div>'
                    f'<div class="scrollx">{table}</div>'
                    + (f'<details class="card advanced"><summary>Run diagnostics</summary>'
                       f'<p><b>Run ID:</b> <code>{_esc(run_id)}</code></p></details>' if run_id else '')
                    + start_panel)
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
                "var mode=(document.getElementById('scanmode')||{}).value||'static';"
                "fetch('/api/campaign/start',{method:'POST',headers:{'Content-Type':'application/json',"
                "'X-Scout-CSRF':CSRF},body:JSON.stringify({confirm:true,idempotency_key:key,seeds:seeds,"
                "campaign:document.getElementById('campaign').value||'adhoc',browser_mode:mode,"
                "coverage:(document.getElementById('coverage')||{}).value||'adaptive'})})"
                ".then(r=>r.json()).then(function(j){if(j.ok){location.reload();}else{"
                "alert('start refused: '+(j.message||j.error));}}).catch(function(e){"
                "alert('start failed: '+e);});}\n"
                "function esc(s){return String(s).replace(/[&<>\"]/g,function(c){"
                "return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c];});}\n"
                "function importList(){var f=document.getElementById('impfile').files[0];"
                "if(!f){alert('choose a .xlsx or .csv file');return;}var rd=new FileReader();"
                "rd.onload=function(){var b64=String(rd.result).split(',').pop();"
                "fetch('/api/scout/import',{method:'POST',headers:{'Content-Type':'application/json',"
                "'X-Scout-CSRF':CSRF},body:JSON.stringify({filename:f.name,content_b64:b64})})"
                ".then(r=>r.json()).then(function(j){if(!j.ok){document.getElementById('imppreview')"
                ".innerHTML='<p class=muted>Import refused: '+esc(j.error||'')+'</p>';return;}"
                "renderImport(j.result);}).catch(function(e){alert('import failed: '+e);});};"
                "rd.readAsDataURL(f);}\n"
                "function mget(r,k){var m=r.metadata||{};for(var kk in m){"
                "if(kk.toLowerCase()===k)return m[kk];}return '';}\n"
                "function renderImport(res){var c=res.counters;var head='<p class=muted>'+c.preselected"
                "+' preselected \\u00b7 '+c.valid_unique+' new \\u00b7 '+c.already_analyzed+' already \\u00b7 '"
                "+c.rejected+' rejected \\u00b7 '+c.dup_in_file+' dup \\u00b7 '+c.invalid+' invalid ('"
                "+c.total+' rows; column '+esc(res.column)+')</p>';var trs=res.rows.map(function(r){"
                "var pre=(r.preselect)?'checked':'';"
                "var dis=(r.valid&&r.disposition!=='duplicate')?'':'disabled';"
                "var score=mget(r,'weighted score')||mget(r,'qa potential');"
                "return '<tr><td><input type=checkbox class=impsel '+pre+' '+dis+' data-seed=\"'"
                "+esc(r.seed_url)+'\"></td><td>'+esc(r.canonical_domain||r.original)+'</td><td>'"
                "+esc(mget(r,'product'))+'</td><td>'+esc(mget(r,'priority'))+'</td><td>'"
                "+esc(r.recommended_action||'')+'</td><td>'+esc(score)+'</td><td>'"
                "+esc(r.disposition)+'</td></tr>';}).join('');"
                "document.getElementById('imppreview').innerHTML=head+'<table><tr><th></th><th>Domain</th>"
                "<th>Product</th><th>Priority</th><th>Rec. action</th><th>Score</th><th>Disposition</th>"
                "</tr>'+trs+'</table>'+'<p><label>Campaign name: "
                "<input id=impcampaign value=curated></label> &nbsp;<label>Coverage: <select "
                "id=impcoverage><option value=adaptive selected>Adaptive \u2014 max 12 pages</option>"
                "<option value=deep>Deep \u2014 max 20 pages</option>"
                "</select></label>"
                " &nbsp;<label>Scan mode: <select id=impscanmode>"
                "<option value=playwright selected>Deep Capture (Playwright)</option>"
                "<option value=static>Static (faster)</option></select></label></p>"
                "<p class=muted>Static = faster HTTP/HTML checks. Deep Capture = real browser: "
                "screenshots, axe accessibility, perf timing and console/network evidence (needs "
                "Chromium). Coverage bounds how many same-site pages are explored (never a quota); "
                "both profiles can stop early once further pages add no new coverage.</p>"
                "<p><label><input type=checkbox id=impconfirm> I confirm this is an authorized, "
                "bounded, read-only scan.</label></p>"
                "<p><button class=\"btn primary\" onclick=\"launchImport()\">Scan selected</button></p>';}\n"
                "function launchImport(){var seeds=[].slice.call(document.querySelectorAll("
                "'.impsel:checked')).map(function(x){return x.getAttribute('data-seed');});"
                "if(!seeds.length){alert('select at least one domain');return;}"
                "if(!document.getElementById('impconfirm').checked){"
                "alert('please confirm the bounded read-only scan');return;}"
                "var key=(crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+Math.random();"
                "var mode=(document.getElementById('impscanmode')||{}).value||'static';"
                "fetch('/api/campaign/start',{method:'POST',headers:{'Content-Type':'application/json',"
                "'X-Scout-CSRF':CSRF},body:JSON.stringify({confirm:true,idempotency_key:key,seeds:seeds,"
                "campaign:document.getElementById('impcampaign').value||'curated',browser_mode:mode,"
                "coverage:(document.getElementById('impcoverage')||{}).value||'adaptive'})})"
                ".then(r=>r.json()).then(function(j){if(j.ok){location.reload();}else{"
                "alert('start refused: '+(j.message||j.error));}}).catch(function(e){"
                "alert('start failed: '+e);});}\n"
                # Watch exactly what this page renders: whether a run is live, the run's own status,
                # and every target's status. A signature blind to those would leave the stale claim
                # standing. Only a bound run is polled — an idle page has nothing to watch.
                + (self._poll_script(
                    "/api/status",
                    "function(j){var p=(j.state||{}).prospects||{};"
                    "var ks=Object.keys(p).sort();"
                    "return [j.running,j.mode,(j.state||{}).status,j.control||{},ks,"
                    "ks.map(function(k){var e=p[k]||{};return [e.status,!!e.started_at];})]}")
                   if running else ""))
            return _page("AI QA Factory — Scout", "/scout", body, script)

        def _scout_campaigns_page(self, q=None) -> str:
            ov = self._read_model().overview()
            # Reuse the unified project index for scout campaigns (no second store).
            from core.orchestration.project_index import ProjectIndex
            from core.scout.operator_state import OperatorStateStore
            all_camps = [p for p in ProjectIndex(service.output_dir).list_projects()
                         if p.type == "scout_campaign"]
            archived_ids = set(
                OperatorStateStore(service.output_dir).snapshot()["archived_runs"])
            show_archived = ((q or {}).get("archived") or [""])[0] in ("1", "true", "only")
            camps = [p for p in all_camps
                     if (p.project_id in archived_ids) is show_archived]
            archived_count = sum(1 for p in all_camps if p.project_id in archived_ids)
            current_count = len(all_camps) - archived_count
            rows = "".join(
                f'<tr><td><a href="/scout/progress?id={_esc(c.project_id)}">'
                f'{_esc(_friendly_record_label(c.title, c.project_id, "Scout campaign"))}</a></td>'
                f'<td>{_badge(c.lifecycle_state)}</td>'
                f'<td>{c.progress}%</td><td>{c.evidence_count}</td>'
                f'<td class="muted">{_esc(c.operator_next_action)}</td>'
                f'<td><a class="chip" href="/scout/progress?id={_esc(c.project_id)}">Open</a></td></tr>'
                for c in camps)
            table = (f'<table class="responsive-table"><caption>'
                     f'{"Archived" if show_archived else "Current"} Scout campaigns</caption>'
                     f'<tr><th>Campaign</th><th>Status</th>'
                     f'<th>Progress</th><th>Evidence</th><th>Next action</th><th>Open</th></tr>{rows}</table>'
                     if rows else (
                         '<div class="card empty muted">No archived campaigns.</div>'
                         if show_archived else
                         '<div class="card empty muted">No current campaigns. '
                         '<a href="/scout">Open Scout to start one</a>.</div>'))
            body = (f'<h1>Scout campaigns</h1><div class="row">'
                    f'<a class="chip" href="/scout/new">New adaptive campaign</a>'
                    f'<a class="chip" href="/scout/history">History</a>'
                    f'<a class="chip" href="/scout">Manual URL Scan</a>'
                    f'<a class="chip" href="/results">Companies &amp; outreach</a>'
                    f'<span class="chip">Active {len(ov.active_campaigns)}</span></div>'
                    f'<div class="tabs" role="tablist" aria-label="Campaign views">'
                    f'<a role="tab" aria-selected="{"true" if not show_archived else "false"}" '
                    f'href="/scout/campaigns">Current ({current_count})</a>'
                    f'<a role="tab" aria-selected="{"true" if show_archived else "false"}" '
                    f'href="/scout/campaigns?archived=1">Archived '
                    f'({archived_count})</a></div>'
                    f'<div class="scrollx">{table}</div>'
                    f'<p class="muted">Campaign start + Pause/Resume/Stop Safely/Cancel controls are '
                    f'on <a href="/scout">Manual URL Scan</a> (bounded, read-only; nothing is sent).</p>')
            return _page("AI QA Factory — Scout campaigns", "/scout", body)

        # --- v3.3 adaptive Scout operator workflow -------------------------------------------
        def _campaign_service(self):
            from core.scout.campaign_service import CampaignService
            return CampaignService(service.output_dir)

        def _scout_preflight(self):
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            body = body or {}
            preset = str(body.get("campaign_preset") or "balanced-production")
            overrides = body.get("overrides") if isinstance(body.get("overrides"), dict) else None
            try:
                out = self._campaign_service().preflight(
                    campaign_preset=preset,
                    session_preset=body.get("session_preset") or None,
                    overrides=overrides,
                    probe_browser_launch=bool(body.get("probe_browser", True)),
                    do_network=bool(body.get("probe_network", True)))
            except Exception as exc:
                return self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return self._json(200, {"ok": True, **out})

        def _scout_launch(self):
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            body = body or {}
            overrides = body.get("overrides") if isinstance(body.get("overrides"), dict) else None
            # ``overrides`` is forwarded field-by-field into the campaign config, so run_purpose
            # would otherwise ride in as an ordinary override and let a request declare its own
            # discovery — and every per-target run it promotes — disposable. Resolve it here, at the
            # untrusted boundary, through the same server-side gate the seeded launcher uses.
            from core.scout.run_purpose import (PurposeNotPermitted, resolve_requested_purpose,
                                                test_purposes_enabled)
            requested_purpose = (overrides or {}).get("run_purpose", body.get("run_purpose"))
            try:
                purpose = resolve_requested_purpose(requested_purpose,
                                                    allow_test=test_purposes_enabled())
            except PurposeNotPermitted as exc:
                return self._json(422, {"ok": False, "error": str(exc)})
            overrides = {**(overrides or {}), "run_purpose": purpose}
            try:
                res = self._campaign_service().launch(
                    campaign_preset=str(body.get("campaign_preset") or "balanced-production"),
                    session_preset=body.get("session_preset") or None, overrides=overrides,
                    approve_live_discovery=bool(body.get("approve_live_discovery")),
                    background=True)
            except Exception as exc:
                return self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return self._json(200, {"ok": True, **res})

        def _scout_control(self, parsed):
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            qs = parse_qs(parsed.query)
            return self._json(200, self._campaign_service().control(
                (qs.get("id") or [""])[0], (qs.get("action") or [""])[0]))

        def _scout_export(self, parsed):
            body = self._read_json_body()
            refusal = self._guard_mutation(body)
            if refusal:
                return self._json(*refusal)
            cid = (parse_qs(parsed.query).get("id") or [""])[0]
            try:
                return self._json(200, {"ok": True, "bundle": self._campaign_service().export_bundle(cid)})
            except Exception as exc:
                return self._json(400, {"ok": False, "error": str(exc)})

        def _scout_new_page(self, q=None) -> str:
            """One Start Scout for all three ways of naming sites.

            The operator chooses WHERE the sites come from — found, pasted, uploaded — and nothing
            else. Depth, coverage, capture and page caps are decisions Scout makes from the same
            tested policy every time; asking the operator to pick them before each run made the
            outcome depend on knowledge of the host rather than on the work.

            The three panels differ only in how the queue is filled. After that they post into the
            same pipeline, and the counts shown before Start come from the same intake code that
            builds the queue afterwards.
            """
            cat = self._campaign_service().catalog()
            site_type_labels = {
                "b2b_saas": "B2B SaaS",
                "commercial_product_company": "Commercial product",
                "ecommerce": "E-commerce",
                "booking_travel": "Travel and booking",
                "professional_services": "Professional services",
                "marketplace": "Marketplace",
            }
            biz = "".join(
                f'<label class="option-tile"><input type="checkbox" name="biztype" '
                f'value="{_esc(s)}"><span>{_esc(site_type_labels.get(s, s.replace("_", " ").title()))}'
                '</span></label>'
                for s in cat["site_types"] if s in site_type_labels)
            body = (
                '<h1>Start Scout</h1>'
                '<p class="page-intro muted">Tell Scout where to get the websites. It scans them the '
                'same safe way whichever source you pick.</p>'
                '<div class="row"><a class="chip" href="/scout/history">History</a>'
                '<a class="chip" href="/scout/attention">Needs attention</a>'
                '<a class="chip" href="/results">Companies &amp; outreach</a></div>'
                '<div class="card formstack campaign-card">'
                '<fieldset class="option-field"><legend>Where should the websites come from?</legend>'
                '<div class="option-grid" id="sources">'
                '<label class="option-tile"><input type="radio" name="source" value="find" checked>'
                '<span>Find websites</span></label>'
                '<label class="option-tile"><input type="radio" name="source" value="paste">'
                '<span>Paste URLs</span></label>'
                '<label class="option-tile"><input type="radio" name="source" value="file">'
                '<span>Upload file</span></label>'
                '</div></fieldset>'

                '<section id="p-find" class="source-panel">'
                '<label>Countries<input id="countries" placeholder="CA, CH"></label>'
                '<p class="field-help">Country codes, separated by commas. Leave blank to search '
                'without a country restriction.</p>'
                '<fieldset class="option-field"><legend>Business types</legend>'
                '<div class="option-grid">' + biz + '</div>'
                '<p class="field-help">Leave all unchecked and Scout looks for small and mid-size '
                'B2B SaaS companies, the profile it is tuned for.</p></fieldset>'
                '<label>Signals to look for<input id="keywords" '
                'placeholder="user feedback, roadmap, changelog"></label>'
                '<p class="field-help">Optional words that should appear on the site.</p>'
                '</section>'

                '<section id="p-paste" class="source-panel" hidden>'
                '<label for="seeds">Website addresses</label>'
                '<textarea id="seeds" rows="6" placeholder="https://example.com&#10;'
                'another-company.com"></textarea>'
                '<p class="field-help">One per line. Addresses you enter yourself are always '
                'scanned — Scout will not drop them for scoring reasons.</p>'
                '</section>'

                '<section id="p-file" class="source-panel" hidden>'
                '<label for="listfile">CSV or XLSX file</label>'
                '<input type="file" id="listfile" accept=".csv,.xlsx">'
                '<p class="field-help">Scout reads the column that holds website addresses and '
                'ignores the rest.</p>'
                '</section>'

                '<div id="intake" class="readiness-output" role="status" aria-live="polite" hidden>'
                '</div>'

                '<label>Maximum sites<input id="maxsites" type="number" min="1" max="50" value="10">'
                '</label>'
                '<p class="field-help">An upper bound for this run. Scout stops earlier when there is '
                'nothing more worth checking.</p>'

                '<div class="banner safety-note"><strong>Read-only scan</strong>'
                '<p id="safetysummary">Read-only scan · up to 10 sites · evidence saved '
                'automatically · no forms, purchases or messages.</p></div>'
                '<label class="approval-choice"><input type="checkbox" id="approve"> '
                '<span><strong>Start this bounded read-only run</strong>'
                '<small>Applies to this run only.</small></span></label>'
                '<div class="row campaign-actions"><button type="button" id="run" '
                'class="chip primary">Start Scout</button>'
                '<span id="msg" class="muted" role="status" aria-live="polite"></span></div></div>')
            script = _START_SCOUT_JS.replace("__CSRF__", json.dumps(csrf_token))
            return _page("AI QA Factory — Start Scout", "/scout", body, script)


        def _scout_progress_page(self, cid: str) -> str:
            body = ('<h1>Campaign progress</h1><div class="row">'
                    '<a class="chip" href="/scout/new">New campaign</a>'
                    '<a class="chip" href="/scout/history">History</a></div>'
                    '<div class="card"><div id="p" class="muted">loading…</div>'
                    '<div class="row"><button id="bp" class="chip primary" '
                    'onclick="ctl(\'pause\')">Pause</button>'
                    '<button id="br" class="chip primary" hidden '
                    'onclick="ctl(\'resume\')">Resume</button>'
                    '<button id="bs" class="chip danger" onclick="ctl(\'stop\')">Stop &amp; Save</button></div>'
                    '<details class="advanced"><summary>Advanced run diagnostics</summary>'
                    '<button class="chip" onclick="exp()">Export internal campaign record</button>'
                    '<p class="muted">For Observer/reviewer diagnostics; this is not the '
                    'client-ready attachment. Download a client ZIP from a completed target card.</p>'
                    '</details>'
                    '<div id="msg" class="muted"></div></div>')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";const CID=" + json.dumps(cid) + ";\n"
                "function ctl(a){fetch('/api/scout/control?id='+encodeURIComponent(CID)+'&action='+a,"
                "{method:'POST',headers:{'X-Scout-CSRF':CSRF}}).then(r=>r.json()).then(load);}\n"
                "function exp(){fetch('/api/scout/export?id='+encodeURIComponent(CID),{method:'POST',"
                "headers:{'X-Scout-CSRF':CSRF}}).then(r=>r.json()).then(function(j){"
                "document.getElementById('msg').textContent=j.ok?('internal record: '+j.bundle):"
                "('export failed: '+j.error);});}\n"
                "function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}\n"
                "function load(){fetch('/api/scout/progress?id='+encodeURIComponent(CID)).then(r=>r.json())"
                ".then(function(j){var c=j.counters||{};var d=(j.decisions||[]);"
                # Show only actions that make sense in the current state.
                "var state=String(j.run_state||'').toLowerCase();"
                "var term=['completed','stopped_with_checkpoint','failed','cancelled'].indexOf(state)>=0;"
                "var paused=['paused','pause_requested'].indexOf(state)>=0;"
                "var bp=document.getElementById('bp'),br=document.getElementById('br'),bs=document.getElementById('bs');"
                "if(bp)bp.hidden=term||paused;if(br)br.hidden=term||!paused;if(bs)bs.hidden=term;"
                # Each analyzed domain links to its target detail (findings/evidence); same tab.
                "var rows=d.map(function(x){var enc=encodeURIComponent(x.domain||'');"
                "var run=encodeURIComponent(x.scout_run||'');var href='/scout/target?domain='+enc+"
                "(run?'&run='+run:'');"
                "return '<tr><td><a href=\"'+href+'\">'+esc(x.domain)+'</a></td><td>'+esc(x.priority)+"
                "'</td><td>'+esc((x.allocation||{}).depth)+'</td><td>'+esc((x.brain||{}).business_model||'')+"
                "'</td></tr>';}).join('');"
                "var labels={running:'Running',paused:'Paused',pause_requested:'Pausing',"
                "completed:'Completed',stopped_with_checkpoint:'Stopped and saved',failed:'Failed',"
                "cancelled:'Cancelled'};"
                "document.getElementById('p').innerHTML='<div class=row><span class=chip>Status: '+"
                "esc(labels[state]||String(j.run_state||'Unknown').replaceAll('_',' '))+'</span>'+"
                "(j.stop_reason?'<span class=chip>Stopped because: '+esc(j.stop_reason)+'</span>':'')+'</div>'+"
                "'<table><tr><th>Discovered</th><th>Eligible</th><th>QA analyzed</th><th>Actionable</th>'+"
                "'<th>Already</th><th>Rejected</th><th>Failed</th></tr><tr><td>'+[c.discovered,c.eligible,"
                "c.qa_analyzed,c.actionable,c.already_analyzed,c.rejected,c.failed].map(v=>esc(v==null?0:v)).join('</td><td>')+"
                "'</td></tr></table>'+(rows?('<table><caption>Adaptive decisions</caption><tr><th>Domain</th>'+"
                "'<th>Priority</th><th>Depth</th><th>Business model</th></tr>'+rows+'</table>'):'');});}\n"
                "load();setInterval(load,3000);\n")
            return _page("AI QA Factory — Campaign progress", "/scout", body, script)

        def _scout_history_page(self, q) -> str:
            from datetime import datetime, timedelta, timezone
            qtext = (q.get("text") or [""])[0]
            frm = (q.get("from") or [""])[0].strip()      # explicit YYYY-MM-DD lower bound
            to = (q.get("to") or [""])[0].strip()          # explicit YYYY-MM-DD upper bound
            show_archived = (q.get("archived") or [""])[0].strip().lower() in ("1", "true", "yes")
            try:
                days = int((q.get("days") or ["0"])[0])    # any custom N days back
            except ValueError:
                days = 0
            since, until = "", ""
            if frm or to:
                since = frm
                until = (to + "T23:59:59+00:00") if to else ""
            elif days > 0:
                since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            result_filter = (q.get("result") or [""])[0].strip()
            # History is the operator's own work by default. Acceptance/diagnostic/manual-test runs
            # are real and are kept, but they are shown only when explicitly asked for — otherwise a
            # release check quietly becomes four more companies to follow up.
            purpose_filter = (q.get("purpose") or [""])[0].strip().lower()[:24]
            rows = self._campaign_service().history_results(filters={
                "text": qtext, "since": since, "until": until, "result": result_filter,
                "purpose": purpose_filter,
                "archived": "only" if show_archived else "",
            })
            active_days = days if (days > 0 and not (frm or to)) else 0
            filtered = bool(qtext or since or until or result_filter)
            total = len(self._campaign_service().history(filters={
                "purpose": purpose_filter,
                "archived": "only" if show_archived else ""}))
            count_label = (f"{len(rows)} shown of {total} total"
                           if filtered and len(rows) != total else f"{total} total")

            def _row(r) -> str:
                # Every cell states a fact about the outcome. "Not found" and "None captured" are
                # said in words rather than left blank, because an empty cell reads as "still
                # working" and this analysis has finished.
                res = r.get("result") or {}
                domain = r.get("domain", "")
                run = r.get("run", "")
                href = (f'/scout/target?domain={_esc(domain)}'
                        + (f'&run={_esc(run)}' if run else ''))
                email = res.get("contact_email") or ""
                contact = (f'<a href="mailto:{_esc(email)}">{_esc(email)}</a>' if email
                           else '<span class="muted">Not found</span>')
                priority = res.get("priority") or ""
                # Why, under the what. A blocked or rejected row without its reason forces the
                # operator to open the target just to learn the run refused it as a social network.
                raw_reason = res.get("reason") or r.get("reason") or ""
                why = (f'<div class="muted result-why">'
                       f'{_esc(_manual_reason_label(raw_reason))}</div>' if raw_reason else '')
                return (
                    f'<tr><td class="select-cell"><input type="checkbox" class="pick" '
                    f'value="{_esc(domain)}" aria-label="Select {_esc(domain)}"></td>'
                    f'<td data-label="Site"><a href="{href}">{_esc(domain)}</a></td>'
                    f'<td data-label="Result">'
                    f'{_badge(res.get("label", "Unknown"), res.get("kind", ""))}{why}</td>'
                    f'<td data-label="Priority">'
                    f'{_badge(priority) if priority else "<span class=\'muted\'>&mdash;</span>"}</td>'
                    f'<td data-label="Evidence" class="muted">'
                    f'{_esc(res.get("evidence_label", "None captured"))}</td>'
                    f'<td data-label="Contact">{contact}</td>'
                    f'<td data-label="Analyzed" class="muted">'
                    f'{_fmt_ts(r.get("last_analysis_at", ""))}</td>'
                    f'<td data-label="Open"><a class="chip" href="{href}">Open</a></td></tr>')

            trs = "".join(_row(r) for r in rows)
            empty_msg = (f'0 shown of {total} total &mdash; no sites match this filter.'
                         if filtered and total > 0 else
                         ('No archived targets.' if show_archived else 'No analyzed sites yet.'))
            table = (f'<table class="responsive-table"><caption>'
                     f'{"Archived" if show_archived else "Active"} targets &mdash; {count_label}</caption>'
                     f'<thead><tr><th><input type="checkbox" id="pickall" aria-label="Select all"></th>'
                     f'<th>Site</th><th>Result</th><th>Priority</th><th>Evidence</th>'
                     f'<th>Contact</th><th>Analyzed</th><th>Open</th></tr></thead>'
                     f'<tbody>{trs}</tbody></table>'
                     if rows else f'<div class="card empty muted">{empty_msg}</div>')
            active_tab = ('<a class="chip" href="/scout/history">Active</a>'
                          if show_archived else '<span class="chip active">Active</span>')
            archived_tab = ('<span class="chip active">Archived</span>' if show_archived else
                            '<a class="chip" href="/scout/history?archived=1">Archived</a>')
            bulk_buttons = (
                '<button class="chip" onclick="bulk(\'restore_targets\')">Restore selected</button>'
                '<button class="chip danger" onclick="forgetSelected()">Forget selected…</button>'
                if show_archived else
                '<button class="chip" onclick="bulk(\'archive_targets\')">Archive selected</button>')
            body = (f'<h1>Scout history</h1><div class="row">'
                    f'<a class="chip" href="/scout/new">New campaign</a>'
                    f'<a class="chip" href="/scout/attention">Needs attention</a></div>'
                    f'<div class="row">{active_tab}{archived_tab}</div>'
                    # Search, one result filter and ONE date disclosure. Range chips, a last-N-days
                    # box and a from/to pair used to sit side by side — three controls for one
                    # question, each silently overriding the others.
                    f'<form method="get" class="row" style="gap:8px;flex-wrap:wrap;align-items:center">'
                    f'<input type="hidden" name="archived" value="{"1" if show_archived else ""}">'
                    f'<label class="sr-only" for="history_text">Filter by domain or text</label>'
                    f'<input id="history_text" name="text" placeholder="filter domain/text" '
                    f'value="{_esc(qtext)}">'
                    f'<label class="sr-only" for="history_result">Filter by result</label>'
                    f'<select id="history_result" name="result">'
                    f'{_result_options(result_filter)}</select>'
                    f'<label class="sr-only" for="history_purpose">Show runs recorded for</label>'
                    f'<select id="history_purpose" name="purpose">'
                    f'{_purpose_options(purpose_filter)}</select>'
                    f'<details class="inline-filter"><summary>Date range</summary>'
                    f'<div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">'
                    f'<label class="muted">Last <input name="days" type="number" min="1" max="3650" '
                    f'style="width:64px" value="{active_days or ""}"> days</label>'
                    f'<span class="muted">or</span>'
                    f'<label class="muted">from <input name="from" type="date" value="{_esc(frm)}"></label>'
                    f'<label class="muted">to <input name="to" type="date" value="{_esc(to)}"></label>'
                    f'</div></details>'
                    f'<button class="chip">Filter</button>'
                    f'<a class="chip" href="/scout/history">Reset</a></form>'
                    f'<div class="scrollx">{table}</div>'
                    f'<div class="card bulkbar" id="bulkbar" hidden><b><span id="selected">0</span> '
                    f'selected</b><div class="row">{bulk_buttons}'
                    f'<button class="chip" onclick="clearSelection()">Clear</button>'
                    f'<span id="bulkmsg" class="muted" aria-live="polite"></span></div></div>'
                    f'<p class="muted">Archive is reversible and is the normal cleanup action. '
                    f'Forget removes dedup/history only after confirmation; exact-run evidence stays '
                    f'preserved until separately deleted.</p>')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";"
                "function picks(){return Array.from(document.querySelectorAll('.pick:checked')).map(x=>x.value);}"
                "function refreshBulk(){var n=picks().length;document.getElementById('selected').textContent=n;"
                "document.getElementById('bulkbar').hidden=!n;}"
                "document.querySelectorAll('.pick').forEach(x=>x.onchange=refreshBulk);"
                "var pa=document.getElementById('pickall');if(pa)pa.onchange=function(){"
                "document.querySelectorAll('.pick').forEach(x=>x.checked=pa.checked);refreshBulk();};"
                "function clearSelection(){document.querySelectorAll('.pick').forEach(x=>x.checked=false);"
                "if(pa)pa.checked=false;refreshBulk();}"
                "function bulk(action,confirmFlag){var d=picks();if(!d.length)return;"
                "fetch('/api/scout/operator',{method:'POST',headers:{'X-Scout-CSRF':CSRF,"
                "'Content-Type':'application/json'},body:JSON.stringify({action:action,domains:d,"
                "confirm:!!confirmFlag})}).then(r=>r.json()).then(j=>{if(j.ok)location.reload();"
                "else document.getElementById('bulkmsg').textContent=j.error||'Action failed';});}"
                "function forgetSelected(){qaConfirm('Forget selected targets from dedup/history? "
                "Exact-run evidence will remain.','Forget targets').then(function(ok){"
                "if(ok)bulk('forget_targets',true);});}")
            return _page("AI QA Factory — Scout history", "/scout", body, script)

        def _scout_target_page(self, domain: str, run: str = "") -> str:
            det = self._campaign_service().target_detail(domain, run=run)
            entry, brain = det.get("entry"), det.get("brain")
            prospect_id = det.get("prospect_id") or ""
            prospect_status = det.get("prospect_status") or ""
            run_id = det.get("run") or det.get("scout_run") or ""
            nav = ((f'<a class="chip" href="/scout/run?id={_esc(run_id)}">Back to run</a>'
                    if run_id else '')
                   + '<a class="chip" href="/scout/history">Back to history</a>')
            # A target whose domain is not in the resolved exact run: honest, never another
            # target's data.  This applies to both run-pinned links and History links, because a
            # drifted History record can still resolve a shared multi-target run.
            if det.get("evidence_status") == "prospect_not_found":
                return _page("AI QA Factory — Target", "/scout",
                             f'<h1>{_esc(domain)}</h1><div class="row">{nav}</div>'
                             f'<div class="card status-hero attention">'
                             f'<div class="banner warn">Evidence for this domain could not be bound '
                             f'to its own analyzed page in the resolved run. No findings, screenshots, '
                             f'network capture, or reproduction are shown here — Scout never shows '
                             f'another target\'s evidence in their place.</div>'
                             f'<p class="muted">Re-run a bounded scan for {_esc(domain)} to rebuild '
                             f'its own evidence.</p></div>'
                             f'<details class="card advanced"><summary>Advanced diagnostics</summary>'
                             f'<p><b>Resolved run:</b> <code>{_esc(run_id or "unavailable")}</code> · '
                             f'<b>Evidence status:</b> <code>prospect_not_found</code></p></details>')
            # An incomplete target gets the honest incomplete-analysis view, never a healthy
            # "0 defects" conclusion. The renderer is chosen by the SAME completeness predicate every
            # other surface uses — NOT by whether the caller happened to pin ?run=. History links here
            # without a run (see the Target column of the history table), and every promoted domain is
            # registered as analyzed regardless of its per-target outcome, so routing on the parameter
            # certified interrupted, skipped and failed targets as "Analysis complete".
            from core.scout.campaign_service import analysis_incomplete
            if analysis_incomplete(prospect_status):
                return self._scout_incomplete_target_html(domain, det, nav)
            if not entry and not brain and not prospect_id:
                return _page("AI QA Factory — Target", "/scout",
                             f'<h1>Target</h1><div class="card empty muted">No record for '
                             f'{_esc(domain)}.</div>')
            # The daily operator surface is compact and outcome-first.  A hidden, environment-only
            # legacy renderer remains available for migration diagnostics; it is never linked from
            # the UI and is off by default.
            if os.getenv("AIQA_SCOUT_LEGACY_TARGET_UI", "").lower() not in ("1", "true", "yes"):
                return self._scout_complete_target_html(domain, det, nav)
            b = brain or {}
            bs = (b.get("brain") or {})
            scores = bs.get("scores", {})
            plan = (b.get("plan") or {})
            findings = det.get("findings") or []
            contacts = det.get("contacts") or []
            draft = det.get("draft") or {}
            media = det.get("media") or []
            network = det.get("network") or {}
            fixability = det.get("fixability") or {}
            scout_run = det.get("scout_run") or ""
            source_kind = det.get("source_kind") or ""
            video_mode = det.get("video_mode") or ""
            evidence_files = det.get("evidence_files") or []
            status = (entry or {}).get("analysis_status", "")
            reason = (entry or {}).get("reason", "")
            # Truthful "what is this" card: an AI understanding card is only produced by adaptive
            # discovery (the Scout Brain). A curated/manual import never runs that step BY DESIGN, so
            # showing bare "—" dashes there looks like broken/missing data. Say plainly which is true.
            _SOURCE_LABEL = {
                "curated": "This target came from a curated list import. Automatic AI understanding "
                           "(archetype / business model / journeys) is not computed for curated "
                           "imports — that is expected, not missing data.",
                "manual": "This target came from a manual URL scan. Automatic AI understanding "
                         "(archetype / business model / journeys) is not computed for manual scans "
                         "— that is expected, not missing data.",
            }
            if bs:
                understanding_html = (
                    f'<p><b>Archetype:</b> {_esc(bs.get("archetype","—"))} · '
                    f'<b>Business model:</b> {_esc(bs.get("business_model","—"))} · '
                    f'<b>Understanding confidence:</b> {_esc(bs.get("understanding_confidence","—"))}%</p>'
                    f'<p><b>Critical journeys:</b> {_esc(", ".join(bs.get("primary_journeys",[])))}</p>')
            elif source_kind in _SOURCE_LABEL:
                understanding_html = f'<p class="muted">{_esc(_SOURCE_LABEL[source_kind])}</p>'
            else:
                understanding_html = ('<p class="muted">No AI understanding was computed for this '
                                      'target (not applicable for this source).</p>')
            body = (
                f'<h1>{_esc(domain)}</h1><div class="row">{nav}</div>'
                f'<div class="card"><h2>What Scout thinks this is</h2>'
                + understanding_html +
                f'<p><b>Priority:</b> {_badge(b.get("priority","—"))} · '
                f'<b>Scores</b> commercial {scores.get("commercial","—")} / QA {scores.get("qa_value","—")} / '
                f'evidence {scores.get("evidence_confidence","—")} / safety {scores.get("safety_confidence","—")} / '
                f'combined {scores.get("combined_opportunity","—")}</p></div>'
                f'<div class="card"><h2>Why Scout tested this / what it skipped</h2>'
                f'<p><b>Depth:</b> {_esc((b.get("allocation") or {}).get("depth","—"))} · '
                f'<b>Policy ceiling:</b> {_esc(plan.get("allowed_interaction_mode","—"))}</p>'
                f'<p><b>Checks selected:</b> {_esc(", ".join(plan.get("checks_selected",[])))}</p>'
                f'<p><b>Checks skipped:</b> {_esc(", ".join(plan.get("checks_skipped",[])))}</p>'
                f'<p><b>Stop boundary:</b> {_esc(", ".join(plan.get("stop_boundaries",[])) or "—")}</p>'
                f'<p class="muted">Current automatic Scout execution uses read-only navigation. '
                f'The policy ceiling describes what a separately authorized flow could permit; it '
                f'is not evidence that an interaction ran.</p>'
                f'<p class="muted"><b>Decisions:</b> {_esc(" · ".join(plan.get("decisions",[])))}</p></div>'
                f'<div class="card"><h2>Persisted record</h2>'
                f'<p><b>Status:</b> {_badge((entry or {}).get("analysis_status","—"))} · '
                f'<b>Evidence ref:</b> <code>{_esc((entry or {}).get("evidence_ref","—"))}</code></p>'
                + ('<div class="banner warn">This target was not analyzed unattended'
                   + (f' — {_esc(reason)}' if reason else '')
                   + '. Scout never solves CAPTCHAs. Solve it yourself in your browser, then use '
                     'the button below and re-run a campaign including this target.</div>'
                   if _looks_blocked(status, reason) else '')
                + ('<div class="row" style="gap:10px;align-items:center;flex-wrap:wrap">'
                   '<button class="chip" type="button" onclick="rescan()">I handled it — rescan '
                   'this target</button>'
                   '<button class="chip" type="button" onclick="replay()">Watch headed replay'
                   '</button><span id="rescanmsg" class="muted"></span></div>' if entry else '')
                + '<p class="muted">A rescan starts a fresh bounded pass. When qualified-auto video '
                'is configured, Scout keeps a short clip only if Playwright reproduces an eligible '
                'broken flow-entry navigation cleanly; otherwise no video is created.</p></div>')

            # Within-site coverage (PR-B): how many meaningful pages Scout explored on THIS target,
            # under which profile, and why it stopped. Independent of how many domains a campaign
            # analyzes (that is the separate campaign-budget axis).
            body += (f'<div class="card"><h2>Coverage</h2>{_coverage_card_html(det.get("coverage"))}'
                     f'</div>')

            # Honest evidence-binding state: a shared multi-target run may register a domain whose own
            # analyzed prospect is not in the store. We refuse to borrow another target's evidence, so
            # the card shows nothing here — say so plainly rather than look like a clean empty result.
            if det.get("evidence_status") == "prospect_not_found":
                body += ('<div class="banner warn">Evidence for this domain could not be bound to its '
                         'own analyzed page in the run, so no findings, screenshots, network capture '
                         'or reproduction are shown here — deliberately, rather than surface evidence '
                         'from a different target. Re-run a scan for this domain to rebuild its own '
                         'evidence.</div>')

            # Sales funnel (engagement pipeline). Won/Delivered come from client-work; the
            # outreach-side transitions are set here. The system never emails anyone.
            if entry:
                eng = (entry or {}).get("engagement_status", "prospect")
                wid = (entry or {}).get("work_id", "")
                funnel_btns = "".join(
                    f'<button class="chip" type="button" onclick="setEng(\'{s}\')">{lbl}</button>'
                    for s, lbl in (("contacted", "Contacted"), ("replied", "Replied"),
                                   ("won", "Won"), ("delivered", "Delivered"), ("lost", "Lost")))
                body += ('<div class="card"><h2>Sales funnel</h2>'
                         f'<p><b>Stage:</b> {_badge(eng)}'
                         + (f' · <b>Work:</b> <code>{_esc(wid)}</code>' if wid else '')
                         + '</p><div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">'
                         + funnel_btns + '<span id="engmsg" class="muted"></span></div>'
                         '<div class="row" style="gap:10px;flex-wrap:wrap;align-items:center;'
                         'margin-top:10px"><button class="btn primary" type="button" '
                         'onclick="startCW()">Start client work</button>'
                         + (f'<a class="chip" href="/work/{_esc(wid)}">open work &#8599;</a>'
                            if wid else '')
                         + '<span id="cwmsg" class="muted"></span></div>'
                         '<p class="muted">Start client work builds a job brief from these findings, '
                         'runs the read-only analyze-job (feasibility + proposal), and links it as a '
                         'proposal. It does NOT change the sales stage. Won / Delivered are '
                         'commitments — set them only after a real, confirmed client agreement '
                         '(they ask for confirmation); Contacted / Replied you set freely here. '
                         'Nothing is emailed by the system.</p></div>')

            # Public contacts (read-only; the system never emails anyone).
            contacts_html = ("".join(f'<span class="chip">{_esc(e)}</span> ' for e in contacts)
                             or '<span class="muted">None found on public pages.</span>')
            body += (f'<div class="card"><h2>Public contact(s)</h2><p>{contacts_html}</p>'
                     f'<p class="muted">Extracted read-only from public pages. Use them to reach out '
                     f'yourself; the system never sends anything.</p></div>')

            # Problem items: ordered by qa_value_score desc, each with a confidence label + a
            # one-line repro hint. Every dynamic cell is HTML-escaped and newline-collapsed; an
            # absent field shows a neutral placeholder (never invented). See _problems_table_html.
            prob_table = _problems_table_html(findings)
            body += (f'<div class="card"><h2>Problems found</h2><div class="scrollx">{prob_table}</div>'
                     f'</div>')

            # Fixability (stage 3 — paid fix scoping). Conservative: nothing is "ready" for a cold
            # prospect (no access yet); this is what we could offer to fix ourselves.
            fx_items = fixability.get("items") or []
            _FX_LABEL = {"fix_ready": "fix ready", "fix_after_access": "fix after access",
                         "out_of_scope": "out of scope"}
            if fx_items:
                fx_rows = "".join(
                    f'<tr><td>{_badge(_FX_LABEL.get(i.get("fix_tier"), i.get("fix_tier","")))}</td>'
                    f'<td class="muted">{_esc(i.get("category") or "—")}</td>'
                    f'<td>{_esc(i.get("title") or "—")}</td>'
                    f'<td class="muted">{_esc(i.get("fix_reason") or "")}</td></tr>' for i in fx_items)
                fx_html = (f'<p class="muted">{_esc(fixability.get("summary",""))}</p>'
                           f'<div class="scrollx"><table><caption>Fixability ({len(fx_items)})'
                           f'</caption><tr><th>Tier</th><th>Type</th><th>Issue</th><th>Why</th></tr>'
                           f'{fx_rows}</table></div>')
            else:
                fx_html = ('<div class="empty muted">No findings to scope yet. After a bounded QA '
                           'analysis, this shows what we could fix ourselves (paid, stage 3).</div>')
            body += ('<div class="card"><h2>Fixability — what we could fix (stage 3, paid)</h2>'
                     + fx_html +
                     '<p class="muted">Conservative + honest: nothing is "ready" for a cold prospect '
                     '(no repo/staging access yet). We never promise a fix outside proven '
                     'capability.</p></div>')

            # Captured evidence media: screenshots inline, video playable, other files downloadable.
            def _art_url(rel: str) -> str:
                return f'/scout/artifact?run={_esc(scout_run)}&rel={_esc(rel)}'

            def _ext(m: str) -> str:
                return m.lower().rsplit(".", 1)[-1] if "." in m else ""
            imgs = [m for m in media if _ext(m) in ("png", "jpg", "jpeg", "webp", "gif")]
            vids = [m for m in media if _ext(m) in ("webm", "mp4")]
            others = [m for m in media if m not in imgs and m not in vids]
            # Name each frame by the page it shows. Three anonymous thumbnails force the operator to
            # open them one by one to work out which is the pricing page and which is the landing.
            shot_roles = {str(s.get("file") or ""): s for s in (det.get("screenshots") or [])
                          if isinstance(s, dict)}

            def _shot_caption(rel: str) -> str:
                meta = shot_roles.get(rel.rsplit("/", 1)[-1]) or {}
                role = str(meta.get("role") or "")
                page = str(meta.get("url") or "")
                if not role:
                    return ""
                return (f'<div class="muted" style="font-size:12px;max-width:280px">{_esc(role)}'
                        + (f' &middot; <span title="{_esc(page)}">{_esc(page[:46])}</span>'
                           if page else "") + "</div>")

            media_html = "".join(
                f'<figure style="display:inline-block;margin:4px;vertical-align:top">'
                f'<a href="{_art_url(m)}" target="_blank" rel="noopener"><img src="{_art_url(m)}" '
                f'alt="{_esc((shot_roles.get(m.rsplit("/", 1)[-1]) or {}).get("role") or "screenshot")}" '
                f'style="max-width:280px;max-height:200px;'
                f'border:1px solid var(--border,#ccc)"></a>{_shot_caption(m)}</figure>'
                for m in imgs)
            media_html += "".join(
                f'<video src="{_art_url(m)}" controls preload="metadata" '
                f'style="max-width:360px;margin:4px"></video>' for m in vids)
            media_html += "".join(
                f'<div><a href="{_art_url(m)}" download>{_esc(m.split("/")[-1])}</a></div>'
                for m in others)
            if not media:
                media_html = ('<div class="empty muted">No screenshots/media captured yet. Launch a '
                              'campaign with <b>Deep capture (Playwright)</b> to record screenshots '
                              'and stronger evidence.</div>')
            body += f'<div class="card"><h2>Screenshots &amp; evidence files</h2>{media_html}</div>'

            # Video is an intentional capture POLICY (video_mode), not a pass/fail check. A captured
            # video is still shown inline above, in the "Screenshots & evidence files" card, exactly
            # like any other captured artifact. This card only appears when NO video exists, and its
            # job is to say why: a manual/disabled policy with no clip is normal, expected behaviour
            # — never presented as a missing/failed capture.
            _VIDEO_POLICY_NOTE = {
                "off": "Video capture is disabled for this run (video_mode=off). This is an "
                      "intentional policy, not a failed capture.",
                "manual": "Video capture is manual/opt-in for this run and none was recorded for "
                         "this target. This is expected, not a defect.",
                "qualified_auto": "No qualifying interaction finding triggered an automatic "
                                  "reproduction video for this target.",
            }
            # What the recording actually shows, next to the recording. A clip on its own invites
            # the reader to supply the conclusion; these four lines state it — including when the
            # conclusion is "the control worked, and this proves only that we can record it".
            body += _interaction_card(det.get("interaction"), _art_url)
            if not vids:
                note = _VIDEO_POLICY_NOTE.get(video_mode,
                    "No reproduction video was captured for this target.")
                body += f'<div class="card"><h2>Reproduction video</h2><p class="muted">{_esc(note)}</p></div>'

            # Accessibility (axe-core) evidence: distinguish "ran, N violations" from "browser
            # evidence unavailable" from "not attempted" (static/non-deep-capture scan) — never
            # conflate a capture-mode limitation with a real defect-free result.
            axe_status = network.get("axe_status", "")
            axe_violations = network.get("axe_violations") or []
            if axe_status == "ok":
                if axe_violations:
                    a_rows = "".join(
                        f'<tr><td>{_esc(str(v.get("id","—")))}</td>'
                        f'<td class="muted">{_esc(str(v.get("impact","—")))}</td>'
                        f'<td>{_esc(_collapse_ws(str(v.get("help",""))) or "—")}</td>'
                        f'<td class="muted">{_esc(str(len(v.get("nodes") or [])))}</td></tr>'
                        for v in axe_violations)
                    axe_html = (f'<div class="scrollx"><table><caption>axe-core violations '
                               f'({len(axe_violations)})</caption><tr><th>Rule</th><th>Impact</th>'
                               f'<th>Description</th><th>Nodes</th></tr>{a_rows}</table></div>')
                else:
                    axe_html = ('<p class="muted">axe-core ran on this page and found 0 '
                               'violations.</p>')
            elif axe_status == "unavailable":
                axe_html = ('<p class="muted">Deep-capture ran but axe-core evidence was unavailable '
                           'for this page (browser/script limitation) — not a defect-free result.</p>')
            else:
                axe_html = ('<div class="empty muted">Accessibility (axe-core) was not attempted for '
                           'this scan mode. Use <b>Deep Capture (Playwright)</b> to run axe-core.</div>')
            body += f'<div class="card"><h2>Accessibility evidence (axe-core)</h2>{axe_html}</div>'

            # Network evidence already captured by Chromium/Playwright (from observation.json).
            if network:
                ce = network.get("console_errors") or []
                fr = network.get("failed_resources") or []
                br = network.get("blocked_requests") or []
                timing = network.get("timing_ms") or {}
                net_html = (
                    f'<p><b>HTTP status:</b> {_esc(str(network.get("status") or "—"))} · '
                    f'<b>Load:</b> {_esc(str(timing.get("load", "—")))} ms</p>'
                    f'<p><b>Console errors ({len(ce)}):</b> {_esc(", ".join(map(str, ce)) or "none")}</p>'
                    f'<p><b>Failed resources ({len(fr)}):</b> '
                    f'{_esc(", ".join(map(str, fr)) or "none")}</p>'
                    f'<p><b>Blocked requests ({len(br)}):</b> '
                    f'{_esc(", ".join(map(str, br)) or "none")}</p>')
            else:
                net_html = ('<div class="empty muted">No network capture yet. Deep capture '
                            '(Playwright) records console errors, failed resources and load timing '
                            'from Chromium.</div>')
            body += f'<div class="card"><h2>Network evidence (Chrome/Playwright)</h2>{net_html}</div>'

            # Structured evidence files — a safe, exact-run/exact-prospect-confined "open" action
            # for redacted observations/traces plus findings/scorecard/coverage/reproduction/manual
            # records, reusing the SAME /scout/artifact route as screenshots. Only files that
            # genuinely exist are linked (never a dead link).
            if evidence_files:
                ev_rows = "".join(
                    f'<li><a href="{_art_url(e["rel"])}" target="_blank" rel="noopener">'
                    f'{_esc(e["label"])}</a></li>' for e in evidence_files)
                ev_html = f'<ul>{ev_rows}</ul>'
            else:
                ev_html = '<p class="muted">No structured evidence files are available.</p>'
            body += (f'<div class="card"><h2>Structured evidence files (diagnostic)</h2>{ev_html}'
                     f'<p class="muted">Opens the underlying captured JSON directly (read-only, '
                     f'served as source text/JSON — never executed).</p></div>')

            # Copy-only outreach draft (never sent). Haiku polishes prose when LLM is live.
            to_addr = _esc(draft.get("contact", "") or (contacts[0] if contacts else ""))
            to_html = to_addr or '<span class="muted">add a recipient manually</span>'
            body += (
                '<div class="card"><h2>Outreach draft — copy only</h2>'
                '<div class="banner warn">The system never sends this. Copy &amp; send it yourself '
                'after review — public information only, nothing was submitted to the site.</div>'
                f'<p><b>Subject:</b> {_esc(draft.get("subject",""))}</p>'
                f'<p><b>To:</b> {to_html}</p>'
                '<label for="draftbody"><b>Draft body</b></label>'
                f'<textarea id="draftbody" readonly rows="11" style="width:100%;box-sizing:border-box">'
                f'{_esc(draft.get("body",""))}</textarea>'
                '<div class="row" style="margin-top:8px;align-items:center;gap:10px">'
                '<button class="chip" type="button" onclick="copyDraft()">Copy draft</button>'
                '<button class="chip" id="polishbtn" type="button" onclick="polishDraft()">'
                'Polish with AI</button>'
                f'<span class="muted">Generated by: <span id="draftgen">'
                f'{_esc(draft.get("generated_by","deterministic"))}</span></span>'
                '<span id="polishmsg" class="muted"></span></div>'
                '<p class="muted">This page loads $0 — the draft above is deterministic. "Polish with '
                'AI" is an explicit, opt-in action that makes a PAID model call only when a live LLM '
                'is configured (it asks for confirmation first). Per-campaign/daily/monthly budget '
                'controls and a no-repeat cache are pending (Slice 3), so each confirmed click may '
                'repeat the call; it never runs automatically on open or refresh.</p></div>'
                '<script>function copyDraft(){var t=document.getElementById("draftbody");'
                't.focus();t.select();try{document.execCommand("copy");}catch(e){}}</script>')

            # Human-in-the-loop rescan (CSRF-guarded POST). Never solves a challenge automatically.
            body += ('<script>var CSRF=' + json.dumps(csrf_token) + ';var DOM=' + json.dumps(domain)
                     + ';function rescan(){var m=document.getElementById("rescanmsg");'
                     'if(m){m.textContent="working…";}'
                     'fetch("/api/scout/rescan?domain="+encodeURIComponent(DOM),{method:"POST",'
                     'headers:{"X-Scout-CSRF":CSRF,"Content-Type":"application/json"},body:"{}"})'
                     '.then(function(r){return r.json();}).then(function(j){'
                     'if(m){m.textContent=j.message||(j.ok?"marked for re-analysis":"failed");}})'
                     '.catch(function(){if(m){m.textContent="request error";}});}'
                     'function replay(){var m=document.getElementById("rescanmsg");'
                     'if(m){m.textContent="opening a browser window…";}'
                     'fetch("/api/scout/replay?domain="+encodeURIComponent(DOM),{method:"POST",'
                     'headers:{"X-Scout-CSRF":CSRF,"Content-Type":"application/json"},body:"{}"})'
                     '.then(function(r){return r.json();}).then(function(j){'
                     'if(m){m.textContent=j.message||(j.ok?"replay started":"replay failed");}})'
                     '.catch(function(){if(m){m.textContent="replay request error";}});}'
                     'function setEng(s){var m=document.getElementById("engmsg");'
                     # Won/Delivered are commitments: require an explicit operator confirmation
                     # (they map to confirm=1; the server refuses them otherwise).
                     'var need=(s==="won"||s==="delivered");'
                     'function save(){if(m){m.textContent="saving…";}'
                     'fetch("/api/scout/engagement?domain="+encodeURIComponent(DOM)+"&status="+'
                     'encodeURIComponent(s)+(need?"&confirm=1":""),{method:"POST",'
                     'headers:{"X-Scout-CSRF":CSRF,"Content-Type":"application/json"},body:"{}"})'
                     '.then(function(r){return r.json();}).then(function(j){'
                     'if(j.ok){location.reload();}else if(m){m.textContent='
                     '(j.needs_confirmation?"confirmation required":"failed");}})'
                     '.catch(function(){if(m){m.textContent="request error";}});}'
                     'if(need){qaConfirm("Mark this prospect \\""+s+"\\"? Do this only after a real, '
                     'confirmed client agreement/delivery.","Confirm "+s).then(function(ok){'
                     'if(ok)save();});return;}save();}'
                     'function startCW(){var m=document.getElementById("cwmsg");'
                     'if(m){m.textContent="running analyze-job…";}'
                     'fetch("/api/scout/start-client-work?domain="+encodeURIComponent(DOM),'
                     '{method:"POST",headers:{"X-Scout-CSRF":CSRF,"Content-Type":"application/json"},'
                     'body:"{}"}).then(function(r){return r.json();}).then(function(j){'
                     'if(j.ok){if(m){m.textContent=j.message||"started";}'
                     'setTimeout(function(){location.reload();},1400);}'
                     'else if(m){m.textContent="failed: "+(j.error||"unknown");}})'
                     '.catch(function(){if(m){m.textContent="request error";}});}'
                     'var POLISHING=false;'
                     'function polishDraft(){var m=document.getElementById("polishmsg");'
                     'var b=document.getElementById("polishbtn");'
                     # In-flight/double-click guard: refuse a second call while one is pending.
                     'if(POLISHING){return;}'
                     # Explicit paid-call confirmation (budget controls are not in place until Slice 3).
                     'qaConfirm("Polish with AI may make a PAID model call when a live LLM '
                     'is configured. Budget limits and no-repeat caching arrive in Slice 3, so each '
                     'confirmed click may repeat the call.","Polish with AI").then(function(ok){'
                     'if(!ok){return;}'
                     'POLISHING=true;if(b){b.disabled=true;}if(m){m.textContent="polishing…";}'
                     'fetch("/api/scout/polish-draft?domain="+encodeURIComponent(DOM),'
                     '{method:"POST",headers:{"X-Scout-CSRF":CSRF,"Content-Type":"application/json"},'
                     'body:"{}"}).then(function(r){return r.json();}).then(function(j){'
                     'if(j.ok&&j.draft){var t=document.getElementById("draftbody");'
                     'if(t){t.value=j.draft.body||t.value;}'
                     'var g=document.getElementById("draftgen");'
                     'if(g){g.textContent=j.draft.generated_by||"deterministic";}'
                     'if(m){m.textContent="";}}else if(m){m.textContent="failed: "+(j.error||"unknown");}})'
                     '.catch(function(){if(m){m.textContent="request error";}})'
                     '.then(function(){POLISHING=false;if(b){b.disabled=false;}});});}</script>')

            return _page("AI QA Factory — Target detail", "/scout", body)

        def _scout_complete_target_html(self, domain: str, det: dict, nav: str) -> str:
            """Outcome-first target card; internal IDs/JSON live only under Advanced diagnostics."""
            entry = det.get("entry") or {}
            brain = det.get("brain") or {}
            run_id = det.get("run") or det.get("scout_run") or ""
            findings = det.get("findings") or []
            media = det.get("media") or []
            network = det.get("network") or {}
            evidence_files = det.get("evidence_files") or []
            coverage = det.get("coverage")
            contacts = det.get("contacts") or []
            contact_records = det.get("contact_records") or []
            draft = det.get("draft") or {}
            fixability = det.get("fixability") or {}
            actionable = [f for f in findings
                          if str(f.get("severity") or "").strip().lower() != "info"]
            informational = len(findings) - len(actionable)
            pages = ((coverage or {}).get("meaningful_pages_tested")
                     if isinstance(coverage, dict) else None)

            def _art_url(rel: str) -> str:
                return f'/scout/artifact?run={_esc(run_id)}&rel={_esc(rel)}'

            def _ext(path: str) -> str:
                return path.lower().rsplit(".", 1)[-1] if "." in path else ""

            imgs = [m for m in media if _ext(m) in ("png", "jpg", "jpeg", "webp", "gif")]
            vids = [m for m in media if _ext(m) in ("webm", "mp4")]
            obs_file = next((e for e in evidence_files if e.get("name") == "observation.json"), None)
            evidence_count = len(media) + len(evidence_files)
            # Name each frame by the page it shows. A row of anonymous thumbnails makes the operator
            # open them one by one to work out which is the pricing page and which is the landing —
            # and makes a client package impossible to check before sending.
            frames = {str(s.get("file") or ""): s for s in (det.get("screenshots") or [])
                      if isinstance(s, dict)}

            def _frame(rel: str) -> dict:
                return frames.get(rel.rsplit("/", 1)[-1]) or {}

            def _caption(rel: str) -> str:
                meta = _frame(rel)
                role, page = str(meta.get("role") or ""), str(meta.get("url") or "")
                if not role and rel.rsplit("/", 1)[-1] == "verification.png":
                    # Not a page of the site: the independent second pass photographing the same
                    # landing page. Saying so beats leaving an unexplained fourth thumbnail.
                    return ('<figcaption class="muted" style="font-size:12px">verification pass '
                            '&middot; same page, re-checked</figcaption>')
                if not role:
                    return ""
                return (f'<figcaption class="muted" style="font-size:12px">{_esc(role)}'
                        + (f' &middot; {_esc(page[:52])}' if page else "") + "</figcaption>")

            media_html = "".join(
                f'<figure style="display:inline-block;margin:0 8px 8px 0;vertical-align:top">'
                f'<a href="{_art_url(m)}" target="_blank" rel="noopener">'
                f'<img src="{_art_url(m)}" alt="'
                f'{_esc(_frame(m).get("role") or f"Captured page for {domain}")}"></a>'
                f'{_caption(m)}</figure>'
                for m in imgs)
            media_html += "".join(
                f'<video src="{_art_url(m)}" controls preload="metadata" '
                f'style="max-width:360px"></video>' for m in vids)
            if not media_html:
                media_html = ('<p class="muted">No visual evidence was captured for this run. '
                              'Use Deep capture for screenshots; video is kept only for a qualifying '
                              'reproduced interaction.</p>')

            # Evidence presence/absence is decided once, in core.scout.evidence_state, so the page,
            # the History row and anything else asking "was there a screenshot?" cannot answer it
            # three slightly different ways. See _evidence_state_grid_html below.
            status_note =("Completed with confirmed actionable findings."
                           if actionable else
                           "Completed. No actionable defect was confirmed in this bounded scan.")
            body = (
                f'<h1>{_esc(domain)}</h1><div class="row">{nav}</div>'
                f'<div class="card status-hero"><div class="row">'
                f'{_badge("Analysis complete", "ok")}<span class="muted">{_esc(status_note)}</span>'
                f'</div><div class="summary-grid" style="margin-top:12px">'
                f'<div class="summary-item"><span class="muted">Actionable findings</span>'
                f'<strong>{len(actionable)}</strong></div>'
                f'<div class="summary-item"><span class="muted">Informational notes</span>'
                f'<strong>{informational}</strong></div>'
                f'<div class="summary-item"><span class="muted">Pages checked</span>'
                f'<strong>{_esc(pages if pages is not None else "—")}</strong></div>'
                f'<div class="summary-item"><span class="muted">Evidence files</span>'
                f'<strong>{evidence_count}</strong></div></div>'
                f'</div>'
                f'<div class="card"><h2>Findings</h2><div class="scrollx">'
                f'{_problems_table_html(findings)}</div></div>'
                f'<div class="card"><h2>Evidence</h2><div class="media-grid">{media_html}</div>'
                f'{_evidence_state_grid_html(det)}'
                f'{_evidence_files_html(evidence_files, _art_url)}'
                f'<p class="muted">This trace is a redacted structured event record, not a native '
                f'Playwright <code>trace.zip</code>. Playwright Inspector is a live developer tool '
                f'and is intentionally not exposed in the operator UI.</p></div>'
                f'<div class="card"><h2>Coverage</h2>{_coverage_card_html(coverage)}</div>')

            if actionable:
                contact_rows = "".join(
                    f'<div><strong>{_esc(row.get("email") or "")}</strong>'
                    f'<br><span class="muted">{_esc(row.get("source") or "Public page")}'
                    + (f' · <a href="{_esc(row.get("source_url") or "")}" target="_blank" '
                       f'rel="noopener">source page</a>'
                       if row.get("source_url") else '')
                    + '</span></div>'
                    for row in contact_records if row.get("email"))
                if not contact_rows and contacts:
                    contact_rows = "".join(
                        f'<div><strong>{_esc(email)}</strong><br>'
                        f'<span class="muted">Public page contact</span></div>'
                        for email in contacts)
                if not contact_rows:
                    contact_rows = '<span class="muted">No public contact found.</span>'
                eng = entry.get("engagement_status", "prospect")
                work_id = entry.get("work_id", "")
                # The talking points are the deterministic bullets the draft is built from. Showing
                # them beside the letter lets the operator check that the prose claims nothing the
                # findings do not support — the draft is prose, these are the facts.
                points = "".join(f'<li>{_esc(point)}</li>'
                                 for point in (draft.get("problem_bullets") or []))
                body += (
                    '<div class="card"><h2>Contact &amp; outreach</h2>'
                    '<div class="evidence-grid">'
                    f'<div class="evidence-item"><h3>Public contact</h3>{contact_rows}</div>'
                    f'<div class="evidence-item"><h3>What we can offer</h3>'
                    f'<p>{_esc(fixability.get("summary") or "Review scope before promising a fix.")}</p>'
                    '<p class="muted">Implementation is offered only after scope agreement and '
                    'repo/staging access. Nothing is promised automatically.</p></div></div>'
                    f'<h3>Talking points</h3><ul class="talking-points">{points}</ul>'
                    f'<h3>Suggested subject</h3><p><code>{_esc(draft.get("subject",""))}</code></p>'
                    f'<h3>Email draft {_badge("Draft — not sent", "attention")}</h3>'
                    '<label for="draftbody" class="sr-only">Outreach draft body</label>'
                    f'<textarea id="draftbody" aria-label="Outreach draft body" readonly rows="9">'
                    f'{_esc(draft.get("body",""))}</textarea>'
                    '<div class="row"><button class="chip" type="button" '
                    'onclick="copyDraft()">Copy draft</button></div>'
                    '<p class="muted">Nothing is sent automatically, and the draft is not part of '
                    'the client package — it is your text, not theirs.</p>'
                    f'<p><b>Prospect stage:</b> {_badge(eng)}</p>'
                    '<div class="row"><button class="btn primary" type="button" '
                    'onclick="startCW()">Prepare client work</button>'
                    '<button class="chip" type="button" onclick="setEng(\'contacted\')">Contacted</button>'
                    '<button class="chip" type="button" onclick="setEng(\'replied\')">Replied</button>'
                    '<button class="chip" type="button" onclick="setEng(\'lost\')">Lost</button>'
                    + (f'<a class="chip" href="/work/{_esc(work_id)}">Open linked work</a>'
                       if work_id else '')
                    + '<span id="actionmsg" class="muted" aria-live="polite"></span></div></div>')
            else:
                body += ('<div class="card"><h2>Contact &amp; outreach</h2>'
                         '<p class="muted">No outreach draft is written because this run confirmed '
                         'no actionable finding. That is not a conclusion that the site is '
                         'defect-free — run a deeper bounded check if more coverage is needed.'
                         '</p></div>')

            body += _client_package_html(self._campaign_service(), domain, run_id, det)

            source_kind = det.get("source_kind") or ""
            source_note = {
                "curated": ("Curated list import; adaptive AI understanding was not computed. "
                            "That is expected, not missing data."),
                "manual": "Manual URL scan; adaptive AI understanding was not computed.",
                "discovery": "Adaptive Scout discovery.",
            }.get(source_kind, ("AI understanding is not applicable for this source; the source "
                                "type was not persisted for this historical run."))
            video_note = {
                "manual": ("Video capture was manual/opt-in; no clip is expected unless the "
                           "operator records a qualifying reproduction. Expected, not a defect."),
                "off": ("Video capture was disabled for this run. This is an intentional policy, "
                        "not a failed capture."),
                "qualified_auto": ("Video was retained only if an eligible interaction finding "
                                   "reproduced cleanly."),
            }.get(det.get("video_mode") or "", "Video policy was not persisted for this run.")
            bsum = brain.get("brain") or {}
            plan = brain.get("plan") or {}
            axe_items = "".join(
                f'<li><code>{_esc(v.get("id") or "unknown-rule")}</code> · '
                f'{_esc(v.get("help") or "")}</li>'
                for v in (network.get("axe_violations") or []))
            structured = "".join(
                f'<li><a href="{_art_url(e["rel"])}" target="_blank" rel="noopener">'
                f'{_esc(e["label"])}</a></li>' for e in evidence_files)
            body += (
                '<details class="card advanced"><summary>Advanced diagnostics</summary>'
                f'<p class="muted">{_esc(source_note)}</p>'
                f'<p><b>Run:</b> <code>{_esc(run_id)}</code> · <b>Prospect:</b> '
                f'<code>{_esc(det.get("prospect_id") or "—")}</code></p>'
                f'<p><b>Archetype:</b> {_esc(bsum.get("archetype") or "—")} · '
                f'<b>Business model:</b> {_esc(bsum.get("business_model") or "—")}</p>'
                f'<p><b>Policy ceiling:</b> {_esc(plan.get("allowed_interaction_mode") or "—")} · '
                f'<b>Checks selected:</b> {_esc(", ".join(plan.get("checks_selected") or []) or "—")}</p>'
                f'<p class="muted">Current automatic Scout execution uses read-only navigation; '
                f'a policy ceiling is not evidence that an interaction ran.</p>'
                f'<p class="muted">{_esc(video_note)}</p>'
                f'<p><b>HTTP:</b> {_esc(network.get("status") or "—")} · '
                f'<b>Console errors:</b> {_esc(len(network.get("console_errors") or []))} · '
                f'<b>Failed resources:</b> {_esc(len(network.get("failed_resources") or []))}</p>'
                f'<ul>{axe_items}</ul>'
                f'<ul>{structured or "<li class=muted>No structured files available.</li>"}</ul>'
                + (f'<p><a href="{_art_url(obs_file["rel"])}">Open page observation</a></p>'
                   if obs_file else '')
                + (f'<p><a href="/api/prospect?run={_esc(run_id)}&id='
                   f'{_esc(det.get("prospect_id") or "")}">View exact-run raw JSON</a></p>'
                   if run_id and det.get("prospect_id") else '')
                + '</details>')

            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";const DOM=" + json.dumps(domain) + ";"
                "function post(u,b){return fetch(u,{method:'POST',headers:{'X-Scout-CSRF':CSRF,"
                "\"Content-Type\":\"application/json\"},body:JSON.stringify(b||{})}).then(r=>r.json());}"
                "function msg(t){var m=document.getElementById('actionmsg');if(m)m.textContent=t;}"
                "function startCW(){msg('preparing…');post('/api/scout/start-client-work?domain='+"
                "encodeURIComponent(DOM),{}).then(j=>{msg(j.message||j.error||'done');"
                "if(j.ok)setTimeout(()=>location.reload(),900);});}"
                "function setEng(s){post('/api/scout/engagement?domain='+encodeURIComponent(DOM)+"
                "'&status='+encodeURIComponent(s),{}).then(j=>{if(j.ok)location.reload();"
                "else msg(j.error||'could not update');});}"
                "function copyDraft(){var t=document.getElementById('draftbody');if(!t)return;"
                "t.focus();t.select();try{document.execCommand('copy');msg('Draft copied.');}catch(e){}}")
            return _page("AI QA Factory — Target result", "/scout", body, script)

        def _scout_incomplete_target_html(self, domain: str, det: dict, nav: str) -> str:
            """Honest incomplete-analysis Target view for a MANUAL_ACTION_REQUIRED / FAILED prospect.

            Renders ONLY persisted truth (never a guessed reason) and never a healthy conclusion:
            0 confirmed findings, the persisted reason/stage/stop-boundary, whether Chromium started
            and the landing loaded, any partial evidence, and the safe recommended operator action."""
            ma = det.get("manual_action") or {}
            run_id = det.get("run") or det.get("scout_run") or ""
            network = det.get("network") or {}
            media = det.get("media") or []
            evidence_files = det.get("evidence_files") or []
            raw_reason = str(ma.get("reason") or "")
            prospect_status = str(det.get("prospect_status") or "")
            # A challenge is not the only way an analysis ends early. Describe what actually
            # happened: a blocked/CAPTCHA target has a persisted reason and a session an operator can
            # take over; an interrupted or skipped target has neither, and offering to "open a manual
            # check" for one would be a false story about the run.
            # A target a later manual check carried to a result keeps its blocked evidence, so
            # raw_reason is still set — but it is no longer asking for anything. Offering "Open
            # manual check" here would send the operator to redo work that is already done, and the
            # "Needs attention" chip would promise a list this target has already left.
            resolved_by_run = str(det.get("resolved_by_run") or "")
            resolved = prospect_status == "RESOLVED_BY_MANUAL_CHECK"
            challenge = (bool(raw_reason) or prospect_status == "MANUAL_ACTION_REQUIRED") \
                and not resolved
            if resolved:
                human_reason = ("A manual check completed this target later, in a separate run. "
                                "This run holds only what was captured before the block.")
            elif prospect_status == "SKIPPED":
                human_reason = "This target was skipped, so it was never analyzed."
            elif prospect_status == "PENDING":
                human_reason = ("The analysis did not finish for this target — the run stopped "
                                "before its result was recorded.")
            else:
                # Only a proven blocking challenge earns a categorical sentence. When the detector
                # failed closed on an ambiguous page it says so, and either way it names the actual
                # signal — an operator who can see the evidence can overrule a wrong call, which is
                # exactly what "The site requested a human verification check" denied them when the
                # site had merely put an anti-spam widget on its own signup form.
                confidence = str(ma.get("challenge_confidence") or "confirmed")
                signal = str(ma.get("challenge_signal") or "")
                if confidence == "suspected":
                    human_reason = "A verification page may have prevented analysis."
                else:
                    human_reason = {
                        "captcha_detected": "The site requested a human verification check.",
                        "access_prohibited": "The site blocked automated access.",
                    }.get(raw_reason, "The browser could not complete this target automatically.")
                if signal:
                    human_reason = f"{human_reason} Detected: {signal}."
            # The badge/chip/title must tell the SAME story as human_reason above, using only
            # statuses that really exist. /scout/attention's blocked list is filtered to
            # MANUAL_ACTION_REQUIRED only (core/scout/challenge_session.py's _blocked_targets), so
            # the "Needs attention" chip and the alarmed hero styling are honest ONLY for a real
            # challenge — offering them to a PENDING/SKIPPED/FAILED target promises a destination it
            # can never reach. Reuse the wording already used elsewhere in this file for the same
            # statuses (the run-results table maps FAILED -> "Could not complete", SKIPPED ->
            # "Skipped") instead of inventing new vocabulary.
            if challenge:
                status_label = "Needs your help"
            elif resolved:
                status_label = "Resolved by a manual check"
            elif prospect_status == "SKIPPED":
                status_label = "Skipped"
            elif prospect_status == "PENDING":
                status_label = "Not analyzed"
            else:
                status_label = "Could not complete"
            hero_class = "status-hero attention" if challenge else "status-hero"
            badge_kind = "attention" if challenge else ""
            attention_chip = ('<a class="chip" href="/scout/attention">Needs attention</a>'
                               if challenge else '')
            page_title = ("AI QA Factory — Needs attention" if challenge
                          else f"AI QA Factory — {status_label}")

            def _art_url(rel: str) -> str:
                return f'/scout/artifact?run={_esc(run_id)}&rel={_esc(rel)}'

            imgs = [m for m in media if m.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".gif"))]
            img_html = "".join(
                f'<a href="{_art_url(m)}" target="_blank" rel="noopener">'
                f'<img src="{_art_url(m)}" alt="Partial page capture for {_esc(domain)}"></a>'
                for m in imgs)
            if not img_html:
                img_html = '<p class="muted">No screenshot was captured before the stop.</p>'
            evidence_links = "".join(
                f'<li><a href="{_art_url(e["rel"])}" target="_blank" rel="noopener">'
                f'{_esc(e["label"])}</a></li>' for e in evidence_files)
            if challenge:
                actions_html = (
                    '<div class="row"><button class="btn primary" id="opencheck" '
                    'onclick="openCheck()">Open manual check</button>'
                    '<button class="chip" id="continuecheck" onclick="challengeAction(\'continue\')" '
                    'disabled>Continue check</button>'
                    '<button class="chip" id="defercheck" onclick="challengeAction(\'defer\')" '
                    'disabled>Defer</button>'
                    '<button class="chip danger" id="skipcheck" onclick="challengeAction(\'skip\')" '
                    'disabled>Skip target</button></div>'
                    '<p id="challengemsg" class="muted" aria-live="polite">Open a visible Chromium '
                    'window, complete the human check there, then choose Continue. The same browser '
                    'session stays open for up to 15 minutes.</p>')
            elif resolved and resolved_by_run:
                # Send the operator to the result instead of asking them to redo the check.
                actions_html = (
                    f'<div class="row"><a class="btn primary" href="/scout/target?'
                    f'run={_esc(resolved_by_run)}&domain={_esc(domain)}">Open the result</a></div>'
                    '<p class="muted">The manual check finished this target in its own run; the '
                    'findings live there, not here.</p>')
            else:
                actions_html = (
                    '<div class="row"><a class="btn primary" href="/scout">'
                    'Scan this target again</a></div>'
                    '<p class="muted">No human check is pending for this target — rescanning is the '
                    'way to get a result.</p>')
            body = (
                f'<h1>{_esc(domain)}</h1><div class="row">{nav}'
                f'{attention_chip}</div>'
                f'<div class="card {hero_class}">'
                f'<div class="row">{_badge(status_label, badge_kind)}'
                f'<span>{_esc(human_reason)}</span></div>'
                '<p><b>0 confirmed findings — analysis incomplete.</b> No conclusion about the site and no outreach '
                'draft were created.</p>'
                f'{actions_html}</div>'
                '<div class="card"><h2>Partial evidence</h2>'
                f'<div class="media-grid">{img_html}</div>'
                f'<p><b>Landing response:</b> HTTP {_esc(network.get("status") or "unavailable")} · '
                f'<b>Files captured:</b> {len(media) + len(evidence_files)}</p>'
                '<p class="muted">Partial evidence confirms only why the scan stopped; it is not a '
                'full QA result.</p></div>'
                '<details class="card advanced"><summary>Advanced diagnostics</summary>'
                f'<p><b>Internal status:</b> <code>{_esc(det.get("prospect_status") or "INCOMPLETE")}</code></p>'
                f'<p><b>Reason:</b> <code>{_esc(raw_reason or "unavailable")}</code> · '
                f'<b>Stage:</b> <code>{_esc(ma.get("stage") or "unavailable")}</code> · '
                f'<b>Stop boundary:</b> <code>{_esc(ma.get("stop_boundary") or "unavailable")}</code></p>'
                f'<p><b>Recorded recommendation:</b> '
                f'{_esc(ma.get("recommended_action") or "Unavailable for this historical run")} · '
                f'<b>Partial evidence:</b> landing HTTP {_esc(network.get("status") or "unavailable")}</p>'
                f'<p><b>Run:</b> <code>{_esc(run_id)}</code> · <b>Prospect:</b> '
                f'<code>{_esc(det.get("prospect_id") or "—")}</code></p>'
                f'<ul>{evidence_links or "<li class=muted>No structured files available.</li>"}</ul>'
                '<p class="muted">Playwright Inspector is a developer debugging window, not a saved '
                'evidence artifact. A trace is shown only when the scan actually recorded one.</p>'
                '</details>')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";const DOM=" + json.dumps(domain)
                + ";const RUN=" + json.dumps(run_id) + ";let SID='';let POLL=null;"
                "function post(u,b){return fetch(u,{method:'POST',headers:{'X-Scout-CSRF':CSRF,"
                "\"Content-Type\":\"application/json\"},body:JSON.stringify(b||{})}).then(r=>r.json());}"
                "function show(s){var m=document.getElementById('challengemsg');if(m)m.textContent=s;}"
                "function buttons(on){['continuecheck','defercheck','skipcheck'].forEach(function(id){"
                "var b=document.getElementById(id);if(b)b.disabled=!on;});}"
                "function openCheck(){var b=document.getElementById('opencheck');if(b)b.disabled=true;"
                "show('Opening visible Chromium…');post('/api/scout/challenge/start',"
                "{domain:DOM,run:RUN}).then(function(j){if(!j.ok){show(j.error||'Could not open');"
                "if(b)b.disabled=false;return;}SID=j.session.id;buttons(true);render(j.session);"
                "POLL=setInterval(poll,1200);});}"
                "function challengeAction(a){if(!SID)return;buttons(false);"
                "post('/api/scout/challenge/action',{id:SID,action:a}).then(function(j){"
                "if(j.session)render(j.session);});}"
                "function poll(){if(!SID)return;fetch('/api/scout/attention').then(r=>r.json()).then(j=>{"
                "var s=(j.sessions||[]).find(x=>x.id===SID);if(s)render(s);});}"
                "function render(s){show(s.message||s.state);var waiting=s.state==='waiting';"
                "buttons(waiting);if(['completed','deferred','skipped','failed','timed_out'].includes(s.state)){"
                "clearInterval(POLL);if(s.state==='completed')setTimeout(function(){location.href="
                "'/scout/target?run='+encodeURIComponent(s.result_run)+'&domain='+encodeURIComponent(DOM);"
                "},900);}}")
            return _page(page_title, "/scout", body, script)

        def _scout_attention_page(self) -> str:
            """One row per site that needs a human — not one per attempt, and no non-sites.

            Both numbers in the headline come from the same inventory that builds the table, so the
            sentence and the rows can never disagree: the count of companies waiting and the count
            of times Scout was blocked are different facts and are named as different facts.
            """
            from core.scout.needs_attention import attention_inventory

            inv = attention_inventory(service.output_dir)
            data = challenge_manager.snapshot()
            sessions = data.get("sessions") or []

            def _attempts_cell(site) -> str:
                # Earlier tries are this site's history. Naming them keeps the row honest about how
                # much has already been spent on it without adding another row to the queue.
                if site.attempt_count <= 1:
                    return '<span class="muted">1 attempt</span>'
                older = "".join(
                    f'<li>{_fmt_ts(a.get("updated_at", ""))} &mdash; '
                    f'<a href="/scout/target?run={_esc(a.get("run_id", ""))}'
                    f'&domain={_esc(site.domain)}">{_esc(a.get("run_id", ""))}</a></li>'
                    for a in site.attempts[1:])
                return (f'<details><summary>{site.attempt_count} attempts</summary>'
                        f'<ul class="attempt-history">{older}</ul></details>')

            rows = "".join(
                '<tr>'
                f'<td data-label="Site"><a href="/scout/target?run={_esc(site.run_id)}'
                f'&domain={_esc(site.domain)}">{_esc(site.domain)}</a></td>'
                f'<td data-label="Reason">{_esc(_manual_reason_label(site.reason))}</td>'
                f'<td data-label="Last blocked" class="muted">{_fmt_ts(site.updated_at)}</td>'
                f'<td data-label="Attempts">{_attempts_cell(site)}</td>'
                f'<td data-label="Action"><a class="chip" href="/scout/target?run='
                f'{_esc(site.run_id)}&domain={_esc(site.domain)}">Open manual check</a></td>'
                '</tr>' for site in inv.sites)
            table = (
                '<table class="responsive-table"><thead><tr><th>Site</th><th>Reason</th>'
                '<th>Last blocked</th><th>Attempts</th><th>Action</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>'
                if rows else
                '<div class="empty muted">No sites need manual attention.</div>')
            # Values that were recorded as targets but are not public websites. They are shown so a
            # bad line in a pasted list or a file is visible rather than silently vanishing — but
            # never as a company, and never with a link that pretends there is a site to open.
            invalid_rows = "".join(
                f'<tr><td data-label="Value"><code>{_esc(bad.value or "(empty)")}</code></td>'
                f'<td data-label="Why">{_esc(bad.reason)}</td>'
                f'<td data-label="From" class="muted">{_esc(bad.run_id)}</td></tr>'
                for bad in inv.invalid)
            invalid_html = (
                f'<details class="card advanced"><summary>{len(inv.invalid)} recorded target(s) '
                f'were not public websites</summary>'
                '<p class="muted">These were never scanned and are not counted as sites.</p>'
                '<table class="responsive-table"><thead><tr><th>Value</th><th>Why</th>'
                f'<th>Recorded in</th></tr></thead><tbody>{invalid_rows}</tbody></table></details>'
                if invalid_rows else '')
            session_rows = "".join(
                '<tr>'
                f'<td data-label="Target">{_esc(s.get("domain",""))}</td>'
                f'<td data-label="State">{_badge(_challenge_state_label(s.get("state","")))}</td>'
                f'<td data-label="Message" class="muted">{_esc(s.get("message",""))}</td>'
                f'<td data-label="Result">'
                + (f'<a href="/scout/target?run={_esc(s.get("result_run",""))}&domain='
                   f'{_esc(s.get("domain",""))}">Open result</a>'
                   if s.get("state") == "completed" else "—")
                + '</td></tr>' for s in sessions[:20])
            sessions_html = (
                '<table class="responsive-table"><thead><tr><th>Target</th><th>State</th>'
                f'<th>Message</th><th>Result</th></tr></thead><tbody>{session_rows}</tbody></table>'
                if session_rows else
                '<div class="empty muted">No manual browser sessions yet.</div>')
            hero_class = "status-hero attention" if inv.sites else "status-hero"
            body = (
                '<h1>Needs attention</h1><div class="row">'
                '<a class="chip" href="/scout/history">History</a>'
                '<button class="chip" onclick="location.reload()">Refresh</button></div>'
                f'<div class="card {hero_class}"><p><b>{_esc(inv.headline())}</b></p>'
                '<p>Open a site to complete its human check, defer it, or skip it. '
                'No CAPTCHA is bypassed automatically.</p></div>'
                f'<div class="card"><h2>Sites blocked before a full analysis</h2>{table}</div>'
                f'{invalid_html}'
                f'<details class="card advanced"><summary>Manual-check session history</summary>'
                f'{sessions_html}</details>')
            return _page("AI QA Factory — Needs attention", "/scout", body,
                         "setTimeout(function(){location.reload();},15000);")

        def _scout_run_results_page(self, run_id: str) -> str:
            """Run-scoped result list for ONE exact run: DONE and MANUAL_ACTION_REQUIRED targets, with
            counts and a human-readable Details link each. Never the generic client/project /results."""
            run_id = str(run_id or "").strip()
            try:
                store = RunStore(service.output_dir, run_id) if run_id else None
            except StoreError:
                store = None
            state = {}
            if store is not None and store.exists():
                try:
                    state = store.load_state() or {}
                except StoreError:
                    state = {}
            prospects = state.get("prospects", {}) or {}
            if not run_id or not prospects:
                return _page("AI QA Factory — Run results", "/scout",
                             f'<h1>Run results</h1><div class="card empty muted">No results for run '
                             f'<code>{_esc(run_id)}</code>.</div>')
            from core.scout.discovery.domain_intel import canonical_domain
            from core.scout.operator_state import OperatorStateStore
            archived = OperatorStateStore(service.output_dir).run_archived(run_id)
            # A skip the operator requested is persisted separately from state.json and applied by
            # the engine before it starts each new target. The request is therefore a real, pending
            # fact the page must show — otherwise a successful click leaves no trace and the operator
            # cannot tell it worked. "Requested" and "applied" are different facts: the request only
            # counts while the target is still queued; once the engine acts, the target's own status
            # becomes SKIPPED and speaks for itself. An entry left behind for a target that has since
            # finished can never apply and is not advertised.
            try:
                skip_requested = {
                    str(pid) for pid in
                    ((store.load_artifact("operator_actions.json") or {}).get("skip_prospects") or [])
                } if store is not None else set()
            except StoreError:
                skip_requested = set()
            # Only a target that has NOT started can still be stopped: the engine checks the request
            # immediately before it begins each target and never interrupts one mid-operation. A
            # started target stays PENDING until it finishes, so started_at — not the status — is
            # what keeps this marker from promising something that cannot happen.
            queued_skips = [pid for pid in sorted(skip_requested)
                            if str((prospects.get(pid) or {}).get("status", "")) == "PENDING"
                            and not (prospects.get(pid) or {}).get("started_at")]
            rows = []
            for pid, p in sorted(prospects.items()):
                dom = canonical_domain(p.get("url", "") or p.get("final_url", "")) or ""
                status = p.get("status", "")
                total = int(p.get("verified_findings", 0) or 0)
                actionable = int(p.get("verified_defects", 0) or 0)
                info = max(total - actionable, 0)
                status_label = _run_prospect_label(p)
                complete = "Complete" if status == "DONE" else (
                    "Not analyzed" if status in ("PENDING", "SKIPPED") else "Incomplete")
                details = (f'<a href="/scout/target?run={_esc(run_id)}&domain={_esc(dom)}">Details</a>'
                           if dom else '<span class="muted">—</span>')
                # Coverage (PR-B): a compact readout from the ALREADY-persisted compact state row.
                # The "coverage" key is entirely absent for pre-coverage-feature legacy runs — that
                # must render as unavailable, distinct from a present key whose value is "explicit"
                # (a legacy/back-compat profile that still carries real, honest coverage data).
                if "coverage" in p:
                    cov_profile = p.get("coverage")
                    cov_label = _COVERAGE_PROFILE_LABEL.get(cov_profile, cov_profile or "—")
                    cov_pages = p.get("meaningful_pages_tested")
                    cov_stop = str(p.get("page_stop_reason") or "")
                    cov_stop_label = _PAGE_STOP_LABEL.get(cov_stop, cov_stop or "—")
                    cov_cell = (f'{_esc(cov_label)} · {_esc(cov_pages if cov_pages is not None else "—")} '
                                f'pages · {_esc(cov_stop_label)}')
                else:
                    cov_cell = '<span class="muted">—</span>'
                rows.append(
                    f'<tr><td class="select-cell"><input type="checkbox" class="pick" '
                    f'value="{_esc(pid)}" data-domain="{_esc(dom)}" '
                    f'aria-label="Select {_esc(dom or pid)}"></td>'
                    f'<td data-label="Target">{_esc(dom)}</td>'
                    f'<td data-label="Status">'
                    f'{_badge(status_label, "attention" if status == "MANUAL_ACTION_REQUIRED" else "")}'
                    + (' <span class="badge attention">Skip requested</span>'
                       if pid in queued_skips else '')
                    + '</td>'
                    f'<td data-label="Actionable">{actionable}</td>'
                    f'<td data-label="Informational">{info}</td>'
                    f'<td data-label="Analysis">{_esc(complete)}</td>'
                    f'<td data-label="Coverage">{cov_cell}</td>'
                    f'<td data-label="Open">{details}</td></tr>')
            table = (f'<table class="responsive-table"><caption>Targets in this run</caption>'
                     f'<thead><tr><th><input type="checkbox" id="pickall" aria-label="Select all"></th>'
                     f'<th>Target</th><th>Status</th><th>Actionable</th>'
                     f'<th>Informational</th><th>Analysis</th><th>Coverage</th><th>Open</th></tr>'
                     f'</thead><tbody>{"".join(rows)}</tbody></table>')
            run_actions = (
                '<button class="chip" onclick="runAction(\'restore_run\')">Restore run</button>'
                if archived else
                '<button class="chip" onclick="runAction(\'archive_run\')">Archive run</button>')
            raw_links = "".join(
                f'<li><code>{_esc(p.get("status") or "UNKNOWN")}</code> · '
                f'<a href="/api/prospect?run={_esc(run_id)}&id={_esc(pid)}">'
                f'{_esc(pid)} raw JSON</a></li>' for pid, p in sorted(prospects.items()))
            body = ('<h1>Run results</h1><div class="row">'
                    '<a class="chip" href="/scout">Manual URL Scan</a>'
                    '<a class="chip" href="/scout/history">History</a>'
                    '<a class="chip" href="/scout/attention">Needs attention</a></div>'
                    + ('<div class="banner warn">This run is archived and hidden from normal '
                       'operator lists.</div>' if archived else '')
                    + (f'<div class="banner">{len(queued_skips)} '
                       f'{"target is" if len(queued_skips) == 1 else "targets are"} queued to be '
                       f'skipped — {"it" if len(queued_skips) == 1 else "they"} will not start.'
                       f'</div>' if queued_skips else '')
                    + f'<div class="card"><div class="summary-grid">'
                    f'<div class="summary-item"><span class="muted">Targets</span>'
                    f'<strong>{len(prospects)}</strong></div>'
                    # One tile per outcome actually present, from the same labels the rows use, so
                    # the tiles account for every target instead of leaving failed, interrupted and
                    # skipped ones in no category at all.
                    + "".join(
                        f'<div class="summary-item"><span class="muted">{_esc(label)}</span>'
                        f'<strong>{count}</strong></div>'
                        for label, count in _run_status_summary(prospects))
                    + f'</div><div class="scrollx" style="margin-top:12px">{table}</div></div>'
                    f'<div class="card bulkbar" id="bulkbar" hidden><b><span id="selected">0</span> '
                    f'selected</b><div class="row">'
                    f'<button class="chip" onclick="selectedAction(\'skip_queued\')">Skip queued</button>'
                    f'<button class="chip" onclick="selectedAction(\'archive_targets\')">'
                    f'Archive from history</button>'
                    f'<button class="chip danger" onclick="deleteEvidence()">Delete heavy evidence…</button>'
                    f'<button class="chip" onclick="clearSelection()">Clear</button>'
                    f'<span id="bulkmsg" class="muted" aria-live="polite"></span></div></div>'
                    f'<details class="card advanced"><summary>Run administration</summary>'
                    f'<p><b>Run ID:</b> <code>{_esc(run_id)}</code> · '
                    f'<b>Internal state:</b> <code>{_esc(state.get("status") or "unknown")}</code></p>'
                    f'<details><summary>Exact-run diagnostics</summary><ul>{raw_links}</ul></details>'
                    f'<div class="row">{run_actions}'
                    f'<button class="chip danger" onclick="deleteRun()">Delete entire run…</button></div>'
                    f'<p class="muted">Archive is reversible. Deleting heavy evidence keeps findings '
                    f'and summary history. Deleting the run is permanent, is refused while active, '
                    f'and requires typing the exact run ID.</p></details>')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";const RUN=" + json.dumps(run_id) + ";"
                "function picks(){return Array.from(document.querySelectorAll('.pick:checked'));}"
                "function refreshBulk(){var n=picks().length;document.getElementById('selected').textContent=n;"
                "document.getElementById('bulkbar').hidden=!n;}"
                "document.querySelectorAll('.pick').forEach(x=>x.onchange=refreshBulk);"
                "var pa=document.getElementById('pickall');if(pa)pa.onchange=function(){"
                "document.querySelectorAll('.pick').forEach(x=>x.checked=pa.checked);refreshBulk();};"
                "function clearSelection(){document.querySelectorAll('.pick').forEach(x=>x.checked=false);"
                "if(pa)pa.checked=false;refreshBulk();}"
                "function post(b){return fetch('/api/scout/operator',{method:'POST',headers:{"
                "'X-Scout-CSRF':CSRF,'Content-Type':'application/json'},body:JSON.stringify(b)})"
                ".then(r=>r.json());}"
                # The server already reports exactly what it did and what it refused; reloading
                # without reading it threw that away and left a successful action looking identical
                # to a dead button. A clean success reloads, because the reloaded page carries the
                # persistent banner and per-row marker. A partial result keeps the operator on the
                # page with the reason, since a refusal is not persisted anywhere and a reload would
                # erase the only account of it.
                "function bulkSummary(j){var out=[];"
                "if(j.requested&&j.requested.length)out.push(j.requested.length+' queued to skip');"
                "if(j.refused&&j.refused.length)out.push(j.refused.length+' refused ('+"
                "j.refused.map(function(r){return (r.prospect_id||'?')+': '+(r.status||'unknown');})"
                ".join(', ')+')');"
                "if(j.removed&&j.removed.length)out.push(j.removed.length+' file(s) removed');"
                "if(j.forgotten&&j.forgotten.length)out.push(j.forgotten.length+' removed from history');"
                "if(j.message)out.push(j.message);"
                "return out.join(' · ');}"
                "function selectedAction(action,confirmFlag){var ps=picks();if(!ps.length)return;"
                "post({action:action,run_id:RUN,prospect_ids:ps.map(x=>x.value),"
                "domains:ps.map(x=>x.dataset.domain).filter(Boolean),confirm:!!confirmFlag})"
                ".then(j=>{var m=document.getElementById('bulkmsg');"
                "if(!j.ok){m.textContent=j.error||'Action failed';return;}"
                "var partial=(j.refused&&j.refused.length)?true:false;"
                "m.textContent=bulkSummary(j)||'Done';"
                "if(!partial)location.reload();});}"
                "function deleteEvidence(){qaConfirm('Delete screenshots, videos and browser traces "
                "for selected targets? Findings and summary history will remain.','Delete evidence')"
                ".then(function(ok){if(ok)selectedAction('delete_evidence',true);});}"
                "function runAction(a){post({action:a,run_id:RUN}).then(j=>{if(j.ok)location.reload();"
                "else alert(j.error||'Action failed');});}"
                "function deleteRun(){qaConfirm('Permanent deletion. Type the exact run ID to continue.',"
                "'Delete entire run',RUN).then(function(ok){if(!ok)return;"
                "post({action:'delete_run',run_id:RUN,confirm:true}).then(j=>{"
                "if(j.ok)location.href='/scout/history';else alert(j.error||'Delete failed');});});}")
            return _page("AI QA Factory — Run results", "/scout", body, script)

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
            body = (f'<h1>Companies &amp; outreach</h1>'
                    f'<p class="muted">A commercial view of analyzed companies, public contacts and '
                    f'draft outreach. For QA history and evidence, use <a href="/scout/history">'
                    f'Scout History</a>.</p>'
                    f'<div class="row"><a class="chip" href="/scout/history">QA History</a>'
                    f'<a class="chip" href="/scout/campaigns">Campaigns</a></div>'
                    f'{form}{chips}<div class="scrollx">{table}</div>'
                    '<p class="muted">Read-only. No outreach is sent from here.</p>')
            return _page("AI QA Factory — Companies & outreach", "/scout", body)

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
                f'<p><a href="/results">&larr; Companies &amp; outreach</a></p>'
                f'<h1>{_esc(d["company"].get("canonical_name") or cid)}</h1>'
                f'<p class="muted">{_esc(d["company"].get("primary_domain"))}</p>'
                f'<h2>Findings</h2><div class="scrollx"><table><caption>{len(d["findings"])} finding(s)</caption>'
                f'<tr><th>Capability</th><th>Severity</th><th>Title</th><th>Verification</th>'
                f'<th>Client-safe</th></tr>{frows or "<tr><td colspan=5 class=muted>none</td></tr>"}</table></div>'
                '<h2>Public contact</h2><div class="card">'
                f'<p>Contact: <code>{_esc(recip)}</code> ({_esc(contact.get("status"))})</p>'
                '<details class="advanced"><summary>Contact provenance</summary>'
                f'<p>Source: {_esc(prov.get("source_category"))} · published '
                f'{_esc(prov.get("publicly_published_for_contact"))} · verified '
                f'{_esc(prov.get("last_verified_at"))}</p>'
                f'<p class="muted">Source URL: {_esc(prov.get("source_url"))}</p></details></div>'
                '<h2>Draft (edit in Gmail; nothing is sent from here)</h2><div class="card">'
                f'<p><strong>Subject:</strong> {_esc(draft.get("subject", "(none)"))}</p>'
                f'<pre>{_esc(draft.get("body", "(no draft)"))}</pre>'
                f'<p>{gmail_action} <span class="muted">— then send manually in Gmail and mark the '
                'company contacted. Live API send stays the optional, one-at-a-time scout send CLI '
                'path.</span></p></div>')
            return _page(f"AI QA Factory — {cid}", "/scout", body)

        def _evidence_li(self, e) -> str:
            rel = e.get("relative_path", "")
            integ = e.get("integrity", "unverified")
            kind = {"verified": "ok", "stale": "blocked"}.get(integ, "")
            label = {"verified": "Verified", "stale": "Stale", "unverified": "Unverified"}.get(integ, "")
            link = (f' — <a href="{_esc(e["href"])}">Preview</a>' if e.get("href") else "")
            return (f'<li>{_esc(rel)} <span class="muted">{_esc(e.get("kind", ""))}</span> '
                    f'{_badge(label, kind)}{link}</li>')

        def _activity_json(self, project, include_diagnostics: bool = False):
            events = []
            from core.orchestration.work_execution import WorkExecutionService
            wx = WorkExecutionService(output_dir=service.output_dir)
            index = self._read_model().project_list(
                view="all", include_diagnostics=include_diagnostics)["projects"]
            from core.orchestration.project_index import ProjectIndex
            object_titles = {
                p.project_id: _friendly_record_label(p.title, p.project_id, "Scout campaign")
                for p in ProjectIndex(service.output_dir).list_projects(include_diagnostics)
            }
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
                                   "object": pid,
                                   "object_label": object_titles.get(
                                       pid, _friendly_record_label("", pid, "Work item")),
                                   "result": hd.get("reason", "")})
            # Scout activity is append-only persisted campaign history. Enumerate canonical
            # campaigns directly from _runcontrol, the same source Observer uses, so the diagnostics
            # toggle cannot inflate campaign counts with per-target/legacy artifact folders. The
            # currently attached run remains a backwards-compatible fallback for an older direct
            # Scout run that pre-dates run-control; campaign ids are de-duplicated before reading.
            scout_run_ids = []
            try:
                from core.scout.canonical_runs import canonical_campaigns
                scout_run_ids = [
                    row["campaign_id"]
                    for row in canonical_campaigns(
                        service.output_dir, include_diagnostics=include_diagnostics)
                    if not project or row["campaign_id"] == project
                ]
            except Exception:
                pass
            try:
                attached_id = str(service.status().get("run_id") or "")
                if attached_id and (not project or project == attached_id):
                    from core.scout.canonical_runs import is_diagnostic_run
                    if include_diagnostics or not is_diagnostic_run(attached_id):
                        scout_run_ids.append(attached_id)
            except Exception:
                pass

            scout_run_ids = list(dict.fromkeys(scout_run_ids))
            scout_events = 0
            scout_runs_without_history = 0
            for run_id in scout_run_ids:
                from core.scout.canonical_runs import is_diagnostic_run
                diagnostic = is_diagnostic_run(run_id)
                try:
                    run_events = RunStore(service.output_dir, run_id).read_events()
                except Exception:
                    run_events = []
                if not run_events:
                    scout_runs_without_history += 1
                    continue
                for event_index, ev in _project_scout_activity_events(run_id, run_events):
                    events.append({
                        "time": str(ev.get("at", "")),
                        "actor": "scout-engine",
                        "action": str(ev.get("event", "scout_event")),
                        "object": run_id,
                        "object_label": object_titles.get(
                            run_id, _friendly_record_label("", run_id, "Scout campaign")),
                        "result": ", ".join(
                            f"{k}={v}" for k, v in ev.items() if k not in ("at", "event")),
                        "campaign_id": run_id,
                        "event_id": f"{run_id}#{event_index}",
                        "diagnostic": diagnostic,
                    })
                    scout_events += 1
            events.sort(key=lambda e: e["time"], reverse=True)
            return {"schema": "dashboard-read-model/v1", "events": events[:200],
                    "scout_run_partial": bool(scout_run_ids) and not scout_events,
                    "scout_campaigns_considered": len(scout_run_ids),
                    "scout_campaigns_without_history": scout_runs_without_history}

        def _activity_page(self, q) -> str:
            diag = self._want_diagnostics(q)
            data = self._activity_json((q.get("project") or [""])[0], diag)
            if diag:
                rows = "".join(
                    f'<tr><td data-label="Time" class="muted">{_fmt_ts(e["time"])}</td>'
                    f'<td data-label="Actor">{_esc(e["actor"])}</td>'
                    f'<td data-label="Action">{_esc(e["action"])}</td>'
                    f'<td data-label="Object"><span>{_esc(e["object"])}</span>'
                    f'{" " + _badge("Diagnostic", "attention") if e.get("diagnostic") else ""}</td>'
                    f'<td data-label="Result" class="muted">{_esc(e["result"])}</td></tr>'
                    for e in data["events"])
            else:
                rows = "".join(
                    f'<tr><td data-label="When" class="muted">{_fmt_ts(e["time"])}</td>'
                    f'<td data-label="Activity">{_esc(_activity_label(e["action"]))}</td>'
                    f'<td data-label="Target" class="muted">'
                    f'{_esc(e.get("object_label") or e["object"])}</td></tr>'
                    for e in data["events"])
            if rows:
                heads = ('<th>Time</th><th>Actor</th><th>Action</th><th>Object</th><th>Result</th>'
                         if diag else '<th>When</th><th>Activity</th><th>Target</th>')
                table = (f'<table class="responsive-table"><caption>Recent activity</caption>'
                         f'<thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table>')
            elif data.get("scout_run_partial"):
                # A Scout run is attached but has no persisted events (e.g. an older run pre-dating
                # event logging) — say that plainly rather than pretend nothing has happened.
                table = ('<div class="card empty muted">A Scout run is attached, but detailed '
                        'historical activity is unavailable for it.</div>')
            else:
                table = ('<div class="card empty muted">No operator activity yet. Campaign and '
                         'work events will appear here after the first run.</div>')
            toggle = (
                '<a class="chip" href="/activity">&#10003; Production only</a>' if diag else
                '<a class="chip" href="/activity?diagnostics=1">Show diagnostics</a>')
            banner = ('<div class="banner warn">Diagnostic activity (smoke/acceptance/demo) is '
                      'included below and should not be treated as production.</div>' if diag else '')
            return _page("AI QA Factory — Activity", "/activity",
                         f'<h1>Activity</h1>{banner}<div class="row">{toggle}</div>'
                         f'<div class="scrollx">{table}</div>')


        def _settings_page(self, q=None) -> str:
            from core.orchestration.tool_broker import ToolBroker
            gmail = next((t for t in ToolBroker(clock=lambda: "").discover()
                         if t.id == "gmail_personal"), None)
            gmail_state = gmail.ui_level if gmail else "Unknown"
            from core.build_identity import current_identity
            ident = current_identity()
            stale = bool(ident.get("stale"))
            build_card = (
                '<div class="card"><h2>Build identity</h2>'
                + (f'<div class="banner warn">{_esc(ident.get("warning",""))}</div>' if stale else '')
                + f'<p><b>Version:</b> {_esc(ident.get("product_version",""))}</p>'
                + f'<p><b>Running commit:</b> <code>{_esc(ident.get("running_sha") or "unknown")}</code>'
                + f' · <b>Repository HEAD:</b> <code>{_esc(ident.get("head_sha") or "unknown")}</code></p>'
                + f'<p><b>Process started:</b> {_esc(ident.get("process_started_at",""))} · '
                + '<b>Serving current code:</b> '
                + (_badge("no — restart required", "attention") if stale else _badge("yes", "ok"))
                + '</p><p class="muted">The running commit is captured at process start; a difference '
                'from repository HEAD means the server is serving older code and should be restarted. '
                'No secrets or absolute paths are shown.</p></div>')
            # Runtime and diagnostics moved here from Overview. They are things an operator looks up
            # when something seems wrong, not things they need while deciding what to scan — and on
            # Overview the full table pushed the one block that starts work below the fold.
            diag_hidden = self._read_model().overview().counts.get("diagnostics_hidden", 0)
            diag_line = (
                f'<p>{diag_hidden} test, replay or diagnostic record(s) are kept out of production '
                f'counts. <a href="/?diagnostics=1">Show them on Overview</a> · '
                f'<a href="/activity?diagnostics=1">Show them in Activity</a></p>'
                if diag_hidden else
                '<p class="muted">No diagnostic or acceptance records are currently hidden.</p>')
            runtime_card = (
                '<div class="card" id="runtime"><h2>Runtime</h2>'
                '<p class="muted">What code this process is actually serving. A Dashboard started '
                'from a working tree can outlive the code it loaded, and a commit SHA cannot reveal '
                'it — an uncommitted edit never moves HEAD.</p>'
                f'{_runtime_block_html(force_open=True)}'
                f'<h3>Diagnostic data</h3>{diag_line}</div>')
            body = (
                '<h1>Settings</h1>'
                f'{runtime_card}'
                '<div class="card"><h2>Appearance</h2>'
                '<p class="muted">Theme is changed from the header. Choose how much information fits '
                'on each page.</p>'
                '<div class="row" role="group" aria-label="Display density">'
                '<button id="density-comfortable" class="btn" aria-pressed="false" '
                'onclick="setDensity(\'comfortable\')">Comfortable</button>'
                '<button id="density-compact" class="btn" aria-pressed="false" '
                'onclick="setDensity(\'compact\')">Compact</button>'
                '<span id="density-status" class="muted" aria-live="polite"></span></div>'
                '<p class="muted">Saved in this browser only.</p></div>'
                '<div class="card"><h2>Scout defaults (bounded, read-only)</h2>'
                '<p>Up to 10 public websites per manual scan, one site at a time. Nothing is sent, '
                'submitted or purchased automatically.</p></div>'
                '<div class="card" id="data-retention"><h2>Data &amp; retention</h2>'
                '<p>Use archive for everyday cleanup. Permanent deletion is limited to exact Scout '
                'runs and heavy evidence, with confirmation.</p>'
                '<div class="retention-grid">'
                '<div class="summary-item"><span class="badge ok">Reversible</span>'
                '<strong>Archive</strong><span class="muted">Hides targets or runs from current views. '
                'Restore them from Archived.</span></div>'
                '<div class="summary-item"><span class="badge attention">Keeps audit</span>'
                '<strong>Forget target</strong><span class="muted">Removes History/dedup memory while '
                'preserving exact-run evidence.</span></div>'
                '<div class="summary-item"><span class="badge danger">Permanent</span>'
                '<strong>Delete</strong><span class="muted">Deletes selected heavy evidence or an '
                'entire inactive run. Raw Activity remains append-only.</span></div></div>'
                '<div class="row" style="margin-top:12px">'
                '<a class="btn" href="/scout/history?archived=1">Archived targets</a>'
                '<a class="btn" href="/scout/campaigns?archived=1">Archived campaigns</a>'
                '<a class="btn" href="/work?view=completed">Completed work</a>'
                '<a class="btn" href="/collab?completed=1">Completed collaboration</a></div></div>'
                f'<div class="card"><h2>Integrations</h2><p>Gmail: {_badge(gmail_state)} '
                '<span class="muted">Optional. No secret values are shown, and sending remains a '
                'separate opt-in action.</span></p>'
                '<p><a href="/tools">Open advanced readiness</a></p></div>'
                '<details class="card advanced"><summary>Advanced integrations &amp; system diagnostics</summary>'
                f'<p><b>Output workspace:</b> <code>{_esc(str(service.output_dir))}</code></p>'
                + build_card +
                f'{self._access_section()}'
                '</details>')
            script = (
                "function applyDensity(d){d=d==='compact'?'compact':'comfortable';"
                "document.documentElement.setAttribute('data-density',d);"
                "['comfortable','compact'].forEach(function(x){var b=document.getElementById('density-'+x);"
                "if(b)b.setAttribute('aria-pressed',x===d?'true':'false');});"
                "var s=document.getElementById('density-status');if(s)s.textContent="
                "(d==='compact'?'Compact':'Comfortable')+' selected';}"
                "function setDensity(d){applyDensity(d);try{localStorage.setItem('qa_density',d);}catch(e){}}"
                "try{applyDensity(localStorage.getItem('qa_density')||'comfortable');}"
                "catch(e){applyDensity('comfortable');}")
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
                f'<tr><td>{_esc(t["name"])}</td>'
                f'<td>{_esc(t["capability"])}</td><td>{_badge(t["ui_level"], _lvl_kind(t["ui_level"]))}</td>'
                f'<td class="muted">{_esc(t["readiness"])}</td>'
                f'<td class="muted">{_esc(t["reason"])}</td>'
                f'<td class="muted">{_esc(t["setup_action"])}</td></tr>' for t in data["tools"])
            table = (f'<table><caption>Current readiness (no live external call from this page)</caption>'
                     f'<tr><th>Tool</th><th>Capability</th><th>Level</th><th>Readiness</th>'
                     f'<th>Reason</th><th>Setup action</th></tr>{rows}</table>')
            body = (f'<p><a href="/settings">&larr; Settings</a></p>'
                    f'<h1>Advanced readiness</h1><p class="muted">Technical readiness for integrations '
                    f'and optional execution tools. Ordinary Scout work does not require every item '
                    f'on this page.</p>'
                    f'<details class="card advanced"><summary>Tool readiness matrix</summary>'
                    f'<div class="scrollx">{table}</div></details>'
                    f'<details class="card advanced"><summary>Service capability matrix</summary>'
                    f'{self._service_capability_section()}</details>')
            return _page("AI QA Factory — Advanced readiness", "/settings", body)

        def _service_capability_section(self) -> str:
            from core.orchestration.service_capability import snapshot as _svc_snap
            svcs = _svc_snap()["services"]

            def _kind(r):
                return {"Live Verified": "ok", "Fixture Verified": "ok", "Runtime Verified": "ok",
                        "Runtime Available": "", "Partially Verified": "attention",
                        "Needs Client": "attention", "Needs Operator": "attention",
                        "Blocked": "blocked", "Unavailable": "blocked"}.get(r, "")

            def _components(s):
                comps = s.get("components") or []
                if not comps:
                    return ""
                items = "".join(
                    f'<li>{_esc(c["name"])} — {_badge(c["readiness"], _kind(c["readiness"]))}'
                    f'{(" · " + _esc(c["evidence"])) if c.get("evidence") else ""}</li>'
                    for c in comps)
                return (f'<details><summary class="muted">per-provider readiness '
                        f'({len(comps)})</summary><ul>{items}</ul></details>')
            rows = "".join(
                f'<tr><td>{_esc(s["name"])}{_components(s)}</td>'
                f'<td>{_badge(s["readiness"], _kind(s["readiness"]))}</td>'
                f'<td class="muted">{_esc(", ".join(s["modes"]))}</td>'
                f'<td class="muted">{_esc(s["operator_action_if_blocked"])}</td></tr>' for s in svcs)
            table = (f'<table><caption>Advertised QA services — honest readiness (real acceptance vs '
                     f'client-required)</caption><tr><th>Service</th><th>Readiness</th><th>Modes</th>'
                     f'<th>If blocked</th></tr>{rows}</table>')
            return (f'<h2>Service capabilities</h2><p class="muted">What the product genuinely supports '
                    f'when the client supplies the repository, environment, accounts, and '
                    f'authorization. A multi-provider row is never shown as Live/Fixture Verified when '
                    f'only one provider is verified — expand it for the honest per-provider readiness.</p>'
                    f'<div class="scrollx">{table}</div>')

        def _access_section(self) -> str:
            items = cached_access_snapshot()["integrations"]

            def _kind(r):
                return {"Runtime Verified": "ok", "Authenticated": "ok", "Live Verified": "ok",
                        "Ready": "ok", "Installed": "", "Connected": "", "Declared": "",
                        "Needs Operator": "attention", "Needs Client": "attention",
                        "Blocked": "blocked", "Unavailable": "blocked"}.get(r, "")

            def _envvars(i):
                ref = (i.get("secret_ref") or "").strip()
                return (f'<br><span class="muted">env (names only): <code>{_esc(ref)}</code></span>'
                        if ref else "")
            # Operator Actions Required, derived from the ACTUAL AccessBootstrap state: every
            # operator-owned integration that is not yet ready, with its exact action + env-var names.
            _NEEDS = {"Needs Operator", "Blocked", "Unavailable"}
            todo = [i for i in items if i["owner"] == "operator" and i["readiness"] in _NEEDS]
            if todo:
                actions = "".join(
                    f'<li><strong>{_esc(i["name"])}</strong> — {_esc(i["setup_action"])}'
                    f'{_envvars(i)}</li>' for i in todo)
                todo_html = (f'<div class="card"><h3>Optional operator setup ({len(todo)})</h3>'
                             f'<p class="muted">Opt-in capabilities — not required for a basic Scout '
                             f'run. Set up only what you need.</p>'
                             f'<ul>{actions}</ul>'
                             f'<p class="muted">Set only env-var NAMES here — never paste secret '
                             f'values into the repo, logs, screenshots, state, or evidence.</p></div>')
            else:
                todo_html = ('<p class="muted">No operator actions outstanding — all operator-owned '
                             'integrations are ready.</p>')
            rows = "".join(
                f'<tr><td>{_esc(i["name"])}{_envvars(i)}</td>'
                f'<td>{_badge(i["readiness"], _kind(i["readiness"]))}</td>'
                f'<td class="muted">{_esc(i["purpose"])}</td><td>{_esc(i["owner"])}</td>'
                f'<td class="muted">{_esc(i["required_scope"])}</td>'
                f'<td class="muted">{_esc(i["setup_action"] or i["check_result"])}</td></tr>'
                for i in items)
            table = (f'<table><caption>Local runtimes + integrations (no secret is shown or stored)'
                     f'</caption><tr><th>Integration</th><th>Readiness</th><th>Purpose</th><th>Owner</th>'
                     f'<th>Required scope</th><th>Setup / Verify</th></tr>{rows}</table>')
            return (f'<div class="card"><h2>Access &amp; Integrations</h2>'
                    f'<p class="muted"><strong>The operator/client items here are opt-in.</strong> '
                    f"Scout's own discovery + QA runs on the local Python runtime (deep browser "
                    f'capture + video use Playwright); the entries below add autonomous execution, '
                    f'email, and client-work capabilities you enable only per need. Real local '
                    f'readiness (cached; probes '
                    f'never block a request). Secrets are referenced by env-var name only, never '
                    f'shown or persisted. Client-owned items stay Needs Client; Upwork intake is '
                    f'always manual. <a href="/settings?refresh=1">Refresh readiness</a></p>'
                    f'{todo_html}<div class="scrollx">{table}</div></div>')

        def _docs_page(self) -> str:
            docs = [("Product contract", "PRODUCT_CONTRACT_V3.md"),
                    ("Client work operator guide", "CLIENT_WORK_OPERATOR_GUIDE.md"),
                    ("Scout operator guide", "SCOUT_OPERATOR_GUIDE.md"),
                    ("Dashboard guide", "DASHBOARD_OPERATOR_GUIDE.md"),
                    ("Tool readiness guide", "TOOL_READINESS_GUIDE.md"),
                    ("Troubleshooting", "TROUBLESHOOTING_OPERATOR.md")]
            items = "".join(f"<li>{_esc(lbl)} — <code>docs/{_esc(f)}</code></li>" for lbl, f in docs)
            body = (
                '<h1>Help</h1><p class="muted">Short answers for the most common operator tasks.</p>'
                '<div class="help-grid">'
                '<section class="card"><h2>Start a Scout campaign</h2>'
                '<ol><li>Open <a href="/scout/new">New Scout campaign</a>.</li>'
                '<li>Choose the run size, countries and industries.</li>'
                '<li>Approve the bounded live run and select Run campaign.</li></ol>'
                '<p>Every run has hard limits and never sends messages, submits forms or makes '
                'purchases automatically.</p></section>'
                '<section class="card"><h2>Use from Claude Code in VS Code</h2>'
                '<p>Open this repository in VS Code, start Claude Code Chat, and paste the client brief '
                'with the goal, constraints and what “done” means. Repository rules load '
                'automatically from <code>CLAUDE.md</code> and <code>AGENTS.md</code>.</p>'
                '<p>Ask the agent to analyze first and wait for approval before implementation. '
                'Start this operator UI separately with <code>python main.py dashboard</code>.</p>'
                '<details><summary>Prompt template</summary>'
                '<pre>Analyze this client request first.\n'
                'Create a saved work item and show fit, risks, missing access, questions, plan, '
                'and validation.\nDo not implement until I approve.\n\n'
                'Client brief:\n[paste the client request, links, files, budget, deadline, and '
                'available access]\n\nDone when:\n'
                '[state the expected deliverables and tests]</pre></details></section>'
                '<section class="card"><h2>Review findings and evidence</h2>'
                '<p>Use <a href="/scout/history">History</a> for analyzed websites. Open a target to '
                'review client-safe findings, screenshots and downloadable evidence.</p>'
                '<p>Use <a href="/results">Companies &amp; outreach</a> only for commercial follow-up '
                'and public-contact drafts.</p></section>'
                '<section class="card"><h2>Pause or stop safely</h2>'
                '<p>The campaign progress page shows only the controls available in the current '
                'state. Stop &amp; Save preserves a checkpoint so the result can be reviewed later.</p>'
                '<p>Immediate cancellation is kept under Emergency action.</p></section>'
                '<section class="card"><h2>Clean up old data</h2>'
                '<p>Archive first whenever possible. Archive is reversible; Forget removes a target '
                'from History/dedup but keeps exact-run evidence; Delete is permanent.</p>'
                '<p><a href="/settings#data-retention">Open Data &amp; retention</a>.</p></section>'
                '<section class="card"><h2>Diagnostics and integrations</h2>'
                '<p>Production views hide smoke, replay and acceptance data by default. Technical '
                'IDs, build details, models and readiness matrices stay inside Advanced sections.</p>'
                '<p><a href="/settings">Open Settings</a>.</p></section>'
                '<section class="card"><h2>When something looks wrong</h2>'
                '<p>Refresh once, then check Needs attention. If the running build is stale or an '
                'integration is unavailable, open Advanced integrations &amp; system diagnostics '
                'in Settings.</p></section></div>'
                f'<details class="card advanced"><summary>Reference files for developers</summary>'
                f'<p class="muted">Open these local files in the repository editor.</p><ul>{items}</ul>'
                f'</details>')
            return _page("AI QA Factory — Help", "/docs", body)

    return _Handler


# The campaign form uses the shared design-system classes/tokens (a themed .card, tokenised
# textarea/inputs/checkbox, and a .btn primary) so nothing is a default-white control in Dark mode.
# Layout (max-width, field widths) and every safety statement are preserved (no redesign).
_START_SCOUT_JS = r"""const CSRF=__CSRF__;
function $(id){return document.getElementById(id);}
function J(u,b){return fetch(u,{method:'POST',headers:{'Content-Type':'application/json',
'X-Scout-CSRF':CSRF},body:JSON.stringify(b)}).then(function(r){return r.json();});}
function source(){var e=document.querySelector('input[name="source"]:checked');
return e?e.value:'find';}
function checks(name){return Array.from(document.querySelectorAll(
'input[name="'+name+'"]:checked')).map(function(e){return e.value;});}
function csv(s){return String(s||'').split(',').map(function(x){return x.trim();}).filter(Boolean);}
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(c){
return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
var PENDING={targets:[],counts:null};
function showPanels(){var s=source();
['find','paste','file'].forEach(function(k){$('p-'+k).hidden=(k!==s);});
$('intake').hidden=(s==='find');
if(s==='find'){PENDING={targets:[],counts:null};}
summary();}
function summary(){var n=parseInt($('maxsites').value,10)||10;
var s=source();var what=(s==='find')?('up to '+n+' sites'):
((PENDING.counts?PENDING.counts.unique_sites:0)+' site(s)');
$('safetysummary').textContent='Read-only scan · '+what+
' · evidence saved automatically · no forms, purchases or messages.';}
function renderIntake(j){PENDING={targets:(j.targets||[]),counts:(j.counts||null)};
var c=j.counts||{};var out=$('intake');out.hidden=false;
var lines=[c.unique_sites+' site(s) will be scanned'];
if(c.duplicates)lines.push(c.duplicates+' duplicate line(s) ignored');
if(c.already_analyzed)lines.push(c.already_analyzed+' already in history (will be re-scanned)');
if(c.rejected)lines.push(c.rejected+' line(s) rejected');
var html='<p>'+esc(lines.join(' · '))+'</p>';
if((j.rejected||[]).length){html+='<ul>'+j.rejected.map(function(r){
return '<li><code>'+esc(r.value)+'</code> — '+esc(r.reason)+'</li>';}).join('')+'</ul>';}
out.innerHTML=html;summary();}
function previewText(){J('/api/scout/intake/preview',{text:$('seeds').value||''})
.then(renderIntake).catch(function(e){$('intake').hidden=false;
$('intake').textContent='Could not read those addresses: '+e;});}
function previewFile(){var f=$('listfile').files[0];if(!f)return;
var reader=new FileReader();reader.onload=function(){
var b64=String(reader.result||'').split(',')[1]||'';
J('/api/scout/import',{filename:f.name,content_b64:b64}).then(function(j){
if(!j.ok){$('intake').hidden=false;$('intake').textContent='Could not read that file: '+
(j.error||'unknown error');return;}
var rows=((j.result||{}).rows||[]).map(function(r){return [r.original];});
return J('/api/scout/intake/preview',{rows:rows}).then(renderIntake);})
.catch(function(e){$('intake').hidden=false;
$('intake').textContent='Could not read that file: '+e;});};
reader.readAsDataURL(f);}
function start(){var msg=$('msg');var btn=$('run');
if(!$('approve').checked){msg.textContent='Confirm the bounded read-only run first.';
$('approve').focus();return;}
var n=parseInt($('maxsites').value,10)||10;var s=source();
btn.disabled=true;msg.textContent='Starting Scout…';
if(s==='find'){var o={max_candidates:n};
var c=csv($('countries').value);if(c.length)o.countries=c;
var b=checks('biztype');if(b.length)o.site_types=b;
var k=csv($('keywords').value);if(k.length)o.keywords=k;
J('/api/scout/launch',{approve_live_discovery:true,overrides:o}).then(function(j){
if(j.ok){location.href='/scout/progress?id='+encodeURIComponent(j.campaign_id);}
else{btn.disabled=false;msg.textContent='Scout could not start: '+(j.error||'unknown error');}})
.catch(function(e){btn.disabled=false;msg.textContent='Scout could not start: '+e;});return;}
var seeds=PENDING.targets.map(function(t){return t.url;});
if(!seeds.length){btn.disabled=false;
msg.textContent='No valid website addresses yet — add some and check the preview.';return;}
var key=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+Math.random();
J('/api/campaign/start',{confirm:true,idempotency_key:key,seeds:seeds.slice(0,n),
campaign:'operator-scan',browser_mode:'auto',coverage:'adaptive',max_sites:n})
.then(function(j){if(j.ok||j.run_id){location.href='/scout/run?id='+encodeURIComponent(j.run_id);}
else{btn.disabled=false;msg.textContent='Scout could not start: '+
(j.message||j.error||'unknown error');}})
.catch(function(e){btn.disabled=false;msg.textContent='Scout could not start: '+e;});}
document.querySelectorAll('input[name="source"]').forEach(function(r){
r.addEventListener('change',showPanels);});
$('seeds').addEventListener('change',previewText);
$('seeds').addEventListener('blur',previewText);
$('listfile').addEventListener('change',previewFile);
$('maxsites').addEventListener('change',summary);
$('run').onclick=start;
showPanels();
"""


_START_PANEL_HTML = """<h2>Start a bounded read-only campaign</h2>
<div class="card formstack" style="max-width:640px">
<p>Runs the existing bounded, read-only Scout engine over 1&ndash;10 <strong>public https</strong>
seeds. It never sends email, submits forms, solves CAPTCHAs, or runs commands. Non-public / private
/ loopback targets are rejected.</p>
<p><label>Public seed URLs (one per line):<br>
<textarea id="seeds" rows="4" placeholder="https://example.com/"></textarea></label></p>
<p><label>Campaign name: <input id="campaign" value="adhoc"></label>
&nbsp;<label>Coverage: <select id="coverage">
<option value="adaptive" selected>Adaptive &mdash; max 12 pages</option>
<option value="deep">Deep &mdash; max 20 pages</option></select></label></p>
<p><label>Scan mode: <select id="scanmode">
<option value="playwright" selected>Deep Capture (Playwright)</option>
<option value="static">Static (faster)</option></select></label></p>
<p class="muted">Static = faster HTTP/HTML checks. Deep Capture = real browser: screenshots, axe
accessibility, performance timing, and console/network evidence (needs Chromium installed).
Coverage decides how many same-site pages Scout explores for meaningful, non-duplicate content
&mdash; an upper bound, never a quota; both profiles can stop early once further pages add no new
coverage. This is separate from how many domains a campaign analyzes.</p>
<p><label><input type="checkbox" id="confirm"> I confirm this is an authorized, bounded, read-only scan.</label></p>
<p><button class="btn primary" onclick="startCampaign()">Start campaign</button></p>
<hr>
<h3>Import a curated list (.xlsx / .csv)</h3>
<p class="muted">Upload a spreadsheet with a URL / Website / Domain / &ldquo;Scout seed URL&rdquo; column.
Bounded &amp; read-only: the file is parsed into seed domains (never stored, never executed) and you pick
which to scan &mdash; it runs the same manual Scout, with zero discovery/Tavily calls.</p>
<p><label>Curated list file (.xlsx / .csv): <input type="file" id="impfile" accept=".xlsx,.csv"></label>
&nbsp;<button class="btn" onclick="importList()">Parse file</button></p>
<div id="imppreview" class="scrollx"></div>
</div>"""


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# Neutral placeholder for an absent field on a card — shown, never invented (see _target findings).
_NEUTRAL = "—"  # em dash, matching the other absent-field cells on this page


def _collapse_ws(s: object) -> str:
    """Collapse any run of whitespace (newlines/tabs/spaces) to a single space and trim.

    Keeps a dynamic finding value on one table line. Call BEFORE ``_esc`` (escaping does not remove
    newlines). ``None`` collapses to ``""``."""
    return " ".join(str("" if s is None else s).split())


def _norm_steps(raw: object) -> list:
    """Defensively normalize ``reproduction_steps`` into a clean list of one-line, non-empty strings.

    Missing/``None`` -> ``[]``; a scalar legacy value (e.g. a single string) is treated as ONE step
    (never iterated character-by-character); list/tuple items are newline-collapsed and empties
    dropped. Never invents a step."""
    if raw is None:
        return []
    items = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for it in items:
        s = _collapse_ws(it)
        if s:
            out.append(s)
    return out


def _confidence_label(f: dict) -> str:
    """One-line confidence label for a finding, or the neutral placeholder when absent (never
    invented). Returned RAW (unescaped) — the caller escapes it."""
    return _collapse_ws(f.get("confidence")) or _NEUTRAL


def _repro_hint(f: dict) -> str:
    """One-line reproduction hint: the first concrete step, or the neutral placeholder when there are
    no steps (never invented). Returned RAW (unescaped) — the caller escapes it."""
    steps = _norm_steps(f.get("reproduction_steps"))
    return steps[0] if steps else _NEUTRAL


def _finding_qa_value(f: dict) -> int:
    """Per-finding QA-opportunity contribution, reusing the canonical scorer (no second source of
    truth) so the problems table can be ordered by qa_value_score desc. Imported lazily to keep the
    dashboard import graph acyclic."""
    from core.scout.priority import qa_value_score
    return qa_value_score([f])


# Human-readable within-site coverage profile label (PR-B). "explicit" is the internal/back-compat
# mode (never offered as an operator choice) — shown honestly as "Legacy explicit" rather than hidden.
# One vocabulary for a prospect's outcome on the run-results page. The rows and the summary tiles
# BOTH read it, so a tile and the rows it counts can never call the same state different things, and
# the tiles partition the run by construction — every prospect lands in exactly one category, which
# is what makes the summary exhaustive rather than merely true.
_RUN_STATUS_LABELS = (
    ("DONE", "Completed"),
    ("MANUAL_ACTION_REQUIRED", "Needs your help"),
    ("RESOLVED_BY_MANUAL_CHECK", "Resolved by a manual check"),
    ("FAILED", "Could not complete"),
    ("PENDING", "Queued"),
    ("SKIPPED", "Skipped"),
)


def _run_status_label(status: str) -> str:
    """Human label for a persisted prospect status. An unknown status is titled, never dropped —
    a target must never fall out of the summary just because its status is new."""
    for known, label in _RUN_STATUS_LABELS:
        if status == known:
            return label
    return str(status or "Unknown").replace("_", " ").title()


def _run_prospect_label(prospect: dict) -> str:
    """Human label for one prospect ROW, which needs one fact the bare status cannot carry.

    A target the engine has started stays PENDING in the compact state until it finishes, so status
    alone cannot tell "waiting its turn" from "being analyzed right now" — and calling the second one
    "Queued" is false while a browser is loading it. The engine persists ``started_at`` the moment it
    begins a target, and that is what separates the two.
    """
    p = prospect or {}
    status = str(p.get("status", "") or "")
    if status == "PENDING" and p.get("started_at"):
        return "In progress"
    return _run_status_label(status)


def _run_status_summary(prospects: dict) -> list:
    """(label, count) per outcome present in the run, in the canonical order above, with "In progress"
    kept next to "Queued" and any unknown status appended. The counts sum to len(prospects) — the page
    asserts nothing the data cannot support."""
    counts: dict = {}
    for p in prospects.values():
        counts[_run_prospect_label(p)] = counts.get(_run_prospect_label(p), 0) + 1
    order = []
    for _, label in _RUN_STATUS_LABELS:
        if label == "Queued":
            order.append("In progress")
        order.append(label)
    ordered = [(label, counts.pop(label)) for label in order if label in counts]
    return ordered + sorted(counts.items())


_COVERAGE_PROFILE_LABEL = {"adaptive": "Adaptive", "deep": "Deep", "explicit": "Legacy explicit"}

# Honest, human-readable page-coverage stop reasons (core/scout/coverage.py CoveragePlanner).
_PAGE_STOP_LABEL = {
    "page_ceiling_reached": "Reached the page ceiling for this profile",
    "no_new_meaningful_coverage": "Stopped early — further pages added no new meaningful coverage",
    "links_exhausted": "All discovered same-site links were explored",
    "links_check_disabled": "Link discovery was disabled for this scan",
}

# Honest, human-readable flow-coverage stop reasons (core/scout/engine.py _flow_coverage).
_FLOW_STOP_LABEL = {
    "flow_check_disabled": "Business-flow check was disabled for this scan",
    "single_step_supported": "A flow entry was detected and its one supported step was checked",
    "no_flow_entry_detected": "No flow entry was detected on this page",
}


def _coverage_card_html(coverage: Optional[dict]) -> str:
    """Render the Target page's compact, truthful within-site Coverage card.

    Uses ONLY the persisted exact-prospect ``coverage.json`` record (see ``coverage.py`` /
    ``engine.py``) — never invents a number. A missing record (historical/legacy run, or a run that
    stopped before any page finished, e.g. manual action) shows an honest unavailable state rather
    than a fabricated zero. The page ceiling is always phrased as an "up to" cap, never a quota, and
    the copy never implies it was fully consumed. Multi-step flow support is never overstated: when
    ``flow_steps_supported == 1`` (true today) it is described plainly as single-step coverage."""
    if not coverage:
        return ('<div class="empty muted">Coverage data is not available for this target — this run '
                'predates within-site coverage tracking, or stopped (e.g. manual action / failure) '
                'before any page finished. This is not the same as zero coverage.</div>')
    profile = _COVERAGE_PROFILE_LABEL.get(coverage.get("coverage"), str(coverage.get("coverage") or "—"))
    ceiling = coverage.get("page_ceiling")
    tested = coverage.get("meaningful_pages_tested")
    noise = coverage.get("pages_skipped_noise")
    dup = coverage.get("pages_skipped_near_duplicate")
    stop = str(coverage.get("page_stop_reason") or "")
    stop_label = _PAGE_STOP_LABEL.get(stop, stop or "—")
    html = (f'<p><b>Profile:</b> {_badge(profile)} · '
            f'<b>Page ceiling:</b> up to {_esc(ceiling if ceiling is not None else "—")} pages '
            f'(a cap, never a quota) · <b>Meaningful pages tested:</b> {_esc(tested if tested is not None else "—")}</p>'
            f'<p><b>Skipped as obvious noise:</b> {_esc(noise if noise is not None else "—")} · '
            f'<b>Skipped as near-duplicates:</b> {_esc(dup if dup is not None else "—")}</p>'
            f'<p><b>Stop reason:</b> {_esc(stop_label)}</p>')
    flows_detected = coverage.get("flows_detected")
    if flows_detected is not None:
        supported = coverage.get("flow_steps_supported")
        used = coverage.get("flow_steps_used")
        fstop = str(coverage.get("flow_stop_reason") or "")
        fstop_label = _FLOW_STOP_LABEL.get(fstop, fstop or "—")
        flow_note = ('Single-step flow coverage — multi-step flows are not implemented yet.'
                     if supported == 1 else f'Supports up to {supported} flow step(s).')
        html += (f'<p><b>Flows detected:</b> {_esc(flows_detected)} · '
                f'<b>Flow entries checked:</b> {_esc(coverage.get("flow_entries_checked", "—"))} · '
                f'<b>Flow steps used:</b> {_esc(used if used is not None else "—")}</p>'
                f'<p class="muted">{_esc(flow_note)} {_esc(fstop_label)}.</p>')
    return html


def _problems_table_html(findings: list) -> str:
    """Render the /target "Problems found" table.

    Rows are ordered by qa_value_score desc (stable sort, so equal scores keep input order). Each
    row shows Severity, Confidence, Type, Issue, Business impact, a one-line Repro hint, and
    Evidence. Every dynamic cell is newline-collapsed then HTML-escaped; an absent confidence/repro/
    type shows the neutral placeholder (never invented). When a finding has more than one step, the
    full path is preserved as a hover ``title`` on the repro cell (escaped as an attribute). Returns
    the empty-state card body when there are no findings."""
    if not findings:
        return ('<div class="empty muted">No verified problem items for this target yet. '
                'Run a live, bounded analysis to populate evidence.</div>')
    ordered = sorted(findings, key=_finding_qa_value, reverse=True)
    rows = []
    for f in ordered:
        steps = _norm_steps(f.get("reproduction_steps"))
        hint = steps[0] if steps else _NEUTRAL
        title_attr = f' title="{_esc(" → ".join(steps))}"' if len(steps) > 1 else ""
        evid = ", ".join(_collapse_ws(r) for r in (f.get("evidence_refs") or []) if _collapse_ws(r))
        # Informational vs actionable: the SAME rule the engine uses to compute verified_defects
        # (severity == "info" is informational, everything else counts as an actionable defect) —
        # so the per-target table never contradicts the run-results totals.
        is_info = str(f.get("severity") or "").strip().lower() == "info"
        kind_label = "Informational" if is_info else "Defect"
        rows.append(
            "<tr>"
            f'<td data-label="Severity">{_badge(_collapse_ws(f.get("severity")) or _NEUTRAL, _sev_badge_kind(f.get("severity") or ""))}</td>'
            f'<td data-label="Kind" class="muted">{_esc(kind_label)}</td>'
            f'<td data-label="Confidence" class="muted">{_esc(_confidence_label(f))}</td>'
            f'<td data-label="Type" class="muted">{_esc(_collapse_ws(f.get("category")) or _NEUTRAL)}</td>'
            f'<td data-label="Issue">{_esc(_collapse_ws(f.get("title")) or _NEUTRAL)}</td>'
            f'<td data-label="Business impact" class="muted">{_esc(_collapse_ws(f.get("business_impact")) or "")}</td>'
            f'<td data-label="Repro hint" class="muted"{title_attr}>{_esc(hint)}</td>'
            f'<td data-label="Evidence" class="muted">{_esc(evid or _NEUTRAL)}</td>'
            "</tr>")
    return (f'<table class="responsive-table"><caption>Problem items ({len(findings)})</caption>'
            '<thead><tr><th>Severity</th><th>Kind</th><th>Confidence</th><th>Type</th><th>Issue</th>'
            '<th>Business impact</th><th>Repro hint</th><th>Evidence</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def _client_work_brief(domain: str, findings: list) -> str:
    """Build the analyze-job brief for a linked prospect from its domain + Scout findings (this is a
    proposal/preparation step — it does not imply the prospect is Won)."""
    lines = [f"Client QA engagement for {domain} (sourced via Scout prospecting).", "",
             "A bounded, public, read-only QA scan surfaced these issues to investigate, reproduce, "
             "and (if the client wants) fix:"]
    if findings:
        for f in findings[:12]:
            sev = str(f.get("severity", "")).upper()
            row = f"- [{sev}] {f.get('category', '')}: {f.get('title', '')}"
            impact = f.get("business_impact", "")
            lines.append(row + (f" — {impact}" if impact else ""))
    else:
        lines.append("- (no public findings captured yet; start with a deeper bounded QA audit)")
    from core.scout.outreach.fixability import classify_fixability
    fx = classify_fixability(findings or [], access_available=False)
    lines += ["", "Requested scope: a deeper QA audit of the key user journeys with reproducible "
              "evidence, severity, and a prioritized fix list. Access (repo / staging / credentials) "
              "to be provided by the client.",
              "", f"Stage-3 (optional paid fix) scoping: {fx['summary']}"]
    return "\n".join(lines)


def _scout_details_cell(run_id: str, pid: str, prospect: dict) -> str:
    """Details cell for a run prospect row: the PRIMARY link is the human-readable exact-run Target
    (never raw JSON), with a separate secondary 'View raw JSON' diagnostic to the technical API."""
    from core.scout.discovery.domain_intel import canonical_domain
    dom = canonical_domain(prospect.get("url", "") or prospect.get("final_url", "")) or ""
    if run_id and dom:
        primary = (f'<a href="/scout/target?run={_esc(run_id)}&domain={_esc(dom)}">Details</a>')
    else:
        primary = '<span class="muted">—</span>'
    # Raw JSON is EXACT-run scoped when a run is known, so a diagnostic opened from a historical run
    # reads that run's confined store — never the active/attached run.
    raw = (f'/api/prospect?run={_esc(run_id)}&id={_esc(pid)}' if run_id
           else f'/api/prospect?id={_esc(pid)}')
    return f'{primary} · <a href="{raw}">View raw JSON</a>'


def _scout_details_primary(run_id: str, prospect: dict) -> str:
    from core.scout.discovery.domain_intel import canonical_domain
    dom = canonical_domain(prospect.get("url", "") or prospect.get("final_url", "")) or ""
    if not run_id or not dom:
        return '<span class="muted">—</span>'
    return f'<a href="/scout/target?run={_esc(run_id)}&domain={_esc(dom)}">Details</a>'


def _prospect_status_label(status: str) -> str:
    return {
        "DONE": "Completed",
        "MANUAL_ACTION_REQUIRED": "Needs your help",
        "FAILED": "Could not complete",
        "PENDING": "Queued",
        "RUNNING": "In progress",
        "SKIPPED": "Skipped",
        "COMPLETED": "Completed",
        "CANCELLED": "Stopped",
        "KILLED": "Cancelled",
    }.get(str(status or "").strip().upper(), str(status or "Unknown").replace("_", " ").title())


def _looks_blocked(status: str, reason: str) -> bool:
    """True when a target looks blocked by an access challenge (CAPTCHA / bot wall / 403 / login),
    so the card shows the honest banner + human-in-the-loop rescan button."""
    s = (str(status) + " " + str(reason)).lower()
    return any(k in s for k in ("challenge", "captcha", "blocked", "bot", "403", "forbidden",
                                "rate limit", "access denied", "login wall", "not authorized"))


def _manual_reason_label(reason: str) -> str:
    return {
        "captcha_detected": "Human verification requested",
        "access_prohibited": "Automated access blocked",
        "403": "Access blocked (HTTP 403)",
    }.get(str(reason or "").strip().lower(), str(reason or "Reason unavailable").replace("_", " "))


def _analysis_status_label(status: str) -> str:
    return {
        "analyzed": "Analyzed",
        "analyzing": "In progress",
        "discovered": "Ready to analyze",
        "failed": "Could not complete",
        "skipped": "Skipped",
        "rejected": "Not eligible",
    }.get(str(status or "").strip().lower(), str(status or "Unknown").replace("_", " ").title())


def _activity_label(action: str) -> str:
    key = str(action or "").strip()
    return {
        "campaign_started": "Campaign started",
        "campaign_finished": "Campaign finished",
        "promoted_to_scout": "Target promoted to Scout",
        "actionable_target_reached": "Actionable target goal reached",
        "budget_stop": "Campaign budget reached",
        "run_started": "Scout run started",
        "prospect_started": "Target analysis started",
        "prospect_done": "Target analysis completed",
        "manual_action_required": "Target needs manual help",
        "prospect_skipped_by_operator": "Queued target skipped",
        "run_finished": "Scout run finished",
    }.get(key, key.replace("_", " ").replace("->", "→").strip().title())


def _challenge_state_label(state: str) -> str:
    return {
        "opening": "Opening browser",
        "waiting": "Waiting for you",
        "continuing": "Checking again",
        "defer_requested": "Deferring",
        "skip_requested": "Skipping",
        "completed": "Completed",
        "deferred": "Deferred",
        "skipped": "Skipped",
        "failed": "Failed",
        "timed_out": "Timed out",
    }.get(str(state or "").strip().lower(), str(state or "Unknown").replace("_", " ").title())


# --- v3.1 design system (local CSS tokens; no external assets) ---------------------------------
_TOKENS_CSS = """
/* Pro Dark design system (dark is the first-run default; Light is an explicit override). Semantic
   tokens; gold accent used sparingly for primary actions, selected nav, active tabs, and focus. */
:root{
 --bg:#0A0F1E; --surface:#151922; --surface-2:#1A2236; --elevated:#1A2236; --border:#1F2940;
 --input:#151922; --text:#F4EDD9; --muted:#9AA3B8; --link:#7FB0FF; --badge-bg:#1A2236;
 --primary:#D4AF37; --primary-ink:#0A0F1E; --accent:#D4AF37; --focus:#D4AF37;
 --ok:#3FB950; --success:#3FB950; --attention:#E3B341; --warning:#E3B341;
 --danger:#EF5757; --error:#EF5757; --information:#58A6FF; --disabled:#5A6373; --code:#0E1424;
 --radius:8px; --pad:16px; --gap:12px; --maxw:1200px; --row:40px;
 --font:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
}
:root[data-theme="light"]{
 --bg:#F4EDD9; --surface:#FBF7EC; --surface-2:#EBE3CE; --elevated:#FFFFFF; --border:#E2DAC6;
 --input:#FFFFFF; --text:#151922; --muted:#5B6470; --link:#0B5FBF; --badge-bg:#EBE3CE;
 --primary:#0A0F1E; --primary-ink:#F4EDD9; --accent:#9A7B1E; --focus:#9A7B1E;
 --ok:#1A7F37; --success:#1A7F37; --attention:#8A5A00; --warning:#8A5A00;
 --danger:#B42318; --error:#B42318; --information:#0B5FBF; --disabled:#9AA3B0; --code:#EEE7D6;
}
:root[data-density="compact"]{ --pad:10px; --gap:8px; --row:32px; }
*{box-sizing:border-box}
body{font-family:var(--font);margin:0;background:var(--bg);color:var(--text);line-height:1.5}
a{color:var(--link);text-decoration:none} a:hover{text-decoration:underline}
/* A link sitting inside a sentence must be distinguishable without colour (WCAG 1.4.1) — our own
   axe run flags exactly this, and we sell those findings. Links that are already distinguishable by
   shape (nav, chips, buttons, tabs) are excluded: underlining them would be noise, not information. */
main p a,main li a,main td a,.quiet-state a,.muted a,figcaption a{text-decoration:underline;text-underline-offset:2px}
main p a.btn,main p a.chip,main li a.btn,main li a.chip,main td a.chip,main td a.btn{text-decoration:none}
/* An in-page action that should read as a link but behave (and be announced) as a button. */
.linklike{background:none;border:0;padding:0;font:inherit;color:var(--link);cursor:pointer}
.linklike:hover{text-decoration:underline}
header.top{background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5}
header.top .wrap{max-width:var(--maxw);margin:0 auto;display:flex;align-items:center;gap:var(--gap);padding:10px var(--pad)}
header.top .brand{font-weight:700} header.top nav{display:flex;gap:4px;margin-left:8px}
header.top nav a{padding:6px 12px;border-radius:6px;color:var(--muted)}
header.top nav a[aria-current="page"]{background:var(--surface-2);color:var(--text);font-weight:600;box-shadow:inset 0 -2px 0 var(--accent)}
header.top .brand{color:var(--text)} header.top .brand::before{content:"";display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--accent);margin-right:7px;vertical-align:middle}
main{max-width:var(--maxw);margin:0 auto;padding:var(--pad)}
html,body{max-width:100%;overflow-x:hidden}
header.top .wrap{flex-wrap:wrap} header.top nav{flex-wrap:wrap}
/* A flex item will not shrink below its content width unless told to, so a wide nav pushed the
   theme button past the header's right padding and body overflow-x:hidden then clipped it. */
header.top nav{flex:1 1 auto;min-width:0}
header.top .theme-toggle{flex:0 0 auto}
/* A dropdown is a list. Its links are inline by default and had no rule to stack them, so the
   items flowed as a paragraph and wrapped mid-list once there were five of them. */
.nav-menu{display:flex;flex-direction:column;gap:2px;padding:6px}
.nav-menu a{display:block;padding:7px 10px;border-radius:6px;color:var(--text);white-space:nowrap}
.nav-menu a:hover{background:var(--surface-2)}
.nav-menu a[aria-current="page"]{background:var(--surface-2);font-weight:600}
/* "Nothing is happening" is a line, not a panel: as a card it competed with the blocks that DID
   have something in them, and several of them on one screen taught the eye to skip that region. */
.quiet-state{margin:.2rem 0 1rem;color:var(--muted);padding:10px 12px;border:1px solid var(--border);
border-radius:var(--radius);background:var(--surface)}
.quiet-state strong{color:var(--text)}
.quiet-state.attention{border-color:var(--attention)}
.scout-actions{margin:.2rem 0 .8rem;flex-wrap:wrap}
.attempt-history{margin:.4rem 0 0;padding-left:1.1rem;font-size:13px}
.inline-filter>summary{cursor:pointer;color:var(--muted);padding:6px 10px;border:1px solid var(--border);border-radius:6px;list-style:none}
.inline-filter[open]>summary{color:var(--text)}
.inline-filter[open]{flex-basis:100%}
.result-why{font-size:12px;margin-top:3px;max-width:34ch}
/* An evidence state carries its reason ("Not captured: no safe interaction reproduced cleanly"),
   which is a sentence, not a word. Badges are nowrap by default, so these overflowed their cell and
   collided with the next one — visible only in a screenshot, never in an HTTP assertion. */
.evidence-item .badge{white-space:normal;display:inline-block;max-width:100%;line-height:1.35}
.evidence-item{min-width:0;overflow-wrap:anywhere}
.scrollx{overflow-x:auto;max-width:100%;margin-bottom:var(--gap)}
h1{font-size:22px;margin:.2rem 0 1rem} h2{font-size:16px;margin:1.4rem 0 .6rem}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:var(--pad);margin-bottom:var(--gap)}
.banner{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius);
 padding:10px 12px;margin-bottom:var(--gap)}.banner.warn{border-color:var(--attention)}
.muted{color:var(--muted)} .row{display:flex;gap:var(--gap);flex-wrap:wrap;align-items:center}
table{border-collapse:collapse;width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)}
caption{text-align:left;color:var(--muted);padding:6px 2px;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);font-size:13px;height:var(--row)}
th{background:var(--surface-2);color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--border);background:var(--badge-bg);color:var(--muted);white-space:nowrap}
/* Visible only to assistive tech: gives a repeated control ("Open") a unique accessible name. */
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
 clip:rect(0 0 0 0);white-space:nowrap;border:0}
.attention-project{font-weight:600}
/* Names the scope a tile counts, so its number is never read as covering the whole product. */
.tile-note{display:block;font-size:11px;color:var(--muted)}
.badge.ok{color:var(--ok)} .badge.attention{color:var(--attention)}
.badge.blocked,.badge.danger{color:var(--error)} .badge.done{color:var(--muted)}
.btn{display:inline-block;padding:8px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:14px}
.btn.primary{background:var(--primary);border-color:var(--primary);color:var(--primary-ink);font-weight:600}
.btn.danger{border-color:var(--error);color:var(--error)}
.btn[aria-pressed="true"],.nav-more[aria-current="page"]{border-color:var(--accent);
 box-shadow:inset 0 -2px 0 var(--accent)}
.btn:disabled{opacity:.55;cursor:not-allowed}
.btn:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.chip{display:inline-flex;gap:6px;align-items:center;padding:2px 10px;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:999px;font-size:12px}
/* Accessibility hotfix: chip-styled BUTTONS did not inherit a text colour (buttons don't inherit
   `color`), so action buttons showed dark default text on the dark surface. Give every chip button a
   contrasting text colour + clear hover/focus/active/disabled + semantic primary/danger variants.
   Palette unchanged (uses existing tokens; text-on-surface and ink-on-accent are WCAG-AA). */
button.chip,a.chip{color:var(--text);background:var(--surface-2)}
button.chip:hover,a.chip:hover{background:var(--surface);border-color:var(--muted);text-decoration:none}
button.chip:active{transform:translateY(1px)}
button.chip:focus-visible,a.chip:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
button.chip:disabled,button.chip[disabled],a.chip[aria-disabled="true"]{opacity:.5;cursor:not-allowed;background:var(--bg);color:var(--muted);border-style:dashed;pointer-events:none}
.chip.primary,button.chip.primary{background:var(--primary);color:var(--primary-ink);border-color:var(--primary);font-weight:600}
button.chip.primary:hover{background:var(--primary);filter:brightness(1.08)}
.chip.danger,button.chip.danger{background:var(--surface-2);color:var(--error);border-color:var(--error)}
button.chip.danger:hover{background:var(--error);color:var(--primary-ink)}
.empty{padding:2rem;text-align:center;color:var(--muted)}
.empty.compact{padding:18px 20px}.empty.compact strong{display:block;color:var(--text);
 margin-bottom:3px}.empty.compact p{margin:12px 0 0}
.empty-actions{justify-content:center}
input,select,textarea{padding:6px 8px;border:1px solid var(--border);border-radius:6px;font-size:14px;background:var(--input);color:var(--text);font-family:inherit;max-width:100%}
textarea{width:100%;resize:vertical}
input[type=checkbox]{accent-color:var(--accent);width:auto;vertical-align:middle}
::placeholder{color:var(--muted);opacity:1}
textarea:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
pre,code{background:var(--code);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
pre{padding:.7rem;border-radius:6px;overflow:auto;white-space:pre-wrap;font-size:12px;border:1px solid var(--border)}
code{padding:1px 5px;border-radius:4px;font-size:12px}
details>summary{cursor:pointer;color:var(--muted)}
.skeleton{background:var(--surface-2);border-radius:6px;height:14px}
.theme-toggle{margin-left:auto;background:none;border:1px solid var(--border);color:var(--muted);border-radius:6px;padding:6px 10px;cursor:pointer;font-size:13px}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin:1rem 0 0;flex-wrap:wrap}
.tabs [role=tab]{padding:8px 14px;border:1px solid transparent;border-bottom:none;background:none;cursor:pointer;color:var(--muted);border-radius:6px 6px 0 0;font-size:14px}
.tabs [role=tab][aria-selected=true]{background:var(--surface);border-color:var(--border);color:var(--text);font-weight:600;margin-bottom:-1px;box-shadow:inset 0 -2px 0 var(--accent)}
[role=tabpanel]{padding-top:.8rem} [role=tabpanel][hidden]{display:none}
.copyok{color:var(--ok)}
.only-mobile{display:none}
.cards{list-style:none;margin:0;padding:0} .cards li{margin-bottom:var(--gap)}
.cards .card h3{font-size:15px;margin:0 0 .3rem} .cards .meta{font-size:12px}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--gap)}
/* On a phone two 150px tiles fit but leave a lone half-width orphan on the next row; one full
   column reads better than a ragged grid. */
@media (max-width:420px){.summary-grid{grid-template-columns:1fr}}
.retention-grid,.help-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
 gap:var(--gap)}
.help-grid .card{margin-bottom:0}.help-grid h2{margin-top:0}
.summary-item{background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:10px}
.summary-item strong{display:block;font-size:20px;line-height:1.2;margin-top:3px}
.overview-summary{margin-bottom:8px}.overview-summary .summary-item{color:var(--text)}
.overview-summary .summary-item:hover{border-color:var(--muted);text-decoration:none}
.compact-details{margin-top:20px;padding:10px 12px}
.work-filter-bar{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--gap);
 flex-wrap:wrap;margin-bottom:8px}
.work-primary-views{display:flex;gap:7px;flex-wrap:wrap}
.work-primary-views .chip[aria-current="page"]{border-color:var(--accent);color:var(--text);
 box-shadow:inset 0 -2px 0 var(--accent);font-weight:600}
.work-status-filter{display:flex;align-items:flex-end;gap:7px;flex-wrap:wrap}
.work-status-filter label{display:block;color:var(--muted);font-size:12px;font-weight:600}
.work-status-filter select{display:block;min-width:170px;margin-top:3px}
.work-status-filter .btn{padding:6px 12px}
.work-view-options{margin:4px 0 var(--gap)}
.work-view-options p{margin-bottom:10px}
.work-intake{margin-top:var(--gap)}
.work-intake>summary{font-weight:600;color:var(--text)}
.work-intake[open]>summary{margin-bottom:8px}
.work-intake-intro{max-width:720px;margin:0 0 16px}
.work-intake-grid{display:grid;grid-template-columns:minmax(140px,190px) minmax(0,1fr);
 gap:7px 14px;max-width:820px;align-items:start}
.work-intake-grid label{font-size:13px;font-weight:600;padding-top:7px}
.work-intake-grid input,.work-intake-grid select{width:100%;max-width:440px}
.work-intake-grid textarea{max-width:100%}
.work-intake-grid .field-help{grid-column:2;margin:-2px 0 7px;max-width:620px}
.work-intake-actions{margin-top:14px}
.form-error{max-width:820px;margin-top:12px;padding:10px 12px;border:1px solid var(--error);
 border-radius:6px;background:var(--surface-2);color:var(--error);font-size:13px}
[aria-invalid="true"]{border-color:var(--error)!important}
.evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:var(--gap)}
.evidence-item{border:1px solid var(--border);border-radius:6px;padding:10px;min-width:0}
.evidence-item h3{font-size:14px;margin:0 0 4px}
.advanced{border:1px solid var(--border);border-radius:6px;padding:10px 12px;
 background:var(--surface-2)}.advanced>summary{font-weight:600;color:var(--text)}
.toast{position:fixed;right:16px;bottom:16px;z-index:30;max-width:min(420px,calc(100vw - 32px));
 background:var(--elevated);border:1px solid var(--attention);border-radius:var(--radius);
 padding:12px 14px;box-shadow:0 12px 32px #0008}
dialog{width:min(520px,calc(100vw - 32px));background:var(--elevated);color:var(--text);
 border:1px solid var(--border);border-radius:var(--radius);padding:var(--pad)}
dialog::backdrop{background:#000a}dialog h2{margin-top:0}
[hidden]{display:none!important}
.bulkbar{position:sticky;bottom:10px;z-index:4;border-color:var(--accent);box-shadow:0 8px 24px #0008}
.status-hero{border-left:4px solid var(--ok)}.status-hero.attention{border-left-color:var(--attention)}
.status-hero.blocked{border-left-color:var(--error)}
.media-grid{display:flex;gap:8px;flex-wrap:wrap}.media-grid img{display:block;max-width:280px;
 max-height:200px;border:1px solid var(--border);border-radius:6px}
.responsive-table td[data-label]::before{display:none}
@media (max-width:640px){ .only-desktop{display:none} .only-mobile{display:block} }
/* Campaign form: stack each field (label above a full-width control); checkboxes stay inline. */
.formstack label{display:block;margin:0 0 14px;color:var(--text);font-weight:600;font-size:13px}
/* Full width is right for a text field and wrong for a radio: inside an option tile the radio
   filled the whole tile and pushed its label out past the border into the next choice. */
.formstack label>select,.formstack label>input:not([type=checkbox]):not([type=radio]){display:block;width:100%;
  max-width:440px;margin-top:5px;font-weight:400}
.formstack label>select[multiple]{max-width:100%}
.formstack>label:has(>input[type=checkbox]){font-weight:400;color:var(--muted)}
.formstack details>summary{margin:2px 0}
.formstack details[open]>summary{margin-bottom:10px}
.page-intro{max-width:720px;margin:-6px 0 14px}
.campaign-card{max-width:900px;margin-top:12px}.campaign-card>h2{margin-top:0}
.field-help{max-width:620px;margin:-9px 0 14px;color:var(--muted);font-size:12px;line-height:1.45}
.option-field{border:0;padding:0;margin:0 0 14px;min-width:0}
.option-field legend{padding:0;margin:0 0 7px;color:var(--text);font-weight:600;font-size:13px}
.option-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
 gap:7px;max-width:720px}
.option-field .field-help{margin:8px 0 0}
.formstack .option-tile{display:flex;align-items:center;gap:8px;margin:0;padding:8px 10px;
 border:1px solid var(--border);border-radius:6px;background:var(--input);font-weight:400;
 font-size:13px;cursor:pointer}
.formstack .option-tile:has(input:checked){border-color:var(--accent);
 background:var(--surface-2);color:var(--text)}
.formstack .option-tile input{margin:0;flex:0 0 auto;width:auto;display:inline-block}
.formstack .option-tile>span{flex:1 1 auto;min-width:0}
.campaign-advanced{max-width:720px;margin:6px 0 16px}
.advanced-intro{margin:0 0 14px}
.advanced-section{padding:14px 0;border-top:1px solid var(--border)}
.advanced-section:first-of-type{padding-top:4px;border-top:0}
.advanced-section h3{margin:0 0 10px;font-size:14px}
.advanced-section:last-of-type{padding-bottom:4px}
.compact-options .option-grid{grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.section-help{margin:-5px 0 12px}
.limit-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.formstack .limit-grid label{margin:0}
.formstack .limit-grid label>input{max-width:100%}
.limit-grid small{display:block;margin-top:4px;color:var(--muted);font-size:11px;
 font-weight:400;line-height:1.35}
.label-note{color:var(--muted);font-weight:400}
.readiness-output{margin-top:10px;padding:10px 12px;border:1px solid var(--border);
 border-radius:6px;background:var(--code);color:var(--text);white-space:pre-line;font-size:12px}
.formstack .feature-choice,.formstack .approval-choice{display:flex;align-items:flex-start;
 gap:9px;max-width:720px;margin:4px 0 16px;padding:10px 12px;border:1px solid var(--border);
 border-radius:6px;background:var(--surface-2);color:var(--text)}
.feature-choice input,.approval-choice input{margin-top:4px}
.feature-choice span,.approval-choice span{display:block}.feature-choice strong,
.approval-choice strong{display:block;font-weight:600}.feature-choice small,
.approval-choice small{display:block;margin-top:2px;color:var(--muted);font-size:12px}
.safety-note{max-width:720px;margin-top:16px}.safety-note p{margin:3px 0 0;color:var(--muted);
 font-size:13px}.campaign-actions{min-height:38px}.campaign-actions button.chip{min-height:38px;
 padding:7px 16px;font-size:13px}
/* Comfortable tap targets for chip-styled buttons/links (labels/badges stay compact). */
button.chip,a.chip{min-height:30px;cursor:pointer}
@media (max-width:640px){
  button.chip,a.chip{min-height:44px;padding:8px 16px;font-size:13px}
  input,select,textarea{font-size:16px}   /* >=16px avoids iOS focus zoom */
  h1{font-size:20px}
  .responsive-table,.responsive-table tbody,.responsive-table tr,.responsive-table td{display:block;width:100%}
  .responsive-table caption{display:block;width:100%}
  .responsive-table thead{display:none}
  .responsive-table tr{border-bottom:1px solid var(--border);padding:8px}
  .responsive-table td{border:0;height:auto;padding:5px 4px;overflow-wrap:anywhere}
  .responsive-table td[data-label]::before{display:block;content:attr(data-label);
    color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase}
  .responsive-table td.select-cell{display:flex;gap:8px;align-items:center}
  .responsive-table td.select-cell::before{display:none}
  .media-grid img,.media-grid video{max-width:100%!important;height:auto}
  .bulkbar{bottom:4px}
  .option-grid{grid-template-columns:1fr}
  .limit-grid{grid-template-columns:1fr}
  .work-filter-bar{align-items:stretch}
  .work-primary-views{width:100%}
  .work-primary-views .chip{flex:1 1 calc(50% - 7px);justify-content:center}
  .work-status-filter{width:100%}.work-status-filter label{flex:1 1 100%}
  .work-status-filter select{min-width:0;width:100%}
  .work-intake-grid{grid-template-columns:1fr;gap:5px}
  .work-intake-grid label{padding-top:5px}
  .work-intake-grid .field-help{grid-column:1;margin:-1px 0 7px}
}
"""

# Legacy run-bound Scout pages predate the Pro Dark shell and hardcode light colours (#ccc/#f4f4f4/
# #eef). Rather than a risky rewrite of each, we inject the shared tokens + control theming AFTER the
# page's own <style> (so it wins) and honour the persisted theme. Layout is preserved (no redesign):
# only colours, borders, code blocks, and form controls are themed so nothing is default-white in Dark.
_LEGACY_THEME_CSS = """
:root{--l-bg:#0A0F1E;--l-surface:#151922;--l-surface2:#1A2236;--l-border:#1F2940;--l-text:#F4EDD9;
 --l-muted:#9AA3B8;--l-link:#7FB0FF;--l-code:#0E1424;--l-primary:#D4AF37;--l-primary-ink:#0A0F1E;
 --l-danger:#EF5757;--l-ok:#3FB950;}
:root[data-theme="light"]{--l-bg:#F4EDD9;--l-surface:#FBF7EC;--l-surface2:#EBE3CE;--l-border:#E2DAC6;
 --l-text:#151922;--l-muted:#5B6470;--l-link:#0B5FBF;--l-code:#EEE7D6;--l-primary:#0A0F1E;
 --l-primary-ink:#F4EDD9;--l-danger:#B42318;--l-ok:#1A7F37;}
body{background:var(--l-bg);color:var(--l-text)}
a{color:var(--l-link)}
table{background:var(--l-surface)}
td,th{border-color:var(--l-border) !important;color:var(--l-text)}
th{background:var(--l-surface2)}
code,pre{background:var(--l-code) !important;color:var(--l-text)}
.mode{background:var(--l-surface2) !important;color:var(--l-text)}
/* Theme-aware status colours (accessible contrast on both surfaces) replacing hardcoded #a00/#070. */
.danger-ctl{color:var(--l-danger) !important}
.ok-ctl{color:var(--l-ok) !important}
.banner{background:var(--l-surface2) !important;border-color:var(--l-border) !important;
 color:var(--l-text) !important}
button,input,select,textarea{background:var(--l-surface);color:var(--l-text);
 border:1px solid var(--l-border);border-radius:6px;padding:.4rem .6rem;font:inherit}
input[type=checkbox]{accent-color:var(--l-primary);width:auto;padding:0}
button{cursor:pointer}
::placeholder{color:var(--l-muted)}
button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,
a:focus-visible{outline:3px solid var(--l-primary);outline-offset:2px}
/* Responsive: legacy pages predate mobile layout. Keep wide tables scrollable within the viewport
   (never forcing page overflow) and tighten the body margin on small screens. */
html,body{max-width:100%;overflow-x:hidden}
table{display:block;overflow-x:auto;max-width:100%}
input,textarea,select{max-width:100%}
@media (max-width:640px){body{margin:1rem}}
"""


def _theme_legacy(html: str) -> str:
    """Inject the shared theme into a legacy page (one that is not built by the Pro Dark ``_page``
    shell), so its controls are never default-white in Dark mode. Idempotent + safe: only touches
    pages without the shared header and with a </head> to inject before."""
    if 'header class="top"' in html or "</head>" not in html or "data-theme" in html:
        return html
    inject = (f'<script>{_THEME_HEAD_JS}</script><style>{_LEGACY_THEME_CSS}</style>'
              '<meta name="viewport" content="width=device-width, initial-scale=1">')
    return html.replace("</head>", inject + "</head>", 1)


# "Scout" is the adaptive Discover Prospects workflow; the legacy seed scanner stays at /scout
# (relabelled "Manual URL Scan"). The nav highlights Scout for any /scout* page.
_NAV = (("Overview", "/"), ("Scout", "/scout/new"), ("Work", "/work"))
_MORE = (("Activity", "/activity"), ("Data management", "/data"),
         ("Collaboration", "/collab"), ("Settings", "/settings"), ("Help", "/docs"))


def _nav_html(active: str) -> str:
    links = []
    for label, href in _NAV:
        is_cur = (href == active) or (href.startswith("/scout") and active.startswith("/scout"))
        cur = ' aria-current="page"' if is_cur else ""
        links.append(f'<a href="{href}"{cur}>{label}</a>')
    more_current = active in {h for _, h in _MORE}
    more = "".join(
        f'<a href="{h}"{" aria-current=\"page\"" if h == active else ""}>{lbl}</a>'
        for lbl, h in _MORE)
    more_cur = ' aria-current="page"' if more_current else ""
    toggle = ('<button type="button" class="theme-toggle" onclick="toggleTheme()" '
              'aria-label="Switch to light theme" title="Switch to light theme">'
              '<span id="themelabel">Light theme</span></button>')
    return (f'<header class="top"><div class="wrap"><span class="brand">AI QA Factory</span>'
            f'<nav aria-label="Primary">{"".join(links)}'
            f'<details style="position:relative"><summary class="btn nav-more" '
            f'style="padding:6px 12px"{more_cur}>More</summary>'
            f'<div class="card nav-menu" style="position:absolute;right:0;min-width:180px;'
            f'z-index:10">{more}</div>'
            f'</details></nav>{toggle}</div></header>')


# No-flash: set the theme from the app-specific local key BEFORE first paint (dark is the default).
# The theme lives only in localStorage - never in project state and never sent to the backend.
_THEME_HEAD_JS = ("(function(){try{var t=localStorage.getItem('aiqa_theme')||'dark';"
                  "document.documentElement.setAttribute('data-theme',t);}catch(e){"
                  "document.documentElement.setAttribute('data-theme','dark');}})();")
_THEME_TOGGLE_JS = ("function _applyThemeLabel(){var t=document.documentElement."
                    "getAttribute('data-theme')||'dark';var l=document.getElementById('themelabel');"
                    "var b=l&&l.closest('button');var next=t==='light'?'dark':'light';"
                    "if(l)l.textContent=next.charAt(0).toUpperCase()+next.slice(1)+' theme';"
                    "if(b){b.setAttribute('aria-label','Switch to '+next+' theme');"
                    "b.setAttribute('title','Switch to '+next+' theme');}}"
                    "function toggleTheme(){var cur=document.documentElement.getAttribute('data-theme')"
                    "==='light'?'light':'dark';var next=cur==='light'?'dark':'light';"
                    "document.documentElement.setAttribute('data-theme',next);"
                    "try{localStorage.setItem('aiqa_theme',next);}catch(e){}_applyThemeLabel();}"
                    "_applyThemeLabel();")

_PAGE_UI_HTML = (
    '<div id="qa-toast" class="toast" role="status" aria-live="polite" '
    'aria-atomic="true" hidden></div>'
    '<dialog id="qa-confirm"><form method="dialog"><h2 id="qa-confirm-title">Confirm action</h2>'
    '<p id="qa-confirm-message"></p><label id="qa-confirm-input-wrap" hidden>'
    'Type the exact value to continue<input id="qa-confirm-input" autocomplete="off"></label>'
    '<div class="row" style="margin-top:16px"><button class="btn" value="cancel">Cancel</button>'
    '<button id="qa-confirm-submit" class="btn danger" value="confirm">Confirm</button></div>'
    '</form></dialog>')
_PAGE_UI_JS = (
    "var _qaToastTimer=null;"
    "function qaNotify(message){var t=document.getElementById('qa-toast');if(!t)return;"
    "t.textContent=String(message||'Something went wrong');t.hidden=false;"
    "if(_qaToastTimer)clearTimeout(_qaToastTimer);"
    "_qaToastTimer=setTimeout(function(){t.hidden=true;},6500);}"
    "window.alert=function(message){qaNotify(message);};"
    "function qaConfirm(message,label,expected){return new Promise(function(resolve){"
    "var d=document.getElementById('qa-confirm'),m=document.getElementById('qa-confirm-message'),"
    "w=document.getElementById('qa-confirm-input-wrap'),i=document.getElementById('qa-confirm-input'),"
    "b=document.getElementById('qa-confirm-submit');"
    "if(!d||typeof d.showModal!=='function'){resolve(window.confirm(message));return;}"
    "m.textContent=message;b.textContent=label||'Confirm';i.value='';"
    "w.hidden=!expected;b.onclick=function(e){if(expected&&i.value!==expected){e.preventDefault();"
    "qaNotify('The value does not match.');i.focus();}};"
    "d.onclose=function(){resolve(d.returnValue==='confirm'&&(!expected||i.value===expected));};"
    "d.showModal();if(expected)i.focus();});}")


def _system_ready_html(output_dir: str, diagnostics_hidden: int = 0) -> str:
    """One line on Overview: is anything about this installation stopping work right now?

    Deliberately built only from facts that are already cached or cost a single stat call. Overview
    is the page an operator lands on constantly, so a readiness check that launched Chromium or
    shelled out to git would tax every visit for information that is almost always "fine".

    When everything is fine it stays a line. When something is wrong it says which thing and links
    to the detail — the operator should never have to open a fold to discover they must restart.
    """
    problems = []
    try:
        from core.build_identity import current_identity
        if current_identity().get("restart_required"):
            problems.append("executable code changed since this process started")
    except Exception:      # noqa: BLE001 - a readiness line must never be the thing that 500s
        pass
    try:
        probe = Path(output_dir) / ".write-probe"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        problems.append("the evidence directory is not writable")
    note = (f' &middot; <span class="muted">{diagnostics_hidden} diagnostic record(s) are hidden '
            f'from production counts.</span>' if diagnostics_hidden else '')
    if problems:
        return (f'<p id="system-ready" class="quiet-state attention">'
                f'<strong>System needs attention</strong> &mdash; {_esc("; ".join(problems))}. '
                f'<a href="/settings#runtime">Open system details</a>.{note}</p>')
    return (f'<p id="system-ready" class="quiet-state"><strong>System ready</strong> '
            f'<span class="muted">&mdash; runtime up to date, evidence directory writable.</span> '
            f'<a href="/settings#runtime">System details</a>{note}</p>')


def _runtime_block_html(force_open: bool = False) -> str:
    """Runtime detail — what code this process is actually serving.

    A Dashboard started from a working tree can quietly outlive the code it loaded, and a commit SHA
    cannot reveal it: an uncommitted edit never moves HEAD. So this reports the fingerprint verdict
    over executable code (``main.py`` + ``core/``), and never calls a process started from a dirty
    tree a clean commit. Docs, outputs, evidence and tests are outside that fingerprint by design —
    editing them changes nothing this process is running.

    Restarting is deliberately NOT offered here: process control stays outside the HTTP surface.
    """
    try:
        from core.build_identity import current_identity
        ident = current_identity()
    except Exception:
        return ""
    restart = bool(ident.get("restart_required"))
    dirty = ident.get("local_changes_at_start")
    dirty_label = "Unknown" if dirty is None else ("Yes" if dirty else "No")
    verdict = ('<strong style="color:var(--attention)">Yes</strong>' if restart
               else "<strong>No</strong>")
    hint = ('<div class="muted">Executable code changed since this process started. Run '
            '<code>tools/restart_dashboard.ps1</code> (or the "AI QA Factory Dashboard" desktop '
            'shortcut).</div>' if restart else '')
    rows = "".join(
        f'<tr><th scope="row">{label}</th><td>{value}</td></tr>'
        for label, value in (
            ("Process started", _esc(ident.get("process_started_at") or "unknown")),
            ("Running HEAD", _esc(ident.get("running_build") or "unknown")),
            ("Local changes at process start", dirty_label),
            ("Restart required", verdict),
        ))
    # The verdict rides in the summary and the block opens itself when a restart is due: a fact the
    # operator must act on cannot live behind a fold they have to know to open.
    return (f'<details class="advanced compact-details"'
            f'{" open" if (restart or force_open) else ""}>'
            f'<summary>Runtime — {"restart required" if restart else "up to date"}</summary>'
            f'<div class="scrollx"><table class="runtime-table">{rows}</table></div>'
            f'{hint}</details>')


def _build_footer_html(active: str = "/") -> str:
    """Compact build-identity footer (version + running SHA, plus a stale-build warning). Never
    raises to the page; cached so it costs no git subprocess per render."""
    try:
        from core.build_identity import current_identity
        ident = current_identity()
    except Exception:
        return ""
    # Follow restart_required, not stale: an uncommitted edit never moves HEAD, so a footer keyed on
    # the SHA alone would stay quiet while the Runtime block on Overview says a restart is due.
    warn = (f'<span style="color:var(--attention);font-weight:600">&#9888; '
            f'{_esc(ident.get("warning",""))}</span> &middot; '
            if ident.get("restart_required") else "")
    scout_surface = active.startswith("/scout") or active in ("/results", "/company")
    identity = (str(ident.get("product_version") or "AI QA Factory")
                if scout_surface else "AI QA Factory &middot; Operator Dashboard")
    return ('<footer style="max-width:var(--maxw);margin:0 auto;padding:10px var(--pad);'
            'color:var(--muted);font-size:12px;border-top:1px solid var(--border)">'
            f'{warn}{identity if not scout_surface else _esc(identity)}</footer>')


def _page(title: str, active: str, body: str, script: str = "") -> str:
    scr = f"<script>{_THEME_TOGGLE_JS}{_PAGE_UI_JS}{script}</script>"
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<link rel=\"icon\" href=\"data:image/svg+xml,"
            f"%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
            f"%3Crect width='16' height='16' rx='4' fill='%23c9a227'/%3E%3C/svg%3E\">"
            f"<title>{_esc(title)}</title><script>{_THEME_HEAD_JS}</script>"
            f"<style>{_TOKENS_CSS}</style></head><body>"
            f"{_nav_html(active)}<main>{body}</main>{_PAGE_UI_HTML}"
            f"{_build_footer_html(active)}{scr}</body></html>")


def _badge(text: str, kind: str = "") -> str:
    return f'<span class="badge {kind}">{_esc(text)}</span>'


def _evidence_state_grid_html(detail: dict) -> str:
    """Every evidence kind with its state and, when it is missing, the reason it is missing.

    Four states, never a blank: Available / Not applicable / Not captured: reason / Capture failed:
    reason. The distinction is what tells the operator whether to re-run — only a capture failure is
    a fault of ours.
    """
    from core.scout.evidence_state import AVAILABLE, CAPTURE_FAILED, evidence_states

    tone = {AVAILABLE: "ok", CAPTURE_FAILED: "danger"}
    cells = []
    for state in evidence_states(detail):
        count = (f' <span class="muted">&middot; {state.count}</span>'
                 if state.is_available and state.count else "")
        cells.append(f'<div class="evidence-item"><h3>{_esc(state.title)}</h3>'
                     f'<span>{_badge(state.label, tone.get(state.state, ""))}{count}</span></div>')
    return f'<div class="evidence-grid" style="margin-top:12px">{"".join(cells)}</div>'


def _evidence_files_html(evidence_files: list, art_url) -> str:
    """Open/Download for each captured file. A file you cannot fetch is not evidence you can send."""
    if not evidence_files:
        return ""
    rows = "".join(
        f'<tr><td>{_esc(e.get("label") or e.get("name") or "")}</td>'
        f'<td><code>{_esc(e.get("name") or "")}</code></td>'
        f'<td><a href="{art_url(e["rel"])}" target="_blank" rel="noopener">Open</a> &middot; '
        f'<a href="{art_url(e["rel"])}&amp;download=1" download>Download</a></td></tr>'
        for e in evidence_files if e.get("rel"))
    return (f'<h3>Captured files</h3><div class="scrollx"><table class="responsive-table">'
            f'<thead><tr><th>What it is</th><th>File</th><th>Actions</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def _client_package_html(service, domain: str, run_id: str, detail: dict) -> str:
    """The client deliverable, kept visibly separate from the operator's own outreach text.

    Generating a package is not approving it. ``approved_for_client_delivery`` stays a human
    decision, so the status tops out at "Ready for review" however clean the build was.
    """
    findings = list(detail.get("findings") or [])
    actionable = [f for f in findings
                  if str(f.get("severity") or "").strip().lower() != "info"]
    media = [str(m) for m in (detail.get("media") or [])]
    shots = sum(1 for m in media if m.lower().rsplit(".", 1)[-1]
                in ("png", "jpg", "jpeg", "webp", "gif"))
    videos = sum(1 for m in media if m.lower().rsplit(".", 1)[-1] in ("webm", "mp4"))
    status = service.client_package_status(domain, run=run_id)
    state = status.get("state") or "not_generated"
    labels = {"not_generated": ("Not generated", ""), "ready": ("Ready for review", "ok"),
              "blocked": ("Blocked", "danger")}
    label, tone = labels.get(state, ("Not generated", ""))
    meta = ""
    if state == "ready":
        meta = (f'<p class="muted">Generated {_fmt_ts(status.get("generated_at", ""))} &middot; '
                f'{_esc(_human_bytes(status.get("bytes", 0)))} &middot; '
                f'<code>{_esc(status.get("filename", ""))}</code></p>')
    elif state == "blocked":
        meta = f'<p class="muted">{_esc(status.get("reason", "Package could not be built."))}</p>'
    # One name, always. Renaming the primary action to "Regenerate and download" once a ZIP existed
    # made the button the operator reaches for change under them after every download.
    #
    # There is deliberately no separate Regenerate control either: this route rebuilds the package
    # from current evidence on every request, so a second button would advertise a distinction the
    # system does not have. The card says that instead.
    rebuild_note = ('Downloading rebuilds the package from the evidence as it stands now. '
                    if state == "ready" else '')
    return (
        f'<div class="card"><h2>Client package</h2>'
        f'<div class="row">{_badge(label, tone)}'
        f'<span class="muted">{len(actionable)} actionable finding(s) &middot; {shots} screenshot(s)'
        f' &middot; {videos} video(s)</span></div>{meta}'
        f'<div class="row" style="margin-top:12px">'
        f'<a class="btn primary" href="/scout/client-evidence?run={_esc(run_id)}'
        f'&amp;domain={_esc(domain)}">Download client evidence (.zip)</a>'
        f'<a class="btn" href="/scout/client-report?run={_esc(run_id)}'
        f'&amp;domain={_esc(domain)}">Preview report</a></div>'
        f'<p class="muted">{rebuild_note}'
        f'One target only — no other company\'s evidence, findings or contacts are '
        f'included. Your talking points, the email draft and where the contact came from stay out of '
        f'it. Building the package is not approval to send it: review the contents first.</p></div>')


_INTERACTION_HEADLINE = {
    "defect": ("A control that does not do what it says", "bad"),
    "interaction_trace": ("A recorded interaction — the control behaved correctly", "muted"),
    "not_run": ("No interaction was recorded", "muted"),
}


def _interaction_card(record, art_url) -> str:
    """Render the recorded interaction: what was true before, what was done, what happened, and
    whether the page was put back.

    The outcome is stated in words rather than left to the video, because a trace and a defect look
    identical on screen — the same click, the same page — and only one of them is something a client
    should ever hear about.
    """
    if not isinstance(record, dict) or not record.get("scenario"):
        return ""
    outcome = str(record.get("outcome") or "not_run")
    headline, kind = _INTERACTION_HEADLINE.get(outcome, _INTERACTION_HEADLINE["not_run"])
    video = record.get("video") if isinstance(record.get("video"), dict) else {}
    ref = str(record.get("video_ref") or "")
    run = str(record.get("run_id") or "")
    pid = str(record.get("prospect_id") or "")
    player = ""
    if ref and run and pid:
        src = art_url(f"prospects/{pid}/{ref}")
        player = (f'<video src="{src}" controls preload="metadata" '
                  f'style="max-width:520px;width:100%;margin:8px 0"></video>')
    elif outcome in ("defect", "interaction_trace"):
        player = (f'<p class="muted">{_esc(str(record.get("video_rejected_reason") or "No clip was kept for this interaction."))}</p>')
    facts = []
    for label, key in (("Before", "baseline"), ("After the action", "observed"),
                       ("After cleanup", "after_cleanup")):
        state = record.get(key) if isinstance(record.get(key), dict) else {}
        if not state:
            continue
        bits = []
        if state.get("result_count") is not None:
            bits.append(f'{state["result_count"]} results stated')
        if state.get("item_signature"):
            bits.append(f'{state["item_signature"][0]} listed')
        if state.get("selected_label") is not None:
            bits.append(f'selected: {state["selected_label"]}')
        if state.get("removable_count") is not None:
            bits.append(f'{state["removable_count"]} removable element(s)')
        facts.append(f'<tr><th scope="row">{_esc(label)}</th>'
                     f'<td class="muted">{_esc(" · ".join(bits) or "nothing measurable")}</td></tr>')
    if video:
        facts.append(
            f'<tr><th scope="row">Recording</th><td class="muted">'
            f'{_esc(str(video.get("mime") or "video"))} · {_human_bytes(video.get("bytes"))} · '
            f'{_esc(str(video.get("duration_s")))}s · {_esc(str(video.get("width")))}&times;'
            f'{_esc(str(video.get("height")))} · SHA-256 '
            f'<code>{_esc(str(video.get("sha256") or "")[:16])}&hellip;</code></td></tr>')
    steps = "".join(f'<li>{_esc(str(s))}</li>' for s in (record.get("steps") or [])[:8])
    cleanup = ("the page was put back" if record.get("cleanup_ok")
               else "the page could not be verified as restored")
    return (f'<div class="card"><h2>Recorded interaction</h2>'
            f'{_badge(headline, kind)}'
            f'<p class="muted">{_esc(str(record.get("reason") or ""))}</p>'
            f'{player}'
            f'<div class="scrollx"><table>{"".join(facts)}</table></div>'
            f'{f"<ol class=muted>{steps}</ol>" if steps else ""}'
            f'<p class="muted">Cleanup: {_esc(cleanup)}.</p></div>')


def _data_empty_note(filters, in_trash: bool) -> str:
    """Say WHY the table is empty. "Trash is empty" under an active filter is simply wrong, and it
    reads as reassurance at the moment an operator is looking for something they cannot find."""
    narrowed = [name for name in ("purpose", "text", "since", "until") if (filters or {}).get(name)]
    if narrowed:
        return "No stored run matches these filters. Clear them to see everything again."
    return "Trash is empty." if in_trash else "No Scout runs are stored yet."


def _human_bytes(size) -> str:
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "unknown size"
    for unit in ("B", "KiB", "MiB"):
        if value < 1024 or unit == "MiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} MiB"


def _purpose_options(selected: str = "") -> str:
    """The purpose filter. Blank means the operator's own work, which is what History is for —
    so the first option says so rather than reading as "no filter applied"."""
    from core.scout.run_purpose import (PURPOSE_ACCEPTANCE, PURPOSE_DIAGNOSTIC, PURPOSE_LABELS,
                                        PURPOSE_MANUAL_TEST)

    choices = [("", "Production work"), ("all", "Everything, including test runs"),
               (PURPOSE_ACCEPTANCE, PURPOSE_LABELS[PURPOSE_ACCEPTANCE]),
               (PURPOSE_DIAGNOSTIC, PURPOSE_LABELS[PURPOSE_DIAGNOSTIC]),
               (PURPOSE_MANUAL_TEST, PURPOSE_LABELS[PURPOSE_MANUAL_TEST])]
    return "".join(f'<option value="{_esc(key)}"'
                   f'{" selected" if key == selected else ""}>{_esc(label)}</option>'
                   for key, label in choices)


def _result_options(selected: str = "") -> str:
    """The result filter, offering exactly the verdicts a row can actually hold."""
    from core.scout.site_result import LABELS

    options = ['<option value="">Any result</option>']
    options += [f'<option value="{_esc(key)}"'
                f'{" selected" if key == selected else ""}>{_esc(label)}</option>'
                for key, label in LABELS.items()]
    return "".join(options)


# Stored source values are lowercase tokens; the operator reads the platform name.
_SOURCE_LABEL = {"upwork": "Upwork", "direct": "Direct client", "other": "Other source",
                 "manual": "Source not specified", "unknown": "Source not specified",
                 "scout": "Scout"}


def _source_label(source: str) -> str:
    key = (source or "").strip().lower()
    return _SOURCE_LABEL.get(key) or key.replace("_", " ").capitalize() or "Source not specified"


_COLLAB_STATE_KIND = {"NEEDS_OWNER": "attention", "BLOCKED": "blocked", "FIXING": "attention",
                      "WAITING_FOR_CI": "attention", "DONE": "done"}


def _collab_body(snap: dict, *, show_completed: bool = False) -> str:
    """Render an operator-first collaboration monitor.

    Current action, ownership and health stay visible. Model names, tokens, SHA/CI evidence and the
    raw timeline remain available under Advanced details for debugging without dominating the page.
    """
    d = snap.get("driver", {})
    b = d.get("budget", {})
    stale = ('<span style="color:var(--attention);font-weight:600">&#9888; heartbeat stale</span>'
             if d.get("stale") else "")
    beat = _fmt_ts(d.get("heartbeat", ""))
    err = (f'<p class="muted">last error: {_esc(d.get("last_error"))}</p>' if d.get("last_error")
           else "")
    banner = ""
    if snap.get("owner_action_required"):
        banner = ('<div class="card" style="border-color:var(--attention)">'
                  '<strong>&#9888; Owner action required</strong> &middot; a thread is waiting on your '
                  'decision (see NEEDS_OWNER below).</div>')
    model = _esc(d.get("model") or "—")
    effort = _esc(d.get("reasoning_effort") or "—")
    driver_card = (
        '<div class="card"><h2 style="margin-top:0">Reviewer</h2>'
        f'<p>{_badge(d.get("stage","IDLE"))} {stale}</p>'
        f'<p class="muted">{int(d.get("processed",0))} items processed today · '
        f'${float(b.get("daily_usd",0)):.2f} estimated usage</p>{err}'
        '<details class="advanced"><summary>Technical details</summary>'
        f'<p>Heartbeat: {_esc(beat)} · model <code>{model}</code> · effort {effort}</p>'
        f'<p>{int(b.get("daily_calls",0))}/{int(b.get("cap_calls",0))} calls · '
        f'{int(b.get("daily_tokens",0))} tokens · '
        f'${float(b.get("daily_usd",0)):.2f}/${float(b.get("cap_usd",0)):.2f}</p></details></div>')

    dl = snap.get("delivery", {})
    bsrc = dl.get("billing_source") or "unknown"
    billing_label = (f'Claude {_esc(dl.get("billing_plan") or "?")} subscription allocation'
                     if bsrc == "subscription" else
                     ("Anthropic API credits" if bsrc == "api_credits" else "unknown (verify via /status)"))
    delivery_card = (
        '<div class="card"><h2 style="margin-top:0">Delivery worker</h2>'
        f'<p>{int(dl.get("delivered",0))} decisions delivered</p>'
        '<details class="advanced"><summary>Technical details</summary>'
        f'<p>Model <code>{_esc(dl.get("claude_model") or "—")}</code> · cost '
        f'${float(dl.get("claude_cost_usd",0)):.4f}</p>'
        f'<p>Billing source: <strong>{billing_label}</strong></p></details></div>')
    driver_card += delivery_card

    sup = snap.get("supervisor", {})
    if sup.get("installed"):
        sup_state = ('<span style="color:var(--attention);font-weight:600">&#9888; heartbeat stale</span>'
                     if not sup.get("fresh") else "supervisor alive")
        driver_card += (
            '<div class="card"><h2 style="margin-top:0">Background supervisor</h2>'
            f'<p>{sup_state}</p><details class="advanced"><summary>Technical details</summary>'
            f'<p>Last check {_esc(_fmt_ts(sup.get("checked_at","")))} · '
            f'up={_esc(str(sup.get("dashboard_up_at_check")))} · '
            f'stale={_esc(str(sup.get("dashboard_stale_at_check")))} · '
            f'action {_esc(sup.get("dashboard_action") or "—")}</p></details></div>')
    else:
        driver_card += ('<div class="card"><h2 style="margin-top:0">Durable supervisor</h2>'
                        '<p class="muted">not installed — run tools/supervisor_install.ps1 for '
                        'session-independent Dashboard + driver recovery</p></div>')

    threads = snap.get("threads", [])
    visible_threads = [t for t in threads
                       if (t.get("state") == "DONE") is show_completed]
    counts = snap.get("counts", {})
    thread_toggle = (
        '<a class="chip" href="/collab">&#10003; Active collaboration</a>'
        if show_completed else
        f'<a class="chip" href="/collab?completed=1">Completed ({int(counts.get("done", 0))})</a>')
    if not visible_threads:
        rows = ('<div class="card"><p class="muted">No completed collaboration tasks.</p></div>'
                if show_completed else
                '<div class="card"><p class="muted">No active collaboration tasks.</p></div>')
    else:
        cards = []
        for index, t in enumerate(visible_threads, start=1):
            kind = _COLLAB_STATE_KIND.get(t.get("state", ""), "")
            sha = _esc((t.get("head_sha") or "")[:12] or "—")
            match = ("&#10003; matches head" if t.get("reviewed_sha_matches_head")
                     else ("&#9888; stale head" if t.get("stale_head") else ""))
            pr = t.get("pr_number")
            pr_txt = f'#{int(pr)}' if pr else "—"
            timeline = " &rarr; ".join(
                f'{_esc(ev.get("kind",""))}' for ev in t.get("timeline", [])) or "—"
            ci = ", ".join(_esc(r) for r in t.get("ci_refs", [])) or "—"
            cards.append(
                f'<div class="card"><h3 style="margin:0 0 6px">Collaboration task {index} '
                f'{_badge(t.get("state","") , kind)}</h3>'
                f'<p><strong>Now:</strong> {_esc(t.get("current_action"))}</p>'
                f'<p><strong>Next:</strong> {_esc(t.get("next_action"))}</p>'
                f'<p class="muted">Owner: {_esc(t.get("actor"))} · PR {pr_txt}</p>'
                f'<details class="advanced"><summary>Technical details</summary>'
                f'<table><tr><td class="muted">Thread ID</td><td>{_esc(t.get("thread_id"))}</td></tr>'
                f'<tr><td class="muted">Branch / PR</td><td>{_esc(t.get("branch") or "—")} · '
                f'{pr_txt}</td></tr>'
                f'<tr><td class="muted">Head SHA</td><td><code>{sha}</code></td></tr>'
                f'<tr><td class="muted">Decision</td><td>{_esc(t.get("decision") or "—")} '
                f'<span class="muted">{match}</span></td></tr>'
                f'<tr><td class="muted">CI evidence</td><td>{ci}</td></tr>'
                f'<tr><td class="muted">Timeline</td><td>{timeline}</td></tr></table></details></div>')
        rows = "".join(cards)

    return (f'<h1>Collaboration</h1><p class="muted">Reviewer and implementation worker status. '
            f'This page refreshes automatically.</p>{banner}'
            f'<div class="row"><span class="chip">Active {int(counts.get("active", 0))}</span>'
            f'<span class="chip">Needs you {int(counts.get("needs_owner", 0))}</span>'
            f'{thread_toggle}</div><div class="summary-grid" style="margin-top:12px">'
            f'{driver_card}</div><h2>{"Completed" if show_completed else "Current tasks"}</h2>{rows}')


def _friendly_record_label(title: object, record_id: object, fallback: str) -> str:
    """Return a stable human label while keeping internal ids out of ordinary UI."""
    display = _collapse_ws(title)
    rid = str(record_id or "").strip()
    if display and display != rid and display.lower() not in ("scout campaign", "work item"):
        return display
    stamp = re.search(r"(?i)(20\d{6})t(\d{6})z?", rid)
    when = ""
    if stamp:
        try:
            from datetime import datetime
            dt = datetime.strptime("".join(stamp.groups()), "%Y%m%d%H%M%S")
            when = dt.strftime("%b %d, %Y %H:%M UTC")
        except ValueError:
            when = ""
    slug = rid[:stamp.start()] if stamp else rid
    slug = re.sub(r"(?i)^(campaign-|run-)", "", slug).strip("-_ ")
    slug = re.sub(r"[-_][0-9a-f]{6,40}$", "", slug, flags=re.I).strip("-_ ")
    words = " ".join(part for part in re.split(r"[-_]+", slug) if part)
    generic = {"", "campaign", "discovery", "run", "scout"}
    label = fallback if words.lower() in generic else words.title()
    return f"{label} · {when}" if when else (label or fallback)


def _fmt_ts(iso: str) -> str:
    """Format an ISO timestamp consistently as 'YYYY-MM-DD HH:MM UTC' (falls back to the raw value)."""
    if not iso:
        return "—"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return str(iso)[:19]


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
    # Freeze the running-build identity EAGERLY, at process/server start — so "running SHA" reflects
    # the commit this dashboard actually started serving (stale detection works before the 1st request).
    from core.build_identity import freeze_running_identity
    freeze_running_identity()
    launcher = launcher or CampaignLauncher(service)
    token = secrets.token_urlsafe(32) if csrf_token is None else csrf_token
    from core.scout.challenge_session import ChallengeSessionManager
    challenge_manager = ChallengeSessionManager(service.output_dir)
    server = ThreadingHTTPServer((host, port),
                                 _make_handler(service, launcher, token, operator_home,
                                               challenge_manager))
    server.scout_csrf_token = token          # type: ignore[attr-defined]
    server.scout_launcher = launcher         # type: ignore[attr-defined]
    server.scout_challenge_manager = challenge_manager  # type: ignore[attr-defined]
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
    # Precompute the Access readiness snapshot off the request path (non-blocking) so a /settings or
    # /api/access request almost never pays the cold-cache subprocess-probe cost.
    threading.Thread(target=lambda: _safe_warm_access(), daemon=True).start()
    return server, f"http://{bound_host}:{bound_port}"


def _safe_warm_access() -> None:
    try:
        cached_access_snapshot()
    except Exception:
        pass


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
