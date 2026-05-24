from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Protocol


class PersistenceBackend(Protocol):
    def save_project(self, project_id: str, data: Dict[str, Any]) -> Path: ...
    def load_project(self, project_id: str) -> Dict[str, Any] | None: ...
    def list_projects(self, filters: Dict[str, Any] | None = None) -> List[str]: ...
    def save_client(self, client_id: str, data: Dict[str, Any]) -> Path: ...
    def load_client(self, client_id: str | None) -> Dict[str, Any]: ...
    def list_clients(self) -> List[Dict[str, Any]]: ...
    def save_snippet(self, snippet_id: str, content: str, tags: List[str] | None = None) -> Path: ...
    def search_snippets(self, query: str, tags: List[str] | None = None) -> List[Dict[str, Any]]: ...
    def pricing_book_path(self) -> Path: ...


class JSONFilePersistence:
    """v5.0.8 default persistence: transparent files, no database server.

    The interface intentionally matches what a future SQLite backend would expose.
    Agents should depend on this abstraction, not on direct database/file calls.
    """

    def __init__(self, memory_dir: str | Path = "memory", output_dir: str | Path = "outputs"):
        self.memory_dir = Path(memory_dir)
        self.output_dir = Path(output_dir)
        self.clients_dir = self.memory_dir / "clients"
        self.snippets_dir = self.memory_dir / "snippets"
        self.lessons_dir = self.memory_dir / "lessons-learned"
        self.projects_dir = self.memory_dir / "projects"
        for path in [self.clients_dir, self.snippets_dir, self.lessons_dir, self.projects_dir]:
            path.mkdir(parents=True, exist_ok=True)
        pricing_path = self.pricing_book_path()
        if not pricing_path.exists():
            pricing_path.write_text(DEFAULT_PRICING_BOOK, encoding="utf-8")

    def save_project(self, project_id: str, data: Dict[str, Any]) -> Path:
        path = self.projects_dir / f"{self._safe_id(project_id)}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_project(self, project_id: str) -> Dict[str, Any] | None:
        candidates = [
            self.projects_dir / f"{self._safe_id(project_id)}.json",
            self.output_dir / project_id / "state.json",
        ]
        for path in candidates:
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    return None
        return None

    def list_projects(self, filters: Dict[str, Any] | None = None) -> List[str]:
        return sorted(path.stem for path in self.projects_dir.glob("*.json"))

    def save_client(self, client_id: str, data: Dict[str, Any]) -> Path:
        path = self.clients_dir / f"{self._safe_id(client_id)}.json"
        existing = self.load_client(client_id)
        existing.update(data)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_client(self, client_id: str | None) -> Dict[str, Any]:
        if not client_id:
            return {}
        path = self.clients_dir / f"{self._safe_id(client_id)}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def list_clients(self) -> List[Dict[str, Any]]:
        clients = []
        for path in sorted(self.clients_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data.setdefault("client_id", path.stem)
                clients.append(data)
            except Exception:
                continue
        return clients

    def save_snippet(self, snippet_id: str, content: str, tags: List[str] | None = None) -> Path:
        safe_id = self._safe_id(snippet_id)
        path = self.snippets_dir / f"{safe_id}.md"
        meta = "---\n" + json.dumps({"tags": tags or []}, ensure_ascii=False) + "\n---\n\n"
        path.write_text(meta + content, encoding="utf-8")
        return path

    def search_snippets(self, query: str, tags: List[str] | None = None) -> List[Dict[str, Any]]:
        q = query.lower().strip()
        results = []
        for path in sorted(self.snippets_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if not q or q in text.lower():
                results.append({"snippet_id": path.stem, "path": str(path), "content": text})
        return results

    def pricing_book_path(self) -> Path:
        return self.memory_dir / "pricing_book.yaml"

    @staticmethod
    def _safe_id(value: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-._")
        return safe or "item"


DEFAULT_PRICING_BOOK = """# AI QA Factory pricing book. Edit this file as real market feedback arrives.
qa_audit:
  triggers: [audit, review, qa readiness, mvp]
  price: "$150–$500 fixed-price audit"
  milestone: "Starter milestone: QA audit report + prioritized risk list + first smoke automation recommendation."
flaky_stabilization:
  triggers: [flaky, stabilize, stabilise, ci]
  price: "$75–$250 starter task or $50/hr ongoing"
  milestone: "Starter milestone: stabilize top 3–5 flaky tests and document root causes."
selenium_migration:
  triggers: [selenium, migration, migrate]
  price: "$500–$2,000+ depending on suite size"
  milestone: "Starter milestone: migrate 2–3 representative Selenium tests to Playwright and define migration plan."
framework_setup:
  triggers: [framework, setup, from scratch]
  price: "$700–$1,500+ fixed scope or $50/hr"
  milestone: "Starter milestone: Playwright + TypeScript scaffold with CI-ready smoke suite."
default:
  price: "$50/hr or $150–$300 discovery milestone"
  milestone: "Starter milestone: scope review + test plan + one critical smoke flow."
"""


def get_persistence(settings) -> PersistenceBackend:
    backend = getattr(settings, "persistence_backend", "json").lower()
    if backend != "json":
        raise ValueError(f"Unsupported PERSISTENCE_BACKEND={backend}. v5.0.8 ships JSONFilePersistence only.")
    return JSONFilePersistence(settings.memory_dir, settings.output_dir)
