from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

FILE_TYPES = {
    "package_json", "tsconfig", "playwright_config", "test_spec",
    "page_object", "fixture", "utility", "test_data", "documentation",
    "gitignore", "ci_config", "example_env", "unknown",
}

FRAMEWORK_TYPES = {"playwright_ts", "api_only", "mixed_ui_api", "unknown"}

SCAFFOLD_STATUSES = {
    "planned", "generated", "needs_review",
    "approved_for_local_validation", "rejected",
}


@dataclass
class FrameworkFile(SchemaMixin):
    id: str = ""
    path: str = ""
    purpose: str = ""
    file_type: str = "unknown"
    client_visible: bool = False
    generated: bool = True
    requires_review: bool = True
    notes: List[str] = field(default_factory=list)


@dataclass
class FrameworkScaffold(SchemaMixin):
    project_id: str = ""
    framework_type: str = "playwright_ts"
    language: str = "typescript"
    test_runner: str = "playwright"
    root_path: str = ""
    files: List[FrameworkFile] = field(default_factory=list)
    generated_from: List[str] = field(default_factory=list)
    scaffold_status: str = "generated"
    client_visible: bool = False
    requires_review: bool = True
    execution_allowed: bool = False
    notes: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "framework_type": self.framework_type,
            "language": self.language,
            "test_runner": self.test_runner,
            "root_path": self.root_path,
            "files": [f.to_dict() for f in self.files],
            "generated_from": list(self.generated_from),
            "scaffold_status": self.scaffold_status,
            "client_visible": self.client_visible,
            "requires_review": self.requires_review,
            "execution_allowed": self.execution_allowed,
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FrameworkScaffold:
        known = {
            "project_id", "framework_type", "language", "test_runner",
            "root_path", "generated_from", "scaffold_status", "client_visible",
            "requires_review", "execution_allowed", "notes", "created_at",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["files"] = [
            FrameworkFile.from_dict(f) if isinstance(f, dict) else f
            for f in data.get("files", [])
        ]
        return cls(**kwargs)


@dataclass
class FrameworkScaffoldPlan(SchemaMixin):
    project_id: str = ""
    target_framework: str = "playwright_ts"
    recommended_structure: List[str] = field(default_factory=list)
    included_layers: List[str] = field(default_factory=list)
    deferred_layers: List[str] = field(default_factory=list)
    blocked_layers: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
