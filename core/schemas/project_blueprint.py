from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin


@dataclass
class ProjectBlueprint(SchemaMixin):
    """Structured source-of-truth for a client project.

    Phase 2B adds planning fields (assumptions, missing_information, safe_next_steps,
    blocked_actions, etc.). All Phase 2A fields are preserved for backward compatibility.
    """

    project_id: str

    # --- Identity ---
    project_name: str = ""
    project_type: str = "unknown"
    client_name: str = ""
    client_goal: str = ""

    # --- Sources ---
    task_source: str = ""           # where the brief/task came from
    target_application: str = ""   # the app under test (never the task source)
    target_urls: List[str] = field(default_factory=list)  # kept for compat
    input_sources: List[str] = field(default_factory=list)  # input_type list

    # --- Environment ---
    environment: str = "unknown"    # local / staging / production / none / unknown

    # --- Scope ---
    tech_stack: List[str] = field(default_factory=list)
    application_surfaces: List[str] = field(default_factory=list)
    scope_notes: str = ""
    out_of_scope_notes: str = ""

    # --- Risk and analysis ---
    risk_areas: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    # --- Planning ---
    missing_information: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    safe_next_steps: List[str] = field(default_factory=list)
    blocked_actions: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)

    # --- Strategy outline ---
    recommended_strategy: str = ""
    tactical_test_focus: List[str] = field(default_factory=list)

    # --- Meta ---
    confidence_level: str = "low"   # low / medium / high
    phase: str = "blueprint"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectBlueprint:
        return super().from_dict(data)
