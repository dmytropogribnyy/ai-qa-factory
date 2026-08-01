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


def _stale_tool_counts(docs_root: pathlib.Path) -> list:
    """Every documented count in `docs_root` that disagrees with the real registration.

    Taking the root as an argument is what lets the guard be exercised on synthetic documents, so
    its strictness is demonstrated rather than asserted.
    """
    planning, observer = _registered_tool_counts()
    total = planning + observer
    stale = []

    def _classify(match, line: str):
        """Label a count from the words on BOTH sides of the number.

        Looking only after the number misread `Observer MCP adapter (read-only, 20 tools)`, whose
        label sits in front of it. And an earlier "any `--list-tools` on the line means this is the
        catalogue total" heuristic flagged a troubleshooting line — "`--list-tools` shows only 7
        tools -> old build" — which correctly describes a BROKEN state. A guard that fails on true
        sentences gets edited instead of the documentation, so an unlabelled count is left
        unadjudicated rather than guessed at.
        """
        after, ctx = match.group(2).lower(), line.lower()
        # 1. The words between the number and "tools" are the most reliable label.
        if "observer" in after:
            return observer, "Observer"
        if "planning" in after or "legacy" in after:
            return planning, "planning"
        # 2. Then an explicit total, before looking backwards — otherwise "the 7 legacy planning
        #    tools = 27 tools total" reads the PREVIOUS count's label onto this one.
        tail = line[match.end():match.end() + 12].lower()
        breakdown = re.search(r"\d+\s+planning", ctx) and re.search(r"\d+\s+observer", ctx)
        if "total" in tail or breakdown:
            return total, "catalogue"
        # 3. Only then the words in front, stopping at the previous number so one count's label can
        #    never be borrowed by the next.
        prefix = line[:match.start()]
        cut = list(re.finditer(r"\d", prefix))
        prefix = prefix[cut[-1].end():] if cut else prefix
        # Eight words, not four: `**Observer tools exposed** — yes (20 read-only tools; ...)` puts
        # its label further from the number than a short window reaches, and a claim whose sibling
        # on the same line IS checked should not go unchecked by accident of spacing.
        before = " ".join(prefix.split()[-8:]).lower()
        if "observer" in before:
            return observer, "Observer"
        if "planning" in before or "legacy" in before:
            return planning, "planning"
        if "read-only" in before and "observer" in ctx:
            return observer, "Observer"
        # 4. A sentence that says the server SERVES or LISTS N tools is claiming the whole
        #    catalogue, even without the word "total": `serves the SAME 27 tools`,
        #    `client lists 27 tools`. Classifying by "does the line mention observer" would be wrong
        #    here — line 32 contains `observer_get_project_overview` and yet claims the total.
        #
        #    The exception is a diagnostic sentence describing a BROKEN state, e.g.
        #    "`--list-tools` shows only 7 tools -> old build". That is not a catalogue claim and
        #    must stay unadjudicated, or the guard starts reporting a correct troubleshooting note
        #    as a defect.
        diagnostic = re.search(r"\bonly\b", before) and re.search(r"->|→|old build|ensure", ctx)
        if not diagnostic and re.search(r"\b(serves|lists|exposes|shows|registers|provides)\b",
                                        before):
            return total, "catalogue"
        # 5. The planning server names itself: `MCP tool list (7 tools)`, `7 MCP tools registered`,
        #    `all 7 MCP tool handlers`, `ARK MCP server (7 tools)`, `callable ... via tool_handlers`.
        #    These are the ARK/planning catalogue, and leaving them unadjudicated meant a repository
        #    search could report "checked" for the totals while seven live planning claims could go
        #    stale unnoticed.
        if not diagnostic and re.search(
                r"ark mcp server|mcp tool list|mcp tools? registered|mcp tool handlers?|"
                r"tool_handlers|mcp tool\b", ctx):
            return planning, "planning"
        return None, "unlabelled"

    for path in sorted(docs_root.rglob("*.md")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"(?i)mcp|observer|planning tool|list-tools|catalog", line):
                continue
            # `tools=N observer=M` is a literal smoke-output quotation: both halves are exact.
            for key, expected in (("tools", total), ("observer", observer)):
                for match in re.finditer(rf"\b{key}=(\d+)", line):
                    if int(match.group(1)) != expected:
                        stale.append(f"{path.name}:{lineno} quotes {key}={match.group(1)}, "
                                     f"registration is {expected}")
            # Prose counts, with ANY run of qualifying words between the number and "tools" —
            # `26 tools`, `19 read-only Observer MCP tools`, `7 legacy planning tools`. Bounding the
            # qualifier to a single optional word is what let `19 read-only Observer MCP tools` sit
            # unseen next to a corrected line that contradicted it.
            for match in re.finditer(r"\b(\d+)\s+((?:[A-Za-z][\w-]*\s+){0,4}?)tools?\b", line, re.I):
                claimed, qualifier = int(match.group(1)), match.group(2)
                expected, kind = _classify(match, line)
                if expected is not None and claimed != expected:
                    stale.append(
                        f"{path.name}:{lineno} claims {claimed} {qualifier}tools ({kind} count); "
                        f"the registration is {planning} planning + {observer} observer = {total}")
    return stale


