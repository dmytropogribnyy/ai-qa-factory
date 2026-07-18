"""FeasibilityAssessor (v3.0.0 Milestone 2).

Turns the existing planning artifacts into a human-readable go/no-go decision. Pure function of the
already-produced WORK_PACKET / CAPABILITY_PLAN / TOOLCHAIN_PLAN / INTAKE_REPORT dicts - it reuses the
planning pipeline's output and never re-runs or duplicates it, performs no LLM/network call, and
never starts implementation.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.schemas.feasibility import (
    NOT_RECOMMENDED,
    RECOMMENDED_TO_TAKE,
    TAKE_AFTER_ACCESS_OR_TOOL_SETUP,
    TAKE_AFTER_CLARIFICATION,
    FeasibilityReport,
)

_UNRESOLVED_PROFILES = frozenset({"", "unknown", "unresolved", "generic"})
# Coarse effort bands from the number of extracted requirements.
_EFFORT_BANDS = ((3, "small (~0.5-1 day)"), (7, "medium (~2-4 days)"), (999, "large (1-2+ weeks)"))


class FeasibilityAssessor:
    """Derive a FeasibilityReport from planning artifact dicts (deterministic)."""

    def assess(self, *, project_id: str, work_packet: Dict[str, Any],
               capability_plan: Dict[str, Any], toolchain_plan: Dict[str, Any],
               intake_report: Dict[str, Any]) -> FeasibilityReport:
        profile = str(work_packet.get("capability_profile") or "")
        selection = intake_report.get("profile_selection", {}) or {}
        confidence = float(selection.get("confidence") or 0.0)
        missing = intake_report.get("missing_information", {}) or {}
        blocking = list(missing.get("blocking", []))
        clarification = list(missing.get("clarification", []))
        approval_needed = list(missing.get("approval_needed", []))

        required_caps = list(capability_plan.get("required_capabilities", []))
        missing_caps = list(capability_plan.get("missing_capabilities", []))
        blocked_caps = list(capability_plan.get("blocked_capabilities", []))
        approvals = list(capability_plan.get("approvals_required", []))
        planned = capability_plan.get("planned", []) or []
        discovery_caps = [p.get("capability", "") for p in planned if p.get("requires_discovery")]

        steps = toolchain_plan.get("steps", []) or []
        selected_tools = sorted({str(s.get("backend")) for s in steps if s.get("backend")})
        optional_tools = sorted({str(s.get("candidate_mcp_server") or s.get("candidate_server") or "")
                                 for s in steps} - {""})

        reasons_reject: List[str] = []
        if profile in _UNRESOLVED_PROFILES:
            reasons_reject.append("the work type could not be confidently classified from the brief")
        if blocked_caps:
            reasons_reject.append(f"required capabilities are blocked by policy: {', '.join(blocked_caps)}")
        if missing_caps:
            reasons_reject.append("required capabilities are not available in this system: "
                                  + ", ".join(missing_caps))

        hard_capability_gap = bool(missing_caps or blocked_caps)
        if profile in _UNRESOLVED_PROFILES or hard_capability_gap:
            verdict = NOT_RECOMMENDED
        elif blocking:
            verdict = TAKE_AFTER_CLARIFICATION
        elif approvals or approval_needed or discovery_caps:
            verdict = TAKE_AFTER_ACCESS_OR_TOOL_SETUP
        else:
            verdict = RECOMMENDED_TO_TAKE

        effort = next(label for cap, label in _EFFORT_BANDS
                      if len(work_packet.get("requirements", [])) <= cap)
        risk = ("high" if verdict == NOT_RECOMMENDED else
                "medium" if verdict in (TAKE_AFTER_CLARIFICATION, TAKE_AFTER_ACCESS_OR_TOOL_SETUP)
                else "low")
        questions = blocking + clarification

        return FeasibilityReport(
            project_id=project_id, verdict=verdict, confidence=round(confidence, 2), profile=profile,
            client_intent=str(work_packet.get("summary") or work_packet.get("title") or ""),
            extracted_requirements=[self._req_text(r) for r in work_packet.get("requirements", [])],
            expected_deliverables=self._deliverables(profile),
            assumptions=["public/authorized access only", "read-only analysis before approval"],
            missing_information=blocking, client_questions=questions,
            technical_fit=self._fit(profile, confidence, hard_capability_gap),
            required_access=sorted({a for a in approval_needed}) or ["as stated in the brief"],
            estimated_effort=effort,
            estimated_duration=("n/a - not recommended" if verdict == NOT_RECOMMENDED
                                else "depends on approvals/clarifications" if risk == "medium"
                                else "within the estimated effort band"),
            risk_level=risk,
            scope_creep_risks=(["undefined/unbounded scope"] if not required_caps else
                               ["watch for scope beyond the agreed capabilities"]),
            validation_strategy=self._validation(profile),
            recommended_proposal=["restate scope", "list deliverables", "state assumptions",
                                  "propose milestones", "note validation + handover"],
            recommended_milestones=self._milestones(profile),
            pricing_guidance=self._pricing(verdict, effort),
            selected_capabilities=required_caps, selected_tools=selected_tools,
            optional_tools=optional_tools, unavailable_blockers=sorted(set(missing_caps + blocked_caps)),
            reasons_to_reject=reasons_reject,
            confidence_explanation=(f"profile '{profile or 'unresolved'}' inferred with "
                                    f"confidence {round(confidence, 2)}; "
                                    f"{len(missing_caps)} missing / {len(blocked_caps)} blocked "
                                    f"capabilities; {len(blocking)} blocking questions"))

    @staticmethod
    def _req_text(r: Any) -> str:
        if isinstance(r, dict):
            return str(r.get("text") or r.get("requirement") or r.get("summary") or r)
        return str(r)

    @staticmethod
    def _deliverables(profile: str) -> List[str]:
        table = {
            "playwright_ts_framework": ["Playwright + TypeScript framework", "critical-flow tests",
                                        "CI integration", "README/handover"],
            "qa_audit": ["QA audit report", "reproductions", "evidence", "severity/impact"],
            "bug_fix": ["reproduction", "root-cause note", "bounded fix", "regression test"],
            "api_testing": ["API test plan", "positive+negative tests", "results report"],
        }
        return table.get(profile, ["agreed deliverables per the brief"])

    @staticmethod
    def _fit(profile: str, confidence: float, gap: bool) -> str:
        if gap:
            return "poor - required capability is unavailable in this system"
        if profile in _UNRESOLVED_PROFILES:
            return "unclear - the work type is ambiguous"
        return f"good - matches the '{profile}' profile (confidence {round(confidence, 2)})"

    @staticmethod
    def _validation(profile: str) -> List[str]:
        return {"playwright_ts_framework": ["run the suite green in CI", "review traces/screenshots"],
                "qa_audit": ["independent reproduction of each finding", "sanitized evidence"],
                "bug_fix": ["reproduce before/after", "regression test passes"],
                "api_testing": ["assert positive+negative cases", "no invented endpoint behavior"],
                }.get(profile, ["validate against the agreed acceptance criteria"])

    @staticmethod
    def _milestones(profile: str) -> List[str]:
        return {"playwright_ts_framework": ["scaffold + config", "critical flows", "CI + reporting",
                                            "docs + handover"],
                }.get(profile, ["analysis + plan", "implementation", "validation", "delivery"])

    @staticmethod
    def _pricing(verdict: str, effort: str) -> str:
        if verdict == NOT_RECOMMENDED:
            return "no pricing - not recommended to take"
        return f"price to the '{effort}' effort band; fixed-price with milestones or a capped hourly rate"
