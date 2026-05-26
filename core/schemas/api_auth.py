"""
Phase 5E — API Auth Smoke schemas.

Safety invariants (hardcoded False, enforced in __post_init__ AND from_dict):
- raw_credentials_logged
- raw_credentials_serialized
- token_logged
- token_serialized
- safe_to_deliver
- approved_for_client_delivery
- personal_account_used
- production_account_used
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.schemas.base import SchemaMixin


@dataclass
class APIAuthTarget:
    """Profile for a safe API auth target."""
    profile_name: str = ""
    base_url: str = ""
    auth_endpoint: str = "/auth"
    safe_read_endpoint: Optional[str] = None
    target_category: str = ""
    description: str = ""


@dataclass
class APIAuthCommand(SchemaMixin):
    """Record of a single API call made during auth execution."""
    id: str = ""
    method: str = ""
    url: str = ""          # URL only — no body/credentials serialized
    status_code: Optional[int] = None
    status: str = "unknown"
    duration_seconds: float = 0.0
    token_present: bool = False
    stdout_excerpt: str = ""   # masked
    stderr_excerpt: str = ""   # masked
    executed: bool = False
    safety_notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Never log token value — only presence flag
        pass


@dataclass
class APIAuthSessionArtifact(SchemaMixin):
    """Reference to a session artifact — never contains raw values."""
    artifact_type: str = ""
    path: str = ""
    internal_only: bool = True
    approved_for_commit: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        self.internal_only = True
        self.approved_for_commit = False

    @classmethod
    def from_dict(cls, data: dict) -> "APIAuthSessionArtifact":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.internal_only = True
        obj.approved_for_commit = False
        return obj


@dataclass
class APIAuthExecutionReport(SchemaMixin):
    """Full report for a Phase 5E API auth execution run."""
    project_id: str = ""
    target_profile: str = ""
    base_url: str = ""
    execution_status: str = "unknown"   # passed / failed / blocked / error
    approval_required: bool = True
    approved: bool = False

    # Safety invariants — always False
    raw_credentials_logged: bool = False
    raw_credentials_serialized: bool = False
    token_logged: bool = False
    token_serialized: bool = False
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    personal_account_used: bool = False
    production_account_used: bool = False

    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    commands: List[APIAuthCommand] = field(default_factory=list)
    session_artifacts: List[APIAuthSessionArtifact] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.raw_credentials_logged = False
        self.raw_credentials_serialized = False
        self.token_logged = False
        self.token_serialized = False
        self.safe_to_deliver = False
        self.approved_for_client_delivery = False
        self.personal_account_used = False
        self.production_account_used = False

    @classmethod
    def from_dict(cls, data: dict) -> "APIAuthExecutionReport":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.raw_credentials_logged = False
        obj.raw_credentials_serialized = False
        obj.token_logged = False
        obj.token_serialized = False
        obj.safe_to_deliver = False
        obj.approved_for_client_delivery = False
        obj.personal_account_used = False
        obj.production_account_used = False
        return obj
