"""M1 — a documented remote-access procedure must never publish the operator Dashboard.

The Dashboard authenticates nothing on its read paths: ``_guard_mutation`` covers state-changing
endpoints only, so every GET is protected solely by the loopback bind. A tunnel terminates that bind
locally, so pointing one at the Dashboard's port publishes findings, evidence, contacts and client
packages to the internet with no credential in front of them. The MCP server is the surface meant to
be reachable — it refuses to start without ``AIQA_MCP_TOKEN``.

**These guards read values, not prose.** An earlier version scanned for exposure words near a port
and skipped any window containing "never", so a dangerous instruction could be waved through by
writing "never" beside it. Prose can say anything; what an operator executes is a port number, and a
port number can be compared. Every check derives its expected value from the source that defines it.

Two further defects, both found only after the fix had merged and both closed here:

* the scan enumerated ``docs/**/*.md`` from the **working tree**, so an untracked local file could
  fail the suite on one machine while CI stayed green — a guard whose verdict depends on someone's
  scratch notes is not a guard;
* the port pattern accepted any 4–5 digit run, so the hex fragment inside ``tunnel_6a5e77892a3c…``
  and a process id both read as ports.

Ports are now recognised only in port position, and only inside a genuine exposure *imperative*, so
the noun "tunnel" in "tunnel ID: …" and a descriptive "…local health port 8080" sentence stay silent.
The fixtures at the bottom assert both directions, because a guard that only proves it stays quiet
has proved nothing.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"
_GUIDE = _DOCS / "CHATGPT_OBSERVER_MCP_CONNECTION.md"

# An exposure imperative: a verb that puts something on the network. "tunnel" counts only when used
# as a verb ("tunnel it to …"); as a noun it appears constantly in legitimate prose ("tunnel ID: …",
# "Tunnel PID 54572") and must not arm the check.
_IMPERATIVE = (
    r"(?:point|forward|expose|publish)\w*"
    r"|tunnel(?:s|ed|led|ing|ling)?\s+(?:it|the|your|this)"
)
# A port in port position — never a bare digit run:
#   :8770        host/URL form
#   port 8770    explicit
#   `8770`       an all-digit backticked target — the shape of the reviewed bypass
_PORT_FORMS = r"(?::(\d{2,5})\b|\bports?\s+(\d{2,5})\b|`(\d{2,5})`)"
# The span between verb and port must allow dots: the instruction that caused all of this reads
# "point it at `http://127.0.0.1:8765`", and a dot-excluding span cannot cross the address.
_EXPOSURE = re.compile(rf"\b(?:{_IMPERATIVE})\b[^\n]{{0,80}}?{_PORT_FORMS}", re.IGNORECASE)
_FENCED = re.compile(r"```.*?```", re.DOTALL)
_INLINE_URL = re.compile(r"`[^`]*?https?://[^\s`]*?:(\d{2,5})[^`]*?`")
_LISTENER_CHECK = re.compile(r"Get-NetTCPConnection\s+-LocalPort\s+(\d{2,5})")


def exposure_targets(text: str) -> list[int]:
    """Every port an exposure imperative aims at. Pure, so the fixtures can drive it directly."""
    found: list[int] = []
    for line in text.splitlines():
        for groups in _EXPOSURE.findall(line):
            port = next((g for g in groups if g), None)
            if port:
                found.append(int(port))
    return found


def tracked_docs() -> list[Path]:
    """Markdown the repository actually contains — never the working tree.

    Fails closed. ``git`` runs with an explicit cwd and **stdin closed**: this repository has already
    lost a day to a Windows hang where a subprocess inherited the MCP server's stdin and
    git-for-Windows blocked forever probing that handle (PR #53). A guard that quietly degraded to
    "no documents to check" would be worse than no guard, so an unusable result raises.
    """
    try:
        done = subprocess.run(
            ["git", "ls-files", "-z", "--", "docs"],
            cwd=_ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - environment failure
        raise AssertionError(f"could not enumerate tracked docs: {exc!r}") from exc
    if done.returncode != 0:
        raise AssertionError(f"git ls-files failed ({done.returncode}): {done.stderr.strip()!r}")
    names = [n for n in done.stdout.split("\0") if n.endswith(".md")]
    if not names:
        raise AssertionError("git ls-files returned no tracked markdown under docs/")
    return [_ROOT / name for name in names]


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
    found = re.search(r"\[int\]\$Port\s*=\s*(\d{2,5})", text)
    assert found, "observer_mcp.ps1 no longer declares a default $Port"
    return int(found.group(1))


def test_powershell_helper_and_python_default_agree():
    assert powershell_helper_port() == mcp_http_port(), (
        f"observer_mcp.ps1 serves port {powershell_helper_port()} while run_mcp_server.py defaults "
        f"to {mcp_http_port()}; an operator following the helper and an operator following the "
        "guide would expose different surfaces"
    )


def test_mcp_http_default_port_is_not_the_dashboard_port():
    assert mcp_http_port() != dashboard_port(), (
        f"the MCP HTTP server and the Dashboard both default to port {mcp_http_port()}; "
        "an operator omitting --port cannot tell which surface a tunnel would reach"
    )


def test_no_exposure_imperative_targets_any_port_but_the_mcp_one():
    expected = mcp_http_port()
    offenders = []
    for path in tracked_docs():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for port in exposure_targets(line):
                if port != expected:
                    offenders.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        f"these instructions aim an exposure mechanism at a port that is not the authenticated MCP "
        f"port ({expected}). The Dashboard ({dashboard_port()}) has no authentication on read "
        f"paths, so publishing it serves client data to anyone with the URL:\n  "
        + "\n  ".join(offenders)
    )


def test_no_executable_snippet_names_the_dashboard_port():
    text = _GUIDE.read_text(encoding="utf-8")
    executable = "\n".join(_FENCED.findall(text))
    offenders = [ln.strip() for ln in executable.splitlines() if str(dashboard_port()) in ln]
    offenders += [
        f"inline URL with port {port}"
        for port in _INLINE_URL.findall(text)
        if int(port) == dashboard_port()
    ]
    assert not offenders, (
        "the remote-access guide contains runnable text naming the Dashboard's port; a reader "
        "copies commands, they do not weigh the surrounding prose:\n  " + "\n  ".join(offenders)
    )


def test_the_documented_listener_check_targets_the_mcp_port():
    checks = [int(p) for p in _LISTENER_CHECK.findall(_GUIDE.read_text(encoding="utf-8"))]
    assert checks, (
        "the guide no longer tells the operator to confirm what is listening before exposing it"
    )
    wrong = [p for p in checks if p != mcp_http_port()]
    assert not wrong, (
        f"the pre-exposure listener check inspects {wrong} while the MCP server serves "
        f"{mcp_http_port()}; the operator would verify one port and publish another"
    )


def test_the_guide_keeps_an_executable_authenticated_route():
    text = _GUIDE.read_text(encoding="utf-8")
    executable = "\n".join(_FENCED.findall(text))
    assert re.search(
        r"(observer_mcp\.ps1[^\n]*-Action\s+http\b|run_mcp_server\.py[^\n]*--http\b)", executable
    ), "no runnable snippet in the guide starts the authenticated MCP HTTP server"
    assert "AIQA_MCP_TOKEN" in executable, (
        "no runnable snippet sets the bearer token the server refuses to start without"
    )
    assert re.search(r"https://[^\s`]*/mcp\b", text), (
        "the guide no longer shows the connector URL ending at the /mcp path"
    )


# --- the guard's own behaviour, pinned in both directions ----------------------------------------
#
# A guard that only demonstrates silence has demonstrated nothing. These use the real strings that
# produced each defect: the two that must be caught, and the four that must not raise an alarm.

_MUST_FLAG = [
    pytest.param(
        "trust and point it at `http://127.0.0.1:8765`. Get the exact command",
        8765,
        id="the-original-pre-M1-instruction",
    ),
    pytest.param(
        "Point the tunnel at the Dashboard default `8765` - never at `8770`.",
        8765,
        id="the-reviewed-bypass-never-must-not-save-it",
    ),
    pytest.param("Expose the dashboard on port 8765 for review.", 8765, id="explicit-port-N"),
    pytest.param("tunnel it to 127.0.0.1:8765 temporarily", 8765, id="tunnel-used-as-a-verb"),
]

_MUST_IGNORE = [
    pytest.param("stable tunnel ID: tunnel_6a5e77892a3c81918f20f44541d4ed65;", id="hex-tunnel-id"),
    pytest.param("Tunnel PID\t54572, started 10:00:12", id="a-process-id"),
    pytest.param(
        "The tunnel client's own local health surface is on port 8080.",
        id="descriptive-local-health-port",
    ),
    pytest.param(
        "`8765` is the operator Dashboard, and it is never the tunnel target.",
        id="a-warning-naming-the-port-with-no-imperative",
    ),
]


@pytest.mark.parametrize("line,port", _MUST_FLAG)
def test_guard_flags_real_exposure_instructions(line, port):
    assert port in exposure_targets(line), (
        f"the guard missed a real exposure instruction: {line!r}"
    )


@pytest.mark.parametrize("line", _MUST_IGNORE)
def test_guard_ignores_numbers_that_are_not_exposure_targets(line):
    assert exposure_targets(line) == [], (
        f"the guard cried wolf on text that exposes nothing: {line!r} -> {exposure_targets(line)}"
    )


def test_an_untracked_markdown_file_cannot_change_the_verdict():
    """The defect that survived review: the scan judged the working tree, not the repository."""
    intruder = _DOCS / "ZZZ_untracked_probe_delete_me.md"
    assert not intruder.exists(), "probe file already present; refusing to overwrite"
    intruder.write_text(
        "Point the tunnel at the Dashboard default `8765` - never at `8770`.\n", encoding="utf-8"
    )
    try:
        assert intruder not in tracked_docs(), (
            "an untracked markdown file reached the tracked-docs enumeration; the guard would again "
            "pass in CI and fail on a machine that merely has scratch notes in docs/"
        )
        # ...and the repository-wide check still passes with that file sitting on disk.
        test_no_exposure_imperative_targets_any_port_but_the_mcp_one()
    finally:
        intruder.unlink()
