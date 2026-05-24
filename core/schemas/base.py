from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Dict, Type, TypeVar

T = TypeVar("T", bound="SchemaMixin")


class SchemaMixin:
    """Serialization mixin for all schema dataclasses."""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
