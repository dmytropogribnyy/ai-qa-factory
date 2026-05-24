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

CREDENTIAL_TYPES: frozenset[str] = frozenset({
    "username_password",
    "api_key",
    "bearer_token",
    "session_cookie",
    "oauth",
    "basic_auth",
    "otp",
    "recovery_code",
    "unknown",
})

CREDENTIAL_STORAGE_MODES: frozenset[str] = frozenset({
    "env_var",
    "env_file",
    "secure_prompt",
    "external_secret_manager",
    "not_stored",
    "unknown",
})

AUTH_FLOW_TYPES: frozenset[str] = frozenset({
    "login",
    "logout",
    "session_persistence",
    "protected_route_access",
    "invalid_login",
    "password_reset",
    "email_verification",
    "two_factor_auth",
    "role_access",
    # Web/mobile extended flow types
    "oauth2_redirect",
    "email_link_open",
    "email_code_read",
    "totp_code_generate",
    "sms_code_manual_input",
    "mobile_deep_link_open",
    "session_storage_state",
    "protected_screen_access",
    "biometric_prompt_check",
    "unknown",
})

AUTH_ACTION_RISK_LEVELS: frozenset[str] = frozenset({
    "safe_auth_smoke",
    "auth_state_change",
    "destructive_account_action",
    "payment_or_auth",
    "security_sensitive",
    "production_read_only",
})

SECRET_REDACTION_TARGETS: frozenset[str] = frozenset({
    "logs",
    "markdown_reports",
    "json_reports",
    "screenshots",
    "videos",
    "traces",
    "console_logs",
    "network_logs",
    "client_reports",
})

APP_SURFACES: frozenset[str] = frozenset({
    "web",
    "mobile_web",
    "ios_app",
    "android_app",
    "desktop",
    "api",
    "unknown",
})

AUTH_MECHANISMS: frozenset[str] = frozenset({
    "username_password",
    "oauth2",
    "social_login",
    "email_magic_link",
    "email_otp",
    "sms_otp",
    "totp",
    "two_factor_auth",
    "passkey",
    "biometric",
    "session_cookie",
    "api_token",
    "sso",
    "unknown",
})

AUTH_PROVIDERS: frozenset[str] = frozenset({
    "local",
    "google",
    "apple",
    "microsoft",
    "github",
    "facebook",
    "custom_oauth2",
    "auth0",
    "okta",
    "firebase_auth",
    "cognito",
    "supabase_auth",
    "unknown",
})

MOBILE_AUTH_CONTEXTS: frozenset[str] = frozenset({
    "mobile_web",
    "native_ios",
    "native_android",
    "deep_link",
    "universal_link",
    "app_link",
    "biometric_prompt",
    "push_approval",
    "unknown",
})

MOBILE_EXECUTION_TARGETS: frozenset[str] = frozenset({
    "playwright_mobile_web_emulation",
    "android_emulator",
    "android_real_device",
    "ios_simulator",
    "ios_real_device",
    "cloud_device_farm",
    "manual_client_device",
    "unknown",
})

MOBILE_TOOLING_OPTIONS: frozenset[str] = frozenset({
    "playwright",
    "appium_optional",
    "maestro_optional",
    "browserstack_optional",
    "sauce_labs_optional",
    "local_android_emulator",
    "local_android_usb_device",
    "macos_ios_simulator",
    "unknown",
})

INTEGRATION_PROVIDERS: frozenset[str] = frozenset({
    "n8n",
    "make",
    "zapier",
    "github_actions",
    "slack",
    "telegram",
    "email",
    "google_drive",
    "jira",
    "linear",
    "notion",
    "browserstack",
    "checkly",
    "unknown",
})

INTEGRATION_DIRECTIONS: frozenset[str] = frozenset({
    "outbound_event",
    "inbound_webhook",
    "bidirectional",
    "manual_export",
})

INTEGRATION_EVENT_TYPES: frozenset[str] = frozenset({
    "project_created",
    "input_classified",
    "work_request_classified",
    "blueprint_created",
    "strategy_created",
    "tactical_plan_created",
    "approval_required",
    "approval_granted",
    "approval_rejected",
    "scaffold_generated",
    "validation_started",
    "validation_completed",
    "evidence_collected",
    "report_generated",
    "client_delivery_ready",
    "client_delivery_blocked",
    "quality_gate_passed",
    "quality_gate_failed",
    "cleanup_available",
    "ai_fallback_detected",
    "blocker_created",
    "blocker_resolved",
    "admin_attention_required",
})
