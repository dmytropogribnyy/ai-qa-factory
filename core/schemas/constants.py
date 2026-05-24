from __future__ import annotations

INPUT_TYPES: frozenset[str] = frozenset({
    "text_brief",
    "task_url",
    "target_url",
    "screenshot",
    "archive",
    "api_spec",
    "test_file",
    "config_file",
    "unknown",
})

RISK_LEVELS: frozenset[str] = frozenset({
    "safe_analysis",
    "safe_local",
    "external_read_only",
    "external_write",
    "production_read_only",
    "payment_or_auth",
    "security_sensitive",
    "client_delivery",
})

PROJECT_TYPES: frozenset[str] = frozenset({
    "web_saas",
    "ecommerce",
    "api_backend",
    "ai_generated_app",
    "admin_panel",
    "auth_heavy",
    "mixed_ui_api",
    "unknown",
})

ENVIRONMENT_TYPES: frozenset[str] = frozenset({
    "local",
    "staging",
    "production",
    "sandbox",
    "unknown",
})

ACTION_STATUSES: frozenset[str] = frozenset({
    "pending",
    "approved",
    "rejected",
    "running",
    "completed",
    "failed",
    "skipped",
})

ACCESS_LEVELS: frozenset[str] = frozenset({
    "none",
    "read_only",
    "read_write",
    "admin",
})

ARTIFACT_TYPES: frozenset[str] = frozenset({
    "test_strategy",
    "test_plan",
    "test_cases",
    "scaffold",
    "proposal",
    "report",
    "evidence",
    "blueprint",
    "delivery_doc",
    "internal_note",
    "unknown",
})

ASSISTANT_TYPES: frozenset[str] = frozenset({
    "prescreen",
    "filter",
    "upwork",
    "plan",
    "test_design",
    "scaffold",
    "audit",
    "review",
    "delivery",
    "full",
    "ask",
    "mcp_guide",
})

WORK_DOMAINS: frozenset[str] = frozenset({
    "web_ui",
    "api",
    "mobile",
    "performance",
    "security",
    "accessibility",
    "data",
    "infrastructure",
    "unknown",
})

TASK_TYPES: frozenset[str] = frozenset({
    "prescreen",
    "proposal",
    "test_design",
    "scaffold",
    "audit",
    "review",
    "delivery",
    "consultation",
    "unknown",
})

DELIVERABLE_TYPES: frozenset[str] = frozenset({
    "proposal",
    "test_strategy",
    "test_plan",
    "test_cases",
    "scaffold",
    "report",
    "evidence_package",
    "delivery_doc",
    "unknown",
})
