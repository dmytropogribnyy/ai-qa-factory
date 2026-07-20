from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


MODEL_PROFILES = {
    "mock": {
        "architect": "mock",
        "coding": "mock",
        "review": "mock",
        "fast": "mock",
        "vision": "mock",
        "fallback": "mock",
    },
    # Preferred high-quality hybrid profile for Dmytro's Factory.
    # OpenAI handles the hardest opportunity routing / reasoning / vision.
    # Claude Sonnet handles practical coding and fast drafting.
    # Claude Opus is reserved for deep review and difficult reasoning.
    "premium_hybrid": {
        "architect": "gpt-5.5",
        "coding": "anthropic/claude-sonnet-4-6",
        "review": "anthropic/claude-opus-4-7",
        "fast": "anthropic/claude-sonnet-4-6",
        "vision": "gpt-5.5",
        "fallback": "gpt-5.4-mini",
    },
    # Good default if only OpenAI API is configured.
    "openai_only": {
        "architect": "gpt-5.5",
        "coding": "gpt-5.4-mini",
        "review": "gpt-5.5",
        "fast": "gpt-5.4-mini",
        "vision": "gpt-5.5",
        "fallback": "gpt-5.4-mini",
    },
    # Good default if only Anthropic API is configured.
    "anthropic_only": {
        "architect": "anthropic/claude-opus-4-7",
        "coding": "anthropic/claude-sonnet-4-6",
        "review": "anthropic/claude-opus-4-7",
        "fast": "anthropic/claude-sonnet-4-6",
        "vision": "anthropic/claude-opus-4-7",
        "fallback": "anthropic/claude-sonnet-4-6",
    },
    # Cost-conscious profile for calibration, summaries and low-risk drafts.
    "budget": {
        "architect": "gpt-5.4-mini",
        "coding": "gpt-5.4-mini",
        "review": "gpt-5.4-mini",
        "fast": "gpt-5.4-mini",
        "vision": "gpt-5.4-mini",
        "fallback": "gpt-5.4-mini",
    },
    # Anthropic-only, deliberately cheap. Used by Scout's optional LLM polish.
    # Haiku is the workhorse (drafts, summaries, quick outputs); Sonnet only for
    # the reasoning/review tiers. Opus is intentionally ABSENT: Scout never uses it.
    "anthropic_budget": {
        "architect": "anthropic/claude-sonnet-5",
        "coding": "anthropic/claude-haiku-4-5",
        "review": "anthropic/claude-sonnet-5",
        "fast": "anthropic/claude-haiku-4-5",
        "vision": "anthropic/claude-sonnet-5",
        "fallback": "anthropic/claude-haiku-4-5",
    },
}

DEFAULT_EFFORTS = {
    "mock": {
        "architect": "none", "coding": "none", "review": "none", "fast": "none", "vision": "none", "fallback": "none",
    },
    "premium_hybrid": {
        "architect": "high",
        "coding": "medium",
        "review": "xhigh",
        "fast": "low",
        "vision": "high",
        "fallback": "low",
    },
    "openai_only": {
        "architect": "high",
        "coding": "medium",
        "review": "high",
        "fast": "low",
        "vision": "high",
        "fallback": "low",
    },
    "anthropic_only": {
        "architect": "high",
        "coding": "medium",
        "review": "xhigh",
        "fast": "low",
        "vision": "high",
        "fallback": "low",
    },
    "budget": {
        "architect": "medium",
        "coding": "low",
        "review": "medium",
        "fast": "low",
        "vision": "medium",
        "fallback": "low",
    },
    # Haiku/Sonnet ignore the effort payload (see LLMRouter._effort_kwargs), so these
    # are advisory only; kept low to stay cheap and fast.
    "anthropic_budget": {
        "architect": "medium",
        "coding": "low",
        "review": "medium",
        "fast": "low",
        "vision": "low",
        "fallback": "low",
    },
}


def _profile_name() -> str:
    name = os.getenv("MODEL_PROFILE", "mock").lower().strip()
    return name if name in MODEL_PROFILES else "mock"


