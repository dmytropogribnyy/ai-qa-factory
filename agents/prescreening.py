from __future__ import annotations

import re
from core.state import QAFactoryState


class PreScreeningAgent:
    """Human-friendly pre-screening before spending time/Connects or taking work.

    This agent answers: is this opportunity suitable, what can Factory do,
    what is the rough effort, what is missing, and which workflow should run next.
    """

    name = "Pre-screening"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        assessment = self._assess(state)
        state.prescreening = assessment
        state.estimated_effort = assessment["estimated_effort"]
        state.system_suitability = assessment["system_suitability"]
        state.required_inputs = assessment["required_inputs"]
        state.recommended_workflow = assessment["recommended_workflow"]
        state.approval_checkpoints = assessment["approval_checkpoints"]
        state.generated_outputs["PRESCREENING_REPORT.md"] = self._render(assessment)
        state.log(f"{self.name}: {assessment['system_suitability']} / {assessment['estimated_effort']}")
        return state

    @classmethod
    def _assess(cls, state: QAFactoryState) -> dict:
        text = state.raw_input.lower()
        action = state.recommended_action
        opp = state.opportunity_type
        support = state.support_level

        blockers: list[str] = []
        required_inputs = ["Full job/client brief or task description", "Target URL/app context if execution is expected"]
        realistic_scope = "Opportunity analysis, proposal pack, QA plan, and human-reviewed delivery artifacts."
        estimated_effort = "Unknown; requires manual scoping"
        system_suitability = "prescreen_only_until_scope_confirmed"
        recommended_workflow = "prescreen"

        if action.startswith("skip"):
            system_suitability = "not_suitable_for_execution"
            estimated_effort = "Do not estimate execution; recommended action is skip."
            recommended_workflow = "filter"
            realistic_scope = "Use Factory only to document the skip reason and avoid spending time/Connects."
        elif opp == "saas_multi_tenant_billing_auth_audit":
            system_suitability = "strong_for_prescreen_and_audit_planning"
            estimated_effort = "Trial: 1 hour / Full audit: 8–12 hours over 3–5 working days"
            recommended_workflow = "audit_then_full_if_approved"
            realistic_scope = "Black-box SaaS risk audit plan, bug report structure, API/DevTools checklist, and delivery summary."
            required_inputs += ["Test org accounts/aliases", "Staging or approved production-safe scope", "Severity rubric", "Permission boundaries for API replay"]
        elif opp == "ai_native_exploratory_qa":
            system_suitability = "strong_for_prescreen_release_qa_and_bug_reporting"
            estimated_effort = "Initial release pass: 4–10 hours; multi-app ongoing QA: ongoing hourly scope"
            recommended_workflow = "upwork_or_full_after_approval"
            realistic_scope = "Exploratory QA strategy, Linear/Loom-style bug reporting pack, Playwright critical-flow candidates, release checklist."
            required_inputs += ["App URLs and test accounts", "Device/browser matrix", "Linear/Loom/Jam preference", "Critical flows and release cadence"]
        elif opp == "flaky_regression_automation":
            system_suitability = "strong_for_repro_and_regression_test_planning"
            estimated_effort = "Starter: 2–5 hours for one recurring bug; larger suite: scope after repo access"
            recommended_workflow = "review_or_full_after_approval"
            realistic_scope = "Analyze failure pattern, propose failing regression test, generate Playwright scaffold/notes where appropriate."
            required_inputs += ["Failing scenario description", "Existing test/code access if available", "CI logs/screenshots/traces"]
        elif opp == "technical_writing":
            system_suitability = "strong_adjacent_for_docs_pitch_and_plan"
            estimated_effort = "Sample rewrite/audit: 1–3 hours; article/docs migration: 4–20+ hours depending on volume"
            recommended_workflow = "job"
            realistic_scope = "Writing pitch, documentation audit plan, outline, sample rewrite, evidence requirements."
            required_inputs += ["Source docs or article brief", "Target audience", "AI policy for the publication/client", "One real writing sample"]
        elif opp == "react_native_maestro_qa":
            system_suitability = "conditional_if_device_tooling_available"
            estimated_effort = "Initial release pass: 3–6 hours; Maestro setup depends on app/build access"
            recommended_workflow = "upwork_or_audit_after_device_check"
            realistic_scope = "Mobile release QA plan, device/tooling checklist, Maestro test strategy."
            required_inputs += ["Mac/Xcode availability", "TestFlight/Internal Testing access", "Android emulator/device", "Maestro or alternative tool confirmation"]
            if "mac" not in text and "xcode" not in text:
                blockers.append("Must confirm Mac/Xcode/iOS Simulator availability before applying.")
        elif opp == "tosca_advisory":
            system_suitability = "advisory_only_unless_real_tosca_experience_confirmed"
            estimated_effort = "No execution estimate unless verified Tosca hands-on capability exists."
            recommended_workflow = "filter_or_advisory"
            realistic_scope = "Opportunity analysis, client questions, terminology map, and honest skip/advisory recommendation."
            blockers.append("Do not claim Tosca implementation expertise unless verified by Dmytro.")
        elif opp in {"nextjs_react_frontend_qa_or_dev", "ai_automation_adjacent"}:
            system_suitability = "partial_adjacent_prescreen_only_until_scope_confirmed"
            estimated_effort = "Discovery: 1–2 hours; execution estimate only after deciding QA vs developer scope."
            recommended_workflow = "prescreen_then_manual_decision"
            realistic_scope = "Scope/risk analysis, QA/UX angle, questions, and possible narrow proposal."
            blockers.append("Clarify whether this is QA/validation/advisory or a developer implementation role.")
        elif support == "strong_execution":
            system_suitability = "likely_suitable_after_human_review"
            estimated_effort = "Small milestone: 2–5 hours; full scope requires app/repo/brief access."
            recommended_workflow = "upwork_or_full_after_approval"
        elif support == "supported_or_adjacent":
            system_suitability = "conditional_or_adjacent"
            estimated_effort = "Discovery first; exact estimate depends on missing evidence/tooling."
            recommended_workflow = "job_then_manual_decision"
        else:
            system_suitability = "manual_review_required"
            estimated_effort = "Cannot estimate reliably from current text."
            recommended_workflow = "filter"
            required_inputs += ["Clear scope", "Expected deliverables", "Access constraints", "Budget/timeline"]

        if "http" in text or re.search(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", text):
            required_inputs.append("If only a link was provided: paste job text or provide a browser/app brief; URL fetching is not a substitute for scope review.")

        approval_checkpoints = [
            "Approve spending Connects / replying to client",
            "Approve proposed scope and first milestone",
            "Approve any real-site testing boundary and credentials handling",
            "Approve final client-facing text before sending",
            "Approve delivery artifacts before sharing",
        ]
        if blockers:
            approval_checkpoints.insert(0, "Resolve blockers before applying or executing")

        return {
            "system_suitability": system_suitability,
            "recommended_workflow": recommended_workflow,
            "estimated_effort": estimated_effort,
            "realistic_scope": realistic_scope,
            "required_inputs": cls._dedupe(required_inputs),
            "blockers": blockers,
            "approval_checkpoints": approval_checkpoints,
            "factory_can_do": cls._factory_can_do(state, system_suitability),
            "factory_should_not_do": cls._factory_should_not_do(state),
        }

    @staticmethod
    def _factory_can_do(state: QAFactoryState, suitability: str) -> list[str]:
        base = [
            "Pre-screen the opportunity and classify fit/risk",
            "Generate human-readable decision and next-step reports",
            "Prepare proposal/screening answers/evidence requests where appropriate",
            "Build QA plan or documentation plan depending on task type",
        ]
        if "strong" in suitability or state.support_level == "strong_execution":
            base += ["Generate Playwright/API starter artifacts where relevant", "Prepare delivery/reporting checklist"]
        if "advisory" in suitability:
            base += ["Provide advisory notes and client questions without overclaiming execution expertise"]
        return base

    @staticmethod
    def _factory_should_not_do(state: QAFactoryState) -> list[str]:
        return [
            "Auto-submit proposals or messages",
            "Claim experience/evidence that Dmytro has not verified",
            "Run destructive tests, real payments, scraping, or unauthorized security testing",
            "Execute evaluator-platform paid tasks with AI",
            "Treat a URL/screenshot alone as enough to accept a scoped client commitment",
        ]

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    @staticmethod
    def _render(assessment: dict) -> str:
        lines = ["# Pre-screening Report", "", "This report answers whether the opportunity is suitable and what Factory can realistically do before Dmytro commits.", ""]
        order = ["system_suitability", "recommended_workflow", "estimated_effort", "realistic_scope", "blockers", "required_inputs", "approval_checkpoints", "factory_can_do", "factory_should_not_do"]
        for key in order:
            value = assessment.get(key)
            lines.append(f"## {key}")
            if isinstance(value, list):
                lines.extend(f"- {item}" for item in value or ["None"])
            else:
                lines.append(str(value or "Not set"))
            lines.append("")
        return "\n".join(lines).strip() + "\n"
