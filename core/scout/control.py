"""Cooperative run control for the Scout engine (Phase 8.3).

Thread-safe pause / resume / cancel / global-kill. The engine checks these cooperatively
between prospects and between checks, so a kill stops future work and interrupts the active
safe loop promptly. There is no forced thread termination (no unsafe interruption).
"""
from __future__ import annotations

import threading
import time


class RunControl:
    def __init__(self) -> None:
        self._paused = threading.Event()
        self._cancelled = threading.Event()
        self._killed = threading.Event()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def cancel(self) -> None:
        self._cancelled.set()
        self._paused.clear()

    def kill(self) -> None:
        self._killed.set()
        self._cancelled.set()
        self._paused.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set() and not self._killed.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_killed(self) -> bool:
        return self._killed.is_set()

    def should_stop(self) -> bool:
        return self._killed.is_set() or self._cancelled.is_set()

    def wait_while_paused(self, poll: float = 0.02) -> None:
        while self._paused.is_set() and not self.should_stop():
            time.sleep(poll)
