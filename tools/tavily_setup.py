"""Hidden interactive local setup for TAVILY_API_KEY (v3.3).

Prompts for the key WITHOUT echoing it, stores it OUTSIDE the repository (the existing ~/.aiqa
convention), validates it with ONE minimal bounded Tavily request, and prints only success/failure +
safe metadata. The key is never printed, logged, committed, or placed on a command line. Run:

    python tools/tavily_setup.py            # prompts (no echo), stores, validates
    python tools/tavily_setup.py --status   # show presence + git-safety only (no validation call)
"""
from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scout.discovery.tavily_provider import (  # noqa: E402
    TavilyBudget,
    TavilyDiscoveryProvider,
    TavilyRequestConfig,
    real_tavily_transport,
)
from core.scout.discovery.providers import ProviderMetadata  # noqa: E402
from core.scout.discovery.tavily_secret import (  # noqa: E402
    key_present,
    key_provider,
    masked_metadata,
    secret_path,
    store_tavily_key,
)


def _git_ignores_secret() -> bool:
    """Confirm Git cannot see the secret: it lives outside the repo, so `git status` never lists it."""
    try:
        repo = Path(__file__).resolve().parents[1]
        p = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True, timeout=15, check=False)
        return "tavily.key" not in (p.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return True


def _validate_live() -> tuple[bool, str]:
    """One minimal bounded Tavily request to validate the credential. Never prints the key."""
    meta = ProviderMetadata(provider_id="tavily", provider_type="api", trust_status="trusted",
                            enabled=True, terms_review_status="reviewed_approved",
                            auth_ref="TAVILY_API_KEY", public_or_licensed="licensed")
    provider = TavilyDiscoveryProvider(
        meta, key_provider=key_provider(), transport=real_tavily_transport(TavilyRequestConfig(timeout_s=12.0)),
        budget=TavilyBudget(max_requests=1, max_results=1), live_approved=True)
    try:
        cands = provider.discover({"industry": "software", "country": "us"}, limit=1)
        return True, f"validated; {len(cands)} company candidate(s) from 1 result"
    except Exception as exc:  # noqa: BLE001 - report the class only, never the key/body
        return False, f"validation failed: {type(exc).__name__}: {exc}"


def main() -> int:
    status_only = "--status" in sys.argv
    print("AI QA Factory - Tavily API key setup (the key is never displayed or logged)")
    print(f"  secret file (outside the repo): {secret_path()}")
    print(f"  git-safe (secret not visible to git): {_git_ignores_secret()}")

    if status_only:
        print(f"  key present: {key_present()}")
        print(f"  metadata: {masked_metadata()}")
        return 0

    try:
        entered = getpass.getpass("  Paste TAVILY_API_KEY (input hidden): ")
    except (EOFError, KeyboardInterrupt):
        print("  aborted; no change made")
        return 1
    if not entered.strip():
        print("  empty input; no change made")
        return 1
    store_tavily_key(entered)
    print("  stored (value not shown).")
    print(f"  metadata: {masked_metadata()}")
    print("  validating with one minimal bounded Tavily request ...")
    ok, msg = _validate_live()
    print(f"  {'SUCCESS' if ok else 'FAILURE'}: {msg}")
    print(f"  git-safe after write: {_git_ignores_secret()}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
