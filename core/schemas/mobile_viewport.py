"""
Phase 5I — Mobile Viewport Emulation schemas.

Playwright-based device emulation for testing mobile web experiences
without Appium. Works on any target already approved for browser execution.

Safety invariants (hardcoded in __post_init__ + from_dict):
- credentials_used=False
- auth_performed=False
- safe_to_deliver=False
- approved_for_client_delivery=False
- human_review_required=True

Real native mobile app testing (Appium/Maestro) is Phase 5K.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOBILE_VIEWPORT_DEVICES = (
    "iPhone 14",
    "iPhone 14 Pro",
    "iPhone 13",
    "Pixel 7",
    "Pixel 5",
    "Galaxy S22",
    "Galaxy S9+",
    "iPad Pro",
    "iPad Mini",
    "Nexus 10",
)

# Devices that also support ecommerce readonly profiles (Amazon/Alza mobile web)
MOBILE_ECOMMERCE_READONLY_DEVICES = (
    "iPhone 14",
    "Pixel 7",
    "Galaxy S22",
    "iPad Pro",
)

MOBILE_VIEWPORT_MODES = (
    "list",            # list tests only, no execution
    "viewport_smoke",  # run smoke suite with device emulation
)

MOBILE_ECOMMERCE_READONLY_PROFILES = (
    "amazon_mobile_readonly",
    "alza_mobile_readonly",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

@dataclass
class MobileViewportProfile(SchemaMixin):
    """Specification of a mobile device viewport for Playwright emulation."""
    device_name: str = ""
    viewport_width: int = 390
    viewport_height: int = 844
    user_agent: str = ""
    is_mobile: bool = True
    has_touch: bool = True
    pixel_ratio: float = 3.0
    playwright_device_name: str = ""  # exact name in Playwright device registry

    @classmethod
    def from_dict(cls, data: dict) -> "MobileViewportProfile":
        return cls(
            device_name=str(data.get("device_name", "")),
            viewport_width=int(data.get("viewport_width", 390)),
            viewport_height=int(data.get("viewport_height", 844)),
            user_agent=str(data.get("user_agent", "")),
            is_mobile=bool(data.get("is_mobile", True)),
            has_touch=bool(data.get("has_touch", True)),
            pixel_ratio=float(data.get("pixel_ratio", 3.0)),
            playwright_device_name=str(data.get("playwright_device_name", "")),
        )


@dataclass
class MobileViewportExecutionCommand(SchemaMixin):
    """A single command record within a mobile viewport execution run."""
    id: str = ""
    command: str = ""
    device_name: str = ""
    cwd: str = ""
    status: str = "pending"   # pending | pass | fail | blocked | skipped
    executed: bool = False
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    duration_seconds: float = 0.0
    safety_notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "MobileViewportExecutionCommand":
        return cls(
            id=str(data.get("id", "")),
            command=str(data.get("command", "")),
            device_name=str(data.get("device_name", "")),
            cwd=str(data.get("cwd", "")),
            status=str(data.get("status", "pending")),
            executed=bool(data.get("executed", False)),
            stdout_excerpt=str(data.get("stdout_excerpt", "")),
            stderr_excerpt=str(data.get("stderr_excerpt", "")),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            safety_notes=list(data.get("safety_notes", [])),
        )


@dataclass
class MobileViewportExecutionReport(SchemaMixin):
    """Report for a mobile viewport smoke run."""
    project_id: str = ""
    device_name: str = ""
    command_mode: str = ""
    readonly_profile: str = ""
    target_url: str = ""
    execution_status: str = "pending"   # pending | complete | blocked | error
    approved: bool = False
    blockers: List[str] = field(default_factory=list)
    commands: List[MobileViewportExecutionCommand] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    config_path: str = ""   # path to generated mobile.config.cjs (runtime only, gitignored)

    # Hardcoded safety fields
    credentials_used: bool = False
    auth_performed: bool = False
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "credentials_used", False)
        object.__setattr__(self, "auth_performed", False)
        object.__setattr__(self, "safe_to_deliver", False)
        object.__setattr__(self, "approved_for_client_delivery", False)
        object.__setattr__(self, "human_review_required", True)

    @classmethod
    def from_dict(cls, data: dict) -> "MobileViewportExecutionReport":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            device_name=str(data.get("device_name", "")),
            command_mode=str(data.get("command_mode", "")),
            readonly_profile=str(data.get("readonly_profile", "")),
            target_url=str(data.get("target_url", "")),
            execution_status=str(data.get("execution_status", "pending")),
            approved=bool(data.get("approved", False)),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
            config_path=str(data.get("config_path", "")),
        )
        # Enforce hardcoded safety regardless of input
        object.__setattr__(obj, "credentials_used", False)
        object.__setattr__(obj, "auth_performed", False)
        object.__setattr__(obj, "safe_to_deliver", False)
        object.__setattr__(obj, "approved_for_client_delivery", False)
        object.__setattr__(obj, "human_review_required", True)
        return obj