def test_every_documented_tool_count_matches_the_real_registration():
    """Fails in EITHER direction, so it cannot rot the next time a tool is added."""
    stale = _stale_tool_counts(_DOCS)
    assert not stale, "documented tool counts disagree with the code that registers them:\n  " + \
                      "\n  ".join(stale)


def test_the_registration_is_the_source_of_truth_not_a_duplicated_constant():
    """The counts come from the real handler maps, so adding a tool moves them automatically."""
    from integrations.mcp.observer_handlers import OBSERVER_HANDLERS, OBSERVER_TOOL_NAMES
    from integrations.mcp.tool_handlers import TOOL_NAMES
    assert len(OBSERVER_TOOL_NAMES) == len(OBSERVER_HANDLERS)
    assert len(TOOL_NAMES) > 0 and len(OBSERVER_TOOL_NAMES) > 0


def test_the_catalogue_guard_rejects_a_wrong_count_in_either_direction(tmp_path):
    """The property the previous guard lacked, demonstrated on synthetic docs.

    That version accepted any of {planning, observer, total} whichever way the sentence was
    labelled, so it only ever failed on the wrong numbers already present — a future
    `7 Observer tools` would have passed it.
    """
    planning, observer = _registered_tool_counts()
    total = planning + observer

    must_fail = [
        f"{observer + 1} Observer MCP tools",              # inflated Observer count
        f"{planning} Observer MCP tools",                  # planning count wearing an Observer label
        f"{observer} legacy planning tools",               # Observer count wearing a planning label
        f"{total - 1} tools total",                        # wrong catalogue total
        f"{observer + 3} read-only Observer MCP tools",    # wrong multi-word Observer claim
    ]
    must_pass = [
        f"{observer} Observer MCP tools",
        f"{planning} legacy planning tools",
        f"{total} tools total",
        "`--list-tools` shows only 7 tools -> old build",  # a symptom, not a catalogue claim
    ]

    def _write(claim: str) -> None:
        (tmp_path / "d.md").write_text("- " + claim + " on the MCP server." + chr(10),
                                       encoding="utf-8")

    for claim in must_fail:
        _write(claim)
        assert _stale_tool_counts(tmp_path), f"the guard accepted a false claim: {claim!r}"
    for claim in must_pass:
        _write(claim)
        assert not _stale_tool_counts(tmp_path), f"the guard flagged a true claim: {claim!r}"


def test_mutating_the_real_catalogue_claims_is_caught_in_both_directions(tmp_path):
    """The reviewer's own mutation proof, kept as a standing test.

    Round 2 passed because the guard caught the wrong numbers that were already in the documents.
    That is not the same property as catching a wrong number *at all*: an independent reviewer
    copied the tree, changed only the two live catalogue claims from 27 to 26, and
    `_stale_tool_counts()` returned `[]` — `serves the SAME 27 tools` and `client lists 27 tools`
    were both reaching the classifier and coming back unlabelled.

    So the check is no longer "are today's numbers right" but "would a wrong number be reported".
    """
    import shutil

    planning, observer = _registered_tool_counts()
    total = planning + observer
    src = _DOCS / "CHATGPT_OBSERVER_MCP_CONNECTION.md"
    shutil.copytree(_DOCS, tmp_path / "docs")
    target = tmp_path / "docs" / src.name
    original = src.read_text(encoding="utf-8")

    # The two live wordings the guard used to miss, mutated in both directions.
    shapes = ("serves the SAME {n} tools", "client lists {n} tools")
    for shape in shapes:
        for wrong in (total - 1, total + 1):
            target.write_text(
                original.replace(shape.format(n=total), shape.format(n=wrong)), encoding="utf-8")
            found = _stale_tool_counts(tmp_path / "docs")
            assert any(str(wrong) in f for f in found), (
                "a wrong catalogue total went unreported for "
                + shape.format(n=wrong) + "; found=" + repr(found))

    # Unmutated, the same documents must be clean — otherwise the test above proves nothing.
    target.write_text(original, encoding="utf-8")
    assert not _stale_tool_counts(tmp_path / "docs")

    # And the diagnostic sentence must survive as a non-claim.
    (tmp_path / "docs" / "diag.md").write_text(
        "- `--list-tools` shows only 7 tools -> old build; ensure observer_handlers is importable."
        + chr(10), encoding="utf-8")
    assert not _stale_tool_counts(tmp_path / "docs"), (
        "a troubleshooting sentence describing a BROKEN state was read as a catalogue claim")


