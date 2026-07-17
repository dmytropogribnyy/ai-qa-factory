"""Scout run service (Phase 8.3).

Manages at most one active run in a background daemon thread, exposing control
(pause/resume/cancel/global-kill) and read access to the run store. The dashboard talks to
this service; nothing here performs any external side effect.

A run is either OWNED (started here — controllable, and the report is built when it finishes
successfully) or READ-ONLY ATTACHED (a finished run opened for viewing — controls fail closed
rather than pretending to succeed).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from core.scout.config import ScoutRunConfig, fresh_run_id
from core.scout.control import RunControl
from core.scout.engine import RUN_COMPLETED, RUN_FAILED, ScoutEngine
from core.scout.store import RunStore

_CONTROL_ACTIONS = ("pause", "resume", "cancel", "kill")


class ScoutService:
    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._store: Optional[RunStore] = None
        self._control: Optional[RunControl] = None
        self._thread: Optional[threading.Thread] = None
        self._events: List[Dict[str, Any]] = []
        self._run_id: str = ""

    # --- lifecycle --------------------------------------------------------
    def start(self, config: ScoutRunConfig, clock=None, backend=None) -> str:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a run is already active")
            run_id = config.run_id or fresh_run_id(config.campaign_name)
            config.run_id = run_id
            store = RunStore(self.output_dir, run_id)
            control = RunControl()
            self._events = []

            def _progress(event: Dict[str, Any]) -> None:
                self._events.append(event)
                del self._events[:-500]  # bounded ring buffer

            engine_kwargs: Dict[str, Any] = {"control": control, "progress": _progress}
            if clock is not None:
                engine_kwargs["clock"] = clock
            if backend is not None:
                engine_kwargs["backend"] = backend
            engine = ScoutEngine(config, store, **engine_kwargs)
            thread = threading.Thread(target=self._worker, args=(engine, store),
                                      name=f"scout-{run_id}", daemon=True)
            self._store, self._control, self._thread, self._run_id = store, control, thread, run_id
            thread.start()
            return run_id

    def _worker(self, engine: ScoutEngine, store: RunStore) -> None:
        """Run the engine, then build the report on a clean completion. Failures are recorded
        honestly (status FAILED) instead of leaving a run wedged at RUNNING."""
        try:
            state = engine.run()
        except Exception as exc:  # a top-level failure must not leave status RUNNING
            self._record_failure(store, exc)
            return
        if state.get("status") == RUN_COMPLETED:
            try:
                from core.scout.report import build_report
                build_report(store)
            except Exception as exc:  # report failure is recorded, run stays completed
                self._events.append({"event": "report_failed", "error": str(exc)[:160]})

    @staticmethod
    def _record_failure(store: RunStore, exc: Exception) -> None:
        try:
            state = store.load_state() if store.exists() else {"run_id": store.root.name}
        except Exception:
            state = {"run_id": store.root.name}
        state["status"] = RUN_FAILED
        state["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        try:
            store.save_state(state)
        except Exception:
            pass

    def attach(self, run_id: str) -> None:
        """Attach READ-ONLY to an existing run store (for viewing a finished run).

        No worker and no control are created, so controls fail closed for this run.
        """
        with self._lock:
            self._store = RunStore(self.output_dir, run_id)
            self._control = None
            self._thread = None
            self._events = []
            self._run_id = run_id

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # --- control ----------------------------------------------------------
    def owns_active_worker(self) -> bool:
        """True only when this service started the run (so controls really affect it)."""
        return self._control is not None and self._thread is not None

    @property
    def mode(self) -> str:
        if self.owns_active_worker():
            return "ACTIVE" if self.is_running() else "OWNED_FINISHED"
        if self._store is not None:
            return "READ_ONLY_ATTACHED"
        return "IDLE"

    def control(self, action: str) -> Tuple[bool, int, str]:
        """Apply a control signal. Returns (ok, http_status, message).

        Fails closed (409) for a read-only attached run — it must never pretend a control
        succeeded. For an owned run the signal is genuinely recorded (idempotent even if the
        run just finished, which is honest, not fake).
        """
        if action not in _CONTROL_ACTIONS:
            return False, 400, f"unknown control action: {action!r}"
        with self._lock:
            if self._control is None:
                return False, 409, "no active controllable run (read-only attached or idle)"
            getattr(self._control, action)()
        running = self.is_running()
        return True, 200, "ok" if running else "signal recorded (run already finished)"

    # Thin wrappers retained for direct/in-process callers (no-op if no owned control).
    def pause(self) -> None:
        if self._control:
            self._control.pause()

    def resume(self) -> None:
        if self._control:
            self._control.resume()

    def cancel(self) -> None:
        if self._control:
            self._control.cancel()

    def kill(self) -> None:
        if self._control:
            self._control.kill()

    # --- read -------------------------------------------------------------
    @property
    def store(self) -> Optional[RunStore]:
        return self._store

    @property
    def run_id(self) -> str:
        return self._run_id

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        state: Dict[str, Any] = {}
        if self._store is not None and self._store.exists():
            try:
                state = self._store.load_state()
            except Exception as exc:
                state = {"status": "UNKNOWN", "error": str(exc)[:120]}
        control_flags = {}
        if self._control is not None:
            control_flags = {
                "paused": self._control.is_paused,
                "cancelled": self._control.is_cancelled,
                "killed": self._control.is_killed,
            }
        return {
            "run_id": self._run_id,
            "running": self.is_running(),
            "mode": self.mode,
            "controllable": self.owns_active_worker(),
            "control": control_flags,
            "state": state,
        }

    def recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        if self._events:
            return self._events[-limit:]
        if self._store is not None:
            try:
                return self._store.read_events()[-limit:]
            except Exception:
                return []
        return []
