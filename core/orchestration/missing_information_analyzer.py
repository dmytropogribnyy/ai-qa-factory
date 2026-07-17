"""MissingInformationAnalyzer — Phase 8.1 (deterministic, no LLM).

Profile-aware rules that surface what is missing, separated into:
- blocking: needed before planning can proceed meaningfully
- clarification: non-blocking questions
- approval_needed: human approvals a later execution phase would require
- future_execution_input: inputs only needed at execution time (not now)

Deterministic; keyword/presence checks only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from core.schemas.input_map import InputMap
from core.schemas.work_request import WorkRequest


@dataclass
class MissingInformation:
    blocking: List[str] = field(default_factory=list)
    clarification: List[str] = field(default_factory=list)
    approval_needed: List[str] = field(default_factory=list)
    future_execution_input: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            "blocking": list(self.blocking),
            "clarification": list(self.clarification),
            "approval_needed": list(self.approval_needed),
            "future_execution_input": list(self.future_execution_input),
        }

    @property
    def has_blocking(self) -> bool:
        return bool(self.blocking)


# Per-profile requirements: (label, needs_target_url)
_PROFILE_RULES: Dict[str, Dict[str, List[str]]] = {
    "web_app_audit": {
        "blocking": ["target URL of the web app"],
        "clarification": ["permission scope for the audit", "authentication requirements"],
        "approval_needed": ["approval to run browser checks against the target"],
        "future_execution_input": ["credentials or test account (execution-time only)"],
    },
    "api_project": {
        "blocking": ["API base URL or OpenAPI/Postman collection"],
        "clarification": ["authentication method"],
        "approval_needed": ["approval to call the API"],
        "future_execution_input": ["API credentials (execution-time only)"],
    },
    "data_project": {
        "blocking": ["database type and access scope (read/write)"],
        "clarification": ["schema or access details"],
        "approval_needed": ["approval for any database access"],
        "future_execution_input": ["database connection reference (execution-time only)"],
    },
    "code_project": {
        "blocking": ["repository or source files", "expected deliverable"],
        "clarification": ["test command to validate the change"],
        "approval_needed": ["approval before any repository write"],
        "future_execution_input": [],
    },
    "automation_project": {
        "blocking": ["automation trigger and target systems"],
        "clarification": ["expected side effects"],
        "approval_needed": ["approval before any external write or side effect"],
        "future_execution_input": [],
    },
    "technical_writing": {
        "blocking": ["target audience", "source material"],
        "clarification": ["desired format"],
        "approval_needed": [],
        "future_execution_input": [],
    },
    "mvp_launch_audit": {
        "blocking": ["target URL or app under review", "audit scope"],
        "clarification": ["launch timeline"],
        "approval_needed": ["approval to run checks against the target"],
        "future_execution_input": [],
    },
    "research_only": {
        "blocking": [],
        "clarification": ["research scope and preferred sources"],
        "approval_needed": [],
        "future_execution_input": [],
    },
}


class MissingInformationAnalyzer:
    """Deterministic, profile-aware missing-information analysis."""

    def analyze(
        self, profile: str, work_request: WorkRequest, input_map: InputMap
    ) -> MissingInformation:
        result = MissingInformation()
        if not profile:
            result.blocking.append("work profile could not be inferred; describe the task and desired outcome")
            return result

        rules = _PROFILE_RULES.get(profile, {})
        has_target_url = bool(getattr(work_request, "target_urls", None)) or any(
            s.input_type in ("target_url", "task_url", "api_docs_url", "repo_url")
            for s in input_map.sources
        )

        for label in rules.get("blocking", []):
            # If a target/URL/repo was already provided, don't ask for it again.
            if has_target_url and any(
                k in label.lower() for k in ("url", "repository", "source files", "collection")
            ):
                continue
            result.blocking.append(label)

        result.clarification.extend(rules.get("clarification", []))
        result.approval_needed.extend(rules.get("approval_needed", []))
        result.future_execution_input.extend(rules.get("future_execution_input", []))
        return result
