"""
Phase 5H — Task Source Integration schemas.

Supports Linear (and future: Jira, ClickUp) as read-only requirement sources.
Task source integration reads ticket data to build test scenarios — it does NOT
test Linear as an app-under-test, and it does NOT write back without explicit approval.

Safety invariants (hardcoded in __post_init__ + from_dict):
- writeback_allowed=False
- status_change_allowed=False
- comment_allowed=False
- webhook_allowed=False
- raw_token_logged=False
- client_delivery_allowed=False
- personal_account_allowed=False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

# Supported task source providers
TASK_SOURCE_PROVIDERS = ("linear", "jira", "clickup", "github_issues")

# Providers executable in Phase 5H (read-only API)
TASK_SOURCE_PROVIDERS_EXECUTABLE_5H = ("linear",)

# Providers that are planning-only in Phase 5H
TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H = ("jira", "clickup", "github_issues")

# Linear API base URL
LINEAR_API_URL = "https://api.linear.app/graphql"

# Max issues to fetch per request (safety limit)
TASK_SOURCE_MAX_ISSUES = 50


@dataclass
class TaskSourceToken(SchemaMixin):
    """Reference to a task source API token — env var name only, never the raw value."""

    provider: str = ""
    token_env_var: str = ""  # e.g. LINEAR_API_TOKEN — name only
    token_present: bool = False  # True if env var is set (value never stored)
    scopes_requested: List[str] = field(default_factory=list)
    read_only_confirmed: bool = False

    def __post_init__(self) -> None:
        # Token value is never stored — only the env var name
        pass


@dataclass
class TaskSourceIssue(SchemaMixin):
    """A single issue/ticket fetched from a task source (read-only)."""

    issue_id: str = ""
    title: str = ""
    description: str = ""
    status: str = ""
    priority: str = ""
    labels: List[str] = field(default_factory=list)
    assignee: str = ""
    url: str = ""
    team: str = ""
    project: str = ""
    acceptance_criteria: List[str] = field(default_factory=list)
    raw_data_logged: bool = False  # hardcoded False

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_data_logged", False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSourceIssue":
        obj = cls(
            issue_id=str(data.get("issue_id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            status=str(data.get("status", "")),
            priority=str(data.get("priority", "")),
            labels=[str(lbl) for lbl in data.get("labels", [])],
            assignee=str(data.get("assignee", "")),
            url=str(data.get("url", "")),
            team=str(data.get("team", "")),
            project=str(data.get("project", "")),
            acceptance_criteria=[str(a) for a in data.get("acceptance_criteria", [])],
        )
        object.__setattr__(obj, "raw_data_logged", False)
        return obj


@dataclass
class TaskSourceFetchPolicy(SchemaMixin):
    """Policy governing what task source operations are allowed."""

    provider: str = ""
    read_allowed: bool = False
    writeback_allowed: bool = False         # hardcoded False
    status_change_allowed: bool = False     # hardcoded False
    comment_allowed: bool = False           # hardcoded False
    webhook_allowed: bool = False           # hardcoded False
    raw_token_logged: bool = False          # hardcoded False
    client_delivery_allowed: bool = False   # hardcoded False
    personal_account_allowed: bool = False  # hardcoded False
    max_issues: int = TASK_SOURCE_MAX_ISSUES

    def __post_init__(self) -> None:
        object.__setattr__(self, "writeback_allowed", False)
        object.__setattr__(self, "status_change_allowed", False)
        object.__setattr__(self, "comment_allowed", False)
        object.__setattr__(self, "webhook_allowed", False)
        object.__setattr__(self, "raw_token_logged", False)
        object.__setattr__(self, "client_delivery_allowed", False)
        object.__setattr__(self, "personal_account_allowed", False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSourceFetchPolicy":
        obj = cls(
            provider=str(data.get("provider", "")),
            read_allowed=bool(data.get("read_allowed", False)),
            max_issues=int(data.get("max_issues", TASK_SOURCE_MAX_ISSUES)),
        )
        object.__setattr__(obj, "writeback_allowed", False)
        object.__setattr__(obj, "status_change_allowed", False)
        object.__setattr__(obj, "comment_allowed", False)
        object.__setattr__(obj, "webhook_allowed", False)
        object.__setattr__(obj, "raw_token_logged", False)
        object.__setattr__(obj, "client_delivery_allowed", False)
        object.__setattr__(obj, "personal_account_allowed", False)
        return obj


@dataclass
class TaskSourceScenario(SchemaMixin):
    """A QA test scenario derived from a task source issue."""

    issue_id: str = ""
    issue_title: str = ""
    scenario_title: str = ""
    scenario_type: str = ""
    target_url: str = ""
    acceptance_criteria: List[str] = field(default_factory=list)
    priority: str = ""
    labels: List[str] = field(default_factory=list)
    derived_from_url: str = ""
    notes: List[str] = field(default_factory=list)


@dataclass
class TaskSourceFetchReport(SchemaMixin):
    """Result of a task source fetch operation."""

    project_id: str = ""
    provider: str = ""
    team_or_project: str = ""
    issues_fetched: int = 0
    issues: List[TaskSourceIssue] = field(default_factory=list)
    scenarios: List[TaskSourceScenario] = field(default_factory=list)
    policy: Optional[TaskSourceFetchPolicy] = None
    token: Optional[TaskSourceToken] = None
    status: str = "pending"  # pending | success | blocked | error
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    artifacts_written: List[str] = field(default_factory=list)
    # Safety invariants
    writeback_performed: bool = False       # hardcoded False
    raw_token_in_output: bool = False       # hardcoded False
    client_delivery_allowed: bool = False   # hardcoded False

    def __post_init__(self) -> None:
        object.__setattr__(self, "writeback_performed", False)
        object.__setattr__(self, "raw_token_in_output", False)
        object.__setattr__(self, "client_delivery_allowed", False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSourceFetchReport":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            provider=str(data.get("provider", "")),
            team_or_project=str(data.get("team_or_project", "")),
            issues_fetched=int(data.get("issues_fetched", 0)),
            issues=[TaskSourceIssue.from_dict(i) for i in data.get("issues", [])],
            scenarios=[TaskSourceScenario.from_dict(s) for s in data.get("scenarios", [])],
            status=str(data.get("status", "pending")),
            blockers=[str(b) for b in data.get("blockers", [])],
            warnings=[str(w) for w in data.get("warnings", [])],
            notes=[str(n) for n in data.get("notes", [])],
            artifacts_written=[str(a) for a in data.get("artifacts_written", [])],
        )
        object.__setattr__(obj, "writeback_performed", False)
        object.__setattr__(obj, "raw_token_in_output", False)
        object.__setattr__(obj, "client_delivery_allowed", False)
        return obj
