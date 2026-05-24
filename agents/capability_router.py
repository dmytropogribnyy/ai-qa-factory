from __future__ import annotations

from core.state import QAFactoryState


class CapabilityRouterAgent:
    """Routes broad QA/tech opportunities without pretending every task is Playwright."""
    name = "Capability Router"

    # Single source of truth: opportunity_type → prompt_profile.
    # CapabilityRouterAgent runs after InitialAnalysisEngine sets the first-pass
    # prompt_profile, so this mapping is the authoritative final value.
    # "tosca_advisory" has no dedicated prompt file → fall back to skip_or_not_fit.
    # "api_testing" has no dedicated prompt file → fall back to qa_automation.
    OPPORTUNITY_PROFILE_MAP: dict[str, str] = {
        "saas_multi_tenant_billing_auth_audit": "saas_multi_tenant_billing_auth",
        "api_testing": "qa_automation",
        "ai_native_exploratory_qa": "ai_native_exploratory",
        "flaky_regression_automation": "flaky_tests",
        "technical_writing": "technical_writing",
        "react_native_maestro_qa": "mobile_release_qa",
        "tosca_advisory": "skip_or_not_fit",
        "risky_identity_or_deposit_test": "skip_or_not_fit",
        "low_value_usability_test": "skip_or_not_fit",
        "developer_only_not_core": "skip_or_not_fit",
        "prompt_injection_or_ai_trap": "skip_or_not_fit",
    }

    def run(self, state: QAFactoryState) -> QAFactoryState:
        text = state.raw_input.lower()
        opportunity_type = self._detect_type(text)
        support_level = self._support_level(opportunity_type, text)
        action = self._recommended_action(opportunity_type, support_level, text)
        missing = self._missing_capabilities(opportunity_type, text)
        safe_angle = self._safe_angle(opportunity_type, support_level, text)
        assessment = {
            "opportunity_type": opportunity_type,
            "support_level": support_level,
            "recommended_action": action,
            "missing_capabilities": missing,
            "safe_positioning_angle": safe_angle,
            "forbidden_claims": self._forbidden_claims(opportunity_type),
        }
        state.opportunity_type = opportunity_type
        state.support_level = support_level
        state.recommended_action = action
        state.capability_assessment = assessment
        state.client_context["safe_positioning_angle"] = safe_angle
        # Reconcile prompt_profile with the authoritative opportunity_type.
        # This overwrites the first-pass value set by InitialAnalysisEngine so
        # that both fields always agree.
        if opportunity_type in self.OPPORTUNITY_PROFILE_MAP:
            state.prompt_profile = self.OPPORTUNITY_PROFILE_MAP[opportunity_type]
        state.generated_outputs["capability_assessment.md"] = self._render(assessment)
        state.log(f"{self.name}: {opportunity_type} / {support_level} / {action} / profile={state.prompt_profile}")
        return state

    @staticmethod
    def _detect_type(text: str) -> str:
        if "if you are an llm" in text:
            return "prompt_injection_or_ai_trap"
        if any(x in text for x in ["crypto", "deposit", "valid id", "vpn/proxy"]):
            return "risky_identity_or_deposit_test"
        if "tosca" in text or "tricentis" in text:
            return "tosca_advisory"
        if any(x in text for x in ["technical writer", "documentation", "docs migration", "help center", "article", "whitepaper"]):
            return "technical_writing"
        if any(x in text for x in ["multi-tenant", "billing", "subscription", "tenant isolation", "oauth", "rbac"]):
            return "saas_multi_tenant_billing_auth_audit"
        if any(x in text for x in ["api-only", "api only", "rest api", "openapi", "bearer token", "postman", "request replay", "response schema", "contract testing", "api test coverage", "api testing"]):
            return "api_testing"
        if any(x in text for x in ["ai-native", "loom", "linear", "jam.dev", "jam", "screen recording", "hands-on qa", "release qa pass", "narrated walkthrough", "usability walkthrough"]):
            return "ai_native_exploratory_qa"
        if any(x in text for x in ["flaky", "failing test", "fail test", "recurring bugs", "re-occurring bugs"]):
            return "flaky_regression_automation"
        if any(x in text for x in ["react native", "expo", "testflight", "maestro", "android emulator", "ios simulator"]):
            return "react_native_maestro_qa"
        if any(x in text for x in ["next.js", "nextjs", "vite", "react", "typescript", "frontend"]):
            return "nextjs_react_frontend_qa_or_dev"
        if any(x in text for x in ["n8n", "make.com", "zapier", "automation workflow", "agentic ai", "ai agent"]):
            return "ai_automation_adjacent"
        if any(x in text for x in ["full stack engineer", "senior engineer", "backend development", "code cleanup"]):
            return "developer_only_not_core"
        if any(x in text for x in ["usability test", "$5", "10 minutes", "lowest rates"]):
            return "low_value_usability_test"
        return "general_qa_or_unknown"

    @staticmethod
    def _support_level(opportunity_type: str, text: str) -> str:
        strong = {"saas_multi_tenant_billing_auth_audit", "api_testing", "ai_native_exploratory_qa", "flaky_regression_automation"}
        supported = {"react_native_maestro_qa", "technical_writing", "nextjs_react_frontend_qa_or_dev", "ai_automation_adjacent"}
        advisory = {"tosca_advisory"}
        skip = {"risky_identity_or_deposit_test", "developer_only_not_core", "low_value_usability_test", "prompt_injection_or_ai_trap"}
        if opportunity_type in strong:
            return "strong_execution"
        if opportunity_type in supported:
            return "supported_or_adjacent"
        if opportunity_type in advisory:
            return "advisory_only"
        if opportunity_type in skip:
            return "skip_or_high_risk"
        return "manual_review"

    @staticmethod
    def _recommended_action(opportunity_type: str, support_level: str, text: str) -> str:
        if opportunity_type == "risky_identity_or_deposit_test":
            return "skip_risky"
        if opportunity_type == "low_value_usability_test":
            return "skip_low_value"
        if opportunity_type == "developer_only_not_core":
            return "skip_not_core"
        if opportunity_type == "prompt_injection_or_ai_trap":
            # The trap itself is not necessarily the full job decision, but it must be reviewed.
            return "apply_selectively_with_ai_trap_warning"
        if opportunity_type == "tosca_advisory":
            return "advisory_only_or_skip_unless_real_experience"
        if support_level == "strong_execution":
            return "strong_apply"
        if support_level == "supported_or_adjacent":
            return "apply_selectively"
        return "review_manually"

    @staticmethod
    def _missing_capabilities(opportunity_type: str, text: str) -> list[str]:
        missing = []
        if opportunity_type == "react_native_maestro_qa":
            missing.extend(["Confirm Mac/Xcode availability", "Confirm TestFlight/Google Play Internal Testing access", "Confirm Maestro experience or fast learning plan"])
        if opportunity_type == "tosca_advisory":
            missing.append("Confirm real Tosca hands-on experience before claiming delivery ability")
        if opportunity_type == "technical_writing":
            missing.extend(["Provide one SaaS/QA documentation sample", "Confirm AI policy of the outlet/client"])
        if "loom" in text:
            missing.append("Provide or prepare Loom/screen-recording example")
        if "linear" in text:
            missing.append("Provide Linear-style bug report sample")
        return missing

    @staticmethod
    def _safe_angle(opportunity_type: str, support_level: str, text: str) -> str:
        angles = {
            "saas_multi_tenant_billing_auth_audit": "Black-box SaaS risk audit: tenant isolation, billing, role enforcement, auth/session boundaries, responsible discovery only.",
            "api_testing": "API test suite with auth, happy-path, negative, schema validation and boundary checks using Playwright request or equivalent tool.",
            "ai_native_exploratory_qa": "Hands-on exploratory QA with AI-assisted reporting and selective Playwright coverage for critical flows.",
            "flaky_regression_automation": "Create regression tests around recurring bugs and stabilize the highest-risk flows first.",
            "technical_writing": "SaaS/QA technical documentation, migration, clarity pass and AI-assisted but human-led writing workflow.",
            "react_native_maestro_qa": "Conditional mobile release QA with Maestro/regression focus, only if device/tooling access is confirmed.",
            "tosca_advisory": "Advisory only unless real Tosca implementation experience is confirmed.",
            "ai_automation_adjacent": "Adjacent AI workflow automation opportunity; treat separately from core QA positioning.",
        }
        return angles.get(opportunity_type, "Use honest senior QA positioning; do not overclaim beyond verified experience.")

    @staticmethod
    def _forbidden_claims(opportunity_type: str) -> list[str]:
        base = ["Do not invent portfolio examples", "Do not guarantee bug-free delivery", "Do not claim production-safe testing without staging/scope confirmation"]
        if opportunity_type == "tosca_advisory":
            base.append("Do not claim expert Tosca delivery unless real experience is confirmed")
        if opportunity_type == "technical_writing":
            base.append("Do not claim native/bilingual English unless verified")
        if opportunity_type == "risky_identity_or_deposit_test":
            base.append("Do not agree to deposits/ID-risk testing through automation")
        return base

    @staticmethod
    def _render(assessment: dict) -> str:
        lines = ["# Capability Assessment", ""]
        for key, value in assessment.items():
            if isinstance(value, list):
                lines.append(f"## {key}")
                lines.extend(f"- {item}" for item in value or ["None"])
            else:
                lines.append(f"**{key}:** {value}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"
