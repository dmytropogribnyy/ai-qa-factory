from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Dict, List

SCHEMA_VERSION = "5.0.5"

# TODO (Phase 2): Wire core.schemas domain models into QAFactoryState.
# Fields to add (all optional, all default to None or empty):
#   input_map: Optional[dict]         -> InputMap.to_dict() / InputMap.from_dict()
#   project_blueprint: Optional[dict] -> ProjectBlueprint.to_dict() / from_dict()
#   approval_history: Optional[dict]  -> ApprovalHistory.to_dict() / from_dict()
#   artifact_manifest: Optional[dict] -> ArtifactManifest.to_dict() / from_dict()
#   project_status: Optional[dict]    -> ProjectStatus.to_dict() / from_dict()
# Defer until Phase 2 to avoid breaking the 69 existing mock-mode tests.


def make_project_id(raw: str, mode: str = "project") -> str:
    base = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:48] or "qa-project"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{mode}-{base}-{digest}"


@dataclass
class QAFactoryState:
    project_id: str
    mode: str
    raw_input: str
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    task_type: str = "analysis"

    # v5.0.8 market/capability routing fields
    source_platform: str = "unknown"
    opportunity_type: str = "unknown"
    support_level: str = "unknown"
    recommended_action: str = "review_manually"
    commercial_fit: str = "unknown"
    capability_assessment: Dict[str, Any] = field(default_factory=dict)
    platform_assessment: Dict[str, Any] = field(default_factory=dict)
    evidence_required: List[str] = field(default_factory=list)
    mandatory_keywords: List[str] = field(default_factory=list)
    screening_questions: List[str] = field(default_factory=list)
    output_pack: List[str] = field(default_factory=list)
    skip_reasons: List[str] = field(default_factory=list)

    # v5.0.8 pre-screening / execution cockpit fields
    prescreening: Dict[str, Any] = field(default_factory=dict)
    system_suitability: str = "unknown"
    estimated_effort: str = ""
    recommended_workflow: str = ""
    required_inputs: List[str] = field(default_factory=list)
    approval_checkpoints: List[str] = field(default_factory=list)

    # v5.0.8 project-specific extension and self-health fields
    project_extensions: List[str] = field(default_factory=list)
    project_extension_requests: List[Dict[str, Any]] = field(default_factory=list)
    health_status: str = "unknown"
    health_findings: List[Dict[str, Any]] = field(default_factory=list)
    safe_auto_fixes: List[str] = field(default_factory=list)

    # v5.0.8 test-design / writing artifact fields
    test_design_artifacts: List[str] = field(default_factory=list)
    test_design_scope: str = ""
    temporary_agent_requests: List[Dict[str, Any]] = field(default_factory=list)
    extension_health_notes: List[str] = field(default_factory=list)

    client_id: str | None = None
    client_context: Dict[str, Any] = field(default_factory=dict)
    project_type: str = "Web Application"
    stack_choice: str = "playwright-ts"
    prompt_profile: str = "qa_automation"

    requirements: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    clarifications: List[str] = field(default_factory=list)
    detected_technologies: List[str] = field(default_factory=list)
    automation_scope: List[str] = field(default_factory=list)
    suggested_specialists: List[str] = field(default_factory=list)

    fit_score: int = 60
    suggested_price: str = ""
    suggested_milestone: str = ""

    quality_gate_results: Dict[str, Any] = field(default_factory=dict)
    generated_outputs: Dict[str, str] = field(default_factory=dict)

    approval_status: str = "needs_human_review"
    next_action: str = "review_outputs"

    # Reserved v5.x growth fields. They are present from v5.0.8 to avoid schema churn later.
    triggered_prompts_answers: Dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "auto"
    state_snapshots_path: str | None = None
    recon_artifacts: List[str] = field(default_factory=list)
    demo_videos: List[str] = field(default_factory=list)
    qa_review_history: List[Dict[str, Any]] = field(default_factory=list)
    agent_feedback: Dict[str, List[str]] = field(default_factory=dict)

    logs: List[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QAFactoryState":
        """Load older/newer state dicts without migrations when possible."""
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        if "schema_version" not in filtered:
            filtered["schema_version"] = "pre-5.0.1"
        return cls(**filtered)

    @classmethod
    def from_json(cls, text: str) -> "QAFactoryState":
        return cls.from_dict(json.loads(text))
