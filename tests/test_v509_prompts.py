"""P1.4 regression tests — mobile prompt filename mismatch fix."""
from pathlib import Path


def test_mobile_release_qa_prompt_file_exists():
    """prompts/qa_plan/mobile_release_qa.md must exist so PromptLoader can load it.

    CapabilityRouterAgent maps react_native_maestro_qa -> mobile_release_qa,
    which causes PromptLoader to look for mobile_release_qa.md. Without this file
    the system silently falls back to the default prompt.
    """
    path = Path("prompts/qa_plan/mobile_release_qa.md")
    assert path.exists(), (
        "prompts/qa_plan/mobile_release_qa.md is missing. "
        "CapabilityRouterAgent.OPPORTUNITY_PROFILE_MAP maps react_native_maestro_qa "
        "to 'mobile_release_qa' but the prompt file did not exist."
    )
    content = path.read_text(encoding="utf-8")
    assert len(content.strip()) > 20, "mobile_release_qa.md appears to be empty."
