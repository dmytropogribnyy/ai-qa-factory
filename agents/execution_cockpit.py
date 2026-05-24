from __future__ import annotations

from core.state import QAFactoryState


class ExecutionCockpitAgent:
    """Creates a human-friendly operating guide for the chosen opportunity."""

    name = "Execution Cockpit"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        state.generated_outputs["EXECUTION_FLOW.md"] = self._execution_flow(state)
        state.generated_outputs["APPROVAL_CHECKPOINTS.md"] = self._approval_checkpoints(state)
        state.generated_outputs["SYSTEM_DIALOG_GUIDE.md"] = self._dialog_guide(state)
        state.generated_outputs["TESTING_READINESS_CHECKLIST.md"] = self._readiness_checklist(state)
        state.generated_outputs["PROJECT_INTAKE_CHECKLIST.md"] = self._intake_checklist(state)
        state.log(f"{self.name}: cockpit artifacts generated")
        return state

    @staticmethod
    def _execution_flow(state: QAFactoryState) -> str:
        suggested = state.recommended_workflow or "manual_review"
        lines = [
            "# Execution Flow",
            "",
            f"**Recommended action:** `{state.recommended_action}`",
            f"**Recommended workflow:** `{suggested}`",
            f"**System suitability:** `{state.system_suitability}`",
            f"**Estimated effort:** {state.estimated_effort or 'Not estimated'}",
            "",
            "## Default flow",
            "1. Pre-screen opportunity (`PRESCREENING_REPORT.md`).",
            "2. Review `DECISION.md` and `READ_ME_FIRST.md`.",
            "3. Resolve missing evidence/access from `evidence_needed.md` and `PROJECT_INTAKE_CHECKLIST.md`.",
            "4. Approve or reject spending time/Connects.",
            "5. If approved, run the recommended workflow in `--step` mode for high-value/high-risk work.",
            "6. Review proposal / QA plan / delivery artifacts.",
            "7. Run tests or site checks only inside approved boundaries.",
            "8. Final human review before client-facing delivery.",
            "",
            "## Suggested commands",
            "```bash",
            "python main.py prescreen --input real_jobs/job_001.txt --allow-mock",
            "python main.py upwork --input real_jobs/job_001.txt --step --require-real-llm",
            "python main.py full --input clients/client_brief.txt --step --require-real-llm",
            "python main.py ask --project-id <project_id> --question \"What should I review first?\"",
            "```",
            "",
            "## Automation boundary",
            "Factory may automate analysis, draft generation, scaffolding and reports. Dmytro approves client-facing text, real-site testing boundaries, credentials use and final delivery.",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _approval_checkpoints(state: QAFactoryState) -> str:
        checkpoints = state.approval_checkpoints or [
            "Approve opportunity fit",
            "Approve scope",
            "Approve real-site testing boundary",
            "Approve final client-facing text",
        ]
        lines = ["# Approval Checkpoints", "", "Factory can run semi-automatically, but these decisions remain human-owned.", ""]
        for idx, item in enumerate(checkpoints, 1):
            lines.append(f"{idx}. [ ] {item}")
        lines += [
            "",
            "## Stop conditions",
            "- Client requests real payment, ID/deposit, scraping, or unauthorized access.",
            "- Required evidence would have to be invented.",
            "- Scope is developer-only while positioning is QA/SDET.",
            "- Budget is not compatible with strategic value.",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _dialog_guide(state: QAFactoryState) -> str:
        return f"""# System Dialog Guide

Use this file as the human-friendly control surface for talking to Factory.

## Current status
- Decision: `{state.recommended_action}`
- Suitability: `{state.system_suitability}`
- Support level: `{state.support_level}`
- Opportunity type: `{state.opportunity_type}`

## Useful questions to ask after a run
```bash
python main.py ask --project-id {state.project_id} --question "Why did you choose this decision?"
python main.py ask --project-id {state.project_id} --question "What evidence do I need before applying?"
python main.py ask --project-id {state.project_id} --question "What should I change in the proposal before sending?"
python main.py ask --project-id {state.project_id} --question "What is the safest first milestone?"
```

## Step-mode feedback examples
When running with `--step`, use concise feedback:
- `redo: make the proposal shorter and more direct`
- `redo: focus on SaaS billing and tenant isolation, not generic automation`
- `skip: do not generate scaffold yet; we need access first`
- `quit: stop before client-facing outputs`

## Human-friendly rule
If the output is hard to understand, ask Factory to explain the decision in plain language before using it.
"""

    @staticmethod
    def _readiness_checklist(state: QAFactoryState) -> str:
        return """# Testing Readiness Checklist

## Minimum for real LLM testing
- [ ] `.env` configured with real LiteLLM/OpenAI/Claude-compatible model IDs
- [ ] API key stored only in environment variables, not in prompts or job files
- [ ] `python main.py upwork --input sample_inputs/upwork_job.txt --require-real-llm` works
- [ ] Token/cost logs appear in `outputs/<project_id>/logs/factory.jsonl` when provider supports usage metadata

## Minimum for real website/app testing
- [ ] Written permission or your own account/test account
- [ ] Staging/test environment preferred
- [ ] No destructive actions
- [ ] No real payments; Stripe/payment flows only in sandbox/test mode
- [ ] Test credentials stored in `.env`, never in generated reports
- [ ] Clear scope: pages, flows, browsers/devices, timebox, reporting format
- [ ] Evidence format agreed: screenshots, Loom/Jam, console/network logs, bug report template

## Optional tools/API depending on project type
- [ ] Playwright browsers installed: `npx playwright install`
- [ ] GitHub access/token if repo analysis or PR workflow is required
- [ ] Linear/Jira access if bugs must be created directly there
- [ ] Loom/Jam.dev account if recorded findings are required
- [ ] TestFlight / Google Play Internal Testing access for mobile release QA
- [ ] Xcode / Android Studio / Maestro for React Native mobile work
- [ ] Postman or API collection if API testing is expected
- [ ] Test data / email aliases / phone number for signup/SMS flows

## Current limitation
Factory can analyze pasted job text and prepared briefs now. URL and screenshot intake should be treated as future adapters unless the content is pasted/described in the input file.
"""

    @staticmethod
    def _intake_checklist(state: QAFactoryState) -> str:
        return """# Project Intake Checklist

Before accepting or executing a task, collect what is needed.

## Opportunity / proposal stage
- [ ] Full job post or client brief
- [ ] Platform/source and deadline
- [ ] Budget/rate constraints
- [ ] Screening questions and required keywords
- [ ] Evidence requested by client
- [ ] Your verified evidence/sample links

## Execution stage
- [ ] Target URL(s)
- [ ] Test accounts and roles
- [ ] Environment: staging/test/production read-only
- [ ] Critical user flows
- [ ] Browser/device matrix
- [ ] Known risks or recent changes
- [ ] Reporting format: doc, Linear/Jira, Loom/Jam, screenshots
- [ ] Timebox and delivery date

## Safety boundaries
- [ ] Payment sandbox confirmed
- [ ] No unauthorized security testing
- [ ] No scraping or abuse
- [ ] No personal ID/deposit tasks unless consciously accepted outside strategic QA work
"""
