from __future__ import annotations

import re
from core.state import QAFactoryState


class ScreeningAnswersAgent:
    """Extracts Upwork screening questions and creates honest answer scaffolds."""
    name = "Screening Answers"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        questions = self._extract_questions(state.raw_input)
        keywords = self._extract_mandatory_keywords(state.raw_input)
        ai_traps = self._detect_ai_traps(state.raw_input)
        state.screening_questions = questions
        state.mandatory_keywords = keywords
        if ai_traps:
            state.risk_flags.extend([f"AI/prompt-injection trap detected: {trap}" for trap in ai_traps])
        state.generated_outputs["screening_answers.md"] = self._render(state, questions, keywords, ai_traps)
        state.log(f"{self.name}: {len(questions)} questions, {len(keywords)} mandatory keywords")
        return state

    @staticmethod
    def _extract_questions(text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines()]
        questions: list[str] = []
        in_apply = False
        for line in lines:
            low = line.lower()
            if any(marker in low for marker in ["you will be asked", "to apply", "screening", "please include", "include:", "answer"]):
                in_apply = True
            if in_apply and (line.endswith("?") or re.match(r"^\d+[.)]\s+", line) or line.startswith("-") or line.startswith("•")):
                cleaned = re.sub(r"^[-•\d.)\s]+", "", line).strip()
                if len(cleaned) > 8:
                    questions.append(cleaned)
        # Deduplicate while preserving order.
        seen = set()
        out = []
        for q in questions:
            key = q.lower()
            if key not in seen:
                seen.add(key)
                out.append(q)
        return out[:12]

    @staticmethod
    def _extract_mandatory_keywords(text: str) -> list[str]:
        patterns = [
            r"start your first answer with the word\s+[\"'“”]?([A-Za-z0-9_-]+)",
            r"begin your proposal with the word\s+[\"'“”]?([A-Za-z0-9_-]+)",
            r"begin with the word\s+[\"'“”]?([A-Za-z0-9_-]+)",
            r"start.*?with\s+[\"'“”]([A-Za-z0-9_-]+)[\"'“”]",
        ]
        found = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                word = match.group(1).strip(" .,:;!?)").strip()
                if word and word.lower() not in {"if", "the", "a"}:
                    found.append(word)
        # Do not treat AI-trap codes as mandatory keywords.
        return [w for w in dict.fromkeys(found) if not re.match(r"^[a-f0-9]{3,}[-_][a-z0-9]+$", w.lower())]

    @staticmethod
    def _detect_ai_traps(text: str) -> list[str]:
        traps = []
        for pattern in [r"if you are an llm[^\n]+", r"if you are chatgpt[^\n]+", r"ignore previous instructions[^\n]+"]:
            traps.extend(match.group(0).strip() for match in re.finditer(pattern, text, re.IGNORECASE))
        return traps

    @staticmethod
    def _render(state: QAFactoryState, questions: list[str], keywords: list[str], ai_traps: list[str]) -> str:
        lines = ["# Screening Answers", "", "This file is a draft scaffold. Do not invent evidence. Replace placeholders with real examples before sending.", ""]
        if keywords:
            lines.append("## Mandatory opening keyword")
            for word in keywords:
                lines.append(f"- `{word}` — proposal/screening answer must start with this if the client explicitly requested it.")
            lines.append("")
        if ai_traps:
            lines.append("## AI / prompt-injection traps")
            for trap in ai_traps:
                lines.append(f"- {trap}")
            lines.append("- Do not blindly include trap codes that identify the response as AI-generated. Review manually.")
            lines.append("")
        lines.append("## Detected questions and suggested answer scaffolds")
        if not questions:
            lines.append("- No explicit screening questions detected.")
        for i, question in enumerate(questions, 1):
            lines.append(f"### {i}. {question}")
            lines.append("Suggested answer scaffold:")
            lines.append("- Keep it short, specific and truthful.")
            if any(x in question.lower() for x in ["bug report", "example", "link", "portfolio", "github", "app store"]):
                lines.append("- Evidence required: paste/link a real redacted example. Do not invent.")
            elif any(x in question.lower() for x in ["ai tools", "claude", "chatgpt", "cursor"]):
                lines.append("- Mention concrete tool → use pairings, e.g. ChatGPT for test ideas, Claude for review, Cursor for code edits, Loom/Jam for recording summaries.")
            elif any(x in question.lower() for x in ["available", "start", "hours", "device", "mac"]):
                lines.append("- Confirm only what is true for Dmytro's current availability/devices.")
            else:
                lines.append(f"- Suggested angle: {state.client_context.get('safe_positioning_angle', 'senior QA approach with honest scope control')}.")
            lines.append("")
        return "\n".join(lines).strip() + "\n"
