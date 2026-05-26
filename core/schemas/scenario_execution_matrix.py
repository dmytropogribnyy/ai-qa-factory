"""Scenario Execution Matrix schemas — Phase 4G.

SAFETY DEFAULTS (hardcoded, cannot be bypassed via constructor or from_dict):
- DedicatedTestAccountRequirement.production_account_allowed=False  (ALWAYS)
- DedicatedTestAccountRequirement.personal_account_allowed=False     (ALWAYS)
- CredentialProvisioningRoute.repo_storage_allowed=False             (ALWAYS)
- CredentialProvisioningRoute.logging_allowed=False                  (ALWAYS)
- CredentialProvisioningRoute.client_visible_allowed=False           (ALWAYS)
- DedicatedTestAccountPlan.safe_for_execution_now=False              (ALWAYS)

Default-False (not forced, builder may set True for implemented lanes):
- allowed_now=False
- credentials_allowed=False
- storage_state_allowed=False
- client_delivery_allowed=False
- evidence_internal_only=True

No execution, no credentials, no auth, no external calls in this module.
Phase 4G is policy/schema/routing/planning only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

LANE_STATUSES = {
    "implemented",
    "planned",
    "blocked",
    "deprecated",
    "unknown",
}


# ---------------------------------------------------------------------------
# ScenarioExecutionLane
# ---------------------------------------------------------------------------

@dataclass
class ScenarioExecutionLane(SchemaMixin):
    """Defines an execution lane: what is allowed, who owns it, what evidence it produces."""
    id: str = ""
    name: str = ""
    status: str = "planned"
    description: str = ""
    allowed_now: bool = False
    implemented: bool = False
    future_phase: Optional[str] = None
    required_approval_flags: List[str] = field(default_factory=list)
    allowed_target_categories: List[str] = field(default_factory=list)
    allowed_profiles: List[str] = field(default_factory=list)
    allowed_credential_sources: List[str] = field(default_factory=list)
    blocked_actions: List[str] = field(default_factory=list)
    owner_tool: Optional[str] = None
    evidence_root: Optional[str] = None
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ScenarioPermissionRule
# ---------------------------------------------------------------------------

@dataclass
class ScenarioPermissionRule(SchemaMixin):
    """A single permission routing rule for a scenario/target combination."""
    id: str = ""
    scenario_type: str = ""
    target_pattern: str = ""
    target_category: str = ""
    execution_lane: str = ""
    allowed_now: bool = False
    requires_approval: bool = True
    approval_flags: List[str] = field(default_factory=list)
    credentials_allowed: bool = False
    credential_policy: str = ""
    storage_state_allowed: bool = False
    evidence_internal_only: bool = True
    client_delivery_allowed: bool = False
    blocked_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ScenarioTargetProfile
# ---------------------------------------------------------------------------

@dataclass
class ScenarioTargetProfile(SchemaMixin):
    """A classified target profile with routing to an execution lane."""
    id: str = ""
    label: str = ""
    target_url_pattern: str = ""
    target_category: str = ""
    scenario_type: str = ""
    execution_lane: str = ""
    allowed_now: bool = False
    approved_profile: bool = False
    requires_credentials: bool = False
    allowed_credentials: List[str] = field(default_factory=list)
    blocked_actions: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ScenarioExecutionDecision
# ---------------------------------------------------------------------------

@dataclass
class ScenarioExecutionDecision(SchemaMixin):
    """Result of classifying a specific URL/scenario into an execution lane."""
    project_id: str = ""
    input_label: str = ""
    target_url: Optional[str] = None
    target_category: str = ""
    scenario_type: str = ""
    execution_lane: str = ""
    allowed_now: bool = False
    implemented_now: bool = False
    required_approval_flags: List[str] = field(default_factory=list)
    selected_tool: Optional[str] = None
    credentials_required: bool = False
    credentials_allowed: bool = False
    storage_state_allowed: bool = False
    evidence_internal_only: bool = True
    client_delivery_allowed: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_next_steps: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DedicatedTestAccountRequirement
# ---------------------------------------------------------------------------

@dataclass
class DedicatedTestAccountRequirement(SchemaMixin):
    """Planning requirement for a future lane that needs a dedicated test account."""
    id: str = ""
    scenario_lane: str = ""
    target_category: str = ""
    provider: str = ""
    account_type: str = ""
    required: bool = False
    acceptable_sources: List[str] = field(default_factory=list)
    forbidden_sources: List[str] = field(default_factory=list)
    requires_client_provided_account: bool = False
    requires_staging_environment: bool = False
    requires_vault_or_runtime_secret: bool = False
    storage_state_allowed_future: bool = False
    production_account_allowed: bool = False
    personal_account_allowed: bool = False
    approved_now: bool = False
    future_phase: Optional[str] = None
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Personal and production accounts are never allowed in any test-account scenario
        self.production_account_allowed = False
        self.personal_account_allowed = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DedicatedTestAccountRequirement:
        from dataclasses import fields as dc_fields
        known = {f.name for f in dc_fields(cls)}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["production_account_allowed"] = False
        kwargs["personal_account_allowed"] = False
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# CredentialProvisioningRoute
# ---------------------------------------------------------------------------

@dataclass
class CredentialProvisioningRoute(SchemaMixin):
    """A credential provisioning route for future test-account scenarios."""
    id: str = ""
    route_type: str = ""
    description: str = ""
    allowed_now: bool = False
    approved_now: bool = False
    secret_storage_location: str = ""
    repo_storage_allowed: bool = False
    logging_allowed: bool = False
    client_visible_allowed: bool = False
    requires_redaction: bool = True
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Repo storage, logging, and client-visible credentials are never allowed
        self.repo_storage_allowed = False
        self.logging_allowed = False
        self.client_visible_allowed = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CredentialProvisioningRoute:
        from dataclasses import fields as dc_fields
        known = {f.name for f in dc_fields(cls)}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["repo_storage_allowed"] = False
        kwargs["logging_allowed"] = False
        kwargs["client_visible_allowed"] = False
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# DedicatedTestAccountPlan
# ---------------------------------------------------------------------------

@dataclass
class DedicatedTestAccountPlan(SchemaMixin):
    """Full planning document for future dedicated test-account lanes."""
    project_id: str = ""
    requirements: List[DedicatedTestAccountRequirement] = field(default_factory=list)
    provisioning_routes: List[CredentialProvisioningRoute] = field(default_factory=list)
    allowed_now: bool = False
    planned_count: int = 0
    blocked_count: int = 0
    safe_for_execution_now: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Dedicated test-account execution is never safe without explicit future approval
        self.safe_for_execution_now = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DedicatedTestAccountPlan:
        scalar_keys = {
            "project_id", "allowed_now", "planned_count", "blocked_count",
            "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in scalar_keys}
        kwargs["requirements"] = [
            DedicatedTestAccountRequirement.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("requirements", [])
        ]
        kwargs["provisioning_routes"] = [
            CredentialProvisioningRoute.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("provisioning_routes", [])
        ]
        kwargs["safe_for_execution_now"] = False
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# ScenarioExecutionMatrixReport
# ---------------------------------------------------------------------------

@dataclass
class ScenarioExecutionMatrixReport(SchemaMixin):
    """Full scenario execution matrix report with lanes, rules, decisions, and test-account plan."""
    project_id: str = ""
    matrix_version: str = "1.0.0"
    lanes: List[ScenarioExecutionLane] = field(default_factory=list)
    permission_rules: List[ScenarioPermissionRule] = field(default_factory=list)
    target_profiles: List[ScenarioTargetProfile] = field(default_factory=list)
    decisions: List[ScenarioExecutionDecision] = field(default_factory=list)
    dedicated_test_account_plan: Optional[DedicatedTestAccountPlan] = None
    allowed_now_count: int = 0
    planned_count: int = 0
    blocked_count: int = 0
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScenarioExecutionMatrixReport:
        scalar_keys = {
            "project_id", "matrix_version",
            "allowed_now_count", "planned_count", "blocked_count",
            "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in scalar_keys}
        kwargs["lanes"] = [
            ScenarioExecutionLane.from_dict(x) if isinstance(x, dict) else x
            for x in data.get("lanes", [])
        ]
        kwargs["permission_rules"] = [
            ScenarioPermissionRule.from_dict(x) if isinstance(x, dict) else x
            for x in data.get("permission_rules", [])
        ]
        kwargs["target_profiles"] = [
            ScenarioTargetProfile.from_dict(x) if isinstance(x, dict) else x
            for x in data.get("target_profiles", [])
        ]
        kwargs["decisions"] = [
            ScenarioExecutionDecision.from_dict(x) if isinstance(x, dict) else x
            for x in data.get("decisions", [])
        ]
        plan = data.get("dedicated_test_account_plan")
        kwargs["dedicated_test_account_plan"] = (
            DedicatedTestAccountPlan.from_dict(plan) if isinstance(plan, dict) else None
        )
        return cls(**kwargs)
