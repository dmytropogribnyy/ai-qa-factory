"""Human-in-the-loop browser sessions for CAPTCHA / access challenges.

The operator explicitly starts one bounded, visible-browser attempt.  The browser remains open in
the worker thread while the Dashboard waits for Continue / Defer / Skip.  No CAPTCHA is solved or
bypassed automatically.  Cookies stay in Playwright process memory only and are never persisted as
evidence.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.scout.discovery.domain_intel import canonical_domain
from core.scout.store import RunStore

_WAIT_TIMEOUT_S = 15 * 60
_TERMINAL = frozenset({"completed", "deferred", "skipped", "failed", "timed_out"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChallengeSessionManager:
    """One process-local browser worker registry with a durable, secret-free status snapshot."""

    def __init__(self, output_dir: str = "outputs", *, wait_timeout_s: float = _WAIT_TIMEOUT_S,
                 backend_factory=None, resolve_dns: bool = True) -> None:
        self.output_dir = str(output_dir)
        self.wait_timeout_s = max(1.0, float(wait_timeout_s))
        self.backend_factory = backend_factory
        self.resolve_dns = bool(resolve_dns)
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._signals: Dict[str, threading.Event] = {}
        self._pending_actions: Dict[str, str] = {}
        self._path = Path(output_dir) / "scout" / "_operator" / "challenge_sessions.json"
        self._load_interrupted()

    def start(self, domain: str, *, source_run: str = "") -> Dict[str, Any]:
        dom = canonical_domain(domain)
        if not dom:
            raise ValueError("invalid domain")
        with self._lock:
            for item in self._sessions.values():
                if item.get("domain") == dom and item.get("state") not in _TERMINAL:
                    return dict(item)
            sid = f"manual-{dom[:80]}-{time.time_ns()}".replace("/", "-").replace("\\", "-")
            session = {
                "id": sid,
                "domain": dom,
                "source_run": str(source_run or "").strip(),
                "result_run": sid,
                "state": "opening",
                "reason": "",
                "message": "Opening a visible Chromium window…",
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._sessions[sid] = session
            self._signals[sid] = threading.Event()
            self._pending_actions[sid] = ""
            self._persist_locked()
        threading.Thread(target=self._run, args=(sid,), name=f"manual-check:{sid}",
                         daemon=True).start()
        return dict(session)

    def signal(self, session_id: str, action: str) -> Dict[str, Any]:
        action = str(action or "").strip().lower()
        if action not in ("continue", "defer", "skip"):
            raise ValueError("action must be continue, defer, or skip")
        with self._lock:
            item = self._sessions.get(session_id)
            if item is None:
                raise KeyError("manual-check session not found")
            if item.get("state") in _TERMINAL:
                return dict(item)
            self._pending_actions[session_id] = action
            item["state"] = {
                "continue": "continuing",
                "defer": "defer_requested",
                "skip": "skip_requested",
            }[action]
            item["message"] = {
                "continue": "Checking the page again in the same browser session…",
                "defer": "Manual check deferred. You can start a fresh attempt later.",
                "skip": "Target skipped for this manual attempt.",
            }[action]
            item["updated_at"] = _now()
            self._persist_locked()
            signal = self._signals.get(session_id)
        if signal is not None:
            signal.set()
        return dict(item)

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._sessions.get(str(session_id or ""))
            return dict(item) if item else None

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            sessions = [dict(v) for v in self._sessions.values()]
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        blocked = _blocked_targets(self.output_dir)
        active_domains = {s.get("domain") for s in sessions if s.get("state") not in _TERMINAL}
        for row in blocked:
            row["active_session"] = row.get("domain") in active_domains
        return {
            "schema": "scout-manual-checks/v1",
            "open_count": sum(1 for s in sessions if s.get("state") not in _TERMINAL),
            "sessions": sessions[:100],
            "blocked_targets": blocked[:200],
        }

    def _manual_gate(self, session_id: str, _page, obs) -> str:
        with self._lock:
            item = self._sessions[session_id]
            item.update({
                "state": "waiting",
                "reason": ("CAPTCHA / human verification" if obs.captcha_marker
                           else f"Access challenge (HTTP {obs.status or 'unknown'})"),
                "message": ("Complete the check in the visible browser, then choose Continue. "
                            "The browser will stay open for up to 15 minutes."),
                "updated_at": _now(),
            })
            self._pending_actions[session_id] = ""
            signal = self._signals[session_id]
            signal.clear()
            self._persist_locked()
        if not signal.wait(self.wait_timeout_s):
            with self._lock:
                item = self._sessions[session_id]
                item["state"] = "timed_out"
                item["message"] = "Manual check timed out; start a fresh attempt when ready."
                item["updated_at"] = _now()
                self._persist_locked()
            return "defer"
        with self._lock:
            return self._pending_actions.get(session_id) or "defer"

    def _run(self, session_id: str) -> None:
        with self._lock:
            session = dict(self._sessions[session_id])
        dom = session["domain"]
        run_id = session["result_run"]
        try:
            from core.scout.backends import PlaywrightBackend
            from core.scout.config import ScoutRunConfig
            from core.scout.engine import ScoutEngine

            cfg = ScoutRunConfig(
                campaign_name="manual-challenge",
                seeds=[f"https://{dom}/"],
                max_sites=1,
                browser_mode="playwright",
                output_dir=self.output_dir,
                run_id=run_id,
                resolve_dns=self.resolve_dns,
            )
            store = RunStore(self.output_dir, run_id)
            if self.backend_factory is not None:
                backend = self.backend_factory(
                    policy=cfg.url_policy(), headful=True,
                    manual_gate=lambda page, obs: self._manual_gate(session_id, page, obs))
            else:
                backend = PlaywrightBackend(
                    policy=cfg.url_policy(), headful=True,
                    manual_gate=lambda page, obs: self._manual_gate(session_id, page, obs))
            state = ScoutEngine(cfg, store, backend=backend).run()
            prospects = state.get("prospects", {}) or {}
            result = next(iter(prospects.values()), {}) or {}
            status = str(result.get("status") or "")
            with self._lock:
                item = self._sessions[session_id]
                requested = self._pending_actions.get(session_id, "")
                if requested == "skip":
                    final_state, message = "skipped", "Target skipped; the original evidence remains."
                elif requested == "defer" or item.get("state") == "timed_out":
                    final_state = "timed_out" if item.get("state") == "timed_out" else "deferred"
                    message = item.get("message") or "Manual check deferred."
                elif status == "DONE":
                    final_state = "completed"
                    message = "Manual check cleared and the bounded QA analysis completed."
                elif status == "MANUAL_ACTION_REQUIRED":
                    final_state = "deferred"
                    message = "The challenge was still present; no full QA conclusion was made."
                else:
                    final_state = "failed"
                    message = f"Manual attempt ended with {status or 'an unknown status'}."
                item.update({"state": final_state, "message": message, "updated_at": _now()})
                self._persist_locked()
            if status == "DONE":
                from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
                AnalyzedSiteRegistry(self.output_dir).record_analysis(
                    dom, status=ANALYZED, evidence_ref=f"scout/{run_id}",
                    campaign_id=run_id)
        except Exception as exc:  # browser/dependency errors are operator-visible, never silent
            with self._lock:
                item = self._sessions[session_id]
                item.update({
                    "state": "failed",
                    "message": f"Could not run the manual browser check: {type(exc).__name__}: {str(exc)[:160]}",
                    "updated_at": _now(),
                })
                self._persist_locked()

    def _load_interrupted(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in raw.get("sessions", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            rec = dict(item)
            if rec.get("state") not in _TERMINAL:
                rec["state"] = "failed"
                rec["message"] = ("The Dashboard restarted while the browser was open. "
                                  "Start a fresh manual attempt.")
                rec["updated_at"] = _now()
            self._sessions[rec["id"]] = rec

    def _persist_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "scout-manual-checks/v1",
            "sessions": sorted(self._sessions.values(),
                               key=lambda x: x.get("updated_at", ""), reverse=True)[:100],
        }
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)


def _blocked_targets(output_dir: str) -> List[Dict[str, Any]]:
    """Read-only inventory of persisted targets that still need human attention."""
    base = Path(output_dir) / "scout"
    rows: List[Dict[str, Any]] = []
    if not base.is_dir():
        return rows
    for state_path in base.glob("*/state.json"):
        run_id = state_path.parent.name
        if run_id.startswith("_"):
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for pid, prospect in (state.get("prospects", {}) or {}).items():
            if not isinstance(prospect, dict) or prospect.get("status") != "MANUAL_ACTION_REQUIRED":
                continue
            dom = canonical_domain(prospect.get("url", "") or prospect.get("final_url", "")) or ""
            reason = str(prospect.get("reason") or "")
            try:
                manual = json.loads(
                    (state_path.parent / "prospects" / pid / "manual_action.json").read_text(
                        encoding="utf-8"))
                reason = str(manual.get("reason") or reason)
            except (OSError, ValueError):
                pass
            rows.append({
                "domain": dom,
                "run_id": run_id,
                "prospect_id": pid,
                "reason": reason,
                "updated_at": str(state.get("finished_at") or state.get("updated_at") or ""),
            })
    rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return rows
