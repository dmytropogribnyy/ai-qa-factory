from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.schemas.base import SchemaMixin

# Hard rule: AuthCheckResult must NEVER store username, password, token,
# cookie, session ID, JWT, or any secret value. Store only metadata and refs.


@dataclass
class AuthFlowStep(SchemaMixin):
    """One step in an authentication flow test plan."""

    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    flow_type: str = "unknown"
    description: str = ""
    risk_level: str = "payment_or_auth"
    requires_credentials: bool = True
    requires_approval: bool = True
    destructive: bool = False
    allowed_in_production: bool = False
    expected_evidence: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthFlowStep:
        return super().from_dict(data)


@dataclass
class AuthFlowPlan(SchemaMixin):
    """Full authentication flow test plan for a project target."""

    project_id: str
    target_ref_id: Optional[str] = None
    credential_ref_ids: List[str] = field(default_factory=list)
    environment_type: str = "unknown"
    # Web/mobile surface context
    app_surface: str = "unknown"
    auth_mechanism: str = "unknown"
    auth_provider: Optional[str] = None
    mobile_auth_context: Optional[str] = None
    steps: List[AuthFlowStep] = field(default_factory=list)
    approval_required: bool = True
    approved: bool = False
    blocked: bool = True
    blocked_reason: Optional[str] = None
    safe_to_execute: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "target_ref_id": self.target_ref_id,
            "credential_ref_ids": self.credential_ref_ids,
            "environment_type": self.environment_type,
            "app_surface": self.app_surface,
            "auth_mechanism": self.auth_mechanism,
            "auth_provider": self.auth_provider,
            "mobile_auth_context": self.mobile_auth_context,
            "steps": [s.to_dict() for s in self.steps],
            "approval_required": self.approval_required,
            "approved": self.approved,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "safe_to_execute": self.safe_to_execute,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthFlowPlan:
        steps = [
            AuthFlowStep.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("steps", [])
        ]
        return cls(
            project_id=data["project_id"],
            target_ref_id=data.get("target_ref_id"),
            credential_ref_ids=data.get("credential_ref_ids", []),
            environment_type=data.get("environment_type", "unknown"),
            app_surface=data.get("app_surface", "unknown"),
            auth_mechanism=data.get("auth_mechanism", "unknown"),
            auth_provider=data.get("auth_provider"),
            mobile_auth_context=data.get("mobile_auth_context"),
            steps=steps,
            approval_required=data.get("approval_required", True),
            approved=data.get("approved", False),
            blocked=data.get("blocked", True),
            blocked_reason=data.get("blocked_reason"),
            safe_to_execute=data.get("safe_to_execute", False),
            notes=data.get("notes", []),
        )


@dataclass
class AuthCheckResult(SchemaMixin):
    """Result of an auth check — metadata only, no secret values ever stored."""

    project_id: str
    action_id: Optional[str] = None
    executed: bool = False
    execution_mode: str = "mock"
    # auth_success is Optional: None means "not yet executed"
    auth_success: Optional[bool] = None
    evidence_refs: List[str] = field(default_factory=list)
    secrets_redacted: bool = True
    client_safe: bool = False
    blocked_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthCheckResult:
        return super().from_dict(data)
