"""UniversalWorkIntake — Phase 8.1 (deterministic, no LLM).

Wraps the safe, heuristic intake components only:
- InputContextResolver (classify-only; redacts secrets; no fetching, no network)
- WorkRequestClassifier (heuristic; no LLM)

Explicitly does NOT use InitialAnalysisEngine (it calls LLMRouter.complete()) or
task_source_fetcher (network). Raw input is redacted at the boundary so no unredacted
secret text reaches WorkRequest.raw_brief.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.input_context_resolver import InputContextResolver
from core.work_request_classifier import WorkRequestClassifier
from core.schemas.input_map import InputMap
from core.schemas.work_request import WorkRequest
from core.schemas.task_classification import TaskClassification
from core.orchestration.providers import ClockProvider, IdProvider
from core.orchestration.content_safety import redact_intake_text


@dataclass
class IntakeResult:
    input_map: InputMap
    work_request: WorkRequest
    task_classification: TaskClassification
    redacted_text: str
    secrets_redacted: bool


class UniversalWorkIntake:
    """Deterministic intake: redact → classify inputs → classify work request."""

    def __init__(self, clock: ClockProvider, ids: IdProvider) -> None:
        self._clock = clock
        self._ids = ids
        self._resolver = InputContextResolver()
        self._classifier = WorkRequestClassifier()

    def run(self, raw_text: str, project_id: str, source_platform: str = "unknown") -> IntakeResult:
        # Single public redactor at the intake boundary so no unredacted secret ever
        # reaches WorkRequest.raw_brief or any artifact (host/path of URLs preserved).
        red = redact_intake_text(raw_text)
        redacted, secrets_found = red.text, red.secrets_found
        input_map = self._resolver.resolve([redacted], project_id)
        # Deterministic identity/timestamps for the input map (production uses real providers).
        input_map.created_at = self._clock.now_iso()
        for src in input_map.sources:
            src.id = self._ids.new_id()
        work_request, classification = self._classifier.classify(
            redacted, input_map, source_platform=source_platform
        )
        # Deterministic identity/timestamps (production uses real providers).
        work_request.id = self._ids.new_id()
        work_request.created_at = self._clock.now_iso()
        classification.classified_at = self._clock.now_iso()
        return IntakeResult(
            input_map=input_map,
            work_request=work_request,
            task_classification=classification,
            redacted_text=redacted,
            secrets_redacted=secrets_found,
        )