def _profile_model(profile: str, alias: str) -> str:
    return MODEL_PROFILES.get(profile, MODEL_PROFILES["mock"]).get(alias, "mock")


def _profile_effort(profile: str, alias: str) -> str:
    return DEFAULT_EFFORTS.get(profile, DEFAULT_EFFORTS["mock"]).get(alias, "low")


def _env_model(name: str, profile: str, alias: str) -> str:
    return os.getenv(name, _profile_model(profile, alias)).strip()


def _env_effort(name: str, profile: str, alias: str) -> str:
    return os.getenv(name, _profile_effort(profile, alias)).lower().strip()


@dataclass(frozen=True)
class Settings:
    llm_mode: str = field(default_factory=lambda: os.getenv("LLM_MODE", "mock").lower())
    model_profile: str = field(default_factory=_profile_name)
    enable_effort_params: bool = field(default_factory=lambda: os.getenv("ENABLE_EFFORT_PARAMS", "true").lower() in {"1", "true", "yes", "on"})

    output_dir: Path = field(default_factory=lambda: Path(os.getenv("OUTPUT_DIR", "outputs")))
    memory_dir: Path = field(default_factory=lambda: Path(os.getenv("MEMORY_DIR", "memory")))
    persistence_backend: str = field(default_factory=lambda: os.getenv("PERSISTENCE_BACKEND", "json").lower())

    architect_model: str = field(default_factory=lambda: _env_model("ARCHITECT_MODEL", _profile_name(), "architect"))
    coding_model: str = field(default_factory=lambda: _env_model("CODING_MODEL", _profile_name(), "coding"))
    review_model: str = field(default_factory=lambda: _env_model("REVIEW_MODEL", _profile_name(), "review"))
    fast_model: str = field(default_factory=lambda: _env_model("FAST_MODEL", _profile_name(), "fast"))
    vision_model: str = field(default_factory=lambda: _env_model("VISION_MODEL", _profile_name(), "vision"))
    fallback_model: str = field(default_factory=lambda: _env_model("FALLBACK_MODEL", _profile_name(), "fallback"))

    architect_effort: str = field(default_factory=lambda: _env_effort("ARCHITECT_EFFORT", _profile_name(), "architect"))
    coding_effort: str = field(default_factory=lambda: _env_effort("CODING_EFFORT", _profile_name(), "coding"))
    review_effort: str = field(default_factory=lambda: _env_effort("REVIEW_EFFORT", _profile_name(), "review"))
    fast_effort: str = field(default_factory=lambda: _env_effort("FAST_EFFORT", _profile_name(), "fast"))
    vision_effort: str = field(default_factory=lambda: _env_effort("VISION_EFFORT", _profile_name(), "vision"))
    fallback_effort: str = field(default_factory=lambda: _env_effort("FALLBACK_EFFORT", _profile_name(), "fallback"))

    llm_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT_SECONDS", "90")))
    llm_max_retries: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "2")))

    @property
    def is_mock(self) -> bool:
        return self.llm_mode == "mock"

    def model_for_alias(self, alias: str) -> str:
        mapping = {
            "architect": self.architect_model,
            "coding": self.coding_model,
            "review": self.review_model,
            "fast": self.fast_model,
            "vision": self.vision_model,
            "fallback": self.fallback_model,
        }
        return mapping.get(alias.lower(), self.fallback_model)

    def effort_for_alias(self, alias: str) -> str:
        mapping = {
            "architect": self.architect_effort,
            "coding": self.coding_effort,
            "review": self.review_effort,
            "fast": self.fast_effort,
            "vision": self.vision_effort,
            "fallback": self.fallback_effort,
        }
        return mapping.get(alias.lower(), self.fallback_effort)


def get_settings() -> Settings:
    settings = Settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ["clients", "snippets", "lessons-learned", "projects"]:
        (settings.memory_dir / subdir).mkdir(parents=True, exist_ok=True)
    return settings
