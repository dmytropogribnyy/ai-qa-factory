"""/target 'Problems found' rendering — confidence label + one-line repro hint, ordered by
qa_value_score desc, HTML-escaped and newline-collapsed, with a neutral placeholder for absent
fields (never invented).

The tests exercise the REAL ``ScoutFinding`` field shapes (via ``ScoutFinding(...).to_dict()``) and
include a page-path wiring test proving that ``target_detail`` actually carries the new projection
AND ``_scout_target_page`` actually renders the new table helper end-to-end over loopback HTTP.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from core.scout.campaign_service import _project_target_finding
from core.scout.dashboard import (
    _HINT_MAX,
    _clip,
    _confidence_label,
    _finding_qa_value,
    _norm_steps,
    _problems_table_html,
    _repro_hint,
    start_dashboard,
)
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.findings import ScoutFinding
from core.scout.service import ScoutService
from core.scout.store import RunStore

_HEADERS = ("Severity", "Confidence", "Type", "Issue", "Business impact", "Repro hint", "Evidence")
_NEUTRAL = "—"  # em dash placeholder


def _finding(**kw):
    """A real ScoutFinding projected to the read-model dict the page consumes."""
    f = ScoutFinding(**kw)
    return _project_target_finding(f.to_dict())


# --------------------------------------------------------------------------------------------------
# ordering
# --------------------------------------------------------------------------------------------------
def test_rows_ordered_by_qa_value_desc():
    """A high/medium/low mix (plus an evidence bonus) renders highest qa_value first, regardless of
    input order."""
    low = _finding(title="low issue", severity="low", confidence="low")
    high = _finding(title="high issue", severity="high", confidence="high",
                    evidence_refs=["scout/x/a.png"])  # 40 + 10 evidence bonus = 50
    medium = _finding(title="medium issue", severity="medium", confidence="medium")
    html = _problems_table_html([low, high, medium])   # deliberately unsorted input
    assert html.index("high issue") < html.index("medium issue") < html.index("low issue")
    # the scorer really is the ordering key
    assert _finding_qa_value(high) > _finding_qa_value(medium) > _finding_qa_value(low)


def test_equal_score_keeps_input_order_stable():
    """Two findings with the SAME qa_value keep their input order (stable sort — no reshuffle)."""
    a = _finding(title="alpha gap", severity="medium", confidence="medium")
    b = _finding(title="bravo gap", severity="medium", confidence="high")
    assert _finding_qa_value(a) == _finding_qa_value(b)
    html = _problems_table_html([a, b])
    assert html.index("alpha gap") < html.index("bravo gap")


# --------------------------------------------------------------------------------------------------
# rendering — confidence label + one-line repro hint
# --------------------------------------------------------------------------------------------------
def test_renders_confidence_label_and_first_step_hint():
    f = _finding(title="Broken checkout", severity="high", confidence="high",
                 reproduction_steps=["Open /cart", "Click Pay", "Observe 500"])
    html = _problems_table_html([f])
    for h in _HEADERS:
        assert f"<th>{h}</th>" in html
    assert "high" in html                              # confidence label cell
    assert "Open /cart" in html                        # one-line hint = first concrete step
    # multi-step finding preserves the full path as an escaped hover title (bounded cell)
    assert 'title="Open /cart → Click Pay → Observe 500"' in html


def test_repro_hint_helper_is_first_nonempty_step():
    f = _finding(title="t", reproduction_steps=["", "  ", "real step", "later"])
    assert _repro_hint(f) == "real step"
    assert _confidence_label(_finding(title="t", confidence="medium")) == "medium"


# --------------------------------------------------------------------------------------------------
# HTML-escaping + newline-collapsing (cell-specific)
# --------------------------------------------------------------------------------------------------
def test_malicious_title_and_repro_step_are_escaped():
    """A <script> in the title AND in a reproduction step must be escaped, not emitted raw."""
    f = _finding(title="<script>alert('t')</script>", severity="high", confidence="high",
                 reproduction_steps=["<script>alert('repro')</script>"])
    html = _problems_table_html([f])
    assert "<script>" not in html
    assert "&lt;script&gt;alert(&#39;t&#39;)&lt;/script&gt;" not in html  # sanity: quotes differ
    assert "&lt;script&gt;" in html                    # both title + step land escaped


def test_legacy_confidence_value_is_escaped():
    """A legacy/projected dict may carry an arbitrary confidence string (ScoutFinding validation is
    bypassed on rehydration); it must be escaped, never emitted as raw markup."""
    legacy = {"title": "legacy", "severity": "low",
              "confidence": '<b>"high"</b>', "reproduction_steps": []}
    html = _problems_table_html([legacy])
    assert "<b>" not in html
    assert "&lt;b&gt;&quot;high&quot;&lt;/b&gt;" in html


def test_newline_in_step_is_collapsed_to_one_line():
    """A multi-line reproduction step renders on a single line in its cell (no raw newline in the
    dynamic value)."""
    f = _finding(title="t", reproduction_steps=["line one\nline two\tline three"])
    # cell-specific: the collapsed value is present and the un-collapsed form is not
    assert _repro_hint(f) == "line one line two line three"
    html = _problems_table_html([f])
    assert "line one line two line three" in html
    assert "line one\nline two" not in html


def test_clip_bounds_a_long_value_with_ellipsis():
    assert _clip("short") == "short"
    long = "x" * (_HINT_MAX + 50)
    clipped = _clip(long)
    assert len(clipped) <= _HINT_MAX and clipped.endswith("…")
    assert _clip(None) == ""


def test_long_repro_step_is_clipped_in_cell_with_full_title():
    """A single over-long step is bounded in the cell (ellipsis) while the full step stays available
    as an escaped hover title."""
    step = "Navigate to the extremely long checkout URL " + ("path/" * 60) + "and observe the error"
    f = _finding(title="t", severity="high", confidence="high", reproduction_steps=[step])
    html = _problems_table_html([f])
    assert "…" in html                                 # cell is visibly bounded
    assert f'title="{step}"' in html                   # full (unclipped) step preserved on hover
    assert _repro_hint(f) == step                       # the logical hint is still the full step


def test_scalar_legacy_reproduction_steps_not_char_joined():
    """A scalar (non-list) legacy reproduction_steps is treated as ONE step, never iterated
    character-by-character."""
    assert _norm_steps("just one string") == ["just one string"]
    assert _norm_steps(None) == []
    assert _norm_steps(["", "  ", "\n"]) == []
    legacy = {"title": "t", "severity": "low", "reproduction_steps": "single legacy step"}
    assert _repro_hint(legacy) == "single legacy step"


# --------------------------------------------------------------------------------------------------
# absent fields → neutral placeholder (never invented)
# --------------------------------------------------------------------------------------------------
def test_absent_confidence_and_repro_use_neutral_placeholder():
    """Missing / None / empty confidence and reproduction_steps render the neutral placeholder and
    never fabricate a value."""
    # severity="info" so the Severity cell text never collides with the confidence words below
    missing = {"title": "no meta", "severity": "info"}         # keys absent entirely
    empty = {"title": "empty meta", "severity": "info",
             "confidence": "", "reproduction_steps": []}
    none_ = {"title": "none meta", "severity": "info",
             "confidence": None, "reproduction_steps": None}
    for f in (missing, empty, none_):
        assert _confidence_label(f) == _NEUTRAL
        assert _repro_hint(f) == _NEUTRAL
    html = _problems_table_html([missing, empty, none_])
    assert html.count(_NEUTRAL) >= 6                            # ≥2 placeholders (conf+repro) × 3 rows
    # no invented confidence words leaked in for the absent rows
    assert "medium" not in html and "high" not in html and "low" not in html


def test_empty_findings_render_empty_state():
    html = _problems_table_html([])
    assert "No verified problem items" in html
    assert "<table" not in html


# --------------------------------------------------------------------------------------------------
# projection carries the new fields (read-model wiring)
# --------------------------------------------------------------------------------------------------
def test_projection_carries_confidence_and_reproduction_steps():
    f = ScoutFinding(title="t", severity="high", confidence="high",
                     reproduction_steps=["a", "b"], evidence_refs=["scout/x/a.png"])
    proj = _project_target_finding(f.to_dict())
    assert proj["confidence"] == "high"
    assert proj["reproduction_steps"] == ["a", "b"]
    # still whitelisted — no leakage of unrelated fields
    assert "verification_state" not in proj and "signature" not in proj


# --------------------------------------------------------------------------------------------------
# page-path wiring — target_detail projection + _scout_target_page render, end-to-end over HTTP
# --------------------------------------------------------------------------------------------------
def _seed_target(out: str, domain: str, finding: ScoutFinding):
    """Seed a registry entry + brain decision + a run store with one verified finding so a real
    ``target_detail(domain)`` returns it (and the page renders it)."""
    AnalyzedSiteRegistry(out).record_analysis(domain, evidence_ref=f"scout/{domain}/qa")
    run_id = "campaignrun-target-1"
    camp_dir = __import__("pathlib").Path(out) / "scout" / "_campaigns" / "camp1"
    camp_dir.mkdir(parents=True, exist_ok=True)
    (camp_dir / "BRAIN_DECISIONS.json").write_text(
        json.dumps({"decisions": [{"domain": domain, "scout_run": run_id}]}), encoding="utf-8")
    st = RunStore(out, run_id)
    pid = "p1"
    st.save_state({"prospects": {pid: {"domain": domain}}})
    st.save_prospect_artifact(pid, "findings.json", {"verified": [finding.to_dict()]})
    return run_id


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_target_page_renders_confidence_and_repro_end_to_end(tmp_path):
    """Real page path: seeding a run store makes GET /scout/target?domain=... exercise the true
    target_detail projection AND the new _problems_table_html render (catches missed wiring)."""
    out = str(tmp_path)
    domain = "acme.com"
    finding = ScoutFinding(title="Checkout returns 500", severity="high", confidence="high",
                           business_impact="Lost sales", evidence_refs=[f"scout/{domain}/a.png"],
                           reproduction_steps=["Open /cart", "Click Pay", "Observe 500 error"])
    _seed_target(out, domain, finding)
    server, url = start_dashboard(ScoutService(out), operator_home=True)
    try:
        status, html = _get(url + "/scout/target?domain=" + domain)
        assert status == 200
        # new columns are wired into the page
        assert "<th>Confidence</th>" in html and "<th>Repro hint</th>" in html
        # projected confidence + one-line repro hint reached the rendered page
        assert "high" in html
        assert "Open /cart" in html
        assert "Checkout returns 500" in html
    finally:
        server.shutdown()
