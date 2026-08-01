"""M9 — what the operator is taught must match the screen the product opens.

Two start surfaces are live and they do different things:

  * **`/scout`** — manual seed scan. Public https seeds, campaign name, **Coverage**, **Scan mode**,
    a curated `.xlsx`/`.csv` import, and a **Start campaign** button.
  * **`/scout/new`** — prospect discovery. **Countries**, **Signals to look for**,
    **Maximum sites**, and a **Start Scout** button.

The audit reported that the guides describe "a start form that no longer exists". They do not — the
form exists; the defect is that nothing tells the operator which of the two surfaces is theirs, and
each guide gets at least one control wrong. Following the wrong guide starts the wrong kind of run.

These guards **render the real routes** through a live loopback dashboard and compare what is served
with what the documents claim. A regex over `dashboard.py` would have been worthless here: during
scoping I found the in-UI Help by its source line and assumed `/help`, which is a 404 — the Help is
served at `/docs`, and only fetching it revealed that. Source text is not a live surface.

The MCP catalogue guard is pinned to the real registration (`TOOL_NAMES + OBSERVER_TOOL_NAMES`) and
fails in **either** direction. Pinning "the docs say 27" would rot the moment a tool is added, which
is exactly how the 26-vs-27 gap arose.
"""
from __future__ import annotations

import pathlib
import re
import urllib.request

import pytest

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService

_DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"
_README = pathlib.Path(__file__).resolve().parents[1] / "README.md"

# The route/label contract this slice makes true. Each entry is asserted against the RENDERED page
# first, so the contract cannot drift away from the product and quietly keep passing.
_SURFACES = {
    "/scout": {
        "labels": ("Coverage", "Scan mode"),
        "button": "Start campaign",
        "purpose": "manual seed scan",
    },
    "/scout/new": {
        "labels": ("Countries", "Signals to look for", "Maximum sites"),
        "button": "Start Scout",
        "purpose": "prospect discovery",
    },
}

