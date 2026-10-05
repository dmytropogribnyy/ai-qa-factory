"""A4.5 foundation closure — one canonical count per fact, and roles that cannot be inherited.

Per the controller's decision (Issue #74):

* **Evidence count** comes from the canonical persisted evidence, and client-safe is its OWN field.
  The Dashboard counted ``report/*.json`` — discovery *planning* artifacts — so every completed
  discovery campaign showed the same constant whether or not one screenshot existed, while the
  Observer counted the real per-prospect artifacts. Two numbers, one label, neither disclosed.
* **Analyzed sites** are unique canonical domains in production scope, with diagnostic reported
  separately. The raw registry tally counted every entry, so the Observer overview disagreed with
  the History total *and* with its own `observer_list_targets`, both of which filter.
* **Campaign count** is the exact persisted count, never ``len()`` of a page. ``list_campaigns``
  clamps to 500, so the overview would report 500 for ever past that many campaigns and a RUNNING
  campaign past index 500 was invisible.
* **`deep="false"`** was truthy, so a STRING launched Chromium under the operator role.
* **The relay role** was selected by an environment variable — the exact pattern the main MCP
  server abandoned, and here it guards the higher privilege: `reviewer` posts the GO the worker
  treats as authorisation.
"""
from __future__ import annotations

import json

import pytest


# --- campaign count: exact persisted, never a page length ----------------------------------------

def _runcontrol(tmp_path, cid: str):
    d = tmp_path / "scout" / "_runcontrol"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cid}.json").write_text(json.dumps({"campaign_id": cid, "state": "COMPLETED"}),
                                   encoding="utf-8")


def test_campaign_count_is_the_persisted_total_not_the_page_length(tmp_path):
    """`list_campaigns(limit=1000)` is clamped to 500 inside, so `len(camps)` capped the truth."""
    from core.scout.canonical_runs import campaign_counts
    for i in range(7):
        _runcontrol(tmp_path, f"camp-{i:03d}")
    _runcontrol(tmp_path, "smoke-a")          # diagnostic by id
    counts = campaign_counts(str(tmp_path))
    assert counts["total"] == 8
    assert counts["production"] == 7 and counts["diagnostic"] == 1


def test_the_overview_reports_the_split_and_discloses_truncation(tmp_path):
    from core.scout.observer_api import ObserverAPI
    for i in range(3):
        _runcontrol(tmp_path, f"camp-{i:03d}")
    ov = ObserverAPI(str(tmp_path)).get_project_overview()
    assert ov["campaign_count"] == 3
    assert ov["campaign_counts"]["production"] == 3
    assert "campaigns_truncated" in ov, "the page/total relationship must be disclosed, not implied"
    assert ov["campaigns_truncated"] is False


# --- analyzed sites: unique canonical domains, production scope -----------------------------------

def _registry(tmp_path):
    from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
    return AnalyzedSiteRegistry(str(tmp_path))


def test_analyzed_sites_exclude_diagnostic_only_domains(tmp_path):
    reg = _registry(tmp_path)
    reg.observe("https://real.example", campaign_id="camp-001", provider="test")
    reg.observe("https://smoke-only.example", campaign_id="smoke-a", provider="test")
    production = reg.scoped_counts(production_only=True)
    diagnostic = reg.scoped_counts(production_only=False, diagnostic_only=True)
    assert production["total"] == 1, "a domain only a smoke run touched is not production scope"
    assert diagnostic["total"] == 1
    assert reg.counts()["total"] == 2, "the raw tally is unchanged and still available"


def test_a_domain_touched_by_both_counts_as_production(tmp_path):
    """A domain a real campaign analysed is production, whatever else also touched it."""
    reg = _registry(tmp_path)
    reg.observe("https://both.example", campaign_id="smoke-a", provider="test")
    reg.observe("https://both.example", campaign_id="camp-001", provider="test")
    assert reg.scoped_counts(production_only=True)["total"] == 1
    assert reg.scoped_counts(production_only=False, diagnostic_only=True)["total"] == 0


