from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Protocol

from core.state import QAFactoryState


@dataclass
class CheckResult:
    name: str
    passed: bool
    warnings: List[str] = field(default_factory=list)
    severity: str = "warning"


class Check(Protocol):
    name: str
    severity: str
    def evaluate(self, state: QAFactoryState) -> CheckResult: ...


class GenericProposalPhrasesCheck:
    name = "generic_proposal_phrases"
    severity = "warning"
    phrases = ["i'm excited", "i am excited", "i believe i am", "dear sir", "dear hiring manager"]

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        text = state.generated_outputs.get("proposal.md", "")
        lowered = text.lower()
        warnings = [f"Generic proposal phrase detected: {phrase}" for phrase in self.phrases if phrase in lowered]
        return CheckResult(self.name, not warnings, warnings, self.severity)


class MissingClientQuestionsCheck:
    name = "missing_client_questions"
    severity = "warning"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        text = state.generated_outputs.get("proposal.md", "")
        warnings = []
        if text and "?" not in text:
            warnings.append("Proposal has no client question. Add 1-2 specific scoping questions.")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class MockModeWarningCheck:
    name = "mock_mode_warning"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        joined = "\n".join(state.generated_outputs.values()).lower()
        warnings = []
        if "mock mode warning" in joined:
            warnings.append("Mock LLM output detected. Do not send client-facing text.")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class WaitForTimeoutCheck:
    name = "wait_for_timeout"
    severity = "warning"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        code = _generated_code(state)
        warnings = ["Hard wait detected: waitForTimeout. Prefer web-first assertions."] if "waitForTimeout" in code else []
        return CheckResult(self.name, not warnings, warnings, self.severity)


class BrittleSelectorCheck:
    name = "brittle_selectors"
    severity = "warning"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        code = _generated_code(state)
        warnings = []
        patterns = [r"nth-child", r"locator\(['\"]//", r"xpath=", r"\.nth\(\d+\)"]
        for pattern in patterns:
            if re.search(pattern, code, re.IGNORECASE):
                warnings.append(f"Potential brittle selector detected: {pattern}")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class HardcodedCredentialsCheck:
    name = "hardcoded_credentials"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        joined = "\n".join(state.generated_outputs.values())
        warnings = []
        risky_patterns = [r"password\s*=\s*['\"][^'\"]+", r"api[_-]?key\s*=\s*['\"][^'\"]+", r"TEST_USER_PASSWORD=['\"]?[A-Za-z0-9!@#$%^&*\-_+]+"]
        for pattern in risky_patterns:
            if re.search(pattern, joined, re.IGNORECASE):
                warnings.append(f"Possible hardcoded credential detected: {pattern}")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class OverclaimsCheck:
    name = "overclaims"
    severity = "warning"
    terms = ["guaranteed", "100%", "fully tested", "no bugs", "bug-free"]

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        text = "\n".join(
            state.generated_outputs.get(name, "") for name in ["proposal.md", "delivery_note.md", "SUMMARY.md"]
        ).lower()
        warnings = [f"Avoid overclaiming: {term}" for term in self.terms if term in text]
        return CheckResult(self.name, not warnings, warnings, self.severity)


class HumanReviewNoteCheck:
    name = "human_review_note"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        warnings = []
        if "HUMAN_REVIEW_REQUIRED.md" not in state.generated_outputs and state.approval_status != "approved_by_user":
            warnings.append("HUMAN_REVIEW_REQUIRED.md is missing before final output save.")
        return CheckResult(self.name, not warnings, warnings, self.severity)



