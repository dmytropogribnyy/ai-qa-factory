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
                return self._html(200, self._projects_page())
            # v3.1 operator dashboard read-model routes
            if path == "/api/overview":
                return self._json(200, self._read_model().overview(
                    include_diagnostics=self._want_diagnostics(q)).to_dict())
            if path == "/api/work":
                view = (q.get("view") or ["all"])[0]
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
                return self._html(200, self._scout_campaigns_page())
            if path == "/activity":
                return self._html(200, self._activity_page(q))
            if path == "/api/activity":
                return self._json(200, self._activity_json((q.get("project") or [""])[0],
                                                           self._want_diagnostics(q)))
            if path == "/settings":
                if (q.get("refresh") or [""])[0]:
                    cached_access_snapshot(refresh=True)   # explicit operator refresh
                return self._html(200, self._settings_page())
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
                return self._html(200, self._collab_page())
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
                             "status": (q.get("status") or [""])[0]})})
            if path == "/api/scout/target":
                return self._json(200, self._campaign_service().target_detail(
                    (q.get("domain") or [""])[0], run=(q.get("run") or [""])[0]))
            if path == "/scout/new":
                return self._html(200, self._scout_new_page())
            if path == "/scout/progress":
                return self._html(200, self._scout_progress_page((q.get("id") or [""])[0]))
            if path == "/scout/history":
                return self._html(200, self._scout_history_page(q))
            if path == "/scout/target":
                return self._html(200, self._scout_target_page(
                    (q.get("domain") or [""])[0], run=(q.get("run") or [""])[0]))
            if path == "/scout/run":
                return self._html(200, self._scout_run_results_page((q.get("id") or [""])[0]))
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
                return self._scout_artifact((q.get("run") or [""])[0], (q.get("rel") or [""])[0])
            if path == "/work-evidence":
                return self._work_evidence((q.get("project") or [""])[0], (q.get("path") or [""])[0])
            if path == "/" or path == "/index.html":
                # Operator home = the new Overview inbox; a Scout-run-bound dashboard keeps its
                # existing run view at "/" (regression-preserved). Both link to each other.
                if operator_home and not service.is_running() and not self._has_active_run():
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

        def _collab_page(self) -> str:
            try:
                snap = self._collab_snapshot()
            except Exception as exc:
                return _page("Collaboration", "/collab",
                             f'<h1>Collaboration</h1><p class="muted">Monitor unavailable: '
                             f'{_esc(type(exc).__name__)}</p>')
            return _page("Collaboration", "/collab", _collab_body(snap),
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
            if parsed.path == "/api/scout/control":
                return self._scout_control(parsed)
            if parsed.path == "/api/scout/export":
                return self._scout_export(parsed)
            if parsed.path == "/api/scout/rescan":
                return self._scout_rescan(parsed)
            if parsed.path == "/api/scout/replay":
                return self._scout_replay(parsed)
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
            if store is None or not pid:
                return {"error": "no prospect"}
            out = {"prospect_id": pid}
            if run:
                out["run"] = run
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

        def _scout_artifact(self, run_id: str, rel: str):
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

        def _operator_overview_page(self, q=None) -> str:
            diag = self._want_diagnostics(q or {})
            ov = self._read_model().overview(include_diagnostics=diag)
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
            hidden = ov.counts.get("diagnostics_hidden", 0)
            diag_toggle = (
                '<a class="chip" href="/">&#10003; Production only — hide diagnostics</a>' if diag else
                (f'<a class="chip" href="/?diagnostics=1">Show diagnostics ({hidden})</a>'
                 if hidden else ''))
            diag_banner = ('<div class="banner warn">Showing diagnostic data (smoke/acceptance/'
                           'replay/demo). These are not production work.</div>' if diag else '')
            body = (f'<h1>Overview</h1>{diag_banner}'
                    f'<div class="row"><span class="chip">Projects {ov.counts.get("projects", 0)}</span>'
                    f'<span class="chip">Needs attention {ov.counts.get("attention", 0)}</span>'
                    f'<span class="chip">Active Scout campaigns {ov.counts.get("active_campaigns", 0)}'
                    f'</span>{diag_toggle}'
                    f'<button class="btn" onclick="location.reload()">Refresh</button></div>'
                    f'{self._poll_html()}'
                    f'<h2>Needs your attention</h2>{att}'
                    f'<h2>Active work</h2><div class="scrollx">{work_tbl}</div>'
                    f'<h2>Scout</h2><div class="scrollx">{camp_tbl}</div>')
            script = ("const CSRF=" + json.dumps(csrf_token) + ";\n"
                      + self._poll_script(
                          "/api/overview",
                          "function(j){return [(j.attention||[]).map(function(a){return a.project_id"
                          "+'|'+a.status+'|'+a.next_action}),(j.active_work||[]).map(function(p){"
                          "return p.project_id+'|'+p.status+'|'+p.progress+'|'+p.next_action}),"
                          "(j.active_campaigns||[]).map(function(c){return c.campaign_id+'|'+c.status"
                          "+'|'+c.progress})]}"))
            return _page("AI QA Factory — Overview", "/", body, script)

        _WORK_VIEWS = (("all", "All Work"), ("needs_attention", "Needs Attention"),
                       ("ready_to_execute", "Ready to Execute"), ("in_progress", "In Progress"),
                       ("blocked", "Blocked"), ("ready_for_review", "Ready for Review"),
                       ("ready_for_delivery", "Ready for Delivery"),
                       ("delivery_prepared", "Delivery Prepared"), ("completed", "Completed"))

        def _work_list_page(self, q) -> str:
            view = (q.get("view") or ["all"])[0]
            diag = self._want_diagnostics(q)
            data = self._read_model().project_list(view=view, include_diagnostics=diag)
            _dsuffix = "&diagnostics=1" if diag else ""
            views = "".join(
                f'<a class="chip" href="/work?view={v}{_dsuffix}" '
                f'{"style=font-weight:600" if v == view else ""}>{_esc(lbl)}</a>'
                for v, lbl in self._WORK_VIEWS)
            views += (
                f'<a class="chip" href="/work?view={view}">&#10003; Production only</a>' if diag else
                f'<a class="chip" href="/work?view={view}&diagnostics=1">Show diagnostics</a>')
            def _row(p):
                return (f'<tr><td><a href="{_esc(p["href"])}">{_esc(p["title"])}</a>'
                        f'<div class="muted">{_esc(p["project_id"])}</div></td>'
                        f'<td>{_badge(p["stage"])}</td><td>{_badge(p["health"], p["health"])}</td>'
                        f'<td>{_esc(p["next_action"])}</td>'
                        f'<td class="muted">{_esc(_fmt_ts(p["updated"]))}</td></tr>')

            def _card(p):
                return (f'<li><div class="card"><h3><a href="{_esc(p["href"])}">{_esc(p["title"])}</a></h3>'
                        f'<div class="muted meta">{_esc(p["project_id"])}</div>'
                        f'<div class="row" style="margin:.4rem 0">{_badge(p["stage"])} '
                        f'{_badge(p["health"], p["health"])}</div>'
                        f'<div><strong>Next:</strong> {_esc(p["next_action"])}</div>'
                        f'<div class="muted meta">Updated {_esc(_fmt_ts(p["updated"]))}</div></div></li>')

            if data["projects"]:
                rows = "".join(_row(p) for p in data["projects"])
                desktop = (f'<div class="scrollx only-desktop"><table><caption>{data["total"]} '
                           f'project(s) — view: {_esc(view)}</caption><tr><th>Project</th><th>Stage</th>'
                           f'<th>Health</th><th>Next action</th><th>Updated</th></tr>{rows}</table></div>')
                cards = ('<ul class="cards only-mobile" aria-label="Projects">'
                         + "".join(_card(p) for p in data["projects"]) + "</ul>")
                table = desktop + cards
            else:
                table = ('<div class="card empty">No projects in this view. '
                         '<a href="/work?view=all">Clear filter</a></div>')
            create = (
                '<details class="card"><summary>Create work from a pasted client brief</summary>'
                '<p class="muted">Analysis only — nothing is executed. This reuses analyze-job.</p>'
                '<p><label>Project name (optional)<br><input id="cw_pid" placeholder="my-project"></label></p>'
                '<p><label>Source platform (optional)<br><input id="cw_src" placeholder="upwork / direct"></label></p>'
                '<p><label>Client brief<br><textarea id="cw_brief" rows="5" style="width:100%"></textarea></label></p>'
                '<p><button class="btn primary" onclick="createWork(this)">Analyze brief</button></p>'
                '<p class="muted">No Upwork API — paste the brief and (optionally) a source reference.</p>'
                '</details>')
            script = (self._work_actions_script() +
                      "function createWork(btn){var b=document.getElementById('cw_brief').value.trim();"
                      "if(!b){alert('paste a client brief');return;}"
                      "if(btn){if(btn.dataset.busy)return;btn.dataset.busy='1';btn.disabled=true;}"
                      "fetch('/api/work/analyze',{method:'POST',headers:{'Content-Type':'application/json',"
                      "'X-Scout-CSRF':CSRF},body:JSON.stringify({text:b,"
                      "project_id:document.getElementById('cw_pid').value.trim(),"
                      "source_platform:document.getElementById('cw_src').value.trim()})})"
                      ".then(r=>r.json()).then(function(j){if(j.ok){location.href='/work/'+j.project_id;}"
                      "else{alert(j.error||'refused');if(btn){btn.disabled=false;delete btn.dataset.busy;}}})"
                      ".catch(function(e){alert(''+e);if(btn){btn.disabled=false;delete btn.dataset.busy;}});}")
            body = (f'<h1>Work</h1><div class="row">{views}'
                    f'<button class="btn" onclick="location.reload()">Refresh</button></div>'
                    f'{self._poll_html()}'
                    f'{table}{create}')
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
                controls = ('<button class="btn" onclick="ctl(\'pause\')">Pause</button>'
                            '<button class="btn" onclick="ctl(\'resume\')">Resume</button>'
                            '<button class="btn" onclick="ctl(\'cancel\')">Stop Safely</button>'
                            '<button class="btn danger" onclick="ctl(\'kill\')">Cancel (kill)</button>')
            else:
                controls = (f'<em class="muted">Controls unavailable — this run is '
                            f'<strong>{_esc(mode)}</strong> (read-only).</em>')
            run_id = status.get("run_id", "")
            prows = "".join(
                f'<tr><td>{_esc(pid)}</td><td class="muted">{_esc(p.get("url", ""))}</td>'
                f'<td>{_badge(p.get("status", ""))}</td><td>{_esc(p.get("priority", ""))}</td>'
                f'<td>{_esc(p.get("verified_defects", 0))}</td>'
                f'<td>{_scout_details_cell(run_id, pid, p)}</td></tr>'
                for pid, p in sorted(prospects.items()))
            table = (f'<table><caption>Prospects in this run</caption><tr><th>ID</th><th>URL</th>'
                     f'<th>Status</th><th>Priority</th><th>Defects</th><th>Details</th></tr>{prows}</table>'
                     if prows else '<div class="card empty muted">No prospects in this run.</div>')
            start_panel = "" if running else _START_PANEL_HTML
            results_link = (f'<a class="chip" href="/scout/run?id={_esc(run_id)}">Run results</a>'
                            if run_id else '')
            body = (f'<h1>Manual URL Scan</h1><p class="muted">{_esc(SCOUT_PRODUCT_NAME)} — bounded, '
                    f'read-only scan of URLs you paste. For automatic prospect discovery use '
                    f'<a href="/scout/new">Discover Prospects</a>. Nothing is sent without your action.</p>'
                    f'<div class="row"><a class="chip" href="/scout/new">Discover Prospects (adaptive)</a>'
                    f'<a class="chip" href="/scout/history">History</a></div>'
                    f'<div class="card"><p>Run <code>{_esc(run_id)}</code> · mode '
                    f'{_badge(mode)} · status {_badge(st.get("status", "n/a"))}</p>'
                    f'<div class="row">{controls}</div></div>'
                    f'<div class="row"><a class="chip" href="/scout/campaigns">Campaigns</a>'
                    f'{results_link}</div>'
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
                "id=impcoverage><option value=adaptive selected>Adaptive (recommended) \u2014 up to "
                "12 pages/site</option><option value=deep>Deep \u2014 up to 20 pages/site</option>"
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
                "alert('start failed: '+e);});}\n")
            return _page("AI QA Factory — Scout", "/scout", body, script)

        def _scout_campaigns_page(self) -> str:
            ov = self._read_model().overview()
            # Reuse the unified project index for scout campaigns (no second store).
            from core.orchestration.project_index import ProjectIndex
            camps = [p for p in ProjectIndex(service.output_dir).list_projects()
                     if p.type == "scout_campaign"]
            rows = "".join(
                f'<tr><td><a href="/scout/progress?id={_esc(c.project_id)}">{_esc(c.title)}</a></td>'
                f'<td>{_badge(c.lifecycle_state)}</td>'
                f'<td>{c.progress}%</td><td>{c.evidence_count}</td>'
                f'<td class="muted">{_esc(c.operator_next_action)}</td>'
                f'<td><a class="chip" href="/scout/progress?id={_esc(c.project_id)}">Open</a></td></tr>'
                for c in camps)
            table = (f'<table><caption>Scout campaigns</caption><tr><th>Campaign</th><th>Status</th>'
                     f'<th>Progress</th><th>Evidence</th><th>Next action</th><th>Open</th></tr>{rows}</table>'
                     if rows else '<div class="card empty muted">No campaigns yet. '
                     '<a href="/scout">Open Scout to start one</a>.</div>')
            body = (f'<h1>Scout campaigns</h1><div class="row">'
                    f'<a class="chip" href="/scout/new">New adaptive campaign</a>'
                    f'<a class="chip" href="/scout/history">History</a>'
                    f'<a class="chip" href="/scout">Manual URL Scan</a>'
                    f'<a class="chip" href="/results">Results</a>'
                    f'<span class="chip">Active {len(ov.active_campaigns)}</span></div>'
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
            try:
                out = self._campaign_service().preflight(
                    campaign_preset=preset,
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

        def _scout_new_page(self) -> str:
            cat = self._campaign_service().catalog()
            opts = "".join(
                f'<option value="{_esc(p["key"])}"{" selected" if p["key"]==cat["default_campaign_preset"] else ""}>'
                f'{_esc(p["label"])}{" (smoke)" if p.get("is_smoke") else ""}</option>'
                for p in cat["campaign_presets"])
            sess = "".join(f'<option value="{_esc(s["key"])}">{_esc(s["label"])} '
                           f'({s["max_discovered"]} discovered / {s["max_qa_analyzed"]} QA / '
                           f'{s["max_duration_min"]}m)</option>' for s in cat["session_presets"])
            strat = "".join(f'<option value="{_esc(s)}">{_esc(s)}</option>'
                            for s in cat["strategies"])
            ind_opts = "".join(f'<option value="{_esc(i)}">{_esc(i)}</option>'
                               for i in cat["industries"])
            site_opts = "".join(f'<option value="{_esc(s)}">{_esc(s.replace("_", " "))}</option>'
                                for s in cat["site_types"])
            body = (
                '<h1>New Scout campaign</h1>'
                '<div class="row"><a class="chip" href="/scout/history">History</a>'
                '<a class="chip" href="/scout">Manual URL Scan</a></div>'
                '<div class="card formstack"><label>Preset<br><select id="preset">' + opts + '</select></label>'
                '<label> Session (budget)<br><select id="session"><option value="">preset default</option>'
                + sess + '</select></label>'
                '<label> Strategy<br><select id="strategy"><option value="">preset default</option>'
                + strat + '</select></label>'
                '<label> Countries (comma, blank = no restriction)<br>'
                '<input id="countries" placeholder="us, de"></label>'
                '<label> Languages (comma)<br><input id="languages" placeholder="en, de"></label>'
                '<label> Industries (multi-select; blank = preset)<br>'
                '<select id="industries" multiple size="6">' + ind_opts + '</select></label>'
                '<label> Site types (multi-select; blank = preset)<br>'
                '<select id="sitetypes" multiple size="6">' + site_opts + '</select></label>'
                '<label> Keywords / commercial signals (comma)<br>'
                '<input id="keywords" placeholder="pricing, free trial, book demo"></label>'
                '<label> Exclude keywords (comma)<br><input id="excludekw"></label>'
                '<label> Min commercial score 0-100 (blank = preset)<br>'
                '<input id="minscore" type="number" min="0" max="100" placeholder="preset default"></label>'
                '<details><summary class="muted">Advanced limits</summary>'
                '<label> Max discovered domains<br><input id="maxdisc" type="number" min="1"></label>'
                '<label> Max pages per site<br><input id="maxpages" type="number" min="1"></label>'
                '</details>'
                '<label><input type="checkbox" id="deepcapture"> Deep capture (Playwright): real '
                'screenshots + network evidence (console errors, failed resources, timing). Slower; '
                'needs Chromium installed. Off = fast static analysis.</label>'
                '<p class="muted">Presets are editable templates. Every run is finite (hard '
                'ceilings) and never sends anything. Live discovery needs your explicit approval '
                'and a configured Tavily key.</p>'
                '<div class="row"><button id="pf" class="chip">Run readiness preflight</button></div>'
                '<pre id="pfout" class="scrollx muted"></pre>'
                '<label><input type="checkbox" id="approve"> I approve one bounded LIVE discovery '
                'run (real external sites, no submissions/purchases/messages)</label>'
                '<div class="row"><button id="run" class="chip primary">Run campaign</button></div>'
                '<div id="msg" class="muted"></div></div>')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";\n"
                "function J(u,b){return fetch(u,{method:'POST',headers:{'Content-Type':'application/json',"
                "'X-Scout-CSRF':CSRF},body:JSON.stringify(b)}).then(r=>r.json());}\n"
                "function v(id){var e=document.getElementById(id);return e?e.value.trim():'';}\n"
                "function csv(s){return s.split(',').map(x=>x.trim()).filter(Boolean);}\n"
                "function multi(id){var e=document.getElementById(id);"
                "return e?Array.from(e.selectedOptions).map(o=>o.value):[];}\n"
                "function ov(){var o={};"
                "var c=v('countries');if(c)o.countries=csv(c);"
                "var lg=v('languages');if(lg)o.languages=csv(lg);"
                "var st=document.getElementById('strategy').value;if(st)o.strategy=st;"
                "var ind=multi('industries');if(ind.length)o.industries=ind;"
                "var sty=multi('sitetypes');if(sty.length)o.site_types=sty;"
                "var kw=v('keywords');if(kw)o.keywords=csv(kw);"
                "var ex=v('excludekw');if(ex)o.exclude_keywords=csv(ex);"
                "var ms=v('minscore');if(ms)o.min_commercial_threshold=parseInt(ms,10);"
                "var md=v('maxdisc');if(md)o.max_candidates=parseInt(md,10);"
                "var mp=v('maxpages');if(mp)o.max_pages_per_site=parseInt(mp,10);"
                "var dc=document.getElementById('deepcapture');"
                "if(dc&&dc.checked)o.browser_mode='playwright';"
                "return o;}\n"
                "document.getElementById('pf').onclick=function(){"
                "document.getElementById('pfout').textContent='running real probes (browser launch"
                " + network)…';"
                "J('/api/scout/preflight',{campaign_preset:document.getElementById('preset').value})"
                ".then(function(j){document.getElementById('pfout').textContent="
                "JSON.stringify(j.preflight||j,null,2);}).catch(e=>{"
                "document.getElementById('pfout').textContent='preflight failed: '+e;});};\n"
                "document.getElementById('run').onclick=function(){"
                "if(!document.getElementById('approve').checked){alert('approve the bounded live run"
                " first');return;}var msg=document.getElementById('msg');msg.textContent='launching…';"
                "J('/api/scout/launch',{campaign_preset:document.getElementById('preset').value,"
                "session_preset:document.getElementById('session').value||null,"
                "approve_live_discovery:true,overrides:ov()}).then(function(j){"
                "if(j.ok){location.href='/scout/progress?id='+encodeURIComponent(j.campaign_id);}"
                "else{msg.textContent='launch refused: '+(j.error||'unknown');}})"
                ".catch(e=>{msg.textContent='launch failed: '+e;});};\n")
            return _page("AI QA Factory — New Scout campaign", "/scout", body, script)

        def _scout_progress_page(self, cid: str) -> str:
            body = ('<h1>Campaign progress</h1><div class="row">'
                    '<a class="chip" href="/scout/new">New campaign</a>'
                    '<a class="chip" href="/scout/history">History</a></div>'
                    '<div class="card"><div id="p" class="muted">loading…</div>'
                    '<div class="row"><button id="bp" class="chip" onclick="ctl(\'pause\')">Pause</button>'
                    '<button id="br" class="chip" onclick="ctl(\'resume\')">Resume</button>'
                    '<button id="bs" class="chip danger" onclick="ctl(\'stop\')">Stop &amp; Save</button>'
                    '<button class="chip" onclick="exp()">Export evidence</button></div>'
                    '<div id="msg" class="muted"></div></div>')
            script = (
                "const CSRF=" + json.dumps(csrf_token) + ";const CID=" + json.dumps(cid) + ";\n"
                "function ctl(a){fetch('/api/scout/control?id='+encodeURIComponent(CID)+'&action='+a,"
                "{method:'POST',headers:{'X-Scout-CSRF':CSRF}}).then(r=>r.json()).then(load);}\n"
                "function exp(){fetch('/api/scout/export?id='+encodeURIComponent(CID),{method:'POST',"
                "headers:{'X-Scout-CSRF':CSRF}}).then(r=>r.json()).then(function(j){"
                "document.getElementById('msg').textContent=j.ok?('bundle: '+j.bundle):('export failed: '+j.error);});}\n"
                "function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}\n"
                "function load(){fetch('/api/scout/progress?id='+encodeURIComponent(CID)).then(r=>r.json())"
                ".then(function(j){var c=j.counters||{};var d=(j.decisions||[]);"
                # After a terminal state, Pause/Resume/Stop no longer apply -> disable them (honest UI).
                "var term=['completed','stopped_with_checkpoint','failed','cancelled'].indexOf(String(j.run_state))>=0;"
                "['bp','br','bs'].forEach(function(id){var b=document.getElementById(id);if(b)b.disabled=term;});"
                # Each analyzed domain links to its target detail (findings/evidence); same tab.
                "var rows=d.map(function(x){var enc=encodeURIComponent(x.domain||'');"
                "return '<tr><td><a href=\"/scout/target?domain='+enc+'\">'+esc(x.domain)+'</a></td><td>'+esc(x.priority)+"
                "'</td><td>'+esc((x.allocation||{}).depth)+'</td><td>'+esc((x.brain||{}).business_model||'')+"
                "'</td></tr>';}).join('');"
                "document.getElementById('p').innerHTML='<div class=row><span class=chip>State: '+esc(j.run_state)+"
                "'</span><span class=chip>Stop: '+esc(j.stop_reason||'—')+'</span></div>'+"
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
            rows = self._campaign_service().history(
                filters={"text": qtext, "since": since, "until": until})
            active_days = days if (days > 0 and not (frm or to)) else 0
            # Honest count: when a filter hides rows, say "N shown of T total" so a filtered view is
            # never mistaken for the whole history (the confusion that motivated this).
            filtered = bool(qtext or since or until)
            total = len(self._campaign_service().history()) if filtered else len(rows)
            count_label = (f"{len(rows)} shown of {total} total"
                           if filtered and len(rows) != total else f"{total} total")
            range_chips = "".join(
                f'<a class="chip{" active" if active_days == val else ""}" '
                f'href="/scout/history?days={val}{("&text=" + _esc(qtext)) if qtext else ""}">{lbl}</a>'
                for val, lbl in ((1, "Today"), (7, "7 days"), (30, "30 days"), (0, "All")))
            trs = "".join(
                f'<tr><td><a href="/scout/target?domain={_esc(r.get("domain",""))}">{_esc(r.get("domain",""))}</a></td>'
                f'<td>{_badge(r.get("analysis_status",""))}</td>'
                f'<td>{_badge(r.get("engagement_status","prospect"))}</td>'
                f'<td class="muted">{_esc(", ".join(r.get("campaign_ids",[])[:2]))}</td>'
                f'<td class="muted">{_fmt_ts(r.get("last_analysis_at",""))}</td>'
                f'<td class="muted">{_esc(r.get("reason","")) or "&mdash;"}</td></tr>'
                for r in rows)
            # Empty state stays honest too: a filter that hides every row must not read as an empty
            # history — say "0 shown of T total" whenever the unfiltered history actually has entries.
            empty_msg = (f'0 shown of {total} total &mdash; no sites match this filter.'
                         if filtered and total > 0 else 'No analyzed sites yet.')
            table = (f'<table><caption>Analyzed-site history &mdash; {count_label}</caption>'
                     f'<tr><th>Domain</th>'
                     f'<th>Status</th><th>Funnel</th><th>Campaigns</th><th>Analyzed</th>'
                     f'<th>Notes</th></tr>{trs}</table>'
                     if rows else f'<div class="card empty muted">{empty_msg}</div>')
            body = (f'<h1>Scout history</h1><div class="row">'
                    f'<a class="chip" href="/scout/new">New campaign</a></div>'
                    f'<div class="row" style="margin-bottom:6px">{range_chips}</div>'
                    f'<form method="get" class="row" style="gap:8px;flex-wrap:wrap;align-items:center">'
                    f'<label class="muted">Last <input name="days" type="number" min="1" max="3650" '
                    f'style="width:64px" value="{active_days or ""}"> days</label>'
                    f'<span class="muted">or</span>'
                    f'<label class="muted">from <input name="from" type="date" value="{_esc(frm)}"></label>'
                    f'<label class="muted">to <input name="to" type="date" value="{_esc(to)}"></label>'
                    f'<input name="text" placeholder="filter domain/text" value="{_esc(qtext)}">'
                    f'<button class="chip">Filter</button>'
                    f'<a class="chip" href="/scout/history">Reset</a></form>'
                    f'<div class="scrollx">{table}</div>'
                    f'<p class="muted">Processed targets are skipped by future campaigns; rescan is '
                    f'explicit. B/C and clean results are retained, never auto-deleted.</p>')
            return _page("AI QA Factory — Scout history", "/scout", body)

        def _scout_target_page(self, domain: str, run: str = "") -> str:
            det = self._campaign_service().target_detail(domain, run=run)
            entry, brain = det.get("entry"), det.get("brain")
            prospect_id = det.get("prospect_id") or ""
            prospect_status = det.get("prospect_status") or ""
            run_id = det.get("run") or det.get("scout_run") or ""
            nav = ((f'<a class="chip" href="/scout/run?id={_esc(run_id)}">Back to run</a>'
                    if run_id else '')
                   + '<a class="chip" href="/scout/history">Back to history</a>')
            # A run-pinned target whose domain is not in that run: honest, never another target's data.
            if run and det.get("evidence_status") == "prospect_not_found":
                return _page("AI QA Factory — Target", "/scout",
                             f'<h1>{_esc(domain)}</h1><div class="row">{nav}</div>'
                             f'<div class="card"><div class="banner warn">No prospect for '
                             f'{_esc(domain)} exists in run <code>{_esc(run_id)}</code>. This target\'s '
                             f'own evidence is unavailable — Scout never shows another target\'s '
                             f'evidence in its place.</div></div>')
            # A run-pinned incomplete target (manual action / failed): honest incomplete-analysis view,
            # never a healthy "0 defects" conclusion.
            if run and prospect_status and prospect_status != "DONE":
                return self._scout_incomplete_target_html(domain, det, nav)
            if not entry and not brain and not prospect_id:
                return _page("AI QA Factory — Target", "/scout",
                             f'<h1>Target</h1><div class="card empty muted">No record for '
                             f'{_esc(domain)}.</div>')
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
                f'<b>Allowed interaction:</b> {_esc(plan.get("allowed_interaction_mode","—"))}</p>'
                f'<p><b>Checks selected:</b> {_esc(", ".join(plan.get("checks_selected",[])))}</p>'
                f'<p><b>Checks skipped:</b> {_esc(", ".join(plan.get("checks_skipped",[])))}</p>'
                f'<p><b>Stop boundary:</b> {_esc(", ".join(plan.get("stop_boundaries",[])) or "—")}</p>'
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
                + '<p class="muted">Recheck / Reproduce / Record short video / Capture stronger '
                'evidence are available on a live-analyzed target (bounded, fail-closed).</p></div>')

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
            media_html = "".join(
                f'<a href="{_art_url(m)}" target="_blank" rel="noopener"><img src="{_art_url(m)}" '
                f'alt="screenshot" style="max-width:280px;max-height:200px;margin:4px;'
                f'border:1px solid var(--border,#ccc)"></a>' for m in imgs)
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

            # Raw evidence files — a safe, exact-run/exact-prospect-confined "open" action for the
            # underlying JSON evidence (observation/findings/scorecard/coverage/reproduction/manual
            # action), reusing the SAME /scout/artifact route as screenshots. Only files that
            # genuinely exist are linked (never a dead link).
            if evidence_files:
                ev_rows = "".join(
                    f'<li><a href="{_art_url(e["rel"])}" target="_blank" rel="noopener">'
                    f'{_esc(e["label"])}</a></li>' for e in evidence_files)
                ev_html = f'<ul>{ev_rows}</ul>'
            else:
                ev_html = '<p class="muted">No raw evidence files are available for this target.</p>'
            body += (f'<div class="card"><h2>Raw evidence files (diagnostic)</h2>{ev_html}'
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
                     'if(need&&!window.confirm("Mark this prospect \\""+s+"\\"? Do this only after a '
                     'real, confirmed client agreement/delivery.")){return;}'
                     'if(m){m.textContent="saving…";}'
                     'fetch("/api/scout/engagement?domain="+encodeURIComponent(DOM)+"&status="+'
                     'encodeURIComponent(s)+(need?"&confirm=1":""),{method:"POST",'
                     'headers:{"X-Scout-CSRF":CSRF,"Content-Type":"application/json"},body:"{}"})'
                     '.then(function(r){return r.json();}).then(function(j){'
                     'if(j.ok){location.reload();}else if(m){m.textContent='
                     '(j.needs_confirmation?"confirmation required":"failed");}})'
                     '.catch(function(){if(m){m.textContent="request error";}});}'
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
                     'if(!window.confirm("Polish with AI may make a PAID model call when a live LLM '
                     'is configured. Budget limits and no-repeat caching arrive in Slice 3, so each '
                     'confirmed click may repeat the call. Continue?")){return;}'
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
                     '.then(function(){POLISHING=false;if(b){b.disabled=false;}});}</script>')

            return _page("AI QA Factory — Target detail", "/scout", body)

        def _scout_incomplete_target_html(self, domain: str, det: dict, nav: str) -> str:
            """Honest incomplete-analysis Target view for a MANUAL_ACTION_REQUIRED / FAILED prospect.

            Renders ONLY persisted truth (never a guessed reason) and never a healthy conclusion:
            0 confirmed findings, the persisted reason/stage/stop-boundary, whether Chromium started
            and the landing loaded, any partial evidence, and the safe recommended operator action."""
            ma = det.get("manual_action") or {}
            run_id = det.get("run") or det.get("scout_run") or ""
            status = det.get("prospect_status") or "INCOMPLETE"
            network = det.get("network") or {}
            media = det.get("media") or []
            evidence_files = det.get("evidence_files") or []

            def _art_url(rel: str) -> str:
                return f'/scout/artifact?run={_esc(run_id)}&rel={_esc(rel)}'

            def _yn(v):
                return "yes" if v is True else ("no" if v is False else "—")

            if ma:
                reason_html = (
                    f'<p><b>Reason:</b> <code>{_esc(str(ma.get("reason","—")))}</code></p>'
                    f'<p><b>Stage:</b> {_esc(str(ma.get("stage","—")))} · '
                    f'<b>Stop boundary:</b> {_esc(str(ma.get("stop_boundary","—")))}</p>'
                    f'<p><b>Chromium started:</b> {_yn(ma.get("chromium_started"))} · '
                    f'<b>Landing page loaded:</b> {_yn(ma.get("landing_loaded"))} · '
                    f'<b>Landing status:</b> {_esc(str(ma.get("landing_status","—")))}</p>'
                    f'<p><b>Recommended action:</b> {_esc(str(ma.get("recommended_action","—")))}</p>')
            else:
                reason_html = ('<p class="muted">No machine-readable reason was persisted for this '
                               'incomplete analysis (older run). It is shown as unavailable rather '
                               'than guessed.</p>')
            partial = []
            if media:
                partial.append(f'{len(media)} evidence file(s) captured before stopping')
            if network.get("status"):
                partial.append(f'landing HTTP {_esc(str(network.get("status")))}')
            partial_html = ('<p><b>Partial evidence:</b> ' + _esc("; ".join(partial)) + '</p>'
                            if partial else '<p class="muted">No partial evidence was collected.</p>')
            if evidence_files:
                ev_items = "".join(
                    f'<li><a href="{_art_url(e["rel"])}" target="_blank" rel="noopener">'
                    f'{_esc(e["label"])}</a></li>' for e in evidence_files)
                partial_html += f'<p><b>Raw evidence files:</b></p><ul>{ev_items}</ul>'
            body = (
                f'<h1>{_esc(domain)}</h1><div class="row">{nav}</div>'
                f'<div class="card"><div class="banner warn">'
                f'<b>Status:</b> {_badge(status)} — analysis incomplete. '
                f'<b>0 confirmed findings — analysis incomplete.</b> '
                f'This target was not fully checked, so no healthy or unhealthy conclusion can be '
                f'drawn.</div></div>'
                f'<div class="card"><h2>Why the analysis stopped</h2>{reason_html}</div>'
                f'<div class="card"><h2>What was collected</h2>{partial_html}'
                f'<p class="muted">Run <code>{_esc(run_id)}</code> · domain '
                f'<code>{_esc(domain)}</code>. Raw diagnostic: '
                f'<a href="/scout/run?id={_esc(run_id)}">back to run results</a>.</p></div>')
            return _page("AI QA Factory — Target (incomplete)", "/scout", body)

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
            rows = []
            for pid, p in sorted(prospects.items()):
                dom = canonical_domain(p.get("url", "") or p.get("final_url", "")) or ""
                status = p.get("status", "")
                total = int(p.get("verified_findings", 0) or 0)
                actionable = int(p.get("verified_defects", 0) or 0)
                info = max(total - actionable, 0)
                complete = "complete" if status == "DONE" else "incomplete"
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
                    f'<tr><td>{_esc(pid)}</td><td>{_esc(dom)}</td><td>{_badge(status)}</td>'
                    f'<td>{actionable}</td><td>{info}</td><td>{_esc(complete)}</td>'
                    f'<td>{cov_cell}</td>'
                    f'<td>{details} · <a href="/api/prospect?run={_esc(run_id)}&id={_esc(pid)}">raw JSON</a></td></tr>')
            table = (f'<table><caption>Targets in run {_esc(run_id)}</caption><tr><th>ID</th>'
                     f'<th>Domain</th><th>Status</th><th>Actionable defects</th>'
                     f'<th>Informational</th><th>Analysis</th><th>Coverage</th><th>Details</th></tr>{"".join(rows)}</table>')
            body = (f'<h1>Run results</h1><div class="row">'
                    f'<a class="chip" href="/scout">Manual URL Scan</a>'
                    f'<a class="chip" href="/scout/history">History</a></div>'
                    f'<div class="card"><p>Run <code>{_esc(run_id)}</code> · '
                    f'{len(prospects)} target(s)</p><div class="scrollx">{table}</div>'
                    f'<p class="muted">Actionable defects + informational observations = total findings. '
                    f'Details opens the human-readable target; raw JSON is a diagnostic.</p></div>')
            return _page("AI QA Factory — Run results", "/scout", body)

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
            body = (f'<h1>Results</h1><div class="row"><a class="chip" href="/scout">Manual URL Scan</a>'
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

        def _activity_json(self, project, include_diagnostics: bool = False):
            events = []
            from core.orchestration.work_execution import WorkExecutionService
            wx = WorkExecutionService(output_dir=service.output_dir)
            index = self._read_model().project_list(
                view="all", include_diagnostics=include_diagnostics)["projects"]
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
            scout_run_id = ""
            # A Scout campaign is real, persisted activity even when it never became a "work"
            # project — merge in the CURRENTLY attached run's own events (same store every other
            # Scout page reads) so a completed scan is never falsely reported as "no activity".
            if not project:
                try:
                    scout_run_id = str(service.status().get("run_id") or "")
                    store = service.store
                    if store is not None:
                        for ev in store.read_events()[-100:]:
                            events.append({
                                "time": str(ev.get("at", "")), "actor": "scout-engine",
                                "action": str(ev.get("event", "scout_event")),
                                "object": scout_run_id or str(ev.get("prospect", "")),
                                "result": ", ".join(
                                    f"{k}={v}" for k, v in ev.items() if k not in ("at", "event"))})
                except Exception:
                    pass
            events.sort(key=lambda e: e["time"], reverse=True)
            return {"schema": "dashboard-read-model/v1", "events": events[:200],
                    "scout_run_partial": bool(scout_run_id) and not events}

        def _activity_page(self, q) -> str:
            diag = self._want_diagnostics(q)
            data = self._activity_json((q.get("project") or [""])[0], diag)
            rows = "".join(
                f'<tr><td class="muted">{_esc(e["time"])}</td><td>{_esc(e["actor"])}</td>'
                f'<td>{_esc(e["action"])}</td><td>{_esc(e["object"])}</td>'
                f'<td class="muted">{_esc(e["result"])}</td></tr>' for e in data["events"])
            if rows:
                table = (f'<table><caption>Recent state transitions</caption><tr><th>Time</th>'
                        f'<th>Actor</th><th>Action</th><th>Project</th><th>Result</th></tr>{rows}'
                        f'</table>')
            elif data.get("scout_run_partial"):
                # A Scout run is attached but has no persisted events (e.g. an older run pre-dating
                # event logging) — say that plainly rather than pretend nothing has happened.
                table = ('<div class="card empty muted">A Scout run is attached, but detailed '
                        'historical activity is unavailable for it.</div>')
            else:
                table = '<div class="card empty muted">No activity yet.</div>'
            toggle = (
                '<a class="chip" href="/activity">&#10003; Production only</a>' if diag else
                '<a class="chip" href="/activity?diagnostics=1">Show diagnostics</a>')
            banner = ('<div class="banner warn">Showing diagnostic activity (smoke/acceptance/demo). '
                      'Not production.</div>' if diag else '')
            return _page("AI QA Factory — Activity", "/activity",
                         f'<h1>Activity</h1>{banner}<div class="row">{toggle}</div>'
                         f'<div class="scrollx">{table}</div>')


        def _settings_page(self) -> str:
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
            body = (
                '<h1>Settings</h1>'
                f'<div class="card"><h2>Workspace</h2>'
                f'<p>Output workspace: <code>{_esc(str(service.output_dir))}</code></p></div>'
                + build_card +
                '<div class="card"><h2>Display density</h2>'
                '<div class="row"><button class="btn" onclick="setDensity(\'comfortable\')">Comfortable</button>'
                '<button class="btn" onclick="setDensity(\'compact\')">Compact</button></div>'
                '<p class="muted">Saved in this browser only (no server preference database).</p></div>'
                '<div class="card"><h2>Scout defaults (bounded, read-only)</h2>'
                '<p class="muted">1–10 public https seeds · static browser · concurrency 1 · read-only.</p></div>'
                f'<div class="card"><h2>Gmail</h2><p>Setup status: {_badge(gmail_state)} '
                '<span class="muted">(no secret is shown; live send is a separate opt-in CLI path)</span></p></div>'
                f'{self._access_section()}')
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
                    f'real live acceptance.</p><div class="scrollx">{table}</div>'
                    f'{self._service_capability_section()}')
            return _page("AI QA Factory — Tools · Tool readiness", "/tools", body)

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
            body = (f'<h1>Documentation</h1><div class="card"><p class="muted">Local documentation '
                    f'(open in your editor):</p><ul>{items}</ul></div>')
            return _page("AI QA Factory — Documentation", "/docs", body)

    return _Handler


# The campaign form uses the shared design-system classes/tokens (a themed .card, tokenised
# textarea/inputs/checkbox, and a .btn primary) so nothing is a default-white control in Dark mode.
# Layout (max-width, field widths) and every safety statement are preserved (no redesign).
_START_PANEL_HTML = """<h2>Start a bounded read-only campaign</h2>
<div class="card" style="max-width:640px">
<p>Runs the existing bounded, read-only Scout engine over 1&ndash;10 <strong>public https</strong>
seeds. It never sends email, submits forms, solves CAPTCHAs, or runs commands. Non-public / private
/ loopback targets are rejected.</p>
<p><label>Public seed URLs (one per line):<br>
<textarea id="seeds" rows="4" placeholder="https://example.com/"></textarea></label></p>
<p><label>Campaign name: <input id="campaign" value="adhoc"></label>
&nbsp;<label>Coverage: <select id="coverage">
<option value="adaptive" selected>Adaptive (recommended) &mdash; up to 12 pages/site</option>
<option value="deep">Deep &mdash; up to 20 pages/site</option></select></label></p>
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
    profile = _COVERAGE_PROFILE_LABEL.get(coverage.get("coverage"), _esc(coverage.get("coverage") or "—"))
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
                     if supported == 1 else f'Supports up to {_esc(supported)} flow step(s).')
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
            f'<td>{_badge(_collapse_ws(f.get("severity")) or _NEUTRAL, _sev_badge_kind(f.get("severity") or ""))}</td>'
            f'<td class="muted">{_esc(kind_label)}</td>'
            f'<td class="muted">{_esc(_confidence_label(f))}</td>'
            f'<td class="muted">{_esc(_collapse_ws(f.get("category")) or _NEUTRAL)}</td>'
            f'<td>{_esc(_collapse_ws(f.get("title")) or _NEUTRAL)}</td>'
            f'<td class="muted">{_esc(_collapse_ws(f.get("business_impact")) or "")}</td>'
            f'<td class="muted"{title_attr}>{_esc(hint)}</td>'
            f'<td class="muted">{_esc(evid or _NEUTRAL)}</td>'
            "</tr>")
    return (f'<table><caption>Problem items ({len(findings)})</caption>'
            '<tr><th>Severity</th><th>Kind</th><th>Confidence</th><th>Type</th><th>Issue</th>'
            '<th>Business impact</th><th>Repro hint</th><th>Evidence</th></tr>'
            + "".join(rows) + "</table>")


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


def _looks_blocked(status: str, reason: str) -> bool:
    """True when a target looks blocked by an access challenge (CAPTCHA / bot wall / 403 / login),
    so the card shows the honest banner + human-in-the-loop rescan button."""
    s = (str(status) + " " + str(reason)).lower()
    return any(k in s for k in ("challenge", "captcha", "blocked", "bot", "403", "forbidden",
                                "rate limit", "access denied", "login wall", "not authorized"))


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
header.top{background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5}
header.top .wrap{max-width:var(--maxw);margin:0 auto;display:flex;align-items:center;gap:var(--gap);padding:10px var(--pad)}
header.top .brand{font-weight:700} header.top nav{display:flex;gap:4px;margin-left:8px}
header.top nav a{padding:6px 12px;border-radius:6px;color:var(--muted)}
header.top nav a[aria-current="page"]{background:var(--surface-2);color:var(--text);font-weight:600;box-shadow:inset 0 -2px 0 var(--accent)}
header.top .brand{color:var(--text)} header.top .brand::before{content:"";display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--accent);margin-right:7px;vertical-align:middle}
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
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--border);background:var(--badge-bg);color:var(--muted)}
.badge.ok{color:var(--ok)} .badge.attention{color:var(--attention)}
.badge.blocked,.badge.danger{color:var(--error)} .badge.done{color:var(--muted)}
.btn{display:inline-block;padding:8px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:14px}
.btn.primary{background:var(--primary);border-color:var(--primary);color:var(--primary-ink);font-weight:600}
.btn.danger{border-color:var(--error);color:var(--error)}
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
@media (max-width:640px){ .only-desktop{display:none} .only-mobile{display:block} }
/* Campaign form: stack each field (label above a full-width control); checkboxes stay inline. */
.formstack label{display:block;margin:0 0 14px;color:var(--text);font-weight:600;font-size:13px}
.formstack label>select,.formstack label>input:not([type=checkbox]){display:block;width:100%;
  max-width:440px;margin-top:5px;font-weight:400}
.formstack label>select[multiple]{max-width:100%}
.formstack>label:has(>input[type=checkbox]){font-weight:400;color:var(--muted)}
.formstack details>summary{margin:2px 0 10px}
/* Comfortable tap targets for chip-styled buttons/links (labels/badges stay compact). */
button.chip,a.chip{min-height:30px;cursor:pointer}
@media (max-width:640px){
  button.chip,a.chip{min-height:44px;padding:8px 16px;font-size:13px}
  input,select,textarea{font-size:16px}   /* >=16px avoids iOS focus zoom */
  h1{font-size:20px}
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
_MORE = (("Collaboration", "/collab"), ("Tools", "/tools"), ("Activity", "/activity"),
         ("Settings", "/settings"), ("Documentation", "/docs"))


def _nav_html(active: str) -> str:
    links = []
    for label, href in _NAV:
        is_cur = (href == active) or (href.startswith("/scout") and active.startswith("/scout"))
        cur = ' aria-current="page"' if is_cur else ""
        links.append(f'<a href="{href}"{cur}>{label}</a>')
    more = "".join(f'<a href="{h}">{lbl}</a>' for lbl, h in _MORE)
    toggle = ('<button type="button" class="theme-toggle" onclick="toggleTheme()" '
              'aria-label="Toggle dark or light theme"><span id="themelabel">Dark</span></button>')
    return (f'<header class="top"><div class="wrap"><span class="brand">AI QA Factory</span>'
            f'<nav aria-label="Primary">{"".join(links)}'
            f'<details style="position:relative"><summary class="btn" style="padding:6px 12px">More</summary>'
            f'<div class="card" style="position:absolute;right:0;min-width:180px;z-index:10">{more}</div>'
            f'</details></nav>{toggle}</div></header>')


# No-flash: set the theme from the app-specific local key BEFORE first paint (dark is the default).
# The theme lives only in localStorage - never in project state and never sent to the backend.
_THEME_HEAD_JS = ("(function(){try{var t=localStorage.getItem('aiqa_theme')||'dark';"
                  "document.documentElement.setAttribute('data-theme',t);}catch(e){"
                  "document.documentElement.setAttribute('data-theme','dark');}})();")
_THEME_TOGGLE_JS = ("function _applyThemeLabel(){var t=document.documentElement."
                    "getAttribute('data-theme')||'dark';var l=document.getElementById('themelabel');"
                    "if(l)l.textContent=t==='light'?'Light':'Dark';}"
                    "function toggleTheme(){var cur=document.documentElement.getAttribute('data-theme')"
                    "==='light'?'light':'dark';var next=cur==='light'?'dark':'light';"
                    "document.documentElement.setAttribute('data-theme',next);"
                    "try{localStorage.setItem('aiqa_theme',next);}catch(e){}_applyThemeLabel();}"
                    "_applyThemeLabel();")


def _build_footer_html() -> str:
    """Compact build-identity footer (version + running SHA, plus a stale-build warning). Never
    raises to the page; cached so it costs no git subprocess per render."""
    try:
        from core.build_identity import current_identity
        ident = current_identity()
    except Exception:
        return ""
    warn = (f'<span style="color:var(--attention);font-weight:600">&#9888; '
            f'{_esc(ident.get("warning",""))}</span> &middot; ' if ident.get("stale") else "")
    return ('<footer style="max-width:var(--maxw);margin:0 auto;padding:10px var(--pad);'
            'color:var(--muted);font-size:12px;border-top:1px solid var(--border)">'
            f'{warn}{_esc(ident.get("product_version",""))} &middot; build '
            f'<code>{_esc(ident.get("running_sha") or "unknown")}</code></footer>')


def _page(title: str, active: str, body: str, script: str = "") -> str:
    scr = f"<script>{_THEME_TOGGLE_JS}{script}</script>"
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<link rel=\"icon\" href=\"data:image/svg+xml,"
            f"%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
            f"%3Crect width='16' height='16' rx='4' fill='%23c9a227'/%3E%3C/svg%3E\">"
            f"<title>{_esc(title)}</title><script>{_THEME_HEAD_JS}</script>"
            f"<style>{_TOKENS_CSS}</style></head><body>"
            f"{_nav_html(active)}<main>{body}</main>{_build_footer_html()}{scr}</body></html>")


def _badge(text: str, kind: str = "") -> str:
    return f'<span class="badge {kind}">{_esc(text)}</span>'


_COLLAB_STATE_KIND = {"NEEDS_OWNER": "attention", "BLOCKED": "blocked", "FIXING": "attention",
                      "WAITING_FOR_CI": "attention", "DONE": "done"}


def _collab_body(snap: dict) -> str:
    """Render the Direct Collaboration Driver monitor (Issue #14.D) — one truthful status area over
    the canonical store: driver heartbeat/spend, an owner-action banner, and a per-thread timeline."""
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
        '<div class="card"><h2 style="margin-top:0">Reviewer driver</h2>'
        f'<p>{_badge(d.get("stage","IDLE"))} &middot; heartbeat {_esc(beat)} {stale}</p>'
        f'<p class="muted">model <code>{model}</code> &middot; effort {effort} &middot; processed '
        f'{int(d.get("processed",0))}</p>'
        f'<p class="muted">today {int(b.get("daily_calls",0))}/{int(b.get("cap_calls",0))} calls '
        f'&middot; {int(b.get("daily_tokens",0))} tokens &middot; '
        f'${float(b.get("daily_usd",0)):.2f}/${float(b.get("cap_usd",0)):.2f} '
        f'<span title="spend is $0 until AIQA_REVIEWER_PRICE_PER_MTOK_IN/OUT is configured; token '
        f'counts are real">(spend est.)</span></p>{err}</div>')

    dl = snap.get("delivery", {})
    bsrc = dl.get("billing_source") or "unknown"
    billing_label = (f'Claude {_esc(dl.get("billing_plan") or "?")} subscription allocation'
                     if bsrc == "subscription" else
                     ("Anthropic API credits" if bsrc == "api_credits" else "unknown (verify via /status)"))
    delivery_card = (
        '<div class="card"><h2 style="margin-top:0">Claude delivery worker</h2>'
        f'<p class="muted">delivered {int(dl.get("delivered",0))} &middot; model '
        f'<code>{_esc(dl.get("claude_model") or "—")}</code> &middot; cost '
        f'${float(dl.get("claude_cost_usd",0)):.4f}</p>'
        f'<p class="muted">billing source: <strong>{billing_label}</strong></p></div>')
    driver_card += delivery_card

    sup = snap.get("supervisor", {})
    if sup.get("installed"):
        sup_state = ('<span style="color:var(--attention);font-weight:600">&#9888; heartbeat stale</span>'
                     if not sup.get("fresh") else "supervisor alive")
        driver_card += (
            '<div class="card"><h2 style="margin-top:0">Durable supervisor</h2>'
            f'<p class="muted">{sup_state} &middot; last check {_esc(_fmt_ts(sup.get("checked_at","")))} '
            f'&middot; at check: up={_esc(str(sup.get("dashboard_up_at_check")))} stale='
            f'{_esc(str(sup.get("dashboard_stale_at_check")))} &middot; action '
            f'{_esc(sup.get("dashboard_action") or "—")}</p></div>')
    else:
        driver_card += ('<div class="card"><h2 style="margin-top:0">Durable supervisor</h2>'
                        '<p class="muted">not installed — run tools/supervisor_install.ps1 for '
                        'session-independent Dashboard + driver recovery</p></div>')

    threads = snap.get("threads", [])
    if not threads:
        rows = '<div class="card"><p class="muted">No collaboration threads yet.</p></div>'
    else:
        cards = []
        for t in threads:
            kind = _COLLAB_STATE_KIND.get(t.get("state", ""), "")
            sha = _esc((t.get("head_sha") or "")[:12] or "—")
            match = ("&#10003; matches head" if t.get("reviewed_sha_matches_head")
                     else ("&#9888; stale head" if t.get("stale_head") else ""))
            dec = (f'<td>{_esc(t.get("decision") or "—")} '
                   f'<span class="muted">{match}</span></td>')
            pr = t.get("pr_number")
            pr_txt = f'#{int(pr)}' if pr else "—"
            timeline = " &rarr; ".join(
                f'{_esc(ev.get("kind",""))}' for ev in t.get("timeline", [])) or "—"
            ci = ", ".join(_esc(r) for r in t.get("ci_refs", [])) or "—"
            cards.append(
                f'<div class="card"><h3 style="margin:0 0 6px">{_esc(t.get("thread_id"))} '
                f'{_badge(t.get("state","") , kind)}</h3>'
                f'<table><tr><td class="muted">actor</td><td>{_esc(t.get("actor"))}</td></tr>'
                f'<tr><td class="muted">now</td><td>{_esc(t.get("current_action"))}</td></tr>'
                f'<tr><td class="muted">next</td><td>{_esc(t.get("next_action"))}</td></tr>'
                f'<tr><td class="muted">branch / PR</td><td>{_esc(t.get("branch") or "—")} &middot; '
                f'{pr_txt}</td></tr>'
                f'<tr><td class="muted">head SHA</td><td><code>{sha}</code></td></tr>'
                f'<tr><td class="muted">decision</td>{dec}</tr>'
                f'<tr><td class="muted">CI evidence</td><td>{ci}</td></tr>'
                f'<tr><td class="muted">timeline</td><td>{timeline}</td></tr></table></div>')
        rows = "".join(cards)

    return (f'<h1>Collaboration</h1><p class="muted">Autonomous GPT reviewer &harr; Claude worker '
            f'&middot; current head <code>{_esc((snap.get("current_head") or "")[:12] or "—")}</code> '
            f'&middot; auto-refreshes</p>{banner}{driver_card}{rows}')


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
