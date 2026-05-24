from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings


@dataclass
class HealthItem:
    name: str
    status: str
    detail: str


class SystemHealthChecker:
    """Local readiness checks for running AI QA Factory safely.

    This checks the Factory environment itself. It does not contact client systems,
    scrape platforms, or validate credentials by sending network requests.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self) -> list[HealthItem]:
        items: list[HealthItem] = []
        items.append(self._python())
        items.extend(self._python_packages())
        items.extend(self._llm_config())
        items.extend(self._dirs())
        items.extend(self._node_playwright())
        items.append(self._gitignore())
        return items

    def render_markdown(self, items: list[HealthItem]) -> str:
        status = "pass" if all(i.status in {"pass", "info"} for i in items) else "review_required"
        lines = [
            "# System Health Check",
            "",
            f"**Overall status:** `{status}`",
            "",
            "| Check | Status | Detail |",
            "|---|---:|---|",
        ]
        for item in items:
            lines.append(f"| {item.name} | `{item.status}` | {item.detail} |")
        lines += [
            "",
            "## Notes",
            "- This is a local Factory readiness check, not a client-site test.",
            "- API key presence is checked only by environment variable name; key values are never printed.",
            "- Real client-facing output still requires `--require-real-llm` and human review.",
        ]
        return "\n".join(lines) + "\n"

    def _python(self) -> HealthItem:
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        status = "pass" if sys.version_info >= (3, 10) else "fail"
        return HealthItem("Python", status, version)

    def _python_packages(self) -> list[HealthItem]:
        required = ["pytest", "dotenv", "litellm"]
        items = []
        for package in required:
            found = importlib.util.find_spec(package) is not None
            items.append(HealthItem(f"Python package: {package}", "pass" if found else "fail", "installed" if found else "missing"))
        return items

    def _llm_config(self) -> list[HealthItem]:
        s = self.settings
        items = [HealthItem("LLM mode", "info" if s.is_mock else "pass", s.llm_mode), HealthItem("MODEL_PROFILE", "info" if s.is_mock else "pass", s.model_profile), HealthItem("ENABLE_EFFORT_PARAMS", "info", str(s.enable_effort_params))]
        model_fields = {
            "ARCHITECT_MODEL": (s.architect_model, s.architect_effort),
            "CODING_MODEL": (s.coding_model, s.coding_effort),
            "REVIEW_MODEL": (s.review_model, s.review_effort),
            "FAST_MODEL": (s.fast_model, s.fast_effort),
            "VISION_MODEL": (s.vision_model, s.vision_effort),
            "FALLBACK_MODEL": (s.fallback_model, s.fallback_effort),
        }
        for name, pair in model_fields.items():
            value, effort = pair
            if s.is_mock:
                status = "info"
            else:
                status = "pass" if value and value != "mock" else "fail"
            items.append(HealthItem(name, status, f"{value or 'missing'} | effort={effort}"))
        key_names = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "AZURE_API_KEY"]
        present = [name for name in key_names if os.getenv(name)]
        if s.is_mock:
            items.append(HealthItem("LLM API key", "info", "not required in mock mode"))
        else:
            items.append(HealthItem("LLM API key", "pass" if present else "fail", ", ".join(present) if present else "none detected"))
            models = [s.architect_model, s.coding_model, s.review_model, s.fast_model, s.vision_model, s.fallback_model]
            needs_openai = any(m.startswith("gpt-") or m.startswith("openai/") for m in models)
            needs_anthropic = any("claude-" in m or m.startswith("anthropic/") for m in models)
            if needs_openai:
                items.append(HealthItem("OPENAI_API_KEY for selected models", "pass" if os.getenv("OPENAI_API_KEY") else "fail", "present" if os.getenv("OPENAI_API_KEY") else "missing"))
            if needs_anthropic:
                items.append(HealthItem("ANTHROPIC_API_KEY for selected models", "pass" if os.getenv("ANTHROPIC_API_KEY") else "fail", "present" if os.getenv("ANTHROPIC_API_KEY") else "missing"))
        return items

    def _dirs(self) -> list[HealthItem]:
        items = []
        for path in [self.settings.output_dir, self.settings.memory_dir, self.settings.memory_dir / "clients", self.settings.memory_dir / "snippets", self.settings.memory_dir / "lessons-learned", self.settings.memory_dir / "projects"]:
            items.append(HealthItem(f"Directory: {path}", "pass" if path.exists() else "fail", "exists" if path.exists() else "missing"))
        return items

    def _node_playwright(self) -> list[HealthItem]:
        items = []
        for tool in ["node", "npm", "npx"]:
            path = shutil.which(tool)
            items.append(HealthItem(f"CLI tool: {tool}", "pass" if path else "warning", path or "not found; needed only for generated Playwright projects"))
        return items

    def _gitignore(self) -> HealthItem:
        path = Path(".gitignore")
        if not path.exists():
            return HealthItem(".gitignore", "warning", "missing")
        text = path.read_text(encoding="utf-8", errors="ignore")
        required = [".env", "outputs", "__pycache__"]
        missing = [item for item in required if item not in text]
        return HealthItem(".gitignore", "pass" if not missing else "warning", "ok" if not missing else f"missing entries: {', '.join(missing)}")
