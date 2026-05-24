"""P1.3 regression tests — hardcoded_credentials false positive fix."""
from core.quality_gate import HardcodedCredentialsCheck
from core.state import QAFactoryState


def _state_with_output(content: str) -> QAFactoryState:
    state = QAFactoryState(project_id="p", mode="filter", raw_input="test")
    state.generated_outputs[".env.example"] = content
    return state


def test_empty_env_placeholder_not_flagged():
    """TEST_USER_PASSWORD= with no value must not trigger the credential gate."""
    state = _state_with_output(
        "BASE_URL=https://example.com\nTEST_USER_EMAIL=\nTEST_USER_PASSWORD=\nAPI_BASE_URL=\n"
    )
    result = HardcodedCredentialsCheck().evaluate(state)
    assert result.passed, (
        f"Empty placeholder 'TEST_USER_PASSWORD=' was falsely flagged: {result.warnings}"
    )


def test_real_password_still_flagged():
    """TEST_USER_PASSWORD with an actual value must still trigger the credential gate."""
    state = _state_with_output("TEST_USER_PASSWORD=SuperSecret123\n")
    result = HardcodedCredentialsCheck().evaluate(state)
    assert not result.passed, (
        "TEST_USER_PASSWORD with a real value should be flagged as a hardcoded credential."
    )
