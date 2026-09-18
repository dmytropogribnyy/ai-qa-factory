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
import typing
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

class _Counts(typing.NamedTuple):
    """The distinct quantities the documentation can claim. They are NOT interchangeable.

    Before the Issue #74 A3.5 role split there were only two (planning, observer) and `total`. The
    split introduced a third: the observer role withholds `observer_export_ai_review_bundle`, so
    "20 registered observer tools" and "19 read-only observer tools" are different facts that
    happened to be one number. A guard that knows only the registration passes
    `Observer MCP adapter (read-only, 20 tools)` — a sentence that counts a file-writing tool as
    read-only — because 20 == 20 for the wrong reason.
    """
    planning: int        # the legacy ARK planning tools
    observer: int        # observer tools REGISTERED (schemas), including the one that writes
    readonly: int        # observer tools actually PUBLISHED to the read-only role
    observer_role: int   # the whole observer role catalog (readonly observer + qa_factory_health)
    operator_role: int   # the whole operator role catalog

    @property
    def total(self) -> int:
        return self.planning + self.observer


def _registered_tool_counts() -> _Counts:
    """Every number derived from the real registration — none of them arithmetic or hardcoded."""
    from integrations.mcp.observer_handlers import OBSERVER_TOOL_NAMES
    from integrations.mcp.server import tool_names
    from integrations.mcp.tool_handlers import TOOL_NAMES
    observer_role = tool_names("observer")
    return _Counts(planning=len(TOOL_NAMES),
                   observer=len(OBSERVER_TOOL_NAMES),
                   readonly=len([n for n in observer_role if n.startswith("observer_")]),
                   observer_role=len(observer_role),
                   operator_role=len(tool_names("operator")))


