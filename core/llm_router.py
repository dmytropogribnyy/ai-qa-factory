from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Dict, Optional
from core.config import Settings


@dataclass
class LLMResponse:
    text: str
    model: str
    task_type: str
    model_alias: str | None = None
    reasoning_effort: str | None = None
    used_fallback: bool = False
    error: Optional[str] = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class LLMRouter:
    TASK_TO_ALIAS: Dict[str, str] = {
        # Opportunity and market reasoning
        "job": "architect", "filter": "architect", "prescreen": "architect", "analysis": "architect",
        "architecture": "architect", "capability": "architect", "platform": "architect", "commercial": "architect",
        "evidence": "architect", "screening": "architect", "extension": "architect", "self_health": "review",
        # Client-facing writing and quick outputs
        "upwork": "fast", "proposal": "fast", "delivery": "fast", "technical_writing": "fast",
        # QA planning and test design
        "plan": "architect", "audit": "architect", "test_strategy": "architect", "test_plan": "architect", "test_cases": "fast",
        # Code / scaffold / automation
        "scaffold": "coding", "playwright": "coding", "api": "coding", "db": "coding", "performance": "coding",
        # Review / quality
        "review": "review", "flakiness": "review", "quality_gate": "review", "ux": "review", "design": "review",
        # Future visual recon
        "vision": "vision",
    }

    def __init__(self, settings: Settings):
        self.settings = settings
        self.call_count = 0
        self.fallback_to_mock_count: int = 0
        self.last_response: LLMResponse | None = None

    def alias_for_task(self, task_type: str) -> str:
        return self.TASK_TO_ALIAS.get(task_type.lower(), "fallback")

    def route(self, task_type: str) -> str:
        return self.settings.model_for_alias(self.alias_for_task(task_type))

    def effort_for_task(self, task_type: str) -> str:
        return self.settings.effort_for_alias(self.alias_for_task(task_type))

    def _record(self, response: LLMResponse) -> LLMResponse:
        self.call_count += 1
        self.last_response = response
        return response

    def complete(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.25,
        max_tokens: int = 1600,
        context: dict | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        # `model` forces a specific model (e.g. Scout's cheap Haiku), bypassing profile routing.
        if model:
            alias, effort = "override", "low"
        else:
            alias = self.alias_for_task(task_type)
            model = self.route(task_type)
            effort = self.effort_for_task(task_type)
        if self.settings.is_mock or model == "mock":
            return self._record(LLMResponse(self._mock_response(task_type, user_prompt=user_prompt, context=context), "mock", task_type, model_alias=alias, reasoning_effort=effort))
        # Reasoning models consume max_tokens for internal thinking first.
        # Boost budget early so the boost covers both the primary call and any retry.
        if self.settings.enable_effort_params and self._effort_kwargs(model, effort).get("reasoning_effort"):
            max_tokens = max(max_tokens, 8192)
        try:
            response = self._litellm_completion(model, system_prompt, user_prompt, temperature, max_tokens, effort, include_optional=True)
            text = response.choices[0].message.content or ""
            usage = self._extract_usage(response)
            return self._record(LLMResponse(text.strip(), model, task_type, model_alias=alias, reasoning_effort=effort, **usage))
        except Exception as first_exc:
            # Some providers/models reject optional params such as reasoning_effort or temperature.
            # Retry the same model once with minimal provider-neutral params before falling back.
            try:
                response = self._litellm_completion(model, system_prompt, user_prompt, temperature, max_tokens, effort, include_optional=False)
                text = response.choices[0].message.content or ""
                usage = self._extract_usage(response)
                return self._record(LLMResponse(text.strip(), model, task_type, model_alias=alias, reasoning_effort=effort, **usage))
            except Exception:
                pass

            fallback_model = self.settings.fallback_model
            fallback_effort = self.settings.fallback_effort
            if fallback_model != model and fallback_model != "mock":
                try:
                    response = self._litellm_completion(fallback_model, system_prompt, user_prompt, temperature, max_tokens, fallback_effort, include_optional=True)
                    text = response.choices[0].message.content or ""
                    usage = self._extract_usage(response)
                    return self._record(LLMResponse(text.strip(), fallback_model, task_type, model_alias="fallback", reasoning_effort=fallback_effort, used_fallback=True, **usage))
                except Exception:
                    try:
                        response = self._litellm_completion(fallback_model, system_prompt, user_prompt, temperature, max_tokens, fallback_effort, include_optional=False)
                        text = response.choices[0].message.content or ""
                        usage = self._extract_usage(response)
                        return self._record(LLMResponse(text.strip(), fallback_model, task_type, model_alias="fallback", reasoning_effort=fallback_effort, used_fallback=True, **usage))
                    except Exception:
                        pass
            self.fallback_to_mock_count += 1
            return self._record(LLMResponse(self._mock_response(task_type, user_prompt=user_prompt, context=context), "mock", task_type, model_alias=alias, reasoning_effort=effort, used_fallback=True, error=str(first_exc)))

    def _litellm_completion(self, model: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, effort: str, include_optional: bool):
        from litellm import completion
        kwargs = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "max_tokens": max_tokens,
            "timeout": self.settings.llm_timeout_seconds,
            "num_retries": self.settings.llm_max_retries,
        }
        if include_optional:
            if self._allows_temperature(model):
                kwargs["temperature"] = temperature
            if self.settings.enable_effort_params:
                optional = self._effort_kwargs(model, effort)
                kwargs.update(optional)
        return completion(**kwargs)

    @staticmethod
    def _allows_temperature(model: str) -> bool:
        # Anthropic notes Opus 4.7 rejects non-default sampling params. Omit them.
        model_l = model.lower()
        return "claude-opus-4-7" not in model_l

    @staticmethod
    def _effort_kwargs(model: str, effort: str) -> dict:
        model_l = model.lower()
        if not effort or effort == "none":
            return {}
        if model_l.startswith("gpt-5"):
            return {"reasoning_effort": effort}
        # LiteLLM / Anthropic adapter behavior can change. Keep the payload modest and retry without it if rejected.
        if "claude-opus-4-7" in model_l or "claude-sonnet-4-6" in model_l:
            return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
        return {}

    @staticmethod
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @classmethod
    def _extract_usage(cls, response: Any) -> dict:
        usage = cls._get(response, "usage")
        prompt_tokens = cls._get(usage, "prompt_tokens")
        completion_tokens = cls._get(usage, "completion_tokens")
        total_tokens = cls._get(usage, "total_tokens")
        hidden = cls._get(response, "_hidden_params", {}) or {}
        cost = cls._get(hidden, "response_cost")
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost,
        }

    @staticmethod
    def _mock_response(task_type: str, user_prompt: str = "", context: dict | None = None) -> str:
        ctx = context or {}
        project_type = ctx.get("project_type", "the project")
        stack = ctx.get("stack_choice", "Playwright + TypeScript")
        milestone = ctx.get("suggested_milestone") or ctx.get("recommended_first_milestone") or "a short QA audit and smoke automation milestone"
        if task_type in {"proposal", "upwork"}:
            return (
                f"I can help with a focused {stack} approach for {project_type}.\n\n"
                f"For a low-risk first step, I would start with {milestone}. "
                "That should quickly expose the riskiest flows, flaky areas and missing coverage before expanding the suite.\n\n"
                "A few questions: do you have a staging environment and test credentials, and which 2-3 flows are most critical before release?\n\n"
                "MOCK MODE WARNING: do not send this to a client without configuring a real LLM and manually editing it."
            )
        if task_type in {"plan", "audit", "analysis", "test_strategy", "test_plan", "test_cases"}:
            return f"## Draft Analysis for {project_type}\n- Recommended stack: {stack}.\n- Start with risk-based scope and a small first milestone.\n- Human review required."
        if task_type in {"review", "flakiness", "quality_gate", "self_health"}:
            return "## Review Draft\n- Avoid hard waits.\n- Prefer role/test-id locators.\n- Add clear assertions.\n- Keep test data isolated.\n- Review in CI with traces."
        if task_type == "delivery":
            return "## Delivery Draft\n- Summarize deliverables, limitations and next steps.\n- Human review required before sending."
        return "## Draft Output\nHuman review required before using this with a client."