# Claims that name a control the product does not render anywhere.
_PHANTOM_CONTROLS = ("Run campaign",)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Serve the real dashboard once and fetch the three routes the operator is pointed at."""
    tmp = tmp_path_factory.mktemp("m9")
    server, url = start_dashboard(ScoutService(str(tmp)), operator_home=True)
    try:
        pages = {}
        for route in ("/scout", "/scout/new", "/docs"):
            with urllib.request.urlopen(url.rstrip("/") + route, timeout=10) as r:
                assert r.status == 200, f"{route} returned {r.status}"
                pages[route] = r.read().decode("utf-8", "replace")
        yield pages
    finally:
        server.shutdown()


def _doc(name: str) -> str:
    return (_DOCS / name).read_text(encoding="utf-8")


# --- the contract must describe the product, or the tests below prove nothing --------------------

def test_the_declared_contract_matches_what_the_routes_actually_render(rendered):
    """Guard on the guards. If a control is renamed, this fails before the doc assertions do."""
    for route, spec in _SURFACES.items():
        html = rendered[route]
        for label in spec["labels"]:
            assert label in html, f"{route} no longer renders {label!r} — the contract is stale"
        assert spec["button"] in html, f"{route} no longer renders a {spec['button']!r} button"


def test_no_start_surface_renders_a_control_the_docs_invent(rendered):
    """Checked on the FORM routes only.

    `/docs` is deliberately excluded: it is the Help text, and whether it *mentions* a phantom
    control is the defect under test, not evidence that the control exists. Asserting over it here
    would conflate "the Help says it" with "the product renders it".
    """
    for phantom in _PHANTOM_CONTROLS:
        for route in _SURFACES:
            assert phantom not in rendered[route], (
                f"{phantom!r} is actually rendered at {route}; the documentation claim would be "
                "true and this test is testing the wrong thing"
            )


# --- the in-UI Help is the operator's fallback when doc and screen disagree ----------------------

def test_the_in_ui_help_names_no_control_that_does_not_exist(rendered):
    help_html = rendered["/docs"]
    for phantom in _PHANTOM_CONTROLS:
        assert phantom not in help_html, (
            f"the in-UI Help tells the operator to select {phantom!r}, which no surface renders"
        )
    assert not re.search(r"countries and industries", help_html, re.I), (
        "the in-UI Help names an 'industries' field; /scout/new renders Countries and "
        "'Signals to look for', and no industries control exists"
    )


def test_the_in_ui_help_distinguishes_the_two_surfaces_by_route(rendered):
    help_html = rendered["/docs"]
    assert "/scout/new" in help_html and "/scout" in help_html, (
        "the Help does not name both routes, so 'the start form' stays ambiguous"
    )
    for spec in _SURFACES.values():
        assert spec["purpose"] in help_html.lower() or spec["purpose"].replace(" ", "&nbsp;") in help_html, (
            f"the Help never says which surface is the {spec['purpose']}"
        )


# --- the guides must each name the surface they describe -----------------------------------------

@pytest.mark.parametrize("doc_name,route", [
    ("SCOUT_OPERATOR_GUIDE.md", "/scout"),
    ("QUICKSTART_OPERATOR.md", "/scout/new"),
    ("RUNBOOK_SCOUT.md", "/scout/new"),
])
def test_each_guide_names_the_exact_route_it_describes(doc_name, route):
    text = _doc(doc_name)
    assert route in text, (
        f"{doc_name} describes a start form without naming {route}, so a new operator cannot tell "
        "which of the two surfaces it means"
    )


def test_the_quickstart_does_not_name_filters_that_do_not_exist():
    text = _doc("QUICKSTART_OPERATOR.md")
    for phantom in ("industry", "depth"):
        assert not re.search(rf"\b{phantom}\b", text, re.I), (
            f"QUICKSTART names a {phantom!r} filter; /scout/new renders Countries, "
            "'Signals to look for' and 'Maximum sites' and nothing else"
        )


def test_the_runbook_does_not_state_a_product_wide_absolute_that_one_surface_contradicts(rendered):
    """RUNBOOK is right about `/scout/new` and wrong about the product."""
    text = _doc("RUNBOOK_SCOUT.md")
    assert "Scan mode" in rendered["/scout"] and "Coverage" in rendered["/scout"], "premise stale"
    # Whitespace-tolerant on purpose: the sentence is wrapped in the source, so an exact-space
    # pattern silently passed and reported a defect as fixed while it was still there.
    assert not re.search(r"There\s+is\s+no\s+scan\s+mode,\s+coverage\s+profile", text), (
        "RUNBOOK_SCOUT states there is no scan mode or coverage profile to choose. That is true of "
        "/scout/new and false of /scout, which renders both — the docs describe one surface as "
        "though it were the only one"
    )


def test_readme_points_a_new_operator_at_a_start_surface():
    text = _README.read_text(encoding="utf-8")
    assert "/scout/new" in text or "/scout" in text, (
        "README lists the guides but never names the route the product actually opens"
    )


# --- the MCP catalogue count must be pinned to the real registration -----------------------------

def _registered_tool_counts() -> tuple[int, int]:
    from integrations.mcp.observer_handlers import OBSERVER_TOOL_NAMES
    from integrations.mcp.tool_handlers import TOOL_NAMES
    return len(TOOL_NAMES), len(OBSERVER_TOOL_NAMES)


def test_every_documented_tool_count_matches_the_real_registration():
    """Fails in EITHER direction, so it cannot rot the next time a tool is added.

    A documented count is accepted when it equals the planning count, the observer count, or their
    total — because "7 planning tools" and "20 observer tools" are both legitimate things to write.
    An earlier version of this guard compared every number against the total alone and flagged two
    correct sentences; a test that cries wolf about true statements teaches people to edit the test.
    """
    planning, observer = _registered_tool_counts()
    total = planning + observer
    legitimate = {planning, observer, total}
    stale = []
    for path in sorted(_DOCS.rglob("*.md")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"(?i)mcp|observer|planning tool|list-tools|catalog", line):
                continue
            # `tools=N observer=M` is a literal smoke-output quotation: both halves are exact.
            for key, expected in (("tools", total), ("observer", observer)):
                for match in re.finditer(rf"\b{key}=(\d+)", line):
                    if int(match.group(1)) != expected:
                        stale.append(f"{path.name}:{lineno} quotes {key}={match.group(1)}, "
                                     f"registration is {expected}")
            # Prose counts: "26 tools", "19 tools", "(read-only, 19 tools)".
            for match in re.finditer(r"\b(\d+)\s+(?:legacy\s+|planning\s+|observer\s+|read-only\s+)?tools?\b",
                                     line, re.I):
                claimed = int(match.group(1))
                if claimed not in legitimate:
                    stale.append(f"{path.name}:{lineno} claims {claimed} tools; the registration is "
                                 f"{planning} planning + {observer} observer = {total}")
    assert not stale, "documented tool counts disagree with the code that registers them:\n  " + \
                      "\n  ".join(stale)


def test_the_registration_is_the_source_of_truth_not_a_duplicated_constant():
    """The counts come from the real handler maps, so adding a tool moves them automatically."""
    from integrations.mcp.observer_handlers import OBSERVER_HANDLERS, OBSERVER_TOOL_NAMES
    from integrations.mcp.tool_handlers import TOOL_NAMES
    assert len(OBSERVER_TOOL_NAMES) == len(OBSERVER_HANDLERS)
    assert len(TOOL_NAMES) > 0 and len(OBSERVER_TOOL_NAMES) > 0
