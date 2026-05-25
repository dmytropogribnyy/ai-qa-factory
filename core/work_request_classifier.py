"""WorkRequestClassifier — classifies InputMap + raw text into WorkRequest + TaskClassification.

Classify-only: no URL fetching, no browser execution, no credential use, no external calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from core.schemas.input_map import InputMap
from core.schemas.task_classification import TaskClassification
from core.schemas.work_request import WorkRequest


# --- Signal keyword tables ---------------------------------------------------------------

_QA_AUTOMATION_SIGNALS = [
    "playwright", "cypress", "selenium", "test automation", "automated test",
    "automation script", "e2e test", "end-to-end", "smoke test", "regression test",
    "test suite", "test framework", "jest", "vitest", "pytest", "test case",
]

_MANUAL_QA_SIGNALS = [
    "manual test", "test plan", "test scenario", "exploratory test",
    "usability test", "uat", "user acceptance", "bug report", "defect",
]

_API_TESTING_SIGNALS = [
    "api test", "rest api", "graphql", "postman", "swagger", "openapi",
    "endpoint test", "api automation", "api spec", "integration test",
]

_TEST_STRATEGY_SIGNALS = [
    "test strategy", "qa strategy", "test approach", "risk-based", "test coverage",
    "testing scope", "test plan", "qa plan",
]

_PROPOSAL_SIGNALS = [
    "proposal", "upwork", "freelance", "bid", "cover letter", "apply for",
    "job post", "client proposal", "fixed price", "hourly rate",
]

_REVIEW_SIGNALS = [
    "review", "code review", "audit", "evaluate", "assess", "check",
    "analyse", "analyze", "quality gate",
]

_DELIVERY_SIGNALS = [
    "deliver", "delivery", "submit", "report", "hand off", "handoff",
    "send to client", "final report",
]

_MOBILE_SIGNALS = [
    "mobile", "ios", "android", "react native", "flutter", "appium",
    "mobile app", "native app", "mobile testing",
]

_SECURITY_SIGNALS = [
    "security", "pentest", "penetration test", "vulnerability", "owasp",
    "xss", "sql injection", "auth bypass",
]

_PERFORMANCE_SIGNALS = [
    "performance", "load test", "stress test", "k6", "jmeter", "lighthouse",
    "latency", "throughput", "benchmark",
]

_CLIENT_WRITING_SIGNALS = [
    "write a proposal", "cover letter", "client email", "client-facing",
    "client report", "deliver report",
]

_DOCUMENTATION_SIGNALS = [
    "document", "readme", "runbook", "docs", "documentation",
    "schema doc", "api doc", "write docs",
]

# Project type signals
_PROJECT_TYPE_SIGNALS: dict[str, list[str]] = {
    "web_saas": ["saas", "dashboard", "multi-tenant", "subscription", "billing", "stripe",
                 "web app", "web application"],
    "ecommerce": ["ecommerce", "e-commerce", "shop", "cart", "checkout", "payment",
                  "product listing", "order"],
    "api_backend": ["api", "rest", "graphql", "backend", "microservice", "endpoint"],
    "ai_generated_app": ["ai-generated", "lovable", "bolt.new", "v0", "cursor",
                         "ai app", "generated app"],
    "admin_panel": ["admin", "admin panel", "dashboard", "backoffice", "back office",
                    "cms", "content management"],
    "auth_heavy": ["auth", "authentication", "login", "sso", "oauth", "jwt", "session",
                   "multi-factor", "2fa"],
    "mixed_ui_api": ["ui and api", "frontend and backend", "full stack", "fullstack",
                     "web and api"],
}


def _count_signals(text: str, signals: list[str]) -> int:
    lower = text.lower()
    return sum(1 for s in signals if s in lower)


def _detect_project_type(text: str) -> str:
    scores = {pt: _count_signals(text, sigs) for pt, sigs in _PROJECT_TYPE_SIGNALS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "unknown"


def _detect_task_type(text: str) -> str:
    """Return the most prominent task type from the brief."""
    scores = {
        "qa_automation": _count_signals(text, _QA_AUTOMATION_SIGNALS),
        "manual_qa": _count_signals(text, _MANUAL_QA_SIGNALS),
        "api_testing": _count_signals(text, _API_TESTING_SIGNALS),
        "test_strategy": _count_signals(text, _TEST_STRATEGY_SIGNALS),
        "proposal": _count_signals(text, _PROPOSAL_SIGNALS),
        "review": _count_signals(text, _REVIEW_SIGNALS),
        "delivery": _count_signals(text, _DELIVERY_SIGNALS),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "unknown"


def _detect_primary_domain(text: str, task_type: str) -> str:
    """Return primary domain: qa, dev_support, client_writing, upwork, documentation, etc."""
    lower = text.lower()
    if any(s in lower for s in _PROPOSAL_SIGNALS) and "upwork" in lower:
        return "upwork"
    if any(s in lower for s in _CLIENT_WRITING_SIGNALS):
        return "client_writing"
    if any(s in lower for s in _DOCUMENTATION_SIGNALS) and task_type not in ("qa_automation",):
        return "documentation"
    # QA is the default — almost everything else maps to it
    qa_score = (
        _count_signals(text, _QA_AUTOMATION_SIGNALS)
        + _count_signals(text, _MANUAL_QA_SIGNALS)
        + _count_signals(text, _API_TESTING_SIGNALS)
        + _count_signals(text, _TEST_STRATEGY_SIGNALS)
    )
    if qa_score > 0 or task_type in ("qa_automation", "manual_qa", "api_testing",
                                      "test_strategy", "review", "delivery"):
        return "qa"
    return "unknown"


def _detect_complexity(text: str, input_map: InputMap) -> str:
    lower = text.lower()
    score = 0
    # Multiple input types add complexity
    unique_types = {s.input_type for s in input_map.sources}
    score += len(unique_types) - 1

    # Credential input always forces high_risk regardless of other signals
    if any(s.input_type == "credentials_reference" for s in input_map.sources):
        return "high_risk"
    if any(s in lower for s in _MOBILE_SIGNALS):
        score += 2
    if any(s in lower for s in _SECURITY_SIGNALS):
        score += 2
    if any(s in lower for s in _PERFORMANCE_SIGNALS):
        score += 1
    if "production" in lower:
        score += 1
    if "real user" in lower or "live" in lower:
        score += 1
    if _count_signals(text, _QA_AUTOMATION_SIGNALS) > 3:
        score += 1

    if score == 0:
        return "simple"
    elif score <= 2:
        return "medium"
    elif score <= 4:
        return "complex"
    return "high_risk"


def _collect_signals(text: str, task_type: str, input_map: InputMap) -> List[str]:
    signals = []
    lower = text.lower()

    type_counts = {}
    for src in input_map.sources:
        type_counts[src.input_type] = type_counts.get(src.input_type, 0) + 1
    for t, c in type_counts.items():
        signals.append(f"input_type:{t}(x{c})")

    if any(s in lower for s in _MOBILE_SIGNALS):
        signals.append("mobile_detected")
    if any(s in lower for s in _SECURITY_SIGNALS):
        signals.append("security_detected")
    if any(s in lower for s in _PERFORMANCE_SIGNALS):
        signals.append("performance_detected")
    if "production" in lower:
        signals.append("production_mentioned")
    if any(s in lower for s in _PROPOSAL_SIGNALS):
        signals.append("proposal_context")
    if any(s in lower for s in _API_TESTING_SIGNALS):
        signals.append("api_testing_keywords")
    if any(s in lower for s in _QA_AUTOMATION_SIGNALS):
        signals.append("qa_automation_keywords")

    signals.append(f"task_type:{task_type}")
    return signals


def _extract_title(text: str) -> str:
    first_line = text.strip().split("\n")[0][:80].strip()
    return first_line if first_line else "Untitled work request"


def _extract_summary(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    joined = " ".join(lines)
    return joined[:300] + ("..." if len(joined) > 300 else "")


# --- Classifier -------------------------------------------------------------------------

class WorkRequestClassifier:
    """Classifies raw text + InputMap into a WorkRequest and TaskClassification.

    Classify-only: no external calls, no URL fetching, no credential use.
    """

    def classify(
        self,
        raw_text: str,
        input_map: InputMap,
        source_platform: str = "unknown",
    ) -> tuple[WorkRequest, TaskClassification]:
        task_type = _detect_task_type(raw_text)
        project_type = _detect_project_type(raw_text)
        primary_domain = _detect_primary_domain(raw_text, task_type)
        complexity = _detect_complexity(raw_text, input_map)
        signals = _collect_signals(raw_text, task_type, input_map)

        # Confidence: rough heuristic based on signal count
        signal_hits = sum(1 for s in signals if not s.startswith("input_type:"))
        confidence = min(0.9, 0.4 + signal_hits * 0.1)

        # Derive target_urls from input_map
        target_url_sources = [
            s.raw_value for s in input_map.sources
            if s.input_type == "target_url"
        ]

        work_request = WorkRequest(
            project_id=input_map.project_id,
            request_title=_extract_title(raw_text),
            request_summary=_extract_summary(raw_text),
            raw_brief=raw_text[:2000],
            source_platform=source_platform,
            target_urls=target_url_sources,
            inputs=[s.input_type for s in input_map.sources],
            tags=self._derive_tags(raw_text, task_type, project_type),
        )

        task_classification = TaskClassification(
            project_id=input_map.project_id,
            task_type=task_type,
            project_type=project_type,
            source_platform=source_platform,
            confidence=round(confidence, 2),
            signals=signals,
            notes=(
                f"primary_domain:{primary_domain} "
                f"complexity:{complexity}"
            ),
            classified_at=datetime.now(timezone.utc).isoformat(),
        )

        return work_request, task_classification

    @staticmethod
    def _derive_tags(text: str, task_type: str, project_type: str) -> List[str]:
        tags = [task_type, project_type]
        lower = text.lower()
        if any(s in lower for s in _MOBILE_SIGNALS):
            tags.append("mobile")
        if any(s in lower for s in _SECURITY_SIGNALS):
            tags.append("security")
        if any(s in lower for s in _PERFORMANCE_SIGNALS):
            tags.append("performance")
        if "playwright" in lower:
            tags.append("playwright")
        if "api" in lower:
            tags.append("api")
        return [t for t in tags if t and t != "unknown"]
