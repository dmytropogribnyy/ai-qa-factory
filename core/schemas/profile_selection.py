"""ProfileSelection schema — Phase 8.1 (deterministic profile inference).

Output of the UniversalProfileSelector. Existing QA-first classifiers are useful
upstream signals but cannot independently choose all eight ARK profiles, so a
dedicated deterministic selector produces this record. Unknown / low-confidence work
must NOT silently become QA automation — it stays unresolved and requests more info.

SAFETY / DESIGN NOTES:
- Deterministic (no LLM). No runtime side effects.
- `selection_source="override"` preserves the inferred value; a mismatch raises a warning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

SELECTION_SOURCES = frozenset({"inferred", "override", "fallback", "unresolved"})


@dataclass
class ProfileSelection(SchemaMixin):
    """Deterministic capability-profile inference for a work packet."""

    inferred_profile: str = ""                  # may be "" when unresolved
    selected_profile: str = ""                  # inferred, override, or "" when unresolved
    selection_source: str = "inferred"
    confidence: float = 0.0
    matched_signals: List[str] = field(default_factory=list)
    alternative_profiles: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return bool(self.selected_profile)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProfileSelection:
        return super().from_dict(data)