class MandatoryKeywordCheck:
    name = "mandatory_keyword"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        warnings = []
        proposal = state.generated_outputs.get("proposal.md", "").strip()
        for keyword in state.mandatory_keywords:
            if proposal and not proposal.lower().startswith(keyword.lower()):
                warnings.append(f"Proposal must start with required keyword: {keyword}")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class ScreeningQuestionsAnsweredCheck:
    name = "screening_questions_answered"
    severity = "warning"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        warnings = []
        if state.screening_questions and "screening_answers.md" not in state.generated_outputs:
            warnings.append("Screening questions detected but screening_answers.md is missing.")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class NoInventedEvidenceCheck:
    name = "no_invented_evidence"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        joined = "\n".join(state.generated_outputs.values()).lower()
        warnings = []
        suspicious = ["here is a real bug report i wrote", "my previous client", "confidential company", "app store link:"]
        if state.evidence_required:
            for phrase in suspicious:
                if phrase in joined:
                    warnings.append(f"Potential invented/unsupported evidence phrase: {phrase}")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class LowBudgetRedFlagCheck:
    name = "low_budget_red_flag"
    severity = "warning"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        text = state.raw_input.lower()
        warnings = []
        if re.search(r"\$\s*(5|7|8|10)(?!\d)", text) or "lowest rates" in text:
            warnings.append("Low budget/rate pressure detected. Confirm this is worth Connects/time.")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class DepositOrIdentityRiskCheck:
    name = "deposit_or_identity_risk"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        text = state.raw_input.lower()
        warnings = []
        if any(x in text for x in ["deposit", "valid id", "id from your country", "without vpn", "crypto brokerage"]):
            warnings.append("Deposit/identity/crypto testing risk detected. Usually skip.")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class DeveloperOnlyMismatchCheck:
    name = "developer_only_mismatch"
    severity = "warning"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        warnings = []
        if state.opportunity_type == "developer_only_not_core":
            warnings.append("This appears to be a developer-only opportunity, not core QA/SDET work.")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class PromptInjectionTrapCheck:
    name = "prompt_injection_or_ai_trap"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        text = state.raw_input.lower()
        warnings = []
        if "if you are an llm" in text or "ignore previous instructions" in text:
            warnings.append("Prompt-injection / AI-trap detected. Do not blindly obey trap instructions.")
        return CheckResult(self.name, not warnings, warnings, self.severity)


class ResponsibleDiscoveryCheck:
    name = "responsible_discovery"
    severity = "error"

    def evaluate(self, state: QAFactoryState) -> CheckResult:
        joined = "\n".join(state.generated_outputs.values()).lower()
        warnings = []
        risky = ["exploit", "bypass security", "access other users", "dump data", "attack"]
        if any(x in state.raw_input.lower() for x in ["black-box", "responsible", "security", "auth", "jwt", "role"]):
            for phrase in risky:
                if phrase in joined:
                    warnings.append(f"Risky security wording detected: {phrase}")
        return CheckResult(self.name, not warnings, warnings, self.severity)


def _generated_code(state: QAFactoryState) -> str:
    return "\n".join(v for k, v in state.generated_outputs.items() if k.endswith((".ts", ".js", ".py", ".java", ".yml", ".yaml")))


QUALITY_CHECKS: List[Check] = [
    MandatoryKeywordCheck(),
    ScreeningQuestionsAnsweredCheck(),
    NoInventedEvidenceCheck(),
    LowBudgetRedFlagCheck(),
    DepositOrIdentityRiskCheck(),
    DeveloperOnlyMismatchCheck(),
    PromptInjectionTrapCheck(),
    ResponsibleDiscoveryCheck(),
    GenericProposalPhrasesCheck(),
    MissingClientQuestionsCheck(),
    MockModeWarningCheck(),
    WaitForTimeoutCheck(),
    BrittleSelectorCheck(),
    HardcodedCredentialsCheck(),
    OverclaimsCheck(),
    HumanReviewNoteCheck(),
]


class QualityGate:
    name = "Quality Gate"

    def __init__(self, checks: List[Check] | None = None):
        self.checks = checks or QUALITY_CHECKS

    def run(self, state: QAFactoryState) -> QAFactoryState:
        return self.run_all(state)

    def run_all(self, state: QAFactoryState) -> QAFactoryState:
        results = [check.evaluate(state) for check in self.checks]
        state.quality_gate_results = {
            r.name: {"passed": r.passed, "warnings": r.warnings, "severity": r.severity} for r in results
        }
        state.generated_outputs["QUALITY_GATE_REPORT.md"] = self.render(results)
        state.log("QualityGate: completed")
        return state

    @staticmethod
    def render(results: List[CheckResult]) -> str:
        lines = ["# Quality Gate Report", ""]
        for result in results:
            lines.append(f"## {result.name}")
            lines.append(f"**Severity:** {result.severity}")
            lines.append(f"**Passed:** {result.passed}")
            if result.warnings:
                lines.extend(f"- {w}" for w in result.warnings)
            else:
                lines.append("- No warnings detected.")
            lines.append("")
        lines.append("Human review still required even if all gates pass.\n")
        return "\n".join(lines)
