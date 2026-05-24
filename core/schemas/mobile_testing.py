from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.schemas.base import SchemaMixin

# Schema-only foundation. No runtime mobile execution in this phase.
# Rules encoded as safe defaults:
# - Playwright mobile web emulation: can run from desktop, no macOS required.
# - Android emulator/device: desktop-compatible if tooling available and approved.
# - iOS simulator: requires macOS (requires_macos = True).
# - iOS real device: requires macOS/Xcode or cloud device farm + approval.
# - Cloud device farms: require explicit approval and credentials.


@dataclass
class MobileTestTarget(SchemaMixin):
    """Describes one mobile test target — surface, platform, and execution requirements."""

    id: str = field(default_factory=lambda: str(uuid4()))
    app_surface: str = "unknown"
    execution_target: str = "unknown"
    platform_name: str = "unknown"
    device_name: Optional[str] = None
    os_version: Optional[str] = None
    browser_name: Optional[str] = None
    # Path to app binary — reference only, no execution in this phase.
    app_path: Optional[str] = None
    app_package_or_bundle_id: Optional[str] = None
    requires_real_device: bool = False
    requires_cloud_device: bool = False
    requires_macos: bool = False
    requires_approval: bool = True
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MobileTestTarget:
        return super().from_dict(data)


@dataclass
class MobileExecutionPlan(SchemaMixin):
    """Execution plan for mobile testing from the current desktop environment."""

    project_id: str
    targets: List[MobileTestTarget] = field(default_factory=list)
    recommended_tooling: List[str] = field(default_factory=list)
    can_run_from_current_desktop: bool = False
    desktop_limitations: List[str] = field(default_factory=list)
    approval_required: bool = True
    safe_to_execute: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "targets": [t.to_dict() for t in self.targets],
            "recommended_tooling": self.recommended_tooling,
            "can_run_from_current_desktop": self.can_run_from_current_desktop,
            "desktop_limitations": self.desktop_limitations,
            "approval_required": self.approval_required,
            "safe_to_execute": self.safe_to_execute,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MobileExecutionPlan:
        targets = [
            MobileTestTarget.from_dict(t) if isinstance(t, dict) else t
            for t in data.get("targets", [])
        ]
        return cls(
            project_id=data["project_id"],
            targets=targets,
            recommended_tooling=data.get("recommended_tooling", []),
            can_run_from_current_desktop=data.get("can_run_from_current_desktop", False),
            desktop_limitations=data.get("desktop_limitations", []),
            approval_required=data.get("approval_required", True),
            safe_to_execute=data.get("safe_to_execute", False),
            notes=data.get("notes", []),
        )
