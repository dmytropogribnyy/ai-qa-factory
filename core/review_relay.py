"""File-backed review relay between a worker agent and an independent reviewer.

The relay is deliberately narrow: it stores bounded, redacted checkpoint/decision/ack records under
``<AIQA_OUTPUT_ROOT>/_review_relay``. It cannot execute shell commands, modify source code, merge pull
requests, send outreach, or approve delivery. Separate MCP processes expose role-specific tools over
this shared store (worker vs reviewer), so the existing read-only Observer remains unchanged.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from core.orchestration.content_safety import redact_intake_text

_RELAY_API_VERSION = "review-relay/v1"
_SAFE_ID = re.compile(r"^rr-[0-9A-Za-z._-]{8,96}$")
_ALLOWED_DECISIONS = {"GO", "NO-GO", "COMMENT"}
_ALLOWED_STATUSES = {"pending", "decided", "acked", "all"}


class ReviewRelayError(ValueError):
    """Raised for invalid or conflicting relay operations."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, *, limit: int) -> str:
    # Redact FIRST, then bound the length. Truncating first could split a secret across the limit so
    # the length-sensitive redaction patterns (e.g. Bearer tokens require >=16 chars) no longer match
    # the truncated fragment, leaking it. Redaction on the full text always removes the whole secret.
    redacted = redact_intake_text(str(value or "").strip()).text
    return redacted[:limit]


def _sha(value: Any) -> str:
    sha = _text(value, limit=64).lower()
    if sha and not re.fullmatch(r"[0-9a-f]{7,64}", sha):
        raise ReviewRelayError("head/base SHA must be 7-64 lowercase hexadecimal characters")
    return sha


