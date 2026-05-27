"""Phase 5M — API Contract schemas.

Models the structured output of API contract import, test generation, and CI/CD building.

Safety invariants (hardcoded in __post_init__ + from_dict):
- raw_secrets_allowed=False
- destructive_api_calls_allowed=False
- production_write_allowed=False
- auto_pr_creation_allowed=False
- client_repo_writeback_allowed=False
- human_review_required=True
- client_delivery_allowed=False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENDPOINT_SAFETY_LEVELS = ("safe_readonly", "requires_approval", "blocked_by_default")

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

RISKY_PATH_TERMS = (
    "delete", "remove", "destroy", "purge", "reset", "clear",
    "payment", "charge", "billing", "refund", "purchase", "checkout",
    "admin", "superuser", "root", "sudo",
    "account", "deactivate", "disable", "ban", "suspend",
    "export", "bulk", "batch",
)

CICD_PLATFORMS = ("github_actions", "gitlab_ci", "azure_devops")

SOURCE_FORMATS = ("openapi_json", "openapi_yaml", "postman_collection", "unknown")


# ---------------------------------------------------------------------------
# API Contract schemas
# ---------------------------------------------------------------------------

@dataclass
class APIParameter(SchemaMixin):
    """A single API endpoint parameter."""
    name: str = ""
    location: str = "query"  # query, path, header, cookie, body
    required: bool = False
    param_type: str = "string"
    description: str = ""


@dataclass
class APIEndpoint(SchemaMixin):
    """A single API endpoint with safety classification."""
    method: str = "GET"
    path: str = "/"
    operation_id: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    parameters: List[APIParameter] = field(default_factory=list)
    requires_auth: bool = False
    safety_classification: str = "safe_readonly"
    safety_reason: str = ""

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["parameters"] = [p.to_dict() for p in self.parameters]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "APIEndpoint":
        params = [
            APIParameter(**p) if isinstance(p, dict) else p
            for p in data.get("parameters", [])
        ]
        return cls(
            method=str(data.get("method", "GET")).upper(),
            path=str(data.get("path", "/")),
            operation_id=str(data.get("operation_id", "")),
            summary=str(data.get("summary", "")),
            tags=list(data.get("tags", [])),
            parameters=params,
            requires_auth=bool(data.get("requires_auth", False)),
            safety_classification=str(data.get("safety_classification", "safe_readonly")),
            safety_reason=str(data.get("safety_reason", "")),
        )


@dataclass
class AuthRequirement(SchemaMixin):
    """Auth requirement detected in the contract."""
    scheme_name: str = ""
    scheme_type: str = "unknown"  # apiKey, http, oauth2, openIdConnect
    description: str = ""
    scopes: List[str] = field(default_factory=list)


@dataclass
class APIContractReport(SchemaMixin):
    """Full API contract analysis report."""
    project_id: str = ""
    source_format: str = "unknown"
    source_file: str = ""
    spec_title: str = ""
    spec_version: str = ""
    base_url: str = ""
    endpoints: List[APIEndpoint] = field(default_factory=list)
    auth_requirements: List[AuthRequirement] = field(default_factory=list)
    total_endpoints: int = 0
    safe_readonly_count: int = 0
    requires_approval_count: int = 0
    blocked_count: int = 0
    parse_errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    raw_secrets_allowed: bool = False
    destructive_api_calls_allowed: bool = False
    production_write_allowed: bool = False
    human_review_required: bool = True
    client_delivery_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_secrets_allowed", False)
        object.__setattr__(self, "destructive_api_calls_allowed", False)
        object.__setattr__(self, "production_write_allowed", False)
        object.__setattr__(self, "human_review_required", True)
        object.__setattr__(self, "client_delivery_allowed", False)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["endpoints"] = [e.to_dict() for e in self.endpoints]
        d["auth_requirements"] = [a.to_dict() for a in self.auth_requirements]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "APIContractReport":
        endpoints = [
            APIEndpoint.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("endpoints", [])
        ]
        auth_reqs = [
            AuthRequirement(**a) if isinstance(a, dict) else a
            for a in data.get("auth_requirements", [])
        ]
        obj = cls(
            project_id=str(data.get("project_id", "")),
            source_format=str(data.get("source_format", "unknown")),
            source_file=str(data.get("source_file", "")),
            spec_title=str(data.get("spec_title", "")),
            spec_version=str(data.get("spec_version", "")),
            base_url=str(data.get("base_url", "")),
            endpoints=endpoints,
            auth_requirements=auth_reqs,
            total_endpoints=int(data.get("total_endpoints", 0)),
            safe_readonly_count=int(data.get("safe_readonly_count", 0)),
            requires_approval_count=int(data.get("requires_approval_count", 0)),
            blocked_count=int(data.get("blocked_count", 0)),
            parse_errors=list(data.get("parse_errors", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "raw_secrets_allowed", False)
        object.__setattr__(obj, "destructive_api_calls_allowed", False)
        object.__setattr__(obj, "production_write_allowed", False)
        object.__setattr__(obj, "human_review_required", True)
        object.__setattr__(obj, "client_delivery_allowed", False)
        return obj


# ---------------------------------------------------------------------------
# Generated Tests schemas
# ---------------------------------------------------------------------------

@dataclass
class GeneratedTestFile(SchemaMixin):
    """Metadata for a single generated test file."""
    filename: str = ""
    artifact_dir: str = ""
    test_type: str = "smoke"  # smoke, schema, negative
    endpoint_count: int = 0
    notes: str = ""


@dataclass
class GeneratedTestsReport(SchemaMixin):
    """Report of all generated test artifacts."""
    project_id: str = ""
    source_contract_file: str = ""
    generated_files: List[GeneratedTestFile] = field(default_factory=list)
    total_test_stubs: int = 0
    safe_endpoints_covered: int = 0
    skipped_blocked_endpoints: int = 0
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    executable_without_approval: bool = False
    raw_secrets_allowed: bool = False
    human_review_required: bool = True
    client_delivery_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable_without_approval", False)
        object.__setattr__(self, "raw_secrets_allowed", False)
        object.__setattr__(self, "human_review_required", True)
        object.__setattr__(self, "client_delivery_allowed", False)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["generated_files"] = [f.to_dict() for f in self.generated_files]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "GeneratedTestsReport":
        files = [
            GeneratedTestFile(**f) if isinstance(f, dict) else f
            for f in data.get("generated_files", [])
        ]
        obj = cls(
            project_id=str(data.get("project_id", "")),
            source_contract_file=str(data.get("source_contract_file", "")),
            generated_files=files,
            total_test_stubs=int(data.get("total_test_stubs", 0)),
            safe_endpoints_covered=int(data.get("safe_endpoints_covered", 0)),
            skipped_blocked_endpoints=int(data.get("skipped_blocked_endpoints", 0)),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "executable_without_approval", False)
        object.__setattr__(obj, "raw_secrets_allowed", False)
        object.__setattr__(obj, "human_review_required", True)
        object.__setattr__(obj, "client_delivery_allowed", False)
        return obj


# ---------------------------------------------------------------------------
# CI/CD schemas
# ---------------------------------------------------------------------------

@dataclass
class CICDConfig(SchemaMixin):
    """CI/CD pipeline configuration artifact."""
    project_id: str = ""
    platform: str = "github_actions"
    workflow_filename: str = ""
    workflow_content: str = ""
    scaffold_root: str = ""
    steps_included: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    auto_pr_creation_allowed: bool = False
    client_repo_writeback_allowed: bool = False
    production_deploy_allowed: bool = False
    human_review_required: bool = True
    client_delivery_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "auto_pr_creation_allowed", False)
        object.__setattr__(self, "client_repo_writeback_allowed", False)
        object.__setattr__(self, "production_deploy_allowed", False)
        object.__setattr__(self, "human_review_required", True)
        object.__setattr__(self, "client_delivery_allowed", False)

    @classmethod
    def from_dict(cls, data: dict) -> "CICDConfig":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            platform=str(data.get("platform", "github_actions")),
            workflow_filename=str(data.get("workflow_filename", "")),
            workflow_content=str(data.get("workflow_content", "")),
            scaffold_root=str(data.get("scaffold_root", "")),
            steps_included=list(data.get("steps_included", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "auto_pr_creation_allowed", False)
        object.__setattr__(obj, "client_repo_writeback_allowed", False)
        object.__setattr__(obj, "production_deploy_allowed", False)
        object.__setattr__(obj, "human_review_required", True)
        object.__setattr__(obj, "client_delivery_allowed", False)
        return obj


@dataclass
class CICDManifest(SchemaMixin):
    """Manifest of all generated CI/CD artifacts."""
    project_id: str = ""
    platform: str = "github_actions"
    artifacts: List[str] = field(default_factory=list)
    scaffold_root: str = ""
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    auto_pr_creation_allowed: bool = False
    client_repo_writeback_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "auto_pr_creation_allowed", False)
        object.__setattr__(self, "client_repo_writeback_allowed", False)
        object.__setattr__(self, "human_review_required", True)

    @classmethod
    def from_dict(cls, data: dict) -> "CICDManifest":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            platform=str(data.get("platform", "github_actions")),
            artifacts=list(data.get("artifacts", [])),
            scaffold_root=str(data.get("scaffold_root", "")),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "auto_pr_creation_allowed", False)
        object.__setattr__(obj, "client_repo_writeback_allowed", False)
        object.__setattr__(obj, "human_review_required", True)
        return obj
