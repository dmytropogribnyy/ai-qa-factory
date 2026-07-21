"""Immutable, deduped collaboration thread store (Issue #14.A2).

Envelopes persist as write-once JSON files under the SAME ``<output_root>/_review_relay`` base the
review relay already uses — there is exactly one canonical collaboration store, never a second DB.
Each envelope is keyed by ``thread_id/idempotency_key`` so replaying the same logical message (after a
retry or a driver restart) is a no-op rather than a duplicate. The store enforces envelope-level
SHA binding: a DECISION whose ``reviewed_sha`` does not match the CHECKPOINT it answers is refused,
so a verdict can never be recorded against a moved head.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REQUIRED_KEYS = ("kind", "thread_id", "idempotency_key")
_REQUEST_KINDS = {"QUESTION", "PROPOSAL", "CHECKPOINT"}
_REPLY_KINDS = {"RESPONSE", "CRITIQUE", "RECOMMENDATION", "DECISION"}


class CollaborationStoreError(ValueError):
    """Raised for an invalid, conflicting, or stale collaboration store operation."""


class CollaborationStore:
    """Cross-process-safe, append-only collaboration thread log over immutable per-message files."""

    def __init__(self, output_root: str = "outputs") -> None:
        self._base = Path(output_root) / "_review_relay"
        self._messages = self._base / "collab_messages"
        self._messages.mkdir(parents=True, exist_ok=True)

    # --- write ----------------------------------------------------------------------------------
    def append(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        for key in _REQUIRED_KEYS:
            if not str(envelope.get(key, "")).strip():
                raise CollaborationStoreError(f"envelope is missing required field: {key}")
        thread = str(envelope["thread_id"])
        key = str(envelope["idempotency_key"])
        thread_dir = self._messages / thread
        thread_dir.mkdir(parents=True, exist_ok=True)
        path = thread_dir / f"{key}.json"
        if path.exists():
            return self._read(path)                 # idempotent replay: restart/retry-safe

        if envelope["kind"] == "DECISION":
            self._assert_decision_binds_to_checkpoint(thread, envelope)

        record = dict(envelope)
        record["message_id"] = f"{thread}:{key}"
        record["stored_at"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        self._write_once(path, record)
        return record

    def _assert_decision_binds_to_checkpoint(self, thread: str, decision: Dict[str, Any]) -> None:
        target = str(decision.get("in_reply_to", "")).strip()
        if not target:
            return                                  # unsolicited decision; nothing to bind against
        cp_path = self._messages / thread / f"{target}.json"
        if not cp_path.exists():
            return
        checkpoint = self._read(cp_path)
        if checkpoint.get("kind") != "CHECKPOINT":
            return
        if str(decision.get("reviewed_sha", "")).lower() != str(checkpoint.get("head_sha", "")).lower():
            raise CollaborationStoreError(
                "stale decision: reviewed_sha does not match the checkpoint head_sha")

    # --- read -----------------------------------------------------------------------------------
    def thread(self, thread_id: str) -> Dict[str, Any]:
        messages = self._thread_messages(thread_id)
        return {"thread_id": thread_id, "count": len(messages), "messages": messages}

    def _thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        thread_dir = self._messages / str(thread_id)
        if not thread_dir.is_dir():
            return []
        rows: List[Dict[str, Any]] = []
        for path in thread_dir.glob("*.json"):
            try:
                rows.append(self._read(path))
            except CollaborationStoreError:
                continue
        rows.sort(key=lambda m: (m.get("stored_at", ""), m.get("message_id", "")))
        return rows

    def threads(self) -> List[str]:
        return sorted(p.name for p in self._messages.glob("*") if p.is_dir())

    def open_requests(self) -> List[Dict[str, Any]]:
        """Request envelopes (question/proposal/checkpoint) that have no reply yet — the driver's queue."""
        pending: List[Dict[str, Any]] = []
        for thread_id in self.threads():
            messages = self._thread_messages(thread_id)
            answered = {str(m.get("in_reply_to", "")) for m in messages if m.get("kind") in _REPLY_KINDS}
            for m in messages:
                if m.get("kind") in _REQUEST_KINDS and m.get("idempotency_key") not in answered:
                    pending.append(m)
        pending.sort(key=lambda m: (m.get("stored_at", ""), m.get("message_id", "")))
        return pending

    def latest_decision(self, thread_id: str) -> Optional[Dict[str, Any]]:
        decisions = [m for m in self._thread_messages(thread_id) if m.get("kind") == "DECISION"]
        return decisions[-1] if decisions else None

    @staticmethod
    def _read(path: Path) -> Dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CollaborationStoreError("message not found") from exc
        except (OSError, ValueError) as exc:
            raise CollaborationStoreError("message is unreadable") from exc
        if not isinstance(data, dict):
            raise CollaborationStoreError("message is malformed")
        return data

    @staticmethod
    def _write_once(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
                fh.write("\n")
        except FileExistsError as exc:
            raise CollaborationStoreError("message already exists") from exc
