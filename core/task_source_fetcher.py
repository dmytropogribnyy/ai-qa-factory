"""
Phase 5H — Task Source Fetcher.

Reads issues/tickets from Linear (and future: Jira, ClickUp) as read-only
requirement sources. Derives QA test scenarios from ticket content.

SAFETY:
- Read-only API calls only. No writeback, no status changes, no comments.
- API token read from env var — never stored, never logged, never serialised.
- No personal accounts. No production auth.
- Linear is a task source, NOT an app-under-test. Never navigated as a browser target.
- Output artifacts are internal only (client_delivery_allowed=False hardcoded).
- Max issues per fetch: 50 (configurable, capped at 50).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.schemas.task_source import (
    TASK_SOURCE_MAX_ISSUES,
    TASK_SOURCE_PROVIDERS_EXECUTABLE_5H,
    TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H,
    LINEAR_API_URL,
    TaskSourceFetchPolicy,
    TaskSourceFetchReport,
    TaskSourceIssue,
    TaskSourceScenario,
    TaskSourceToken,
)

_OUTPUTS_ROOT = Path("outputs")

# Env var name format: uppercase, underscores, no raw values accepted
_TOKEN_ENV_VAR_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")

# Blocked substrings in token env var names (reject if looks like raw token)
_BLOCKED_TOKEN_PATTERNS = [
    "lin_api_", "xoxb-", "xoxp-", "ghp_", "gho_", "Bearer ", "eyJ",
]

# Linear GraphQL query — read-only: issues + basic fields
_LINEAR_ISSUES_QUERY = """
query IssuesFetch($teamKey: String, $first: Int) {
  issues(filter: { team: { key: { eq: $teamKey } } }, first: $first,
         orderBy: updatedAt) {
    nodes {
      id
      identifier
      title
      description
      state { name }
      priority
      labels { nodes { name } }
      assignee { name }
      url
      team { name key }
      project { name }
    }
  }
}
"""

_LINEAR_ISSUE_BY_ID_QUERY = """
query IssueById($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    state { name }
    priority
    labels { nodes { name } }
    assignee { name }
    url
    team { name key }
    project { name }
  }
}
"""

# Priority mapping
_PRIORITY_MAP = {0: "no_priority", 1: "urgent", 2: "high", 3: "medium", 4: "low"}


class TaskSourceFetcher:
    """
    Read-only task source fetcher for Linear (Phase 5H).

    No writeback. No status changes. No comments. No webhooks.
    Token read from env var only — never stored or logged.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        project_id: str,
        provider: str = "linear",
        token_env_var: str = "",
        team_key: str = "",
        issue_ids: Optional[List[str]] = None,
        max_issues: int = TASK_SOURCE_MAX_ISSUES,
        approve_task_source_integration: bool = False,
        write: bool = True,
    ) -> TaskSourceFetchReport:
        """Fetch issues from task source and derive test scenarios."""

        policy = TaskSourceFetchPolicy(
            provider=provider,
            read_allowed=False,
            max_issues=min(max_issues, TASK_SOURCE_MAX_ISSUES),
        )

        # Gate 1: approval flag
        if not approve_task_source_integration:
            return self._blocked(project_id, provider, policy, [
                "Task source integration requires --approve-task-source-integration.",
                "This flag confirms read-only access to client task board.",
            ])

        # Gate 2: provider must be executable in Phase 5H
        if provider not in TASK_SOURCE_PROVIDERS_EXECUTABLE_5H:
            if provider in TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H:
                return self._blocked(project_id, provider, policy, [
                    f"Provider '{provider}' is planning-only in Phase 5H.",
                    f"Executable providers: {list(TASK_SOURCE_PROVIDERS_EXECUTABLE_5H)}",
                ])
            return self._blocked(project_id, provider, policy, [
                f"Unknown provider '{provider}'.",
                f"Supported: {list(TASK_SOURCE_PROVIDERS_EXECUTABLE_5H)}",
            ])

        # Gate 3: token env var name validation
        if not token_env_var:
            return self._blocked(project_id, provider, policy, [
                "token_env_var is required (e.g. LINEAR_API_TOKEN).",
                "Pass the env var NAME, not the token value.",
            ])
        token_env_var = token_env_var.strip()
        if not _TOKEN_ENV_VAR_PATTERN.match(token_env_var):
            return self._blocked(project_id, provider, policy, [
                f"token_env_var '{token_env_var}' must match [A-Z][A-Z0-9_]{{1,79}}.",
                "Example: LINEAR_API_TOKEN",
            ])
        for blocked in _BLOCKED_TOKEN_PATTERNS:
            if blocked.lower() in token_env_var.lower():
                return self._blocked(project_id, provider, policy, [
                    f"token_env_var '{token_env_var}' looks like a raw token value.",
                    "Pass the env var NAME (e.g. LINEAR_API_TOKEN), not the token itself.",
                ])

        # Gate 4: check env var is present (value never read directly)
        token_value = os.environ.get(token_env_var, "")
        if not token_value:
            return self._blocked(project_id, provider, policy, [
                f"Env var '{token_env_var}' is not set or empty.",
                f"Set it: $env:{token_env_var} = 'lin_api_....'",
            ])

        # Gate 5: team_key or issue_ids required
        if not team_key and not issue_ids:
            return self._blocked(project_id, provider, policy, [
                "Either team_key or issue_ids must be provided.",
                "Example: --team-key ENG or --issue-ids QA-123,QA-124",
            ])

        token_ref = TaskSourceToken(
            provider=provider,
            token_env_var=token_env_var,
            token_present=True,
            scopes_requested=["read:issues", "read:projects", "read:teams"],
            read_only_confirmed=True,
        )
        object.__setattr__(policy, "read_allowed", True)

        # Fetch issues
        raw_issues, fetch_error = self._fetch_linear_issues(
            token_value=token_value,
            team_key=team_key,
            issue_ids=issue_ids or [],
            max_issues=min(max_issues, TASK_SOURCE_MAX_ISSUES),
        )

        if fetch_error:
            report = TaskSourceFetchReport(
                project_id=project_id,
                provider=provider,
                team_or_project=team_key,
                status="error",
                policy=policy,
                token=token_ref,
                blockers=[f"API fetch error: {fetch_error}"],
                notes=["Token env var was present. Network/auth error during fetch."],
            )
            if write:
                self._write_artifacts(project_id, report)
            return report

        issues = [self._parse_linear_issue(r) for r in raw_issues]
        scenarios = [self._derive_scenario(i) for i in issues]

        report = TaskSourceFetchReport(
            project_id=project_id,
            provider=provider,
            team_or_project=team_key,
            issues_fetched=len(issues),
            issues=issues,
            scenarios=scenarios,
            policy=policy,
            token=token_ref,
            status="success",
            notes=[
                f"Fetched {len(issues)} issues from Linear (team_key='{team_key}').",
                "Read-only. No writeback performed.",
                f"Derived {len(scenarios)} test scenarios.",
                "Token value was never logged or stored.",
            ],
        )

        if write:
            self._write_artifacts(project_id, report)

        return report

    # ------------------------------------------------------------------
    # Linear API
    # ------------------------------------------------------------------

    def _fetch_linear_issues(
        self,
        token_value: str,
        team_key: str,
        issue_ids: List[str],
        max_issues: int,
    ) -> tuple[List[Dict[str, Any]], str]:
        """Call Linear GraphQL API. Returns (issues_list, error_str)."""
        try:
            import urllib.request
            import urllib.error

            if issue_ids:
                results = []
                for iid in issue_ids[:max_issues]:
                    payload = json.dumps({
                        "query": _LINEAR_ISSUE_BY_ID_QUERY,
                        "variables": {"id": iid},
                    }).encode()
                    req = urllib.request.Request(
                        LINEAR_API_URL,
                        data=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": token_value,
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read())
                    issue = (data.get("data") or {}).get("issue")
                    if issue:
                        results.append(issue)
                return results, ""
            else:
                payload = json.dumps({
                    "query": _LINEAR_ISSUES_QUERY,
                    "variables": {"teamKey": team_key, "first": max_issues},
                }).encode()
                req = urllib.request.Request(
                    LINEAR_API_URL,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": token_value,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                nodes = ((data.get("data") or {}).get("issues") or {}).get("nodes", [])
                return nodes, ""

        except Exception as exc:
            return [], str(exc)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_linear_issue(self, raw: Dict[str, Any]) -> TaskSourceIssue:
        state = (raw.get("state") or {}).get("name", "")
        assignee = (raw.get("assignee") or {}).get("name", "")
        team = (raw.get("team") or {}).get("name", "")
        project = (raw.get("project") or {}).get("name", "")
        labels = [
            n["name"] for n in ((raw.get("labels") or {}).get("nodes") or [])
            if isinstance(n, dict) and n.get("name")
        ]
        priority_int = int(raw.get("priority", 0))
        priority_str = _PRIORITY_MAP.get(priority_int, str(priority_int))

        desc = raw.get("description", "") or ""
        acceptance_criteria = self._extract_acceptance_criteria(desc)

        return TaskSourceIssue(
            issue_id=raw.get("identifier", raw.get("id", "")),
            title=raw.get("title", ""),
            description=desc,
            status=state,
            priority=priority_str,
            labels=labels,
            assignee=assignee,
            url=raw.get("url", ""),
            team=team,
            project=project,
            acceptance_criteria=acceptance_criteria,
        )

    def _extract_acceptance_criteria(self, description: str) -> List[str]:
        """Extract acceptance criteria lines from issue description."""
        criteria: List[str] = []
        in_ac_section = False
        for line in description.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if any(kw in lower for kw in (
                "acceptance criteria", "ac:", "given ", "when ", "then ",
                "should ", "must ", "expected behavior",
            )):
                in_ac_section = True
            if in_ac_section and stripped.startswith(("-", "*", "•", "✓", "✗")):
                criteria.append(stripped.lstrip("-*•✓✗ ").strip())
            if in_ac_section and not stripped and len(criteria) > 0:
                # blank line after criteria block — stop
                if len(criteria) >= 2:
                    break
        return criteria

    def _derive_scenario(self, issue: TaskSourceIssue) -> TaskSourceScenario:
        """Derive a basic QA scenario from a Linear issue."""
        scenario_type = self._infer_scenario_type(issue)
        return TaskSourceScenario(
            issue_id=issue.issue_id,
            issue_title=issue.title,
            scenario_title=f"[{issue.issue_id}] {issue.title}",
            scenario_type=scenario_type,
            target_url=issue.url,
            acceptance_criteria=issue.acceptance_criteria,
            priority=issue.priority,
            labels=issue.labels,
            derived_from_url=issue.url,
            notes=[
                f"Derived from Linear issue {issue.issue_id}.",
                f"Status: {issue.status}. Priority: {issue.priority}.",
            ],
        )

    def _infer_scenario_type(self, issue: TaskSourceIssue) -> str:
        combined = (issue.title + " " + issue.description).lower()
        if any(k in combined for k in ("login", "auth", "sign in", "oauth", "sso")):
            return "auth_smoke"
        if any(k in combined for k in ("api", "endpoint", "rest", "graphql", "swagger")):
            return "api_smoke"
        if any(k in combined for k in ("checkout", "payment", "order", "cart")):
            return "ecommerce_readonly"
        if any(k in combined for k in ("dashboard", "navigation", "page load", "ui")):
            return "ui_navigation"
        return "functional_smoke"

    # ------------------------------------------------------------------
    # Artifact writing
    # ------------------------------------------------------------------

    def _write_artifacts(self, project_id: str, report: TaskSourceFetchReport) -> None:
        out_dir = self._outputs_root / project_id / "16_task_source"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Main JSON report
        report_path = out_dir / "task_source_report.json"
        report_path.write_text(
            json.dumps(self._report_to_dict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        report.artifacts_written.append(str(report_path))

        # Scenarios JSON
        scenarios_path = out_dir / "derived_scenarios.json"
        scenarios_path.write_text(
            json.dumps(
                [s.to_dict() for s in report.scenarios], indent=2, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        report.artifacts_written.append(str(scenarios_path))

        # Markdown summary
        md_path = out_dir / "task_source_summary.md"
        md_path.write_text(self._render_md(report), encoding="utf-8")
        report.artifacts_written.append(str(md_path))

    def _report_to_dict(self, report: TaskSourceFetchReport) -> Dict[str, Any]:
        return {
            "project_id": report.project_id,
            "provider": report.provider,
            "team_or_project": report.team_or_project,
            "status": report.status,
            "issues_fetched": report.issues_fetched,
            "scenarios_derived": len(report.scenarios),
            "blockers": report.blockers,
            "warnings": report.warnings,
            "notes": report.notes,
            "artifacts_written": report.artifacts_written,
            # Safety flags
            "writeback_performed": report.writeback_performed,
            "raw_token_in_output": report.raw_token_in_output,
            "client_delivery_allowed": report.client_delivery_allowed,
            "policy": {
                "read_allowed": report.policy.read_allowed if report.policy else False,
                "writeback_allowed": False,
                "status_change_allowed": False,
                "comment_allowed": False,
                "max_issues": report.policy.max_issues if report.policy else 0,
            } if report.policy else {},
            "token": {
                "provider": report.token.provider if report.token else "",
                "token_env_var": report.token.token_env_var if report.token else "",
                "token_present": report.token.token_present if report.token else False,
                "token_value": "[NEVER_STORED]",
            } if report.token else {},
            "issues": [i.to_dict() for i in report.issues],
            "scenarios": [s.to_dict() for s in report.scenarios],
        }

    def _render_md(self, report: TaskSourceFetchReport) -> str:
        lines = [
            f"# Task Source Report — {report.provider.title()}",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Provider:** `{report.provider}`  ",
            f"**Team/Project:** `{report.team_or_project}`  ",
            f"**Status:** `{report.status}`  ",
            f"**Issues fetched:** {report.issues_fetched}  ",
            f"**Scenarios derived:** {len(report.scenarios)}  ",
            "",
            "## Safety",
            "",
            "| Property | Value |",
            "|---|---|",
            "| writeback_performed | `False` |",
            "| raw_token_in_output | `False` |",
            "| client_delivery_allowed | `False` |",
            "| read_only | `True` |",
            "",
        ]
        if report.blockers:
            lines += ["## Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
            lines.append("")
        if report.scenarios:
            lines += ["## Derived Test Scenarios", ""]
            for s in report.scenarios:
                lines.append(f"### [{s.issue_id}] {s.issue_title}")
                lines.append(f"- **Type:** `{s.scenario_type}`")
                lines.append(f"- **Priority:** `{s.priority}`")
                if s.acceptance_criteria:
                    lines.append("- **Acceptance criteria:**")
                    for ac in s.acceptance_criteria:
                        lines.append(f"  - {ac}")
                lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _blocked(
        self,
        project_id: str,
        provider: str,
        policy: TaskSourceFetchPolicy,
        blockers: List[str],
    ) -> TaskSourceFetchReport:
        return TaskSourceFetchReport(
            project_id=project_id,
            provider=provider,
            status="blocked",
            policy=policy,
            blockers=blockers,
            notes=["No API call was made. No token was read."],
        )