# The only tool-count sentences that may go unguarded: they describe a BROKEN state ("old build"),
# so they are not claims about the catalogue and must not be validated as if they were.
_DIAGNOSTIC_CLAIMS = {
    ("CHATGPT_OBSERVER_MCP_CONNECTION.md", 135),
    ("OBSERVER_MCP_V33.md", 98),
}


def test_every_tool_count_claim_is_either_guarded_or_explicitly_diagnostic(tmp_path):
    """Completeness, measured by mutation rather than asserted.

    Round 2 shipped a guard that validated the numbers already present and left several live claims
    unadjudicated — a repository search could report "checked" while a future partial update went
    unnoticed. This walks every tool-count sentence in `docs/`, mutates that one occurrence, and
    requires the guard to report it; anything it cannot report must be on the diagnostic list above,
    with a reason.
    """
    import shutil

    claims = []
    for path in sorted(_DOCS.rglob("*.md")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"(?i)mcp|observer|planning tool|list-tools|catalog", line):
                continue
            for match in re.finditer(r"\b(\d+)\s+((?:[A-Za-z][\w-]*\s+){0,4}?)tools?\b", line, re.I):
                claims.append((path, lineno, match.group(0)))
    assert claims, "no tool-count claims found at all — the scan is broken, not the docs"

    # Copy the corpus ONCE and restore the single mutated file after each claim.
    #
    # The first version re-copied the tree every iteration, `rmtree(..., ignore_errors=True)`
    # followed by `copytree` into the same destination. On Windows that makes correctness depend on
    # deletion timing: when the removal does not complete (an open handle is enough), `rmtree`
    # swallows it and `copytree` raises `FileExistsError` on the very next iteration. It passed in a
    # worktree and on two green Windows CI runs, and failed deterministically in the canonical
    # checkout — a green gate somewhere is not evidence of a test that survives anywhere.
    work = tmp_path / "docs"
    shutil.copytree(_DOCS, work)
    pristine = {p: p.read_bytes() for p in work.rglob("*.md")}

    unguarded = []
    for path, lineno, text in claims:
        target = work / path.relative_to(_DOCS)
        original = pristine[target]
        try:
            lines = original.decode("utf-8").splitlines()
            n = int(re.match(r"(\d+)", text).group(1))
            lines[lineno - 1] = lines[lineno - 1].replace(
                text, text.replace(str(n), str(n + 5), 1), 1)
            target.write_bytes(chr(10).join(lines).encode("utf-8"))
            if not any(f"{path.name}:{lineno}" in f for f in _stale_tool_counts(work)):
                unguarded.append((path.name, lineno, text))
        finally:
            # Exact bytes, always — a half-mutated corpus would silently corrupt every later claim.
            target.write_bytes(original)

    # Residue check: "restored in `finally`" is worth nothing unless it is verified.
    residue = [str(p.relative_to(work)) for p, b in pristine.items() if p.read_bytes() != b]
    assert not residue, f"the mutation walk left the copied corpus modified: {residue}"

    unexplained = [u for u in unguarded if (u[0], u[1]) not in _DIAGNOSTIC_CLAIMS]
    assert not unexplained, (
        "these tool-count claims could be changed to a wrong number without the guard reporting "
        "it, and they are not on the diagnostic list: " + repr(unexplained))
