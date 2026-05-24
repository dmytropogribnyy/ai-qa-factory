"""P1.2 regression tests — Playwright scaffold false-green assertion fixes."""
from agents.playwright_generator import PlaywrightGeneratorAgent


def test_config_has_no_example_com_default():
    """playwright.config.ts must not fall back to example.com when BASE_URL is unset."""
    config = PlaywrightGeneratorAgent._playwright_config()
    assert "|| 'https://example.com'" not in config, (
        "baseURL fallback to 'https://example.com' was not removed. "
        "Tests would silently pass against example.com instead of failing."
    )
    assert "process.env.BASE_URL," in config, (
        "baseURL should be set to process.env.BASE_URL with no fallback."
    )


def test_api_health_status_codes_exclude_404():
    """API health check must not accept 404 as a passing status code."""
    health = PlaywrightGeneratorAgent._api_health()
    assert "404" not in health, (
        "404 must be removed from API health check status codes. "
        "A missing endpoint should fail, not pass."
    )
    assert "[200, 204]" in health, (
        "API health check should only accept 200 or 204."
    )
