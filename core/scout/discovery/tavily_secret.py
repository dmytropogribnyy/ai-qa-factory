"""Local, outside-repo secret handling for TAVILY_API_KEY (v3.3).

No keyring dependency is added; this reuses the project's existing convention of storing local
credentials OUTSIDE the repository (``%USERPROFILE%\\.aiqa`` — the same place the Gmail tokens live),
referenced by env-var NAME. The key is read from the ``TAVILY_API_KEY`` environment variable if set,
otherwise from the local secret file. The value is never printed, logged, committed, serialized, or
returned by any status/readiness surface — only presence and safe metadata are ever exposed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, Optional

ENV_NAME = "TAVILY_API_KEY"


def secret_path() -> Path:
    """The outside-repo secret file location (never inside the repository)."""
    base = os.environ.get("AIQA_SECRETS_DIR") or str(Path.home() / ".aiqa" / "secrets")
    return Path(base) / "tavily.key"


def get_tavily_key(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Return the key from the env var (preferred) or the local secret file; None if absent."""
    e = env if env is not None else os.environ
    v = (e.get(ENV_NAME) or "").strip()
    if v:
        return v
    try:
        fv = secret_path().read_text(encoding="utf-8").strip()
        return fv or None
    except OSError:
        return None


def key_present(env: Optional[Dict[str, str]] = None) -> bool:
    return bool(get_tavily_key(env))


def store_tavily_key(value: str) -> Path:
    """Atomically store the key in the outside-repo secret file with best-effort restrictive perms.
    The caller (setup command) obtained the value via a no-echo prompt; it is never logged here."""
    value = (value or "").strip()
    if not value:
        raise ValueError("empty key")
    p = secret_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, p)
    try:
        if os.name == "posix":
            os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def key_provider(env: Optional[Dict[str, str]] = None) -> Callable[[], Optional[str]]:
    """A late-binding provider callable for TavilyDiscoveryProvider (re-reads each call; never caches
    the value on an object)."""
    return lambda: get_tavily_key(env)


def masked_metadata(env: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    """Safe, non-secret metadata about the key's presence (never the value)."""
    k = get_tavily_key(env)
    return {"present": bool(k), "length": (len(k) if k else 0),
            "prefix_ok": bool(k and k.startswith("tvly-")), "source": (
                ENV_NAME if (env or os.environ).get(ENV_NAME) else
                ("file" if k else "none")),
            "path_outside_repo": str(secret_path())}
