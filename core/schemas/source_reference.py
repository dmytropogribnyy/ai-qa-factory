from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from core.schemas.base import SchemaMixin


@dataclass
class SourceReference(SchemaMixin):
    """Points to the origin of a work request (task tracker, job board, email, etc.)."""

    url: str = ""
    platform: str = "unknown"
    title: str = ""
    raw_text: str = ""
    retrieved_at: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceReference:
        return super().from_dict(data)
