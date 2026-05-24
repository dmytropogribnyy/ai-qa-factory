from __future__ import annotations

import re
from typing import Any, Dict, List
from core.llm_router import LLMRouter


class InitialAnalysisEngine:
    """Deep first-pass analysis for QA freelance work.

    This stays deterministic enough for dry-run mode, but enriches the state with
    project type, stack choice, risk flags, automation scope and client questions.
    """

    def __init__(self, router: LLMRouter):
        self.router = router

    def analyze(self, raw_input: str, mode: str) -> Dict[str, Any]:
        text = raw_input.lower()
        stack_choice = self._recommend_stack(text)
        project_type = self._detect_project_type(text)
        automation_scope = self._detect_automation_scope(text)
        risks = self._detect_risks(text)
        clarifications = self._generate_clarifications(text)
        detected = self._detect_technologies(text)

        llm_note = self.router.complete(
            task_type="analysis",
            system_prompt=(
                "You are a senior QA automation consultant. Analyze the client request honestly. "
                "Focus on scope, risks, stack, environment gaps, automation strategy and first paid milestone. "
                "Do not invent facts. Keep it practical for freelance delivery."
            ),
            user_prompt=(
                f"Mode: {mode}\n"
                f"Raw request:\n{raw_input}\n\n"
                "Return: 1) short diagnosis, 2) risks, 3) recommended first milestone, "
                "4) questions to ask before committing."
            ),
            max_tokens=900,
        ).text

        return {
            "task_type": self._detect_task_type(text, mode),
            "stack_choice": stack_choice,
            "requirements": self._extract_requirements(raw_input),
            "risk_flags": risks,
            "clarifications": clarifications,
            "fit_score": self._calculate_fit_score(text, stack_choice, project_type),
            "project_type": project_type,
            "detected_technologies": detected,
            "automation_scope": automation_scope,
            "prompt_profile": self._prompt_profile(text, project_type, stack_choice),
            "client_context": {
                "llm_deep_analysis": llm_note,
                "mode": mode,
                "recommended_first_milestone": self._recommended_first_milestone(text, stack_choice),
                "proposal_angle": self._proposal_angle(text, project_type, stack_choice),
            },
        }

    @staticmethod
    def _detect_task_type(text: str, mode: str) -> str:
        if mode in {"job", "audit", "plan", "scaffold", "review", "delivery", "mcp-guide", "full"}:
            return mode
        if any(t in text for t in ["upwork", "proposal", "job", "freelancer"]):
            return "job"
        if any(t in text for t in ["bug", "defect", "expected", "actual", "flaky"]):
            return "review"
        return "analysis"

    @staticmethod
    def _recommend_stack(text: str) -> str:
        if "tosca" in text:
            return "tosca-advisory"
        if "selenium" in text and "java" in text and "playwright" not in text:
            return "selenium-java-fallback"
        if "cypress" in text and "playwright" not in text:
            return "cypress-fallback"
        # "mobile" alone is too broad — "mobile viewport" / "mobile responsive" are web concerns.
        # Require unambiguous native-mobile signals alongside or instead of the bare word.
        if any(t in text for t in ["android", "ios", "appium", "maestro", "react native", "testflight", "expo"]):
            return "mobile-maestro-advisory"
        if "mobile" in text and not any(w in text for w in ["viewport", "responsive", "browser", "web"]):
            return "mobile-maestro-advisory"
        if "api" in text and any(t in text for t in ["api-only", "api only", "backend only", "endpoints only"]):
            return "api-first-with-playwright-request"
        return "playwright-ts"

    @staticmethod
    def _detect_project_type(text: str) -> str:
        if any(t in text for t in ["lovable", "cursor", "bolt", "v0", "ai-generated", "ai generated", "mvp"]):
            return "AI-generated MVP / fast-built product"
        if "saas" in text:
            return "SaaS product"
        if any(t in text for t in ["enterprise", "microservices", "platform"]):
            return "Enterprise platform"
        if any(t in text for t in ["ecommerce", "e-commerce", "checkout", "shop", "cart"]):
            return "E-commerce web app"
        if any(t in text for t in ["mobile", "ios", "android"]):
            return "Mobile app"
        if any(t in text for t in ["api", "backend", "endpoint"]):
            return "API/backend service"
        return "Web application"

    @staticmethod
    def _detect_technologies(text: str) -> List[str]:
        keys = {
            "playwright": "Playwright", "typescript": "TypeScript", "javascript": "JavaScript",
            "selenium": "Selenium", "java": "Java", "cypress": "Cypress", "api": "API", "rest": "REST",
            "graphql": "GraphQL", "postgres": "PostgreSQL", "mysql": "MySQL", "mongodb": "MongoDB",
            "github actions": "GitHub Actions", "gitlab": "GitLab CI", "azure devops": "Azure DevOps",
            "jenkins": "Jenkins", "docker": "Docker", "k6": "k6", "artillery": "Artillery",
            "figma": "Figma", "stripe": "Stripe", "auth": "Authentication", "oauth": "OAuth",
            "next.js": "Next.js", "nextjs": "Next.js", "react native": "React Native", "maestro": "Maestro",
            "linear": "Linear", "loom": "Loom", "tosca": "Tosca", "supabase": "Supabase", "bullmq": "BullMQ",
        }
        return [v for k, v in keys.items() if k in text]

    @staticmethod
    def _detect_automation_scope(text: str) -> List[str]:
        scope = []
        if any(t in text for t in ["ui", "web", "browser", "frontend", "login", "checkout", "dashboard"]):
            scope.append("UI automation")
        if any(t in text for t in ["api", "rest", "graphql", "endpoint", "postman"]):
            scope.append("API testing")
        if any(t in text for t in ["db", "database", "sql", "postgres", "mysql", "data validation"]):
            scope.append("DB validation")
        if any(t in text for t in ["performance", "load", "stress", "k6", "latency"]):
            scope.append("Performance smoke testing")
        if any(t in text for t in ["figma", "ux", "ui/ux", "accessibility", "a11y", "responsive"]):
            scope.append("UX/accessibility review")
        if any(t in text for t in ["manual", "exploratory", "regression"]):
            scope.append("Manual exploratory/regression checks")
        return scope or ["Risk-based web QA audit", "Playwright smoke automation"]

    @staticmethod
    def _detect_risks(text: str) -> List[str]:
        risks = []
        if any(t in text for t in ["urgent", "asap", "tomorrow", "today", "quickly"]):
            risks.append("High urgency: limit scope and propose a small first milestone.")
        if any(t in text for t in ["payment", "stripe", "checkout", "subscription", "billing"]):
            risks.append("Payment flow: run only in sandbox/test mode and confirm no real charges.")
        if "production" in text:
            risks.append("Production mentioned: request a staging/test environment before automation.")
        if any(t in text for t in ["performance", "load", "stress"]):
            risks.append("Performance testing: clarify load model, target metrics and environment limits.")
        if any(t in text for t in ["ios", "android", "appium", "maestro", "react native", "testflight", "expo"]) or (
            "mobile" in text and not any(w in text for w in ["viewport", "responsive", "browser", "web"])
        ):
            risks.append("Mobile testing: clarify device/OS matrix and whether automation is expected or advisory.")
        if any(t in text for t in ["no documentation", "unclear", "messy", "legacy"]):
            risks.append("Unclear or legacy system: start with audit/discovery before committing to fixed automation scope.")
        return risks or ["No critical red flags detected at first pass."]

    @staticmethod
    def _generate_clarifications(text: str) -> List[str]:
        qs = [
            "Do you have a staging/test environment?",
            "Which 2-3 user flows are most critical before release?",
            "Can you provide test credentials and stable test data?",
            "Which CI/CD tool should run the tests?",
        ]
        if "api" in text:
            qs.append("Do you have API docs, OpenAPI schema, or a Postman collection?")
        if any(t in text for t in ["figma", "design", "ux", "ui"]):
            qs.append("Can you provide Figma/design links or expected UI states?")
        if any(t in text for t in ["payment", "stripe", "checkout"]):
            qs.append("Can payment scenarios be tested only in sandbox mode?")
        if any(t in text for t in ["database", "db", "sql"]):
            qs.append("Is read-only DB access available for validation checks?")
        return qs

    @staticmethod
    def _extract_requirements(raw_input: str) -> List[str]:
        lines = [line.strip(" -•\t") for line in raw_input.splitlines() if line.strip()]
        cleaned = [line for line in lines if len(line) > 25]
        return cleaned[:12] or [raw_input.strip()[:500]]

    @staticmethod
    def _recommended_first_milestone(text: str, stack: str) -> str:
        if any(t in text for t in ["flaky", "unstable", "failing"]):
            return "Audit and stabilize the top flaky tests, then document root causes."
        if "selenium" in text and "playwright" in text:
            return "Migration discovery: select 3 representative Selenium tests and convert them to Playwright."
        if any(t in text for t in ["mvp", "lovable", "bolt", "cursor", "ai-generated"]):
            return "QA readiness audit for auth, core flows, edge cases and release risks."
        if "api" in text and "ui" not in text:
            return "API smoke suite with auth, happy-path and negative checks."
        if stack == "playwright-ts":
            return "Small Playwright smoke suite around login/core navigation/one critical flow."
        return "Short QA audit and test strategy before automation scope is finalized."

    @staticmethod
    def _proposal_angle(text: str, project_type: str, stack: str) -> str:
        if any(t in text for t in ["flaky", "unstable", "ci"]):
            return "stability and CI feedback"
        if any(t in text for t in ["mvp", "ai-generated", "lovable", "bolt"]):
            return "release readiness for fast-built MVP"
        if "selenium" in text and "playwright" in text:
            return "safe migration from Selenium to Playwright"
        if "api" in text:
            return "risk-based UI/API coverage"
        return f"structured QA automation for {project_type} using {stack}"

    @staticmethod
    def _prompt_profile(text: str, project_type: str, stack: str) -> str:
        # Most-specific / highest-value checks first so broadly-worded jobs
        # (mentioning "ci" or "flaky" alongside billing) resolve correctly.
        if "selenium" in text and "playwright" in text:
            return "selenium_migration"
        if any(t in text for t in ["multi-tenant", "tenant isolation", "billing", "subscription", "oauth", "rbac"]):
            return "saas_multi_tenant_billing_auth"
        if any(t in text for t in ["react native", "expo", "maestro", "testflight"]):
            return "mobile_release_qa"
        if any(t in text for t in ["ai-native", "loom", "linear", "jam.dev", "jam", "screen recording", "hands-on qa", "release qa pass", "narrated walkthrough", "usability walkthrough"]):
            return "ai_native_exploratory"
        if any(t in text for t in ["lovable", "bolt", "cursor", "ai-generated", "mvp"]):
            return "ai_mvp_audit"
        # "ci" alone is too broad — only treat as flaky-profile when the job is
        # explicitly about unstable/failing tests, not just mentioning CI pipelines.
        if any(t in text for t in ["flaky", "unstable"]):
            return "flaky_tests"
        if any(t in text for t in ["article", "blog", "technical writing", "technical writer", "documentation", "help center", "docs migration", "content"]):
            return "technical_writing"
        if any(t in text for t in ["ux", "walkthrough", "jam.dev", "screen recording", "usability"]):
            return "ux_walkthrough"
        return "qa_automation"

    @staticmethod
    def _calculate_fit_score(text: str, stack: str, project_type: str) -> int:
        score = 55
        for kw in ["playwright", "typescript", "qa automation", "automation", "api testing", "ci/cd", "saas", "mvp", "flaky", "regression", "multi-tenant", "stripe", "billing", "linear", "loom", "exploratory", "documentation", "technical writing"]:
            if kw in text:
                score += 7
        for kw in ["manual only", "data entry", "cheap", "$5", "$10", "student"]:
            if kw in text:
                score -= 14
        if stack == "playwright-ts":
            score += 5
        if "selenium" in text and "playwright" not in text:
            score -= 4
        if project_type.startswith("AI-generated"):
            score += 4
        return max(25, min(98, score))
