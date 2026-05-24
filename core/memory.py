from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class SimpleMemory:
    """Small JSON memory layer. No RAG yet."""

    def __init__(self, root: str | Path = "memory"):
        self.root = Path(root)
        self.clients_dir = self.root / "clients"
        self.patterns_dir = self.root / "patterns"
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        self.patterns_dir.mkdir(parents=True, exist_ok=True)

    def load_client(self, client_id: str | None) -> Dict[str, Any]:
        if not client_id:
            return {}
        path = self.clients_dir / f"{client_id}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def load_pattern(self, name: str) -> Dict[str, Any]:
        path = self.patterns_dir / f"{name}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_client_note(self, client_id: str, data: Dict[str, Any]) -> Path:
        path = self.clients_dir / f"{client_id}.json"
        existing = self.load_client(client_id)
        existing.update(data)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
