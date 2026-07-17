"""Scout run service (Phase 8.3).

Manages at most one active run in a background daemon thread, exposing control
(pause/resume/cancel/global-kill) and read access to the run store. The dashboard talks to
this service; nothing here performs any external side effect.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from core.scout.config import ScoutRunConfig, make_run_id
from core.scout.control import RunControl
from core.scout.engine import ScoutEngine
from core.scout.store import RunStore


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
    def start(self, config: ScoutRunConfig, clock=None) -> str:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a run is already active")
            run_id = config.run_id or make_run_id(config.campaign_name, config.seeds, "now")
            config.run_id = run_id
            store = RunStore(self.output_dir, run_id)
            control = RunControl()
            self._events = []

            def _progress(event: Dict[str, Any]) -> None:
                self._events.append(event)
                del self._events[:-500]  # bounded ring buffer

            engine_kwargs = {"control": control, "progress": _progress}
            if clock is not None:
                engine_kwargs["clock"] = clock
            engine = ScoutEngine(config, store, **engine_kwargs)
            thread = threading.Thread(target=engine.run, name=f"scout-{run_id}", daemon=True)
            self._store, self._control, self._thread, self._run_id = store, control, thread, run_id
            thread.start()
            return run_id

    def attach(self, run_id: str) -> None:
        """Attach read-only to an existing run store (for viewing a finished run)."""
        with self._lock:
            self._store = RunStore(self.output_dir, run_id)
            self._run_id = run_id

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # --- control ----------------------------------------------------------
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
