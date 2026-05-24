"""P1.1 regression tests — ai_native_exploratory_qa keyword narrowing and ordering fix."""
from agents.capability_router import CapabilityRouterAgent


def test_saas_billing_not_hijacked_by_manual_keyword():
    """'manual' alone must not route to ai_native_exploratory_qa when billing keywords present."""
    text = "we need manual billing testing for our multi-tenant saas subscription platform"
    result = CapabilityRouterAgent._detect_type(text)
    assert result == "saas_multi_tenant_billing_auth_audit", (
        f"Expected saas billing route, got {result!r}. "
        "'manual' keyword must not hijack saas billing detection."
    )


def test_exploratory_word_alone_does_not_trigger_ai_native():
    """'exploratory' or 'manual' alone must no longer route to ai_native_exploratory_qa."""
    for keyword in ["exploratory testing needed", "manual qa needed"]:
        result = CapabilityRouterAgent._detect_type(keyword)
        assert result != "ai_native_exploratory_qa", (
            f"Input {keyword!r} triggered ai_native_exploratory_qa via generic term. "
            "Only high-signal terms should trigger this type."
        )


def test_high_signal_ai_native_keywords_still_route_correctly():
    """High-signal terms like 'loom' and 'ai-native' must still route to ai_native_exploratory_qa."""
    for text in [
        "record loom video walkthroughs of each bug found",
        "ai-native qa approach with screen recording",
        "hands-on qa release qa pass with narrated walkthrough",
    ]:
        result = CapabilityRouterAgent._detect_type(text)
        assert result == "ai_native_exploratory_qa", (
            f"Input {text!r} should route to ai_native_exploratory_qa, got {result!r}."
        )
