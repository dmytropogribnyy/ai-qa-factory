"""Durable operator-only archive and cleanup state for Scout.

This module deliberately does not create another prospect/run store.  It adds a small, atomic
overlay beside the existing Scout stores so the Dashboard can hide archived targets/runs and audit
operator cleanup actions without changing analytical truth.  Destructive cleanup remains explicit
and path-confined; the default action is always reversible archive.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from core.scout.store import RunStore, StoreError

_HEAVY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4", ".har", ".zip",
})
_HEAVY_NAMES = frozenset({"browser_trace.json"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique(values: Iterable[str]) -> List[str]:
    return sorted({str(v or "").strip() for v in values if str(v or "").strip()})


class OperatorStateStore:
    """Atomic archive/cleanup overlay under ``outputs/scout/_operator``."""

    def __init__(self, output_dir: str = "outputs") -> None:
        self.output_dir = Path(output_dir).resolve()
        self.root = (self.output_dir / "scout" / "_operator").resolve()
        if self.output_dir not in self.root.parents:
            raise StoreError("operator state escapes output directory")
        self.path = self.root / "state.json"

    def snapshot(self) -> Dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        return {
            "schema": "scout-operator-state/v1",
            "archived_targets": _unique(raw.get("archived_targets") or []),
            "archived_runs": _unique(raw.get("archived_runs") or []),
            "audit": list(raw.get("audit") or [])[-500:],
        }

    def target_archived(self, domain: str) -> bool:
        return str(domain or "").strip() in set(self.snapshot()["archived_targets"])

    def run_archived(self, run_id: str) -> bool:
        return str(run_id or "").strip() in set(self.snapshot()["archived_runs"])

    def archive_targets(self, domains: Iterable[str]) -> Dict[str, Any]:
        values = _unique(domains)
        state = self.snapshot()
        state["archived_targets"] = _unique([*state["archived_targets"], *values])
        self._audit(state, "targets_archived", targets=values)
        self._save(state)
        return {"ok": True, "archived": values}

    def restore_targets(self, domains: Iterable[str]) -> Dict[str, Any]:
        values = _unique(domains)
        remove = set(values)
        state = self.snapshot()
        state["archived_targets"] = [x for x in state["archived_targets"] if x not in remove]
        self._audit(state, "targets_restored", targets=values)
        self._save(state)
        return {"ok": True, "restored": values}

    def archive_run(self, run_id: str) -> Dict[str, Any]:
        run_id = self._safe_run(run_id)
        state = self.snapshot()
        state["archived_runs"] = _unique([*state["archived_runs"], run_id])
        self._audit(state, "run_archived", run_id=run_id)
        self._save(state)
        return {"ok": True, "run_id": run_id, "archived": True}

    def restore_run(self, run_id: str) -> Dict[str, Any]:
        run_id = self._safe_run(run_id)
        state = self.snapshot()
        state["archived_runs"] = [x for x in state["archived_runs"] if x != run_id]
        self._audit(state, "run_restored", run_id=run_id)
        self._save(state)
        return {"ok": True, "run_id": run_id, "archived": False}

    def request_skip(self, run_id: str, prospect_ids: Iterable[str]) -> Dict[str, Any]:
        """Persist a skip request for still-pending targets.

        The engine reads this exact run-scoped file before every new target.  This avoids mutating a
        concurrently-written state.json and means the current page operation finishes safely while
        selected queued targets never start.
        """
        run_id = self._safe_run(run_id)
        store = RunStore(str(self.output_dir), run_id)
        if not store.exists():
            raise StoreError("run not found")
        state = store.load_state() or {}
        prospects = state.get("prospects", {}) or {}
        requested = []
        refused = []
        for pid in _unique(prospect_ids):
            RunStore._safe_component(pid)
            status = str((prospects.get(pid) or {}).get("status") or "")
            if status == "PENDING":
                requested.append(pid)
            else:
                refused.append({"prospect_id": pid, "status": status or "unknown"})
        prior = store.load_artifact("operator_actions.json") or {}
        queued = _unique([*(prior.get("skip_prospects") or []), *requested])
        store.save_artifact("operator_actions.json", {
            "schema": "scout-operator-actions/v1",
            "skip_prospects": queued,
            "updated_at": _now(),
        })
        global_state = self.snapshot()
        self._audit(global_state, "queued_targets_skipped", run_id=run_id, targets=requested)
        self._save(global_state)
        return {"ok": True, "run_id": run_id, "requested": requested, "refused": refused}

    def delete_heavy_evidence(self, run_id: str, prospect_ids: Iterable[str], *,
                              confirm: bool) -> Dict[str, Any]:
        if not confirm:
            raise StoreError("evidence deletion requires explicit confirmation")
        run_id = self._safe_run(run_id)
        store = RunStore(str(self.output_dir), run_id)
        if not store.exists():
            raise StoreError("run not found")
        removed: List[str] = []
        for pid in _unique(prospect_ids):
            RunStore._safe_component(pid)
            pdir = store.prospect_dir(pid)
            if not pdir.is_dir():
                continue
            for path in sorted(pdir.iterdir()):
                if not path.is_file():
                    continue
                if path.suffix.lower() in _HEAVY_SUFFIXES or path.name in _HEAVY_NAMES:
                    path.unlink()
                    removed.append(f"prospects/{pid}/{path.name}")
            store.save_prospect_artifact(pid, "evidence_cleanup.json", {
                "schema": "scout-evidence-cleanup/v1",
                "removed_at": _now(),
                "removed": [x for x in removed if x.startswith(f"prospects/{pid}/")],
                "summary_preserved": True,
            })
        # Client ZIPs are derived copies of the same screenshots/video/trace. Invalidate every
        # cached export for this run so "Delete heavy evidence" cannot leave a downloadable copy.
        self._delete_client_exports(run_id)
        state = self.snapshot()
        self._audit(state, "heavy_evidence_deleted", run_id=run_id, removed=removed)
        self._save(state)
        return {"ok": True, "run_id": run_id, "removed": removed}

    def delete_run(self, run_id: str, *, confirm: bool, active_run_id: str = "",
                   active: bool = False) -> Dict[str, Any]:
        if not confirm:
            raise StoreError("run deletion requires explicit confirmation")
        run_id = self._safe_run(run_id)
        if active and run_id == str(active_run_id or ""):
            raise StoreError("active run cannot be deleted; stop it safely first")
        store = RunStore(str(self.output_dir), run_id)
        if not store.exists():
            raise StoreError("run not found")
        state = store.load_state() or {}
        if str(state.get("status") or "").upper() in {"PENDING", "RUNNING"}:
            raise StoreError("non-terminal run cannot be deleted; stop it safely first")
        root = store.root
        if root == self.output_dir or self.output_dir not in root.parents:
            raise StoreError("refusing to delete outside Scout storage")
        shutil.rmtree(root)
        self._delete_client_exports(run_id)
        op = self.snapshot()
        op["archived_runs"] = [x for x in op["archived_runs"] if x != run_id]
        self._audit(op, "run_deleted", run_id=run_id)
        self._save(op)
        return {"ok": True, "run_id": run_id, "deleted": True,
                "history_preserved": True}

    @staticmethod
    def _safe_run(run_id: str) -> str:
        value = str(run_id or "").strip()
        RunStore._safe_component(value)
        return value

    def _delete_client_exports(self, run_id: str) -> None:
        export_root = (self.output_dir / "scout" / "_client_exports").resolve()
        from core.scout.client_evidence import client_export_dir
        target = client_export_dir(str(self.output_dir), run_id)
        if target != export_root and export_root in target.parents and target.is_dir():
            shutil.rmtree(target)

    @staticmethod
    def _audit(state: Dict[str, Any], action: str, **fields: Any) -> None:
        state.setdefault("audit", []).append({"at": _now(), "action": action, **fields})
        state["audit"] = state["audit"][-500:]

    def _save(self, state: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "scout-operator-state/v1",
            "archived_targets": _unique(state.get("archived_targets") or []),
            "archived_runs": _unique(state.get("archived_runs") or []),
            "audit": list(state.get("audit") or [])[-500:],
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)