def _stale_tool_counts(docs_root: pathlib.Path) -> list:
    """Every documented count in `docs_root` that disagrees with the real registration.

    Taking the root as an argument is what lets the guard be exercised on synthetic documents, so
    its strictness is demonstrated rather than asserted.
    """
    c = _registered_tool_counts()
    planning, observer, total = c.planning, c.observer, c.total
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
        # 0. "read-only" names a DIFFERENT quantity from "observer" since the role split withheld
        #    `observer_export_ai_review_bundle`. Resolving it to the registration total is exactly
        #    how a sentence that counts a writer as read-only stayed green.
        if "read-only" in after and "observer" in ctx:
            return c.readonly, "read-only Observer"
        # 1. The words between the number and "tools" are the most reliable label.
        if "observer" in after:
            return observer, "Observer"
        if "planning" in after or "legacy" in after:
            return planning, "planning"
        # 2. The words in front, stopping at the previous number so one count's label can never be
        #    borrowed by the next.
        prefix = line[:match.start()]
        cut = list(re.finditer(r"\d", prefix))
        prefix = prefix[cut[-1].end():] if cut else prefix
        # Eight words, not four: `**Observer tools exposed** — yes (20 read-only tools; ...)` puts
        # its label further from the number than a short window reaches, and a claim whose sibling
        # on the same line IS checked should not go unchecked by accident of spacing.
        before = " ".join(prefix.split()[-8:]).lower()
        # 3. A ROLE CATALOG is its own quantity. Keyed on the words immediately before the number,
        #    never on the whole line: a sentence that merely mentions
        #    `observer_export_ai_review_bundle` must not thereby read as an observer-role claim.
        if "operator role" in before:
            return c.operator_role, "operator role catalog"
        if "observer role" in before:
            return c.observer_role, "observer role catalog"
        # 4. Then an explicit total — otherwise "the 7 legacy planning tools = 27 tools total"
        #    reads the PREVIOUS count's label onto this one.
        tail = line[match.end():match.end() + 12].lower()
        breakdown = re.search(r"\d+\s+planning", ctx) and re.search(r"\d+\s+observer", ctx)
        if "total" in tail or breakdown:
            return total, "catalogue"
        if "read-only" in before and "observer" in ctx:
            return c.readonly, "read-only Observer"
        if "observer" in before:
            return observer, "Observer"
        if "planning" in before or "legacy" in before:
            return planning, "planning"
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
            # `tools=N observer=M` is a literal quotation of the smoke's own output. The smoke
            # drives the DEFAULT transport, so it prints the observer ROLE catalog, not the
            # registration total — checking it against the total is what let `tools=27 observer=20`
            # stay green after the role split withheld a tool from that transport.
            for key, expected in (("tools", c.observer_role), ("observer", c.readonly)):
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
                        f"the real {kind} count is {expected} "
                        f"(planning {planning}, observer registered {observer}, read-only observer "
                        f"{c.readonly}, observer role {c.observer_role}, operator role "
                        f"{c.operator_role})")
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
    c = _registered_tool_counts()
    planning, observer, total = c.planning, c.observer, c.total

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

    c = _registered_tool_counts()
    src = _DOCS / "CHATGPT_OBSERVER_MCP_CONNECTION.md"
    shutil.copytree(_DOCS, tmp_path / "docs")
    target = tmp_path / "docs" / src.name
    original = src.read_text(encoding="utf-8")

    # The two live wordings the guard used to miss, mutated in both directions. Both describe what
    # the REMOTE transport serves, which since the role split is the observer role catalogue and no
    # longer the registration total.
    right = c.observer_role
    shapes = ("serves the SAME observer role catalog ({n} tools)",
              "client lists the observer role catalog ({n} tools)")
    for shape in shapes:
        # A shape that no longer occurs makes `replace` a no-op and the mutation proof vacuous:
        # the document would be checked against itself and pass. That is not hypothetical - both
        # shapes silently stopped matching when this slice reworded them.
        assert shape.format(n=right) in original, (
            "the mutation fixture no longer matches the live document, so it proves nothing: "
            + shape.format(n=right))
        for wrong in (right - 1, right + 1):
            target.write_text(
                original.replace(shape.format(n=right), shape.format(n=wrong)), encoding="utf-8")
            found = _stale_tool_counts(tmp_path / "docs")
            assert any(str(wrong) in f for f in found), (
                "a wrong catalogue count went unreported for "
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
# Claims the guard deliberately leaves unadjudicated, keyed by (file, the exact sentence).
#
# This was keyed by (file, line number) and that was wrong. A line number is not the claim's
# identity: every edit ABOVE a sentence re-breaks the entry although nothing about the claim
# changed. One entry moved 98 -> 115 -> 118 -> 122 -> 124 inside a single slice and twice reddened
# CI on a sentence nobody had touched. Worse, re-pointing it at the new number is indistinguishable
# from silencing a real finding: when it finally broke on two lines at once, one of them
# ("20 tools: the read-only observer") was NOT diagnostic at all but a live, genuinely unguarded
# catalogue claim that a line bump would have buried.
#
# The sentence is the identity. It needs revisiting exactly when the sentence itself changes, which
# is exactly when re-adjudication is wanted.
_DIAGNOSTIC_CLAIMS = {
    # Both describe a BROKEN state ("old build"), not a claim about the catalogue. A guard that
    # reports a correct troubleshooting note as a defect gets the documentation edited instead.
    ("CHATGPT_OBSERVER_MCP_CONNECTION.md",
     "- `doctor` shows only 7 tools → old build; ensure "
     "`integrations/mcp/observer_handlers.py` is present."),
    ("OBSERVER_MCP_V33.md",
     "- `--list-tools` shows only 7 tools → old build; ensure `observer_handlers` is "
     "importable."),
}


class _Claim(typing.NamedTuple):
    file: str
    lineno: int
    text: str       # the matched count, e.g. "20 tools"
    sentence: str   # the whole stripped line — the claim's stable identity


def _unguarded_claims(docs_root: pathlib.Path, work: pathlib.Path) -> list:
    """Every tool-count claim in `docs_root` the guard could NOT report if it went wrong.

    Taking the corpus root as an argument is what lets the walk be exercised on synthetic
    documents, so that its discrimination is demonstrated rather than asserted.
    """
    import shutil

    claims = []
    for path in sorted(docs_root.rglob("*.md")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"(?i)mcp|observer|planning tool|list-tools|catalog", line):
                continue
            for match in re.finditer(r"\b(\d+)\s+((?:[A-Za-z][\w-]*\s+){0,4}?)tools?\b",
                                     line, re.I):
                claims.append((path, lineno, match.group(0), line.strip()))
    assert claims, "no tool-count claims found at all — the scan is broken, not the docs"

    # Copy the corpus ONCE and restore the single mutated file after each claim.
    #
    # The first version re-copied the tree every iteration, `rmtree(..., ignore_errors=True)`
    # followed by `copytree` into the same destination. On Windows that makes correctness depend on
    # deletion timing: when the removal does not complete (an open handle is enough), `rmtree`
    # swallows it and `copytree` raises `FileExistsError` on the very next iteration. It passed in a
    # worktree and on two green Windows CI runs, and failed deterministically in the canonical
    # checkout — a green gate somewhere is not evidence of a test that survives anywhere.
    shutil.copytree(docs_root, work)
    pristine = {q: q.read_bytes() for q in work.rglob("*.md")}

    unguarded = []
    for path, lineno, text, sentence in claims:
        target = work / path.relative_to(docs_root)
        original = pristine[target]
        try:
            lines = original.decode("utf-8").splitlines()
            n = int(re.match(r"(\d+)", text).group(1))
            lines[lineno - 1] = lines[lineno - 1].replace(
                text, text.replace(str(n), str(n + 5), 1), 1)
            target.write_bytes(chr(10).join(lines).encode("utf-8"))
            if not any(f"{path.name}:{lineno}" in f for f in _stale_tool_counts(work)):
                unguarded.append(_Claim(path.name, lineno, text, sentence))
        finally:
            # Exact bytes, always — a half-mutated corpus would corrupt every later claim.
            target.write_bytes(original)

    # Residue check: "restored in `finally`" is worth nothing unless it is verified.
    residue = [str(q.relative_to(work)) for q, b in pristine.items() if q.read_bytes() != b]
    assert not residue, f"the mutation walk left the copied corpus modified: {residue}"
    return unguarded


def test_every_tool_count_claim_is_either_guarded_or_explicitly_diagnostic(tmp_path):
    """Completeness, measured by mutation rather than asserted.

    Round 2 shipped a guard that validated the numbers already present and left several live claims
    unadjudicated — a repository search could report "checked" while a future partial update went
    unnoticed. This walks every tool-count sentence in `docs/`, mutates that one occurrence, and
    requires the guard to report it; anything it cannot report must be on the diagnostic list above,
    with a reason.
    """
    unguarded = _unguarded_claims(_DOCS, tmp_path / "docs")
    unexplained = [u for u in unguarded if (u.file, u.sentence) not in _DIAGNOSTIC_CLAIMS]
    assert not unexplained, (
        "these tool-count claims could be changed to a wrong number without the guard reporting "
        "it, and they are not on the diagnostic list: "
        + repr([(u.file, u.lineno, u.text) for u in unexplained]))


def test_the_diagnostic_allowlist_is_keyed_to_the_sentence_not_to_its_position(tmp_path):
    """The behavioural control for the re-keying: prove the key is the claim, not the line.

    Without this, "keyed by sentence" is a claim about the source rather than a demonstrated
    property — and a presence-of-text assertion has twice passed in this slice while the
    behaviour was broken. Three properties, each with its own failure mode:

      1. an unadjudicated claim IS reported, so the walk still exercises the guard;
      2. the SAME sentence at a DIFFERENT line yields the SAME key — what the line-number key got
         wrong, and the only reason CI went red twice on prose nobody had touched;
      3. a DIFFERENT sentence carrying the SAME number is still reported — the key is the
         sentence, not the digits, or one entry would silently excuse every claim sharing its count.
    """
    corpus = tmp_path / "src"
    (corpus / "sub").mkdir(parents=True)
    # Deliberately unadjudicable: no observer/planning/role/total label anywhere near the number.
    sentence = "The MCP bundle ships 12 tools."
    variant = "The MCP bundle ships 12 tools for review."
    (corpus / "a.md").write_bytes(("# Heading\n" + sentence + "\n").encode("utf-8"))
    (corpus / "sub" / "b.md").write_bytes(
        ("# Heading\n\n<!-- padding -->\n\n" + sentence + "\n" + variant + "\n").encode("utf-8"))

    found = _unguarded_claims(corpus, tmp_path / "work")
    by_key = {(u.file, u.sentence): u for u in found}

    # 1. both files' claims are reported, so the walk is actually exercising the guard.
    assert ("a.md", sentence) in by_key, f"unadjudicated claim not reported: {sorted(by_key)}"
    assert ("b.md", sentence) in by_key, f"unadjudicated claim not reported: {sorted(by_key)}"
    # 2. same sentence, different line numbers, identical key.
    assert by_key[("a.md", sentence)].lineno != by_key[("b.md", sentence)].lineno, \
        "the fixture no longer places the same sentence at two different lines"
    # 3. the same number in a different sentence is a DIFFERENT claim.
    assert ("b.md", variant) in by_key, "a sentence sharing the number must be reported separately"

    allowlisted = {("b.md", sentence)}
    remaining = {k for k in by_key if k not in allowlisted}
    assert ("b.md", sentence) not in remaining, "the entry did not suppress its own sentence"
    assert ("b.md", variant) in remaining, \
        "allowlisting one sentence must not excuse another that merely shares the number"
    assert ("a.md", sentence) in remaining, \
        "allowlisting a sentence in one file must not excuse the same sentence in another"


def test_every_diagnostic_allowlist_entry_still_matches_a_live_sentence():
    """A dead entry is a lie about the corpus: it records an adjudication for prose that is gone."""
    live = {(q.name, line.strip())
            for q in _DOCS.rglob("*.md")
            for line in q.read_text(encoding="utf-8").splitlines()}
    dead = [e for e in _DIAGNOSTIC_CLAIMS if e not in live]
    assert not dead, ("these diagnostic-allowlist entries no longer match any sentence in docs/ "
                      "— re-adjudicate or remove them: " + repr(dead))
