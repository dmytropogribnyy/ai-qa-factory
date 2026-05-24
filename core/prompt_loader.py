from __future__ import annotations

from pathlib import Path


class PromptLoader:
    def __init__(self, root: str | Path = "prompts"):
        self.root = Path(root)

    def load(self, category: str, profile: str, fallback: str = "default") -> str:
        candidates = [self.root / category / f"{profile}.md"]
        if fallback and fallback != profile:
            candidates.append(self.root / category / f"{fallback}.md")
        default_path = self.root / category / "default.md"
        if default_path not in candidates:
            candidates.append(default_path)
        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        return ""