class ReviewRelay:
    """Cross-process-safe review queue using immutable per-record JSON files."""

    def __init__(self, output_root: str = "outputs") -> None:
        self._base = Path(output_root) / "_review_relay"
        self._checkpoints = self._base / "checkpoints"
        self._decisions = self._base / "decisions"
        self._acks = self._base / "acks"
        for path in (self._checkpoints, self._decisions, self._acks):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(checkpoint_id: str) -> str:
        value = str(checkpoint_id or "").strip()
        if not _SAFE_ID.fullmatch(value):
            raise ReviewRelayError("invalid checkpoint_id")
        return value

    @staticmethod
    def _read(path: Path) -> Dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ReviewRelayError("record not found") from exc
        except (OSError, ValueError) as exc:
            raise ReviewRelayError("record is unreadable") from exc
        if not isinstance(data, dict):
            raise ReviewRelayError("record is malformed")
        return data

    @staticmethod
    def _write_once(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
                fh.write("\n")
        except FileExistsError as exc:
            raise ReviewRelayError("record already exists") from exc

    def submit_checkpoint(
        self,
        *,
        slice_name: str,
        branch: str,
        head_sha: str,
        summary: str,
        question: str = "",
        evidence: str = "",
        base_sha: str = "",
        pr_number: Any = None,
    ) -> Dict[str, Any]:
        head = _sha(head_sha)
        if not head:
            raise ReviewRelayError("head_sha is required")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        checkpoint_id = f"rr-{stamp}-{uuid4().hex[:10]}"
        pr = None
        if pr_number not in (None, ""):
            try:
                pr = max(1, int(pr_number))
            except (TypeError, ValueError) as exc:
                raise ReviewRelayError("pr_number must be a positive integer") from exc
        payload = {
            "api_version": _RELAY_API_VERSION,
            "checkpoint_id": checkpoint_id,
            "created_at": _now(),
            "slice_name": _text(slice_name, limit=160),
            "branch": _text(branch, limit=200),
            "head_sha": head,
            "base_sha": _sha(base_sha),
            "pr_number": pr,
            "summary": _text(summary, limit=16000),
            "question": _text(question, limit=6000),
            "evidence": _text(evidence, limit=16000),
            "status": "pending",
            "merge_authorized": False,
        }
        self._write_once(self._checkpoints / f"{checkpoint_id}.json", payload)
        return dict(payload)

    def get_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        cid = self._validate_id(checkpoint_id)
        result = self._read(self._checkpoints / f"{cid}.json")
        decision_path = self._decisions / f"{cid}.json"
        ack_path = self._acks / f"{cid}.json"
        if decision_path.exists():
            result["decision"] = self._read(decision_path)
            result["status"] = "acked" if ack_path.exists() else "decided"
        if ack_path.exists():
            result["ack"] = self._read(ack_path)
        return result

    def list_checkpoints(self, *, status: str = "pending", limit: int = 20) -> Dict[str, Any]:
        wanted = str(status or "pending").strip().lower()
        if wanted not in _ALLOWED_STATUSES:
            raise ReviewRelayError("status must be pending, decided, acked, or all")
        bounded_limit = max(1, min(int(limit), 100))
        rows: List[Dict[str, Any]] = []
        for path in self._checkpoints.glob("rr-*.json"):
            try:
                full = self.get_checkpoint(path.stem)
            except ReviewRelayError:
                continue
            if wanted != "all" and full.get("status") != wanted:
                continue
            rows.append({
                "checkpoint_id": full.get("checkpoint_id", ""),
                "created_at": full.get("created_at", ""),
                "slice_name": full.get("slice_name", ""),
                "branch": full.get("branch", ""),
                "head_sha": full.get("head_sha", ""),
                "pr_number": full.get("pr_number"),
                "status": full.get("status", "pending"),
                "summary_preview": str(full.get("summary", ""))[:600],
                "question_preview": str(full.get("question", ""))[:400],
            })
        rows.sort(key=lambda item: (item.get("created_at", ""), item.get("checkpoint_id", "")),
                  reverse=True)
        return {"api_version": _RELAY_API_VERSION, "total": len(rows),
                "checkpoints": rows[:bounded_limit]}

    def post_decision(
        self,
        *,
        checkpoint_id: str,
        decision: str,
        reviewed_sha: str,
        message: str,
        reviewer: str = "gpt-reviewer",
    ) -> Dict[str, Any]:
        cid = self._validate_id(checkpoint_id)
        checkpoint = self._read(self._checkpoints / f"{cid}.json")
        verdict = str(decision or "").strip().upper()
        if verdict not in _ALLOWED_DECISIONS:
            raise ReviewRelayError("decision must be GO, NO-GO, or COMMENT")
        reviewed = _sha(reviewed_sha)
        expected = str(checkpoint.get("head_sha", "")).lower()
        if verdict in {"GO", "NO-GO"} and reviewed != expected:
            raise ReviewRelayError("reviewed_sha does not match the checkpoint head_sha")
        payload = {
            "api_version": _RELAY_API_VERSION,
            "checkpoint_id": cid,
            "created_at": _now(),
            "decision": verdict,
            "reviewed_sha": reviewed,
            "message": _text(message, limit=16000),
            "reviewer": _text(reviewer, limit=120) or "gpt-reviewer",
            "merge_authorized": False,
            "next_slice_authorized": verdict == "GO",
        }
        self._write_once(self._decisions / f"{cid}.json", payload)
        return dict(payload)

    def get_decision(self, checkpoint_id: str) -> Dict[str, Any]:
        cid = self._validate_id(checkpoint_id)
        self._read(self._checkpoints / f"{cid}.json")
        path = self._decisions / f"{cid}.json"
        if not path.exists():
            return {"api_version": _RELAY_API_VERSION, "checkpoint_id": cid, "status": "pending"}
        payload = self._read(path)
        payload["status"] = "acked" if (self._acks / f"{cid}.json").exists() else "decided"
        return payload

    def acknowledge_decision(self, *, checkpoint_id: str, note: str = "") -> Dict[str, Any]:
        cid = self._validate_id(checkpoint_id)
        decision = self.get_decision(cid)
        if decision.get("status") == "pending":
            raise ReviewRelayError("cannot acknowledge before a decision exists")
        payload = {
            "api_version": _RELAY_API_VERSION,
            "checkpoint_id": cid,
            "created_at": _now(),
            "decision": decision.get("decision", ""),
            "reviewed_sha": decision.get("reviewed_sha", ""),
            "note": _text(note, limit=4000),
        }
        self._write_once(self._acks / f"{cid}.json", payload)
        return dict(payload)

    def status(self) -> Dict[str, Any]:
        pending = self.list_checkpoints(status="pending", limit=100)["total"]
        decided = self.list_checkpoints(status="decided", limit=100)["total"]
        acked = self.list_checkpoints(status="acked", limit=100)["total"]
        return {"api_version": _RELAY_API_VERSION, "pending": pending,
                "decided": decided, "acked": acked,
                "capabilities": ["checkpoint_queue", "sha_bound_decisions", "audit_ack"],
                "prohibited": ["shell", "source_write", "git_merge", "external_send"]}
