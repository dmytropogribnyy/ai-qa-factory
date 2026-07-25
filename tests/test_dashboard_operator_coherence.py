"""Operator-facing coherence regressions for the Dashboard (Overview / Work).

Every defect pinned here was found by driving the real Dashboard in Chromium against seeded
operator data. They share one root cause family: the same operator question was answered by two
different code paths, so the two answers disagreed on screen.

Covered:
  * a count on Overview must equal what its own destination view shows;
  * intake questions stop blocking once the operator has approved the plan;
  * "Blockers" means one thing (execution blockers); intake questions are shown as their own,
    separately labelled thing;
  * the list and the detail of one project must state the SAME next action;
  * no raw lifecycle enum or internal health token is rendered to the operator;
  * the project-name pattern must be a regex the browser can actually compile.
"""
from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from core.dashboard.actions import ProjectDetailBuilder
from core.dashboard.read_model import DashboardReadModel
from core.orchestration.project_index import ProjectIndex
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService

_RAW_ENUMS = ("RECEIVED", "INTAKE_COMPLETE", "PLANNED", "WAITING_FOR_INFORMATION",
              "WAITING_FOR_APPROVAL", "READY_TO_EXECUTE", "EXECUTING", "EXECUTION_PARTIAL",
              "VERIFYING", "REPAIR_REQUIRED", "READY_FOR_REVIEW", "READY_FOR_DELIVERY",
              "DELIVERY_PREPARED")


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def _json(url: str) -> dict:
    return json.loads(_get(url))


