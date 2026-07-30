"""M1 — a documented remote-access procedure must never publish the operator Dashboard.

The Dashboard authenticates nothing on its read paths: ``_guard_mutation`` covers state-changing
endpoints only, so every GET is protected solely by the loopback bind. A tunnel terminates that bind
locally, so pointing one at the Dashboard's port publishes findings, evidence, contacts and client
packages to the internet with no credential in front of them.

The MCP server is the surface that *is* meant to be reachable — it refuses to start without
``AIQA_MCP_TOKEN``. These tests pin the two properties that keep the two apart:

1. the MCP HTTP server's default port is not the Dashboard's default port, so an operator who omits
   ``--port`` cannot silently land on the Dashboard's; and
2. no operator-facing document tells anyone to point a tunnel or public URL at the Dashboard's port.

Ports are read out of the source rather than hard-coded here, so the guard follows a future change
of either default instead of pinning today's numbers.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"

# Words that turn a bare address into an instruction to expose it.
_EXPOSURE = re.compile(
    r"(tunnel|public|publish|expose|ngrok|cloudflared|internet|remote)", re.IGNORECASE
)


def _default_port(path: Path, needle: str) -> int:
    """Read an argparse default port straight out of the source that defines it."""
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if needle in line and "default=" in line:
            match = re.search(r"default=(\d{2,5})", line)
            if match:
                return int(match.group(1))
    raise AssertionError(f"no default port found for {needle!r} in {path.name}")


def dashboard_port() -> int:
    return _default_port(_ROOT / "main.py", '"--port"')


def mcp_http_port() -> int:
    return _default_port(_ROOT / "tools" / "run_mcp_server.py", '"--port"')


def test_mcp_http_default_port_is_not_the_dashboard_port():
    """The tunnelled surface and the unauthenticated one must not share a default.

    They did: both defaulted to 8765, which is what made 'point your tunnel at 8765' read as
    sensible advice while actually publishing the Dashboard.
    """
    assert mcp_http_port() != dashboard_port(), (
        f"the MCP HTTP server and the Dashboard both default to port {mcp_http_port()}; "
        "an operator omitting --port cannot tell which surface a tunnel would reach"
    )


_CONTEXT = 3
# A passage that forbids something is a warning, not an instruction. The check has to tell them
# apart, because the fix for this defect necessarily prints the dangerous port in order to name it.
_PROHIBITION = re.compile(r"\bnever\b", re.IGNORECASE)


def _doc_lines_exposing(port: int):
    """Every documentation line that names the port inside an *instructional* exposure context.

    The context is a window, not the single line: the instruction that made this a real defect read
    "Publish a public HTTPS URL … (a tunnel). … point it at `http://127.0.0.1:8765`", with the word
    'tunnel' two lines above the address. A line-local check passes on that text while the operator
    still follows it to the same place.

    Known and accepted limit: a window containing "never" is treated as a warning and skipped, so
    the guard could be defeated by writing "never" beside a genuine instruction. That trade is
    deliberate — the alternative is a test that cannot distinguish the defect from its own fix, and
    a guard nobody can satisfy gets deleted. The original dangerous passage contained no "never",
    which is why it is still caught.
    """
    hits = []
    for path in sorted(_DOCS.rglob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if str(port) not in line:
                continue
            window = lines[max(0, index - _CONTEXT): index + _CONTEXT + 1]
            if any(_PROHIBITION.search(neighbour) for neighbour in window):
                continue
            if any(_EXPOSURE.search(neighbour) for neighbour in window):
                hits.append(f"{path.relative_to(_ROOT)}:{index + 1}: {line.strip()}")
    return hits


def test_no_document_tells_the_operator_to_expose_the_dashboard_port():
    """A procedure that publishes the Dashboard is a safety defect, not a documentation nit."""
    hits = _doc_lines_exposing(dashboard_port())
    assert not hits, (
        "these documentation lines put the Dashboard's port in an exposure context — the Dashboard "
        "has no authentication on read paths, so following them publishes client data:\n  "
        + "\n  ".join(hits)
    )


def test_the_remote_access_guide_still_documents_a_working_route():
    """Guard against 'fixing' the danger by deleting the capability.

    The outbound stdio tunnel is the route that actually works; the guide must keep describing it.
    """
    guide = _DOCS / "CHATGPT_OBSERVER_MCP_CONNECTION.md"
    text = guide.read_text(encoding="utf-8")
    assert "run_mcp_server.py" in text, "the guide no longer names the MCP server it connects"
    assert "AIQA_MCP_TOKEN" in text, "the guide no longer states the bearer-token requirement"


_WARNING_CANARY = "never the tunnel target"


def test_the_guide_warns_that_the_dashboard_must_not_be_tunnelled():
    """The trap is subtle enough that silence is not enough — the guide must say it outright.

    This pins one short phrase deliberately. Removing the danger by deleting the sentence that names
    it would otherwise pass every other test here, and the next operator would rediscover the trap.
    """
    guide = _DOCS / "CHATGPT_OBSERVER_MCP_CONNECTION.md"
    text = guide.read_text(encoding="utf-8")
    assert _WARNING_CANARY in text, (
        f"the remote-access guide must state in so many words that the Dashboard is "
        f"{_WARNING_CANARY!r}; a reader who only sees the safe procedure will not know why the "
        "obvious alternative is unsafe"
    )