def test_analyzed_sites_are_deduplicated_by_canonical_domain(tmp_path):
    reg = _registry(tmp_path)
    reg.observe("https://dup.example/a", campaign_id="camp-001", provider="test")
    reg.observe("https://dup.example/b", campaign_id="camp-002", provider="test")
    assert reg.scoped_counts(production_only=True)["total"] == 1


# --- evidence: canonical source, client-safe as its own field -------------------------------------

def test_evidence_count_ignores_planning_artifacts_and_counts_real_evidence(tmp_path):
    """`report/*.json` is the discovery PLAN, not evidence."""
    from core.scout.evidence_counts import campaign_evidence_counts
    run = tmp_path / "scout" / "camp-1"
    (run / "report").mkdir(parents=True)
    for name in ("DISCOVERY_PLAN.json", "PROMOTED_TARGETS.json", "SUMMARY.json"):
        (run / "report" / name).write_text("{}", encoding="utf-8")
    prospect = run / "prospects" / "p1"
    prospect.mkdir(parents=True)
    (prospect / "shot.png").write_bytes(b"x")
    (prospect / "steps.json").write_text("{}", encoding="utf-8")
    # A DIRECT run: no run-control record, and a state.json carrying no candidate list.
    (tmp_path / "scout" / "camp-1" / "state.json").write_text(
        json.dumps({"run_id": "camp-1", "status": "COMPLETED"}), encoding="utf-8")

    counts = campaign_evidence_counts(str(tmp_path), "camp-1")
    assert counts["total"] == 2, "the three planning files are not evidence"
    assert counts["client_safe"] == 0, "nothing is client-safe until an index says so"


def test_client_safe_is_counted_separately_and_requires_the_items_own_proof(tmp_path):
    from core.scout.evidence_counts import campaign_evidence_counts
    run = tmp_path / "scout" / "camp-1"
    prospect = run / "prospects" / "p1"
    prospect.mkdir(parents=True)
    (prospect / "a.json").write_text("{}", encoding="utf-8")
    (prospect / "EVIDENCE_INDEX_f1.json").write_text(json.dumps({"evidence": [
        {"evidence_id": "e1", "client_safe": True, "sanitization_status": "sanitized",
         "verification_status": "VERIFIED"},
        {"evidence_id": "e2", "client_safe": True, "sanitization_status": "rejected",
         "verification_status": "VERIFIED"},          # rejected: never client-safe
        {"evidence_id": "e3", "client_safe": True, "sanitization_status": "sanitized",
         "verification_status": "UNVERIFIED"},        # unverified: never client-safe
    ]}), encoding="utf-8")
    # A DIRECT run: no run-control record, and a state.json carrying no candidate list.
    (tmp_path / "scout" / "camp-1" / "state.json").write_text(
        json.dumps({"run_id": "camp-1", "status": "COMPLETED"}), encoding="utf-8")

    counts = campaign_evidence_counts(str(tmp_path), "camp-1")
    assert counts["client_safe"] == 1, "only the sanitised AND verified item counts"
    assert counts["total"] >= 1


def test_an_unreadable_evidence_index_is_reported_not_read_as_none_client_safe(tmp_path):
    from core.scout.evidence_counts import campaign_evidence_counts
    prospect = tmp_path / "scout" / "camp-1" / "prospects" / "p1"
    prospect.mkdir(parents=True)
    (prospect / "EVIDENCE_INDEX_f1.json").write_text("{torn", encoding="utf-8")
    # A DIRECT run: no run-control record, and a state.json carrying no candidate list.
    (tmp_path / "scout" / "camp-1" / "state.json").write_text(
        json.dumps({"run_id": "camp-1", "status": "COMPLETED"}), encoding="utf-8")
    counts = campaign_evidence_counts(str(tmp_path), "camp-1")
    assert counts["unreadable_indexes"] == 1
    assert counts["client_safe"] == 0