def _seed(root: Path, pid: str, *, status: str, missing=(), title: str = "") -> None:
    ark = root / pid / "40_ark_work"
    ark.mkdir(parents=True, exist_ok=True)
    (ark / "WORK_PACKET.json").write_text(json.dumps({
        "title": title or f"Client project {pid}", "created_at": "2026-07-24T10:00:00Z",
        "source_platform": "upwork", "missing_information": list(missing)}), encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text(json.dumps({
        "status": status, "updated_at": "2026-07-24T10:05:00Z", "history": []}), encoding="utf-8")
    (ark / "FEASIBILITY_REPORT.json").write_text(json.dumps({
        "verdict": "RECOMMENDED_TO_TAKE", "client_intent": "do the work"}), encoding="utf-8")


def _stand(tmp_path: Path):
    """A project in every lifecycle band that the operator can reach from Overview."""
    _seed(tmp_path, "awaiting", status="WAITING_FOR_INFORMATION",
          missing=["API base URL"])
    _seed(tmp_path, "approved", status="READY_TO_EXECUTE",
          missing=["API base URL"])          # the SAME intake question, but already approved
    _seed(tmp_path, "prepared", status="DELIVERY_PREPARED", missing=["API base URL"])
    _seed(tmp_path, "done", status="COMPLETED")
    return ScoutService(str(tmp_path))


# --- 1. every Overview count equals what its destination shows ----------------------------------

def test_overview_counts_match_the_view_they_link_to(tmp_path):
    service = _stand(tmp_path)
    server, url = start_dashboard(service, operator_home=True)
    try:
        counts = _json(url + "/api/overview")["counts"]
        needs = _json(url + "/api/work?view=needs_attention")["total"]
        openw = _json(url + "/api/work?view=active")["total"]
    finally:
        server.shutdown()
    assert counts["attention"] == needs, (
        f'Overview says {counts["attention"]} need attention but /work?view=needs_attention '
        f"lists {needs}")
    assert counts["open_work"] == openw, (
        f'Overview says {counts["open_work"]} open but /work?view=active lists {openw}')


def _seed_failed_campaign(root: Path, campaign_id: str, name: str) -> None:
    """A production Scout campaign that ended FAILED (not a diagnostic run)."""
    control = root / "scout" / "_runcontrol"
    control.mkdir(parents=True, exist_ok=True)
    (control / f"{campaign_id}.json").write_text(
        json.dumps({"campaign_id": campaign_id, "state": "failed"}), encoding="utf-8")
    base = root / "scout" / campaign_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.json").write_text(json.dumps({"campaign_name": name}), encoding="utf-8")
    (base / "state.json").write_text(json.dumps({
        "campaign_id": campaign_id, "status": "FAILED",
        "started_at": "2026-07-24T10:00:00Z"}), encoding="utf-8")


def test_failed_scout_campaign_does_not_inflate_the_work_attention_tile(tmp_path):
    """The "Needs attention" tile links to /work?view=needs_attention, which only ever contains
    client work. Counting a failed Scout campaign into that same number made the tile promise more
    rows than its own destination can show.
    """
    _seed(tmp_path, "awaiting", status="WAITING_FOR_INFORMATION", missing=["API base URL"])
    _seed_failed_campaign(tmp_path, "campaign-acme-20260724t090000z-0f9d21", "Acme discovery")
    service = ScoutService(str(tmp_path))
    server, url = start_dashboard(service, operator_home=True)
    try:
        overview = _json(url + "/api/overview")
        listed = _json(url + "/api/work?view=needs_attention")
        html = _get(url + "/")
    finally:
        server.shutdown()
    assert overview["counts"]["attention"] == listed["total"] == 1, (
        f'tile says {overview["counts"]["attention"]}, /work?view=needs_attention lists '
        f'{listed["total"]}')
    assert {a["project_id"] for a in overview["attention"]} == {"awaiting"}
    # The failed campaign must stay visible - counted and linked on its own terms, never hidden.
    assert overview["counts"]["scout_attention"] == 1
    scout_items = overview["scout_attention"]
    assert [s["project_id"] for s in scout_items] == ["campaign-acme-20260724t090000z-0f9d21"]
    assert all(s["href"] == "/scout/campaigns" for s in scout_items)
    body = html.split("<main>", 1)[-1]
    assert "Acme discovery" in body, "the failed campaign is not shown to the operator"
    assert 'href="/scout/campaigns"' in body


def test_every_overview_tile_that_links_to_work_matches_that_view(tmp_path):
    """Generic guard: whatever tiles Overview grows, a tile pointing at a /work view must show that
    view's row count. This catches the next variant of the defect without enumerating tiles.
    """
    _stand(tmp_path)
    _seed_failed_campaign(tmp_path, "campaign-acme-20260724t090000z-0f9d21", "Acme discovery")
    service = ScoutService(str(tmp_path))
    server, url = start_dashboard(service, operator_home=True)
    try:
        html = _get(url + "/")
        tiles = re.findall(
            r'<a class="summary-item" href="(/work\?view=[a-z_]+)">.*?'
            r'<span class="muted">([^<]+)</span>\s*<strong>(\d+)</strong>', html, re.S)
        assert tiles, "Overview should still offer work tiles"
        totals = {href: _json(url + href.replace("/work?", "/api/work?"))["total"]
                  for href, _, _ in tiles}
    finally:
        server.shutdown()
    for href, label, shown in tiles:
        assert int(shown) == totals[href], (
            f'tile "{label.strip()}" shows {shown} but {href} lists {totals[href]}')


def test_overview_attention_list_is_the_needs_attention_view(tmp_path):
    """The cards under "Needs your attention" are the same projects the count promises."""
    service = _stand(tmp_path)
    server, url = start_dashboard(service, operator_home=True)
    try:
        overview = _json(url + "/api/overview")
        listed = _json(url + "/api/work?view=needs_attention")
    finally:
        server.shutdown()
    assert ({a["project_id"] for a in overview["attention"]}
            == {p["project_id"] for p in listed["projects"]})


# --- 2. intake questions stop blocking after approval -------------------------------------------

def test_approved_project_is_not_reported_as_blocked_by_intake_questions(tmp_path):
    _stand(tmp_path)
    entries = {p.project_id: p for p in ProjectIndex(str(tmp_path)).list_projects()}
    approved = entries["approved"]
    assert approved.blockers == [], (
        "a project the operator already approved must not still claim blocking information is "
        f"missing (got {approved.blockers})")
    assert "answer the client questions" not in approved.operator_next_action
    # The question itself is not lost - it stays available as intake context.
    assert approved.missing_information == ["API base URL"]
    # Still awaiting the client => still blocking.
    assert entries["awaiting"].blockers == ["API base URL"]


def test_prepared_delivery_reason_is_the_delivery_action_not_a_stale_intake_question(tmp_path):
    service = _stand(tmp_path)
    model = DashboardReadModel(str(tmp_path))
    prepared = [a for a in model.overview().attention if a["project_id"] == "prepared"]
    assert prepared, "a prepared delivery still needs the operator to send it"
    assert "API base URL" not in prepared[0]["reason"]
    assert "send" in prepared[0]["reason"].lower()
    del service


def test_every_lifecycle_state_has_an_operator_next_action(tmp_path):
    """No state may fall through to a generic placeholder, and no post-approval state may tell the
    operator to approve a plan they already approved."""
    for status in _RAW_ENUMS + ("BLOCKED", "FAILED", "CANCELLED", "COMPLETED"):
        root = tmp_path / status.lower()
        _seed(root, "p", status=status)
        entry = ProjectIndex(str(root)).list_projects()[0]
        action = entry.operator_next_action
        assert action and "review the project state" != action, f"{status} has no real next action"
        if status in ("READY_TO_EXECUTE", "EXECUTING", "EXECUTION_PARTIAL", "VERIFYING",
                      "READY_FOR_REVIEW", "READY_FOR_DELIVERY", "DELIVERY_PREPARED", "COMPLETED"):
            assert "approve the plan" not in action, (
                f"{status} is past approval but still asks the operator to approve the plan")


# --- 3. list and detail agree ------------------------------------------------------------------

def test_list_and_detail_state_the_same_next_action(tmp_path):
    _stand(tmp_path)
    index = {p.project_id: p for p in ProjectIndex(str(tmp_path)).list_projects()}
    builder = ProjectDetailBuilder(str(tmp_path))
    for pid in ("awaiting", "approved", "prepared"):
        detail = builder.detail(pid)
        assert detail["summary"]["next_action"] == index[pid].operator_next_action, (
            f"{pid}: Work list and Work detail disagree on the next action")


def test_detail_separates_execution_blockers_from_intake_questions(tmp_path):
    _stand(tmp_path)
    detail = ProjectDetailBuilder(str(tmp_path)).detail("awaiting")
    assert detail["summary"]["blockers"] == [], "no execution blocker was recorded"
    assert detail["summary"]["missing_information"] == ["API base URL"], (
        "the detail page must show the intake question the Work list counts")


# --- 4. no internal vocabulary reaches the operator ---------------------------------------------

def test_operator_pages_never_render_raw_lifecycle_enums(tmp_path):
    service = _stand(tmp_path)
    server, url = start_dashboard(service, operator_home=True)
    try:
        pages = {p: _get(url + p) for p in
                 ("/", "/work", "/work/awaiting", "/work/approved", "/work/prepared")}
    finally:
        server.shutdown()
    for path, html in pages.items():
        body = html.split("<main>", 1)[-1]
        for enum in _RAW_ENUMS:
            assert f">{enum}<" not in body, f"{path} renders the raw lifecycle enum {enum}"


def test_health_is_rendered_as_operator_language_not_an_internal_token(tmp_path):
    service = _stand(tmp_path)
    server, url = start_dashboard(service, operator_home=True)
    try:
        html = _get(url + "/work?view=all")
    finally:
        server.shutdown()
    body = html.split("<main>", 1)[-1]
    assert ">attention<" not in body, "the Health column leaks the internal bucket name"
    assert ">ok<" not in body
    assert "Needs attention" in body or "On track" in body


# --- 5. the promised client-side validation must actually run -----------------------------------

def test_project_name_pattern_compiles_in_a_modern_browser(tmp_path):
    """`pattern` is compiled with the RegExp `v` flag; an unescaped `-` makes it throw, which
    silently disables the validation the field advertises."""
    service = _stand(tmp_path)
    server, url = start_dashboard(service, operator_home=True)
    try:
        html = _get(url + "/work")
    finally:
        server.shutdown()
    patterns = re.findall(r'pattern="([^"]+)"', html)
    assert patterns, "the project-name field should still constrain input"
    for pattern in patterns:
        inner = re.findall(r"\[([^\]]*)\]", pattern)
        for cls in inner:
            trailing = re.search(r"(?<!\\)-\s*$", cls)
            assert not trailing, (
                f"character class [{cls}] ends with an unescaped '-': the browser refuses to "
                "compile this pattern under the v flag, so the field is silently unvalidated")


# --- 6. inline handlers must survive HTML attribute parsing -------------------------------------

def test_inline_click_handlers_are_not_truncated_by_the_attribute_quoting(tmp_path):
    """A handler built with json.dumps() contains double quotes. Emitted into a double-quoted
    onclick attribute unescaped, the attribute ends at the first quote and the handler is cut to
    `qaConfirm(` - every confirm-guarded action becomes a button that silently does nothing.
    """
    _seed(tmp_path, "prepared", status="DELIVERY_PREPARED")
    service = ScoutService(str(tmp_path))
    server, url = start_dashboard(service, operator_home=True)
    try:
        html = _get(url + "/work/prepared")
    finally:
        server.shutdown()
    handlers = re.findall(r'onclick="([^"]*)"', html)
    assert handlers, "the detail page should still offer lifecycle actions"
    guarded = [h for h in handlers if "qaConfirm" in h]
    assert guarded, "a DELIVERY_PREPARED project must offer confirm-guarded actions"
    for handler in guarded:
        assert handler.count("(") == handler.count(")"), (
            f"onclick handler is truncated (unbalanced brackets): {handler!r}")
        assert "wact(" in handler, (
            f"the confirmed action never reaches the guarded endpoint: {handler!r}")


# --- 7. structure an operator can navigate by keyboard / screen reader --------------------------

class _FieldNameAudit(HTMLParser):
    """Collect form controls that no assistive technology could name.

    A control is named by an explicit ``<label for>``, an aria-label/labelledby, or by being
    wrapped in a ``<label>`` (implicit labelling) - all three count.
    """

    def __init__(self) -> None:
        super().__init__()
        self.label_depth = 0
        self.label_targets: set = set()
        self.unnamed: list = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.label_targets.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            if a.get("type") == "hidden":
                return
            named = bool(a.get("aria-label") or a.get("aria-labelledby") or self.label_depth)
            self.unnamed.append((a.get("id") or a.get("name") or tag, named, a.get("id") or ""))

    def handle_endtag(self, tag):
        if tag == "label" and self.label_depth:
            self.label_depth -= 1

    def missing(self):
        return [ident for ident, named, fid in self.unnamed
                if not named and fid not in self.label_targets]


def test_every_visible_field_has_an_accessible_name(tmp_path):
    service = _stand(tmp_path)
    server, url = start_dashboard(service, operator_home=True)
    try:
        pages = {p: _get(url + p) for p in
                 ("/work", "/scout/new", "/scout/history", "/settings")}
    finally:
        server.shutdown()
    for path, html in pages.items():
        audit = _FieldNameAudit()
        audit.feed(html)
        assert not audit.missing(), f"{path}: fields with no accessible name: {audit.missing()}"


def test_work_list_does_not_skip_a_heading_level(tmp_path):
    """h1 -> h3 leaves screen-reader users without a way to reach the results region."""
    _stand(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        body = _get(url + "/work?view=all").split("<main>", 1)[-1]
    finally:
        server.shutdown()
    levels = [int(m) for m in re.findall(r"<h([1-4])[ >]", body)]
    previous = 0
    for level in levels:
        assert not (previous and level > previous + 1), f"heading jumps h{previous} -> h{level}"
        previous = level


def test_work_caption_names_the_view_the_way_the_operator_selected_it(tmp_path):
    _stand(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _get(url + "/work?view=needs_attention")
    finally:
        server.shutdown()
    assert "needs_attention</caption>" not in html
    assert "Needs attention</caption>" in html
