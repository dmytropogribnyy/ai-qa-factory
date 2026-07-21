"""Budget + reliability guardrails for the collaboration driver (Issue #14.E).

The full product-wide LLM ledger is deferred to Slice 3; this is the minimal local safety envelope the
driver cannot ship without: per-review input/output limits, per-thread and daily spend/call caps,
bounded retries with exponential backoff, an idempotent response cache keyed by message fingerprint,
and — crucially — a **fail-closed** verdict so a reached cap stops the loop and escalates to the owner
instead of spending further. Usage events and cache entries persist under the SAME ``_review_relay``
base so there is no second store and everything survives a restart.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from core.orchestration.content_safety import redact_intake_text


class RetryExhausted(RuntimeError):
    """Raised when bounded retries are exhausted without success (never an unlimited loop)."""


@dataclass(frozen=True)
class BudgetPolicy:
    max_input_chars: int = 60000
    max_output_chars: int = 20000
    per_thread_calls: int = 12
    per_thread_usd: float = 2.0
    daily_calls: int = 100
    daily_usd: float = 10.0
    max_retries: int = 3
    backoff_base_seconds: float = 1.0


@dataclass(frozen=True)
class BudgetVerdict:
    allowed: bool
    reason: str = ""
    cap: str = ""


def run_with_retries(fn: Callable[[], Any], *, policy: BudgetPolicy,
                     sleep: Callable[[float], None]) -> Any:
    """Call ``fn`` up to ``policy.max_retries`` times with exponential backoff; then fail closed."""
    attempts = max(1, int(policy.max_retries))
    last_exc: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - bounded retry wraps any transient failure
            last_exc = exc
            if attempt < attempts - 1:
                sleep(policy.backoff_base_seconds * (2 ** attempt))
    raise RetryExhausted(f"exhausted {attempts} attempts: {last_exc}") from last_exc


class BudgetLedger:
    """Append-only usage ledger + response cache with fail-closed cap checks."""

    def __init__(self, output_root: str = "outputs", policy: Optional[BudgetPolicy] = None,
                 clock: Optional[Callable[[], str]] = None) -> None:
        self._policy = policy or BudgetPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        base = Path(output_root) / "_review_relay"
        self._events = base / "collab_budget"
        self._cache = base / "collab_cache"
        for path in (self._events, self._cache):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def policy(self) -> BudgetPolicy:
        return self._policy

    def _today(self) -> str:
        return str(self._clock())[:10]

    # --- usage ----------------------------------------------------------------------------------
    def record(self, thread_id: str, *, calls: int = 1, usd: float = 0.0,
               input_chars: int = 0, output_chars: int = 0, input_tokens: int = 0,
               output_tokens: int = 0, total_tokens: int = 0) -> Dict[str, Any]:
        event = {"thread_id": str(thread_id), "date": self._today(), "calls": int(calls),
                 "usd": float(usd), "input_chars": int(input_chars),
                 "output_chars": int(output_chars), "input_tokens": int(input_tokens),
                 "output_tokens": int(output_tokens), "total_tokens": int(total_tokens),
                 "at": self._clock()}
        path = self._events / f"{event['date']}-{uuid4().hex}.json"
        with path.open("x", encoding="utf-8") as fh:
            json.dump(event, fh, ensure_ascii=False, sort_keys=True)
        return event

    def _events_today(self):
        today = self._today()
        for path in self._events.glob(f"{today}-*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("date") == today:
                yield data

    def usage(self, thread_id: str) -> Dict[str, Any]:
        tid = str(thread_id)
        t_calls = t_usd = d_calls = d_usd = d_tokens = t_tokens = 0.0
        for e in self._events_today():
            d_calls += e.get("calls", 0)
            d_usd += e.get("usd", 0.0)
            d_tokens += e.get("total_tokens", 0)
            if e.get("thread_id") == tid:
                t_calls += e.get("calls", 0)
                t_usd += e.get("usd", 0.0)
                t_tokens += e.get("total_tokens", 0)
        return {"thread_calls": int(t_calls), "thread_usd": round(t_usd, 6),
                "thread_tokens": int(t_tokens), "daily_calls": int(d_calls),
                "daily_usd": round(d_usd, 6), "daily_tokens": int(d_tokens)}

    def check(self, thread_id: str) -> BudgetVerdict:
        u = self.usage(thread_id)
        p = self._policy
        if u["daily_calls"] >= p.daily_calls:
            return BudgetVerdict(False, "daily call cap reached", "daily_calls")
        if u["daily_usd"] >= p.daily_usd:
            return BudgetVerdict(False, "daily spend cap reached", "daily_usd")
        if u["thread_calls"] >= p.per_thread_calls:
            return BudgetVerdict(False, "per-thread call cap reached", "per_thread_calls")
        if u["thread_usd"] >= p.per_thread_usd:
            return BudgetVerdict(False, "per-thread spend cap reached", "per_thread_usd")
        return BudgetVerdict(True)

    # --- input clamp + response cache -----------------------------------------------------------
    def clamp_input(self, text: str) -> str:
        return redact_intake_text(str(text or "")).text[: self._policy.max_input_chars]

    def cache_get(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        path = self._cache / f"{self._safe(fingerprint)}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def cache_put(self, fingerprint: str, response: Dict[str, Any]) -> None:
        path = self._cache / f"{self._safe(fingerprint)}.json"
        if path.exists():
            return                                  # idempotent: first cached response wins
        with path.open("x", encoding="utf-8") as fh:
            json.dump(response, fh, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _safe(fingerprint: str) -> str:
        token = "".join(c for c in str(fingerprint) if c.isalnum() or c in "._-")
        if not token:
            raise ValueError("invalid cache fingerprint")
        return token[:96]
