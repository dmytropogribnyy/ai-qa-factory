"""UniversalProfileSelector — Phase 8.1 (deterministic profile inference).

Existing classifiers are QA-first; this selector understands all eight ARK profiles.
It scores the (already-redacted) brief against per-profile keyword signals. Unknown or
low-signal work stays unresolved rather than silently becoming QA automation.

Deterministic: no LLM. Tie-breaks are alphabetical so output is reproducible.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from core.schemas.capability import CAPABILITY_PROFILES
from core.schemas.profile_selection import ProfileSelection

# Per-profile keyword signals (lowercase). Weighted by specificity.
_PROFILE_SIGNALS: Dict[str, List[str]] = {
    "api_project": ["api", "openapi", "swagger", "postman", "endpoint", "rest ",
                    "graphql", "api contract", "webhook"],
    "data_project": ["database", "postgres", "mysql", "mongodb", "mongo", " sql",
                     "rls", "migration", "db schema", "supabase", "data pipeline"],
    "web_app_audit": ["accessibility", "a11y", "lighthouse", "core web vitals",
                      "web app", "website audit", "audit the site", "e2e", "ui test",
                      "playwright", "test the website", "qa audit"],
    "automation_project": ["automation", "automate", "workflow", "scrape", "scraping",
                           "n8n", "zapier", "make.com", "rpa", "bot "],
    "technical_writing": ["documentation", "technical writing", "help center",
                          "user guide", "write an article", "readme", "api docs",
                          "content writing", "tutorial"],
    "mvp_launch_audit": ["mvp", "pre-launch", "launch readiness", "go live",
                         "production readiness", "release readiness"],
    "research_only": ["research", "investigate", "feasibility", "compare options",
                      "evaluate options", "market research", "explore"],
    "code_project": ["implement", "build a feature", "develop", "refactor", "bug fix",
                     "write code", "sdk", "integration code", "new feature", "coding"],
}

_MIN_CONFIDENCE = 0.35


class UniversalProfileSelector:
    """Deterministic capability-profile inference."""

    def select(
        self,
        text: str,
        signals: Optional[List[str]] = None,
        override: Optional[str] = None,
    ) -> ProfileSelection:
        haystack = " " + text.lower() + " " + " ".join(signals or []).lower() + " "
        scores: Dict[str, int] = {}
        matched: Dict[str, List[str]] = {}
        for profile, kws in _PROFILE_SIGNALS.items():
            hits = [kw.strip() for kw in kws if kw in haystack]
            if hits:
                scores[profile] = len(hits)
                matched[profile] = hits

        warnings: List[str] = []
        inferred = ""
        confidence = 0.0
        alternatives: List[str] = []
        matched_signals: List[str] = []

        if scores:
            # Deterministic ranking: score desc, then profile name asc.
            ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
            inferred, top_score = ranked[0]
            confidence = min(0.9, 0.3 + 0.15 * top_score)
            matched_signals = sorted(matched[inferred])
            alternatives = [p for p, s in ranked[1:] if s > 0]
            if len(ranked) > 1 and ranked[1][1] == top_score:
                warnings.append(
                    f"ambiguous inference: {inferred} ties with {ranked[1][0]}; low confidence"
                )
                confidence = min(confidence, _MIN_CONFIDENCE)

        # Resolve selection.
        if override:
            if override not in CAPABILITY_PROFILES:
                warnings.append(f"override '{override}' is not a known profile; ignored")
                selected, source = inferred, "inferred"
            else:
                selected, source = override, "override"
                if inferred and override != inferred:
                    warnings.append(
                        f"override '{override}' differs from inferred '{inferred}'"
                    )
            if not selected:
                source = "unresolved"
        elif not inferred:
            selected, source = "", "unresolved"
            warnings.append("insufficient signal to infer a profile; more information needed")
        elif confidence < _MIN_CONFIDENCE:
            # Low confidence: do not silently commit to a domain profile.
            selected, source = "", "unresolved"
            warnings.append(
                f"low-confidence inference '{inferred}' (conf={round(confidence, 2)}); "
                "profile left unresolved pending clarification"
            )
        else:
            selected, source = inferred, "inferred"

        return ProfileSelection(
            inferred_profile=inferred,
            selected_profile=selected,
            selection_source=source,
            confidence=round(confidence, 2),
            matched_signals=matched_signals,
            alternative_profiles=alternatives,
            warnings=warnings,
        )
