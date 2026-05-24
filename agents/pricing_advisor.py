from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from core.state import QAFactoryState


class PricingAdvisorAgent:
    name = "Pricing Advisor"

    def __init__(self, persistence=None):
        self.persistence = persistence

    def run(self, state: QAFactoryState) -> QAFactoryState:
        text = state.raw_input.lower()
        book = self._load_pricing_book()
        selected = self._select_entry(text, book)
        price = selected.get("price") or "$50/hr or $150–$300 discovery milestone"
        milestone = selected.get("milestone") or "Starter milestone: scope review + test plan + one critical smoke flow."

        state.suggested_price = price
        state.suggested_milestone = milestone
        state.client_context["suggested_price"] = price
        state.client_context["suggested_milestone"] = milestone
        state.generated_outputs["pricing_and_milestone.md"] = (
            "# Pricing and Milestone Suggestion\n\n"
            f"**Suggested price:** {price}\n\n"
            f"**Suggested first milestone:** {milestone}\n\n"
            "Human review required before quoting. Adjust for client budget, scope and urgency.\n"
        )
        state.log(f"{self.name}: suggested {price}")
        return state

    def _pricing_path(self) -> Path | None:
        if self.persistence and hasattr(self.persistence, "pricing_book_path"):
            return self.persistence.pricing_book_path()
        default = Path("memory/pricing_book.yaml")
        return default if default.exists() else None

    def _load_pricing_book(self) -> Dict[str, Dict[str, Any]]:
        path = self._pricing_path()
        if not path or not path.exists():
            return DEFAULT_BOOK
        try:
            return _parse_simple_pricing_yaml(path.read_text(encoding="utf-8")) or DEFAULT_BOOK
        except Exception:
            return DEFAULT_BOOK

    @staticmethod
    def _select_entry(text: str, book: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        for key, entry in book.items():
            if key == "default":
                continue
            triggers = entry.get("triggers", [])
            if any(str(trigger).lower() in text for trigger in triggers):
                return entry
        return book.get("default", DEFAULT_BOOK["default"])


def _parse_simple_pricing_yaml(raw: str) -> Dict[str, Dict[str, Any]]:
    """Tiny YAML subset parser to avoid adding PyYAML for one config file."""
    book: Dict[str, Dict[str, Any]] = {}
    current: str | None = None
    for original in raw.splitlines():
        line = original.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current = line[:-1].strip()
            book[current] = {}
            continue
        if current and line.startswith("  ") and ":" in line:
            key, value = line.strip().split(":", 1)
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                items = [item.strip().strip('"\'') for item in value[1:-1].split(",") if item.strip()]
                book[current][key] = items
            else:
                book[current][key] = value.strip().strip('"\'')
    return book


DEFAULT_BOOK: Dict[str, Dict[str, Any]] = {
    "qa_audit": {
        "triggers": ["audit", "review", "qa readiness", "mvp"],
        "price": "$150–$500 fixed-price audit",
        "milestone": "Starter milestone: QA audit report + prioritized risk list + first smoke automation recommendation.",
    },
    "flaky_stabilization": {
        "triggers": ["flaky", "stabilize", "stabilise", "ci"],
        "price": "$75–$250 starter task or $50/hr ongoing",
        "milestone": "Starter milestone: stabilize top 3–5 flaky tests and document root causes.",
    },
    "selenium_migration": {
        "triggers": ["selenium", "migration", "migrate"],
        "price": "$500–$2,000+ depending on suite size",
        "milestone": "Starter milestone: migrate 2–3 representative Selenium tests to Playwright and define migration plan.",
    },
    "framework_setup": {
        "triggers": ["framework", "setup", "from scratch"],
        "price": "$700–$1,500+ fixed scope or $50/hr",
        "milestone": "Starter milestone: Playwright + TypeScript scaffold with CI-ready smoke suite.",
    },
    "default": {
        "price": "$50/hr or $150–$300 discovery milestone",
        "milestone": "Starter milestone: scope review + test plan + one critical smoke flow.",
    },
}
