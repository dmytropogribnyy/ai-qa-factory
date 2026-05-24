from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class AIProviderStatus(SchemaMixin):
    """Status of one LLM provider in the routing config."""

    provider: str = ""
    model_id: str = ""
    role: str = ""
    available: bool = True
    latency_ms: float = 0.0
    last_checked_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AIProviderStatus:
        return super().from_dict(data)


@dataclass
class AIFallbackEvent(SchemaMixin):
    """One recorded LLM fallback event (primary unavailable, fallback used)."""

    id: str = field(default_factory=lambda: str(uuid4()))
    primary_provider: str = ""
    fallback_provider: str = ""
    reason: str = ""
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AIFallbackEvent:
        return super().from_dict(data)


@dataclass
class AIResilienceReport(SchemaMixin):
    """Report on AI provider health and fallback history."""

    project_id: str
    providers: List[AIProviderStatus] = field(default_factory=list)
    fallback_events: List[AIFallbackEvent] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "providers": [p.to_dict() for p in self.providers],
            "fallback_events": [e.to_dict() for e in self.fallback_events],
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AIResilienceReport:
        providers = [
            AIProviderStatus.from_dict(p) if isinstance(p, dict) else p
            for p in data.get("providers", [])
        ]
        fallback_events = [
            AIFallbackEvent.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("fallback_events", [])
        ]
        return cls(
            project_id=data["project_id"],
            providers=providers,
            fallback_events=fallback_events,
            generated_at=data.get("generated_at", datetime.now(timezone.utc).isoformat()),
        )
