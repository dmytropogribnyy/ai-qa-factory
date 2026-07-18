"""Guarded campaign-start launcher (v3.0.0 Milestone 4b).

The Scout dashboard historically exposed NO HTTP start endpoint by design. This module adds a
carefully guarded one for the local operator, keeping every existing safety control:

- **Loopback + origin + CSRF** are enforced by the HTTP layer (``dashboard.py``); this launcher
  is the policy core and is transport-agnostic (unit-testable without a socket).
- **Bounded, read-only only.** A campaign is a ``ScoutRunConfig`` (1..10 public seeds, bounded
  pages/bytes/timeout, ``concurrency == 1``, read-only check families). The browser mode is forced
  to ``static`` - the web endpoint never launches a real browser.
- **Unsafe targets rejected.** Every seed passes ``url_safety.check_url`` (public http(s) only; no
  credentials, loopback, private/link-local/reserved IPs, odd ports, or DNS-rebinding). The
  local-fixture allowlist is a SERVER-side setting, never taken from the request (no SSRF bypass).
- **Explicit confirmation** (``confirm == true``) is required - no accidental starts.
- **Idempotency.** A duplicate ``idempotency_key`` returns the same run id instead of starting a
  second campaign.
- **One active campaign.** A start is refused (409) while another campaign is running.
- **Persist before execution.** The campaign intent is written to a durable registry BEFORE the
  worker is spawned, so a crash/restart leaves an honest record.

The launcher never sends email, submits forms, solves CAPTCHAs, or runs arbitrary commands: it can
only start the existing bounded read-only Scout engine.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.scout.config import MAX_SEEDS, ScoutConfigError, ScoutRunConfig, fresh_run_id
from core.scout.url_safety import Resolver, UrlPolicy, dedupe_eligible

_REGISTRY_DIRNAME = "_campaigns"
_MAX_SEED_STRLEN = 2048


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CampaignStartResult:
    ok: bool
    status: int
    message: str
    run_id: str = ""
    idempotent: bool = False
    rejected: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "status": self.status, "message": self.message,
                "run_id": self.run_id, "idempotent": self.idempotent, "rejected": self.rejected}


def _reject(status: int, message: str, rejected: Optional[List[Dict[str, str]]] = None
            ) -> CampaignStartResult:
    return CampaignStartResult(ok=False, status=status, message=message, rejected=rejected or [])


class CampaignLauncher:
    """Policy core for starting a bounded, read-only Scout campaign over HTTP.

    ``allowed_local_hosts`` / ``resolve_dns`` are SERVER settings (empty allowlist in live use, so
    localhost/private targets stay rejected); the untrusted request can never widen them. ``starter``
    and ``resolver`` are injectable for deterministic tests.
    """

    def __init__(self, service: Any, *, registry_dir: Optional[str] = None,
                 allowed_local_hosts=frozenset(), resolve_dns: bool = True,
                 resolver: Optional[Resolver] = None,
                 starter: Optional[Callable[[ScoutRunConfig], str]] = None,
                 clock: Callable[[], str] = _now_iso) -> None:
        self._service = service
        self._allowed = frozenset(allowed_local_hosts)
        self._resolve_dns = resolve_dns
        self._resolver = resolver
        self._starter = starter or service.start
        self._clock = clock
        base = Path(registry_dir) if registry_dir else Path(service.output_dir) / "scout" / _REGISTRY_DIRNAME
        self._registry = base
        self._lock = threading.Lock()

    # --- registry (persist-before-execution) -----------------------------------------------------
    def _record_path(self, key: str) -> Path:
        # Content-address the key so an arbitrary string is a safe, confined filename.
        import hashlib
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self._registry / f"{digest}.json"

    def _lookup(self, key: str) -> Optional[Dict[str, Any]]:
        path = self._record_path(key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _persist(self, key: str, record: Dict[str, Any]) -> None:
        self._registry.mkdir(parents=True, exist_ok=True)
        path = self._record_path(key)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    # --- start -----------------------------------------------------------------------------------
    def start(self, request: Dict[str, Any]) -> CampaignStartResult:
        if not isinstance(request, dict):
            return _reject(400, "request body must be a JSON object")
        if request.get("confirm") is not True:
            return _reject(400, "explicit confirmation required (confirm=true)")
        key = request.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            return _reject(400, "idempotency_key is required")
        key = key.strip()

        with self._lock:
            existing = self._lookup(key)
            if existing:
                prior = existing.get("status")
                # ONLY a genuinely STARTED record is an idempotent success. STARTING is ambiguous
                # (a crash may have happened between persist and start), and REJECTED/FAILED are
                # explicit non-starts - all three must retry, never report a false success.
                if prior == "STARTED" and existing.get("run_id"):
                    return CampaignStartResult(ok=True, status=200, run_id=existing["run_id"],
                                               message="idempotent replay (campaign already started)",
                                               idempotent=True)
            if self._service.is_running():
                return _reject(409, "a campaign is already active; stop it before starting another")

            seeds = request.get("seeds")
            if not isinstance(seeds, list) or not seeds or not all(isinstance(s, str) for s in seeds):
                return _reject(400, "seeds must be a non-empty list of URL strings")
            if len(seeds) > MAX_SEEDS:
                return _reject(422, f"too many seeds: {len(seeds)} (max {MAX_SEEDS})")
            if any(len(s) > _MAX_SEED_STRLEN for s in seeds):
                return _reject(422, "a seed URL is unreasonably long")

            policy = UrlPolicy(allowed_local_hosts=self._allowed, resolve_dns=self._resolve_dns)
            eligible, rejected = dedupe_eligible(seeds, policy=policy, resolver=self._resolver)
            if rejected:
                return _reject(422, "unsafe or ineligible targets were rejected",
                               rejected=[{"url": r.raw, "reason": r.reason} for r in rejected])
            if not eligible:
                return _reject(400, "no eligible seeds after safety filtering")

            try:
                cfg = self._build_config(request, [e.normalized for e in eligible])
            except ScoutConfigError as exc:
                return _reject(422, f"invalid campaign limits: {exc}")
            cfg.run_id = fresh_run_id(cfg.campaign_name)

            record = {"idempotency_key": key, "run_id": cfg.run_id, "status": "STARTING",
                      "requested_at": self._clock(), "source": "dashboard_http", "confirmed": True,
                      "previous_status": (existing or {}).get("status"),
                      "config": cfg.material_signature()}
            self._persist(key, record)                      # persist BEFORE execution

            try:
                run_id = self._starter(cfg)
            except RuntimeError as exc:                       # one-active guard in the service
                return self._fail(key, record, 409, str(exc))
            except Exception as exc:  # noqa: BLE001 - any starter failure is recorded honestly, not swallowed
                return self._fail(key, record, 500, f"campaign start failed: {exc}")
            record["status"] = "STARTED"
            record["run_id"] = run_id
            self._persist(key, record)
            return CampaignStartResult(ok=True, status=202, run_id=run_id,
                                       message="bounded read-only campaign started")

    def _fail(self, key: str, record: Dict[str, Any], status: int, message: str
              ) -> CampaignStartResult:
        """Record a non-start honestly (REJECTED for a refusal, FAILED for a starter error) so a
        later replay retries instead of reading a false success."""
        record["status"] = "REJECTED" if status < 500 else "FAILED"
        record["error"] = message[:200]
        self._persist(key, record)
        return _reject(status, message)

    def _build_config(self, request: Dict[str, Any], seeds: List[str]) -> ScoutRunConfig:
        """Build a bounded config from untrusted input. Only an allowlist of fields is honored;
        ``browser_mode`` is forced to ``static`` (the web endpoint never launches a browser) and
        ``allowed_local_hosts`` comes from the SERVER, never the request."""
        campaign = request.get("campaign")
        name = _safe_name(campaign) if isinstance(campaign, str) else "adhoc"
        families = request.get("check_families")
        kwargs: Dict[str, Any] = {
            "campaign_name": name, "seeds": seeds, "browser_mode": "static",
            "output_dir": str(self._service.output_dir), "concurrency": 1,
            "allowed_local_hosts": self._allowed, "resolve_dns": self._resolve_dns,
        }
        if isinstance(request.get("max_sites"), int) and not isinstance(request.get("max_sites"), bool):
            kwargs["max_sites"] = request["max_sites"]
        if isinstance(request.get("max_pages"), int) and not isinstance(request.get("max_pages"), bool):
            kwargs["max_pages_per_site"] = request["max_pages"]
        if isinstance(families, list) and families and all(isinstance(f, str) for f in families):
            kwargs["check_families"] = families
        return ScoutRunConfig(**kwargs)


def _safe_name(value: str) -> str:
    slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in value.strip())[:40]
    return slug.strip("-") or "adhoc"
