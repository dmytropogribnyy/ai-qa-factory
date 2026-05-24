from __future__ import annotations

import re
from core.state import QAFactoryState


class ProjectExtensionAgent:
    """Suggests temporary/project-specific extension packs without mutating code.

    The goal is fast adaptation for one opportunity: a special capability profile,
    prompt profile, checklist, or future custom specialist. Nothing is activated
    without Dmytro's approval.
    """

    name = "Project Extension Agent"

    EXTENSION_TRIGGERS = {
        "tosca": ("tosca_advisory_pack", "Tosca advisory pack", "Advisory-only Tosca terminology, client questions and scope warnings."),
        "maestro": ("mobile_maestro_pack", "Mobile Maestro pack", "React Native/Expo release QA checklist and Maestro YAML starter notes."),
        "react native": ("react_native_release_pack", "React Native release pack", "Device matrix, TestFlight/Google Play readiness and release regression flow."),
        "sharetribe": ("sharetribe_marketplace_pack", "Sharetribe marketplace advisory pack", "Marketplace messaging/transaction flow risks; likely dev-heavy."),
        "n8n": ("ai_automation_pack", "AI automation workflow pack", "n8n/Make workflow discovery, testing and handoff checklist."),
        "make.com": ("ai_automation_pack", "AI automation workflow pack", "n8n/Make workflow discovery, testing and handoff checklist."),
        "technical documentation": ("technical_docs_pack", "Technical documentation pack", "SaaS documentation migration, sample rewrite and editor-facing pitch pack."),
        "help center": ("technical_docs_pack", "Technical documentation pack", "Help center migration and IA/readability audit pack."),
        "stripe": ("billing_risk_pack", "Billing risk pack", "Stripe sandbox, subscription, invoice and plan-limit testing checklist."),
        "multi-tenant": ("tenant_isolation_pack", "Tenant isolation pack", "Org/user role matrix, API tampering checks and responsible-discovery guardrails."),
        "offline": ("pwa_offline_pack", "PWA/offline pack", "Offline sync, storage, conflict and recovery testing checklist."),
        "bullmq": ("async_jobs_pack", "Async jobs/race-condition pack", "Queue/race-condition testing notes and observability questions."),
        "linear": ("bug_reporting_pack", "Bug reporting pack", "Linear ticket structure with screenshots, Loom, logs and severity."),
        "loom": ("bug_reporting_pack", "Bug reporting pack", "Recorded evidence and narrated reproduction package."),
        "test strategy": ("test_design_pack", "Test design pack", "Strategy, plan and test-case artifact generation for requirements/briefs."),
        "test plan": ("test_design_pack", "Test design pack", "Strategy, plan and test-case artifact generation for requirements/briefs."),
        "test cases": ("test_design_pack", "Test design pack", "Strategy, plan and test-case artifact generation for requirements/briefs."),
        "acceptance criteria": ("test_design_pack", "Test design pack", "Strategy, plan and test-case artifact generation for requirements/briefs."),
    }

    def run(self, state: QAFactoryState) -> QAFactoryState:
        text = state.raw_input.lower()
        requests: list[dict] = []
        seen: set[str] = set()
        for keyword, (pack_id, title, purpose) in self.EXTENSION_TRIGGERS.items():
            if keyword in text and pack_id not in seen:
                seen.add(pack_id)
                requests.append({
                    "pack_id": pack_id,
                    "title": title,
                    "trigger": keyword,
                    "purpose": purpose,
                    "status": "suggested_not_activated",
                    "approval_required": True,
                })

        if state.support_level in {"advisory_only", "supported_partial"} and "capability_gap_pack" not in seen:
            requests.append({
                "pack_id": "capability_gap_pack",
                "title": "Capability gap pack",
                "trigger": state.support_level,
                "purpose": "Clarify what the system can do, what Dmytro must verify manually, and what must not be claimed.",
                "status": "suggested_not_activated",
                "approval_required": True,
            })

        state.project_extension_requests = requests
        state.project_extensions = [r["pack_id"] for r in requests]
        if requests:
            state.approval_checkpoints.append("Approve or reject suggested project-specific extension packs before client-facing work.")
        state.generated_outputs["PROJECT_EXTENSION_PLAN.md"] = self._build_report(state, requests)
        state.log(f"{self.name}: {len(requests)} extension packs suggested")
        return state

    def _build_report(self, state: QAFactoryState, requests: list[dict]) -> str:
        lines = [
            "# Project Extension Plan",
            "",
            "Purpose: allow AI QA Factory to adapt quickly to a specific project without pretending to support every stack deeply.",
            "",
            "## Rule",
            "Temporary extension packs may add prompts, checklists, sample artifacts or advisory specialists, but they must not auto-claim new hands-on expertise and must not execute risky actions without approval.",
            "",
        ]
        if not requests:
            lines += ["## Suggested packs", "", "- None required for this input. Core workflow is enough."]
        else:
            lines += ["## Suggested packs", ""]
            for item in requests:
                lines.append(f"### {item['title']}")
                lines.append(f"- Pack ID: `{item['pack_id']}`")
                lines.append(f"- Trigger: `{item['trigger']}`")
                lines.append(f"- Purpose: {item['purpose']}")
                lines.append(f"- Status: `{item['status']}`")
                lines.append("- Approval required: yes")
                lines.append("")
        lines += [
            "## How to activate safely",
            "1. Review whether this pack is needed for the current opportunity.",
            "2. Add a prompt/profile/checklist under `prompts/`, `capabilities/`, or `project_extensions/` only if useful.",
            "3. Keep the pack project-scoped until it proves reusable on 2-3 real opportunities.",
            "4. Promote it to a permanent capability only after repeated value is proven.",
            "",
            "## Forbidden",
            "- Do not invent project experience or tool expertise.",
            "- Do not auto-submit proposals or client messages.",
            "- Do not run destructive tests or real payments.",
            "- Do not add permanent complexity for a one-off edge case.",
        ]
        return "\n".join(lines) + "\n"
