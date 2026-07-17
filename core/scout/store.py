"""Durable local run store for the Scout (Phase 8.3).

Everything for one run lives under `<output_dir>/scout/<run_id>/`. Writes are atomic
(temp file + os.replace) and path-confined (no write may escape the run directory).
Completed prospect stages are immutable — resume skips them and never re-runs them.
Corruption fails closed (a truncated/garbled state file raises rather than silently resetting).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class StoreError(Exception):
    pass


class StoreCorruptionError(StoreError):
    pass


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class RunStore:
    def __init__(self, output_dir: str, run_id: str) -> None:
        if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id or os.path.isabs(run_id):
            raise StoreError(f"unsafe run_id: {run_id!r}")
        self.output_dir = Path(output_dir).resolve()
        self.root = (self.output_dir / "scout" / run_id).resolve()
        if self.output_dir not in self.root.parents:
            raise StoreError("run directory escapes the output directory")

    # --- path confinement -------------------------------------------------
    def _confine(self, *parts: str) -> Path:
        target = (self.root.joinpath(*parts)).resolve()
        if target != self.root and self.root not in target.parents:
            raise StoreError(f"path escapes the run directory: {parts}")
        return target

    def exists(self) -> bool:
        return (self.root / "state.json").exists()

    def reset(self) -> None:
        """Delete this run directory (path-confined) for an explicit safe replacement.

        Only ever removes ``<output_dir>/scout/<run_id>/`` — never anything outside it (the
        constructor already guarantees the root is confined). Used by the deterministic demo,
        which intentionally reuses a fixed run id; normal fresh scans never reuse a run id.
        """
        import shutil
        if self.root == self.output_dir or self.output_dir not in self.root.parents:
            raise StoreError("refusing to reset a directory outside the run tree")
        if self.root.exists():
            shutil.rmtree(self.root)

    # --- config (immutable once written) ----------------------------------
    def write_config(self, config: Dict[str, Any]) -> None:
        path = self._confine("config.json")
        if path.exists():
            return  # immutable
        _atomic_write_text(path, json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True))

    def load_config(self) -> Dict[str, Any]:
        return self._load_json(self._confine("config.json"))

    # --- run state --------------------------------------------------------
    def save_state(self, state: Dict[str, Any]) -> None:
        _atomic_write_text(self._confine("state.json"),
                           json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True))

    def load_state(self) -> Dict[str, Any]:
        return self._load_json(self._confine("state.json"))

    # --- events (append-only) ---------------------------------------------
    def append_event(self, event: Dict[str, Any]) -> None:
        path = self._confine("events.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def read_events(self) -> List[Dict[str, Any]]:
        path = self._confine("events.jsonl")
        if not path.exists():
            return []
        out: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # tolerate a torn final line in the append-only log
        return out

    # --- per-prospect artifacts -------------------------------------------
    def save_prospect_artifact(self, prospect_id: str, name: str, obj: Any) -> str:
        self._safe_component(prospect_id)
        self._safe_component(name)
        path = self._confine("prospects", prospect_id, name)
        _atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
        return str(path.relative_to(self.root)).replace("\\", "/")

    def load_prospect_artifact(self, prospect_id: str, name: str) -> Optional[Any]:
        path = self._confine("prospects", prospect_id, name)
        if not path.exists():
            return None
        return self._load_json(path)

    def prospect_dir(self, prospect_id: str) -> Path:
        self._safe_component(prospect_id)
        return self._confine("prospects", prospect_id)

    # --- final report (atomic, secret-scanned set) ------------------------
    def report_dir(self) -> Path:
        return self._confine("report")

    # --- helpers ----------------------------------------------------------
    @staticmethod
    def _safe_component(name: str) -> None:
        if not name or "/" in name or "\\" in name or ".." in name or os.path.isabs(name):
            raise StoreError(f"unsafe path component: {name!r}")

    @staticmethod
    def _load_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise StoreError(f"missing artifact: {path.name}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StoreCorruptionError(f"corrupt artifact {path.name}: {exc}") from exc