# --- `deep` is a boolean --------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["false", "true", "0", 1, 0, [], {}])
def test_a_non_boolean_deep_is_refused_rather_than_coerced(value):
    """`bool("false")` is True, so a string launched Chromium under the operator role."""
    from integrations.mcp import server as mcp_server
    mcp_server.set_role("operator")
    try:
        out = mcp_server._call_handler("observer_get_system_readiness", {"deep": value})
        # The contract is a JSON STRING, like every other branch of this function. The first
        # version of this test accepted either a string or a TextContent list, and that
        # flexibility is exactly what let a branch returning the wrong type pass.
        assert isinstance(out, str), f"_call_handler must return a JSON string, got {type(out)}"
        payload = json.loads(out)
        assert payload["status"] == "error", f"deep={value!r} must be refused, not coerced"
        assert "boolean" in payload["message"]
    finally:
        mcp_server.set_role(None)


def test_a_real_boolean_deep_is_still_accepted_by_the_operator_role():
    """Control: the strictness must not break the legitimate call."""
    from integrations.mcp import server as mcp_server
    mcp_server.set_role("operator")
    try:
        out = mcp_server._call_handler("observer_get_system_readiness", {"deep": False})
        assert isinstance(out, str), f"_call_handler must return a JSON string, got {type(out)}"
        assert json.loads(out).get("status") != "error"
    finally:
        mcp_server.set_role(None)


# --- the relay role cannot be inherited -----------------------------------------------------------

def test_an_inherited_environment_cannot_grant_the_relay_reviewer_role(monkeypatch):
    """`reviewer` posts the GO the worker treats as authorisation - it must be declared, not inherited."""
    from integrations.mcp import review_relay_server as relay
    relay.set_relay_role(None)
    monkeypatch.setenv("AIQA_REVIEW_RELAY_ROLE", "reviewer")
    with pytest.raises(RuntimeError, match="cannot be granted"):
        relay.relay_role()


def test_the_environment_may_still_select_the_lower_privilege_worker_role(monkeypatch):
    """Ambient configuration may restrict, never widen - existing worker config keeps working."""
    from integrations.mcp import review_relay_server as relay
    relay.set_relay_role(None)
    monkeypatch.setenv("AIQA_REVIEW_RELAY_ROLE", "worker")
    assert relay.relay_role() == "worker"


def test_an_explicit_declaration_grants_the_reviewer_role(monkeypatch):
    from integrations.mcp import review_relay_server as relay
    monkeypatch.delenv("AIQA_REVIEW_RELAY_ROLE", raising=False)
    try:
        relay.set_relay_role("reviewer")
        assert relay.relay_role() == "reviewer"
    finally:
        relay.set_relay_role(None)


def test_no_role_at_all_refuses_rather_than_defaulting(monkeypatch):
    from integrations.mcp import review_relay_server as relay
    relay.set_relay_role(None)
    monkeypatch.delenv("AIQA_REVIEW_RELAY_ROLE", raising=False)
    with pytest.raises(RuntimeError):
        relay.relay_role()


# --- the delivery tool grant is not a security boundary, and must not be described as one ---------

def test_the_session_delivery_tool_grant_is_not_described_as_a_restriction():
    """`--allowedTools` ADDS permitted tools; it does not narrow the built-in set.

    Per the controller: the operator's `bypassPermissions` setting is theirs to keep, but the system
    must not treat this flag as a security boundary when it does not restrict anything. Either the
    launch uses a genuinely restrictive flag, or the comment says plainly that it is not a sandbox.
    """
    import inspect

    from core.collaboration import session_delivery
    src = inspect.getsource(session_delivery)
    if "--allowedTools" not in src:
        pytest.skip("the tool grant was removed entirely")
    window = src[max(0, src.index("--allowedTools") - 1200):src.index("--allowedTools") + 1200]
    restrictive = ("--disallowedTools" in window or "--restricted" in window
                   or '"--tools"' in window)
    disclaimed = "not a security boundary" in window.lower()
    assert restrictive or disclaimed, (
        "`--allowedTools` only ADDS tools. Either restrict the grant with --tools/--disallowedTools/"
        "--restricted, or state at the call site that this is not a security boundary - describing "
        "it as 'the narrowest possible grant' claims a bound it does not provide")


# --- no consumer may launch the relay REVIEWER through the environment ---------------------------

def _repo_root():
    import pathlib
    return pathlib.Path(__file__).resolve().parents[1]


