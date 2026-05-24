from __future__ import annotations

from core.state import QAFactoryState


class EvidencePackAgent:
    """Lists proof required for an opportunity and guards against invented claims."""
    name = "Evidence Pack"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        required = self._required_evidence(state)
        state.evidence_required = list(dict.fromkeys(state.evidence_required + required))
        state.generated_outputs["evidence_needed.md"] = self._render(state)
        state.log(f"{self.name}: {len(state.evidence_required)} evidence items")
        return state

    @staticmethod
    def _required_evidence(state: QAFactoryState) -> list[str]:
        text = state.raw_input.lower()
        items = []
        if "bug report" in text or "linear" in text:
            items.append("Redacted real bug report / Linear-style ticket example")
        if "loom" in text or "screen recording" in text or "jam.dev" in text:
            items.append("Short Loom/Jam screen-recording example or readiness to create one")
        if "playwright" in text:
            items.append("Playwright + TypeScript sample repo or code snippet")
        if "multi-tenant" in text or "data isolation" in text:
            items.append("Example approach for tenant isolation / role-boundary testing")
        if "stripe" in text or "billing" in text:
            items.append("Stripe/billing sandbox testing checklist")
        if "maestro" in text or "react native" in text or "testflight" in text:
            items.append("Mobile device/tooling confirmation: Mac, Xcode, Android Studio, TestFlight/Google Play testing")
        if "documentation" in text or "technical writer" in text:
            items.append("Technical writing / SaaS documentation sample")
        if "github" in text or "portfolio" in text:
            items.append("Portfolio/GitHub link relevant to the requested work")
        return items

    @staticmethod
    def _render(state: QAFactoryState) -> str:
        lines = ["# Evidence Needed", "", "The system must not fabricate proof. Use this as a checklist before sending a proposal.", ""]
        if not state.evidence_required:
            lines.append("- No special evidence requirement detected. Still review claims manually.")
        else:
            for item in state.evidence_required:
                lines.append(f"- [ ] {item}")
        lines += [
            "",
            "## Evidence policy",
            "- Use real redacted examples only.",
            "- If evidence is missing, say what you can do and ask to discuss scope; do not invent.",
            "- Keep credentials, client names and private URLs out of proposals unless explicitly approved.",
        ]
        return "\n".join(lines).strip() + "\n"
