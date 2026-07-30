"""M1 — a documented remote-access procedure must never publish the operator Dashboard.

The Dashboard authenticates nothing on its read paths: ``_guard_mutation`` covers state-changing
endpoints only, so every GET is protected solely by the loopback bind. A tunnel terminates that bind
locally, so pointing one at the Dashboard's port publishes findings, evidence, contacts and client
packages to the internet with no credential in front of them. The MCP server is the surface meant to
be reachable — it refuses to start without ``AIQA_MCP_TOKEN``.

**These guards read values, not prose.** An earlier version of this file scanned for exposure words
near a port and skipped any window containing "never", which meant a dangerous instruction could be
waved through by writing "never" beside it. Prose can say anything; what an operator actually
executes is a port number, and a port number can be compared. Every check below therefore derives
its expected value from the source that defines it — the argparse default, the PowerShell parameter
default, the listener command the guide tells you to run — so the guards follow a future change of
any of them instead of pinning today's numbers, and no wording defeats them.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"
_GUIDE = _DOCS / "CHATGPT_OBSERVER_MCP_CONNECTION.md"

# An imperative that puts something on the network, with its port within the same clause. This is
# the shape of the defect: "…point it at `http://127.0.0.1:8765`". Nearby prose cannot suppress it.
# The leading \b matters: without it "checkpoint-id … --timeout 3600" matches on the "point" inside
# "checkpoint" and the guard cries wolf on unrelated documents.
_EXPOSURE_IMPERATIVE = re.compile(
    r"\b(?:point|forward|expose|publish|tunnel)\w*\b[^.\n]{0,80}?(\d{4,5})", re.IGNORECASE
)
_FENCED = re.compile(r"```.*?```", re.DOTALL)
_INLINE_URL = re.compile(r"`[^`]*?https?://[^\s`]*?:(\d{4,5})[^`]*?`")
_LISTENER_CHECK = re.compile(r"Get-NetTCPConnection\s+-LocalPort\s+(\d{4,5})")


def _argparse_default(path: Path, flag: str) -> int:
    for line in path.read_text(encoding="utf-8").splitlines():
        if flag in line and "default=" in line:
            found = re.search(r"default=(\d{2,5})", line)
            if found:
                return int(found.group(1))
    raise AssertionError(f"no argparse default for {flag!r} in {path.name}")


def dashboard_port() -> int:
    return _argparse_default(_ROOT / "main.py", '"--port"')


def mcp_http_port() -> int:
    return _argparse_default(_ROOT / "tools" / "run_mcp_server.py", '"--port"')


def powershell_helper_port() -> int:
    text = (_ROOT / "tools" / "observer_mcp.ps1").read_text(encoding="utf-8")
    found = re.search(r"\[int\]\$Port\s*=\s*(\d{4,5})", text)
    assert found, "observer_mcp.ps1 no longer declares a default $Port"
    return int(found.group(1))


# 3. The two implementations of "the MCP port" must not drift apart.
def test_powershell_helper_and_python_default_agree():
    assert powershell_helper_port() == mcp_http_port(), (
        f"observer_mcp.ps1 serves port {powershell_helper_port()} while run_mcp_server.py defaults "
        f"to {mcp_http_port()}; an operator following the helper and an operator following the "
        "guide would expose different surfaces"
    )


def test_mcp_http_default_port_is_not_the_dashboard_port():
    """The tunnelled surface and the unauthenticated one must not share a default.

    They did: both defaulted to 8765, which is what made "point your tunnel at 8765" read as
    sensible advice while actually publishing the Dashboard.
    """
    assert mcp_http_port() != dashboard_port(), (
        f"the MCP HTTP server and the Dashboard both default to port {mcp_http_port()}; "
        "an operator omitting --port cannot tell which surface a tunnel would reach"
    )


# 1. No instruction anywhere may aim an exposure mechanism at anything but the MCP port.
def test_no_exposure_imperative_targets_any_port_but_the_mcp_one():
    """Value check, not a word check — this is what the "never" heuristic failed to do.

    "Point the tunnel at the Dashboard's default 8765 — never at 8770" is caught here: the port
    inside the imperative is compared against the MCP default and does not match.
    """
    expected = mcp_http_port()
    offenders = []
    for path in sorted(_DOCS.rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for port in _EXPOSURE_IMPERATIVE.findall(line):
                if int(port) != expected:
                    offenders.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        f"these instructions aim an exposure mechanism at a port that is not the authenticated MCP "
        f"port ({expected}). The Dashboard ({dashboard_port()}) has no authentication on read "
        f"paths, so publishing it serves client data to anyone with the URL:\n  "
        + "\n  ".join(offenders)
    )


# 1 (second shape). Prose may name the dangerous port in order to warn about it; nothing the
# operator can copy and run may contain it.
def test_no_executable_snippet_names_the_dashboard_port():
    text = _GUIDE.read_text(encoding="utf-8")
    executable = "\n".join(_FENCED.findall(text))
    offenders = [
        line.strip()
        for line in executable.splitlines()
        if str(dashboard_port()) in line
    ]
    offenders += [
        f"inline URL with port {port}"
        for port in _INLINE_URL.findall(text)
        if int(port) == dashboard_port()
    ]
    assert not offenders, (
        "the remote-access guide contains runnable text naming the Dashboard's port; a reader "
        "copies commands, they do not weigh the surrounding prose:\n  " + "\n  ".join(offenders)
    )


# 2. The check the guide tells the operator to run before exposing anything must inspect the port
#    that is actually going to be exposed.
def test_the_documented_listener_check_targets_the_mcp_port():
    text = _GUIDE.read_text(encoding="utf-8")
    checks = [int(p) for p in _LISTENER_CHECK.findall(text)]
    assert checks, (
        "the guide no longer tells the operator to confirm what is listening before exposing it"
    )
    wrong = [p for p in checks if p != mcp_http_port()]
    assert not wrong, (
        f"the pre-exposure listener check inspects {wrong} while the MCP server serves "
        f"{mcp_http_port()}; the operator would verify one port and publish another"
    )


# 4. The authenticated route must remain genuinely executable — not merely mentioned.
def test_the_guide_keeps_an_executable_authenticated_route():
    """Guard against "fixing" the danger by hollowing out the capability.

    Two unrelated substrings elsewhere in the document are not a procedure. This requires a runnable
    command that actually starts the authenticated server, and a connector URL that ends at the MCP
    path.
    """
    text = _GUIDE.read_text(encoding="utf-8")
    executable = "\n".join(_FENCED.findall(text))
    starts_server = re.search(
        r"(observer_mcp\.ps1[^\n]*-Action\s+http\b|run_mcp_server\.py[^\n]*--http\b)", executable
    )
    assert starts_server, (
        "no runnable snippet in the guide starts the authenticated MCP HTTP server; the route is "
        "described but not executable"
    )
    assert "AIQA_MCP_TOKEN" in executable, (
        "no runnable snippet sets the bearer token the server refuses to start without"
    )
    assert re.search(r"https://[^\s`]*/mcp\b", text), (
        "the guide no longer shows the connector URL ending at the /mcp path"
    )