def _is_prose_or_negative_control(line: str) -> bool:
    """Distinguish a LAUNCH from an assertion that the launch is refused, or from prose about it.

    Naming the forbidden shape is how both the CI negative control and the runbook explain the rule,
    so a scan that matched the string alone reported the very text documenting the fix. The answer is
    not to weaken the scan or to reword around it - a guard that cannot tell a launch from a refusal
    check is measuring the wrong thing.
    """
    stripped = line.strip()
    if stripped.startswith("#"):                       # a comment explaining the rule
        return True
    if "cannot be granted" in line or "refus" in line.lower():
        return True                                    # an assertion that the grant is refused
    return False


def test_no_consumer_launches_the_relay_reviewer_through_the_environment():
    """The sibling sweep this slice first got wrong.

    The server was changed so an inherited `AIQA_REVIEW_RELAY_ROLE=reviewer` can no longer grant the
    higher-privilege role — and the CI workflow and the runbook were left starting the reviewer that
    exact way. The code was right and its consumers were not, which is how a green local suite sat
    beside a red `relay-smoke`.

    `worker` through the environment is still legitimate (ambient config may restrict, never widen),
    so only the reviewer grant is forbidden here.
    """
    import re
    root = _repo_root()
    targets = [p for p in (list((root / ".github").rglob("*.yml"))
                           + list((root / ".github").rglob("*.yaml"))
                           + list((root / "docs").rglob("*.md"))
                           + list(root.glob("*.md"))
                           + list((root / "tools").glob("*.ps1")))
               if p.is_file()]
    assert targets, "the scan found no consumer files at all — it is broken, not the repo"

    offenders = []
    pattern = re.compile(r"AIQA_REVIEW_RELAY_ROLE\s*[=:]\s*[\"']?reviewer", re.I)
    for path in targets:
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not pattern.search(line):
                continue
            if _is_prose_or_negative_control(line):
                continue
            offenders.append(f"{path.relative_to(root).as_posix()}:{lineno}")
    assert not offenders, (
        "these launch the relay reviewer via the environment, which the server now refuses; "
        "pass `--role reviewer` explicitly instead: " + repr(offenders))


def test_the_consumer_scan_would_catch_a_reintroduced_env_reviewer(tmp_path):
    """Control: the scan must actually match the shapes consumers use."""
    import re
    pattern = re.compile(r"AIQA_REVIEW_RELAY_ROLE\s*[=:]\s*[\"']?reviewer", re.I)
    for shape in ('export AIQA_REVIEW_RELAY_ROLE=reviewer',
                  '$env:AIQA_REVIEW_RELAY_ROLE = "reviewer"',
                  '  AIQA_REVIEW_RELAY_ROLE: reviewer',
                  'AIQA_REVIEW_RELAY_ROLE=reviewer python tools/run_review_relay_mcp.py'):
        assert pattern.search(shape), f"the scan would miss {shape!r}"
    assert not pattern.search('AIQA_REVIEW_RELAY_ROLE=worker python x.py'), \
        "worker via the environment is still allowed and must not be reported"


def test_the_consumer_scan_still_flags_a_real_launch_after_the_prose_exemption():
    """The exemption must not hollow out the guard: a real launch line is still an offender."""
    launches = [
        'export AIQA_REVIEW_RELAY_ROLE=reviewer AIQA_RELAY_MCP_TOKEN=t',
        '$env:AIQA_REVIEW_RELAY_ROLE = "reviewer"',
        '  AIQA_REVIEW_RELAY_ROLE: reviewer',
        'AIQA_REVIEW_RELAY_ROLE=reviewer python tools/run_review_relay_mcp.py --http',
    ]
    for line in launches:
        assert not _is_prose_or_negative_control(line), f"a real launch was exempted: {line!r}"

    exempt = [
        '# an inherited AIQA_REVIEW_RELAY_ROLE=reviewer would grant the higher role',
        'AIQA_REVIEW_RELAY_ROLE=reviewer python x.py 2>&1 | grep -q "cannot be granted"',
    ]
    for line in exempt:
        assert _is_prose_or_negative_control(line), f"a control/prose line was flagged: {line!r}"
