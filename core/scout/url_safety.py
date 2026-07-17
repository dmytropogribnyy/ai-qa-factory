"""Fail-closed URL eligibility for the Scout runtime (Phase 8.3).

Only public http(s) URLs are eligible. Everything below is rejected:
- credentials/userinfo in the URL;
- non-http(s) schemes;
- unsafe ports (only 80 / 443 / the scheme default are allowed);
- malformed hosts and single-label/internal names;
- IP literals or DNS results in loopback / private / link-local / reserved /
  multicast / unspecified ranges;
- redirect targets that resolve to any prohibited host.

An explicit, test-scoped `allowed_local_hosts` allowlist permits a specific local
fixture host (e.g. `127.0.0.1:8931`) for the deterministic E2E without loosening the
default: production/live use passes an empty allowlist, so localhost stays rejected.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Callable, FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

ALLOWED_SCHEMES: FrozenSet[str] = frozenset({"http", "https"})
ALLOWED_PORTS: FrozenSet[int] = frozenset({80, 443})
_DEFAULT_PORT = {"http": 80, "https": 443}

# A DNS resolver returns a list of IP strings for (host, port). Injectable for tests.
Resolver = Callable[[str, int], List[str]]


@dataclass(frozen=True)
class UrlPolicy:
    """Policy controlling which URLs are eligible."""

    # Explicit local hosts ("host" or "host:port") permitted despite being local.
    # Empty by default → localhost / private ranges are rejected (fail closed).
    allowed_local_hosts: FrozenSet[str] = field(default_factory=frozenset)
    # Resolve DNS and validate every resolved IP (prevents rebinding to internal hosts).
    resolve_dns: bool = True


@dataclass(frozen=True)
class UrlEligibility:
    raw: str
    eligible: bool
    normalized: str = ""
    host: str = ""
    port: Optional[int] = None
    scheme: str = ""
    reason: str = ""


def _default_resolver(host: str, port: int) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:  # DNS failure → treat as not resolvable
        raise _DnsError(str(exc)) from exc
    return sorted({info[4][0] for info in infos})


class _DnsError(Exception):
    pass


def _ip_is_prohibited(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → prohibited (fail closed)
    return not addr.is_global or addr.is_multicast or addr.is_reserved or addr.is_unspecified


def _host_is_ip_literal(host: str) -> Optional[str]:
    """Return the IP string if host is an IP literal (incl. bracketed IPv6), else None."""
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        return None


def _valid_hostname(host: str) -> bool:
    if not host or len(host) > 253 or ".." in host:
        return False
    labels = host.rstrip(".").split(".")
    if len(labels) < 2:  # single-label / internal names rejected
        return False
    for label in labels:
        if not label or len(label) > 63:
            return False
        if label[0] == "-" or label[-1] == "-":
            return False
        if not all(c.isalnum() or c == "-" for c in label):
            return False
    return True


def check_url(
    raw: str,
    policy: Optional[UrlPolicy] = None,
    resolver: Optional[Resolver] = None,
) -> UrlEligibility:
    """Return a fail-closed eligibility decision for `raw` (no network unless resolve_dns)."""
    policy = policy or UrlPolicy()
    if not isinstance(raw, str) or not raw.strip():
        return UrlEligibility(raw=str(raw), eligible=False, reason="empty URL")
    raw = raw.strip()
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        return UrlEligibility(raw=raw, eligible=False, reason=f"malformed URL: {exc}")

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return UrlEligibility(raw=raw, eligible=False, scheme=scheme,
                              reason=f"scheme not allowed: {scheme or '(none)'}")
    if parts.username or parts.password or "@" in parts.netloc:
        return UrlEligibility(raw=raw, eligible=False, reason="credentials in URL are not allowed")

    host = (parts.hostname or "").lower()
    if not host:
        return UrlEligibility(raw=raw, eligible=False, reason="URL has no host")
    try:
        port = parts.port
    except ValueError:
        return UrlEligibility(raw=raw, eligible=False, host=host, reason="invalid port")
    effective_port = port if port is not None else _DEFAULT_PORT[scheme]

    host_key = f"{host}:{port}" if port is not None else host
    explicitly_allowed = host in policy.allowed_local_hosts or host_key in policy.allowed_local_hosts

    # An explicitly allow-listed local fixture host may use its own ephemeral port;
    # every other host is restricted to the safe public ports.
    if not explicitly_allowed and port is not None and port not in ALLOWED_PORTS:
        return UrlEligibility(raw=raw, eligible=False, host=host, port=port,
                              reason=f"port not allowed: {port}")

    normalized = _normalize(scheme, host, port, parts)

    # IP-literal hosts: only allowed if global, or explicitly allow-listed (fixtures).
    ip_literal = _host_is_ip_literal(host)
    if ip_literal is not None:
        if explicitly_allowed:
            return UrlEligibility(raw=raw, eligible=True, normalized=normalized, host=host,
                                  port=effective_port, scheme=scheme, reason="explicit local allowlist")
        if _ip_is_prohibited(ip_literal):
            return UrlEligibility(raw=raw, eligible=False, host=host, port=effective_port,
                                  scheme=scheme, reason=f"prohibited IP address: {ip_literal}")
        return UrlEligibility(raw=raw, eligible=True, normalized=normalized, host=host,
                              port=effective_port, scheme=scheme)

    # Named hosts.
    if host in ("localhost",) or host.endswith(".localhost"):
        if explicitly_allowed:
            return UrlEligibility(raw=raw, eligible=True, normalized=normalized, host=host,
                                  port=effective_port, scheme=scheme, reason="explicit local allowlist")
        return UrlEligibility(raw=raw, eligible=False, host=host, reason="localhost is not allowed")
    if not _valid_hostname(host):
        return UrlEligibility(raw=raw, eligible=False, host=host,
                              reason="malformed or single-label host")

    if explicitly_allowed:
        return UrlEligibility(raw=raw, eligible=True, normalized=normalized, host=host,
                              port=effective_port, scheme=scheme, reason="explicit local allowlist")

    # DNS guard: every resolved IP must be a global address (blocks rebinding to internal).
    if policy.resolve_dns:
        resolve = resolver or _default_resolver
        try:
            ips = resolve(host, effective_port)
        except _DnsError as exc:
            return UrlEligibility(raw=raw, eligible=False, host=host,
                                  reason=f"host does not resolve: {exc}")
        if not ips:
            return UrlEligibility(raw=raw, eligible=False, host=host, reason="host does not resolve")
        for ip in ips:
            if _ip_is_prohibited(ip):
                return UrlEligibility(raw=raw, eligible=False, host=host,
                                      reason=f"host resolves to a prohibited address: {ip}")

    return UrlEligibility(raw=raw, eligible=True, normalized=normalized, host=host,
                          port=effective_port, scheme=scheme)


def _normalize(scheme: str, host: str, port: Optional[int], parts) -> str:
    netloc = host
    if port is not None and port != _DEFAULT_PORT[scheme]:
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def dedupe_eligible(
    raws: List[str],
    policy: Optional[UrlPolicy] = None,
    resolver: Optional[Resolver] = None,
) -> Tuple[List[UrlEligibility], List[UrlEligibility]]:
    """Return (eligible_unique, rejected). Eligible are de-duplicated by normalized URL."""
    eligible: List[UrlEligibility] = []
    rejected: List[UrlEligibility] = []
    seen: set = set()
    for raw in raws:
        result = check_url(raw, policy=policy, resolver=resolver)
        if not result.eligible:
            rejected.append(result)
            continue
        if result.normalized in seen:
            continue
        seen.add(result.normalized)
        eligible.append(result)
    return eligible, rejected
