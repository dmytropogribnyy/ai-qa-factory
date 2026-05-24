from __future__ import annotations

import re
from core.state import QAFactoryState


class PlatformRouterAgent:
    """Detects where an opportunity came from and what output format it needs."""
    name = "Platform Router"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        text = state.raw_input.lower()
        if state.client_context.get("source_platform_override"):
            platform = state.client_context["source_platform_override"]
        elif state.source_platform and state.source_platform != "unknown":
            platform = state.source_platform
        else:
            platform = "upwork" if state.mode in {"upwork", "job", "filter"} else self._detect_platform(text)
        output_pack = self._output_pack(platform, text)
        assessment = {
            "source_platform": platform,
            "output_pack": output_pack,
            "ai_policy_warning": self._ai_policy_warning(platform, text),
            "submission_style": self._submission_style(platform),
        }
        state.source_platform = platform
        state.platform_assessment = assessment
        state.output_pack = output_pack
        state.generated_outputs["platform_assessment.md"] = self._render(assessment)
        state.log(f"{self.name}: {platform}")
        return state

    @staticmethod
    def _detect_platform(text: str) -> str:
        if "upwork" in text or "connects" in text or "proposals:" in text or "posted yesterday" in text or "hourly" in text and "activity on this job" in text:
            return "upwork"
        if any(x in text for x in ["fiverr", "peopleperhour", "project catalog"]):
            return "microservice_marketplace"
        if any(x in text for x in ["draft.dev", "ndash", "airbyte", "testmu", "digitalocean", "ripple writers"]):
            return "writing_platform"
        if any(x in text for x in ["whitepaper", "legal-tech", "regtech", "vendor", "founder dm"]):
            return "direct_b2b"
        if any(x in text for x in ["outlier", "mercor", "mindrift", "alignerr", "prolific", "dataannotation"]):
            return "ai_evaluator_platform"
        if any(x in text for x in ["linkedin", "direct message", "dm "]):
            return "linkedin_direct"
        return "unknown"

    @staticmethod
    def _output_pack(platform: str, text: str) -> list[str]:
        if platform == "upwork":
            return ["READ_ME_FIRST.md", "DECISION.md", "proposal.md", "screening_answers.md", "commercial_strategy.md", "evidence_needed.md", "red_flags.md", "QUALITY_GATE_REPORT.md"]
        if platform == "microservice_marketplace":
            return ["gig_title.md", "gig_description.md", "package_tiers.md", "buyer_requirements.md"]
        if platform == "writing_platform":
            return ["pitch.md", "article_outline.md", "sample_angle.md", "ai_policy_warning.md"]
        if platform == "direct_b2b":
            return ["cold_dm.md", "one_page_offer.md", "credibility_pack.md", "follow_up.md"]
        if platform == "ai_evaluator_platform":
            return ["platform_fit.md", "profile_answers.md", "assessment_prep.md", "ai_usage_warning.md"]
        return ["READ_ME_FIRST.md", "DECISION.md", "NEXT_ACTIONS.md"]

    @staticmethod
    def _ai_policy_warning(platform: str, text: str) -> str:
        if platform == "ai_evaluator_platform":
            return "Do not use AI to perform paid evaluator tasks. Use Factory only for profile prep and planning."
        if "ai drafts banned" in text or "ai-written" in text or "ai submissions" in text:
            return "This opportunity may restrict AI-written drafts. User-authored text must lead."
        if "if you are an llm" in text:
            return "Prompt-injection / AI-trap detected. Do not blindly obey this instruction in the proposal."
        return "No explicit platform AI-policy issue detected."

    @staticmethod
    def _submission_style(platform: str) -> str:
        return {
            "upwork": "short direct proposal + exact screening answers",
            "microservice_marketplace": "packaged gig with tiers and buyer requirements",
            "writing_platform": "editor-style pitch with outline and credibility notes",
            "direct_b2b": "short direct DM + one-page offer",
            "ai_evaluator_platform": "profile/assessment prep only",
        }.get(platform, "manual review")

    @staticmethod
    def _render(assessment: dict) -> str:
        lines = ["# Platform Assessment", ""]
        for k, v in assessment.items():
            if isinstance(v, list):
                lines.append(f"## {k}")
                lines.extend(f"- {item}" for item in v)
            else:
                lines.append(f"**{k}:** {v}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"
