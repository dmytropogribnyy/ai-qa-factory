"""
Pytest configuration: force mock mode and suppress noisy LiteLLM AWS warnings.

pytest_configure runs before any test module is imported, so env vars are set
before core/config.py calls load_dotenv() — which never overrides existing env vars.
This means .env values of LLM_MODE=real / MODEL_PROFILE=premium_hybrid are ignored
during pytest without touching normal CLI execution.
"""

from __future__ import annotations

import logging
import os
import warnings


def pytest_configure(config: object) -> None:
    # Force mock mode unless the shell already has an explicit override.
    # setdefault wins over .env because we run before load_dotenv() is called.
    os.environ.setdefault("LLM_MODE", "mock")
    os.environ.setdefault("MODEL_PROFILE", "mock")

    # Tell LiteLLM to stay quiet — optional dependency warnings (botocore/AWS)
    # are harmless in mock mode and clutter the test output.
    os.environ.setdefault("LITELLM_LOG", "ERROR")

    # Belt-and-suspenders: silence via Python logging and warnings as well.
    for logger_name in ("LiteLLM", "litellm", "litellm.utils", "litellm.main"):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    warnings.filterwarnings("ignore", message=".*botocore.*")
    warnings.filterwarnings("ignore", message=".*boto3.*")
    warnings.filterwarnings("ignore", message=".*sagemaker.*", category=UserWarning)

    # Real-browser Scout acceptance (Phase 8.3.1). Skipped automatically unless the optional
    # playwright package + a Chromium build are available; keeps the ordinary suite deterministic.
    config.addinivalue_line(
        "markers",
        "playwright_acceptance: real local Chromium acceptance for the Scout browser backend",
    )
    config.addinivalue_line(
        "markers",
        "final1_browser_acceptance: real local Chromium + axe + performance + reversible acceptance",
    )
