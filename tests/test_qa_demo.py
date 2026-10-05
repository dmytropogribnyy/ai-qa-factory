"""QA Evidence & Retest: a targeted before/after accessibility retest.

The demo checks ONE owned synthetic page with two deliberate defects (axe ``image-alt`` and
``label``), applies a PREDEFINED fix to the SAME fixture URL, and retests. It is not AI-generated
remediation and not a general accessibility audit: only the two target rules decide the verdict,
and any other axe rule stays visible as out-of-scope.

Contract pinned here for ``core.scout.qa_demo``:

- ``compare_retest(before, after) -> {status, resolved, remaining, reason, ...}`` where status is
  FIX_VERIFIED | RETEST_FAILED | BASELINE_NOT_REPRODUCED | BLOCKED. Unknown, unavailable, failed or
  malformed observations are BLOCKED — never a clean pass.
- ``run_qa_demo(output_dir, run_id) -> dict`` with the compare keys at top level plus ``run_id``,
  ``before`` / ``after`` observations (``screenshot_ref`` relative to the RunStore root),
  ``evidence`` (canonical ``EvidenceRecord`` dicts), ``targeted_rules`` and ``limitations``.
  New run ids are ``demo-qa-<id>``; unsafe ids (including the legacy ``demo-interview-`` prefix)
  raise ``ValueError`` before any side effect; an existing run is never overwritten.
- ``load_qa_demo(output_dir, run_id) -> dict`` returns the persisted result; a missing, malformed
  or tampered run never loads as FIX_VERIFIED. Runs saved under the legacy ``demo-interview-`` id
  and ``interview_qa_demo/v1`` schema still load read-only.

Unit tests use a fake ``PlaywrightBackend.observe`` that fetches the REAL local fixture server, so
the defective -> repaired switch at one URL is exercised without a browser. The single real-browser
acceptance at the bottom is marked ``final1_browser_acceptance`` and skips with an explicit reason
when Playwright, Chromium or axe-core is missing.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
import shutil
import struct
import urllib.request
import uuid
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from core.schemas.evidence import EvidenceRecord
from core.scout import demo_site
from core.scout import qa_demo
from core.scout.backends import PageObservation, PlaywrightBackend
from core.scout.qa_demo import compare_retest, load_qa_demo, run_qa_demo
from core.scout.store import RunStore, StoreError

TARGETS = ["image-alt", "label"]
PNG_SIG = b"\x89PNG\r\n\x1a\n"
_FIXTURE_PAGES_AT_IMPORT = dict(demo_site.FIXTURE_PAGES)


def _fresh_id() -> str:
    return f"demo-qa-{uuid.uuid4().hex[:12]}"


def _obs(*rules: str, **over) -> dict:
    base = {"ok": True, "status": 200, "axe_status": "ok",
            "axe_violations": [{"id": r, "impact": "serious"} for r in rules],
            "screenshot_ref": "evidence/shot.png"}
    base.update(over)
    return base


def _check_shape(result: dict) -> None:
    assert result["status"] in {"FIX_VERIFIED", "RETEST_FAILED", "BASELINE_NOT_REPRODUCED", "BLOCKED"}
    assert isinstance(result["reason"], str) and result["reason"].strip()
    assert all(isinstance(r, str) for r in result["resolved"] + result["remaining"])


def _tree(root: Path) -> dict:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _assert_never_success(fn) -> None:
    try:
        res = fn()
    except (ValueError, OSError, StoreError):
        return
    assert isinstance(res, dict) and res.get("status") != "FIX_VERIFIED", res


# --- compare_retest ------------------------------------------------------------------------------

def test_both_targets_before_and_none_after_is_fix_verified():
    before, after = _obs("image-alt", "label"), _obs()
    snapshot = copy.deepcopy((before, after))
    result = compare_retest(before, after)
    _check_shape(result)
    assert result["status"] == "FIX_VERIFIED"
    assert sorted(result["resolved"]) == TARGETS and result["remaining"] == []
    assert (before, after) == snapshot  # inputs are evidence; comparison never rewrites them


def test_unchanged_defect_is_retest_failed():
    result = compare_retest(_obs("image-alt", "label"), _obs("image-alt", "label"))
    _check_shape(result)
    assert result["status"] == "RETEST_FAILED"
    assert result["resolved"] == [] and sorted(result["remaining"]) == TARGETS


def test_partial_fix_is_retest_failed_with_exact_split():
    result = compare_retest(_obs("image-alt", "label"), _obs("label"))
    _check_shape(result)
    assert result["status"] == "RETEST_FAILED"
    assert result["resolved"] == ["image-alt"] and result["remaining"] == ["label"]


@pytest.mark.parametrize("before_rules", [(), ("image-alt",), ("label",), ("color-contrast",)])
def test_missing_baseline_is_not_reproduced(before_rules):
    result = compare_retest(_obs(*before_rules), _obs())
    _check_shape(result)
    assert result["status"] == "BASELINE_NOT_REPRODUCED"


_BAD_OBSERVATIONS = {
    "axe_unavailable": lambda o: {**o, "axe_status": "unavailable", "axe_violations": []},
    "axe_not_attempted": lambda o: {**o, "axe_status": "", "axe_violations": []},
    "axe_error_status": lambda o: {**o, "axe_status": "error"},
    "navigation_failed": lambda o: {**o, "ok": False, "status": 0},
    "ok_but_http_404": lambda o: {**o, "status": 404},
    "ok_not_a_bool": lambda o: {**o, "ok": "true"},
    "violations_not_list": lambda o: {**o, "axe_violations": None},
    "violation_without_id": lambda o: {**o, "axe_violations": o["axe_violations"] + [{"impact": "x"}]},
    "violation_not_dict": lambda o: {**o, "axe_violations": o["axe_violations"] + ["label"]},
    "violation_unknown_id": lambda o: {**o, "axe_violations": o["axe_violations"] + [{"id": "unknown"}]},
    "no_screenshot": lambda o: {**o, "screenshot_ref": ""},
    "truncated": lambda o: {k: v for k, v in o.items() if k in ("ok", "status")},
    "empty": lambda o: {},
    "not_a_dict": lambda o: None,
}


@pytest.mark.parametrize("mutation", sorted(_BAD_OBSERVATIONS))
def test_untrustworthy_observation_on_either_side_is_blocked(mutation):
    bad = _BAD_OBSERVATIONS[mutation]
    for before, after in ((bad(_obs("image-alt", "label")), _obs()),
                          (_obs("image-alt", "label"), bad(_obs()))):
        result = compare_retest(before, after)
        _check_shape(result)
        assert result["status"] == "BLOCKED", (mutation, result)


def test_out_of_scope_rules_stay_visible_and_never_count_as_resolved():
    result = compare_retest(_obs("image-alt", "label", "color-contrast", "region"),
                            _obs("color-contrast"))
    _check_shape(result)
    assert result["status"] == "FIX_VERIFIED"   # verdict is about the two targets only ...
    assert sorted(result["resolved"]) == TARGETS
    assert "region" not in result["resolved"] and "color-contrast" not in result["remaining"]
    extra = {k: v for k, v in result.items() if k not in ("status", "resolved", "remaining")}
    assert "color-contrast" in json.dumps(extra)  # ... and the remaining rule is surfaced, not hidden
    assert not re.search(r"wcag[- ]?complian|fully accessible", json.dumps(result), re.I)


# --- run_qa_demo: refusals before side effects ---------------------------------------------------

_UNSAFE_IDS = ["", "demo-qa-", "../demo-qa-x", "demo-qa-x/../../escape",
               "demo-qa-a\\b", "<ABS>", "/demo-qa-x", "scout-run-001",
               "Demo-QA-x", "demo-qa-x\n", "demo-qa-x y", "demo-qa-é",
               "../demo-interview-x", "demo-interview-x\n", "Demo-Interview-x"]


def _forbid_side_effects(monkeypatch) -> list:
    calls: list = []

    def _no_browser(self, url, *a, **k):
        calls.append(("observe", url))
        raise AssertionError("browser must not launch")

    def _no_server(*a, **k):
        calls.append(("serve", a))
        raise AssertionError("fixture server must not start")

    monkeypatch.setattr(PlaywrightBackend, "observe", _no_browser)
    monkeypatch.setattr(demo_site, "serve_demo_site", _no_server)
    monkeypatch.setattr(qa_demo, "serve_demo_site", _no_server, raising=False)
    monkeypatch.setattr(RunStore, "reset", lambda self: calls.append(("reset", self.root)))
    return calls


@pytest.mark.parametrize("raw_id", _UNSAFE_IDS)
def test_unsafe_run_id_is_refused_before_any_side_effect(raw_id, tmp_path, monkeypatch):
    calls = _forbid_side_effects(monkeypatch)
    run_id = str(tmp_path / "abs" / "demo-qa-x") if raw_id == "<ABS>" else raw_id
    out = tmp_path / "out"
    for fn in (run_qa_demo, load_qa_demo):
        with pytest.raises(ValueError):
            fn(str(out), run_id)
    assert calls == []
    assert not out.exists() and not (tmp_path / "abs").exists()


@pytest.mark.parametrize("existing", ["state", "bare_dir"])
def test_existing_run_is_never_overwritten(existing, tmp_path, monkeypatch):
    calls = _forbid_side_effects(monkeypatch)
    out, run_id = str(tmp_path / "out"), _fresh_id()
    store = RunStore(out, run_id)
    if existing == "state":
        store.save_state({"sentinel": "earlier run"})
    else:
        store.root.mkdir(parents=True)
        (store.root / "keep.txt").write_text("earlier attempt", encoding="utf-8")
    before = _tree(Path(out))
    with pytest.raises((FileExistsError, ValueError, StoreError)):
        run_qa_demo(out, run_id)
    assert _tree(Path(out)) == before
    assert calls == []  # no browser, no server, and never a reset/delete


def test_no_caller_supplied_target():
    params = set(inspect.signature(run_qa_demo).parameters)
    assert {"output_dir", "run_id"} <= params
    assert not [p for p in params if re.search(r"url|target|host|site", p, re.I)]


# --- run_qa_demo with a fake browser over the REAL local fixture server --------------------------

def _png(seed: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"\x00" + bytes([seed % 256, 0x40, 0x80])
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _fetch(url: str) -> tuple[int, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _axe_like(html: str) -> list:
    """A crude stand-in for axe on the two target rules, in the production backend's shape."""
    found = []
    if re.search(r"<img\b(?![^>]*\balt\s*=)[^>]*>", html, re.I):
        found.append({"rule": "image-alt", "impact": "critical", "help": "img alt", "selector": "img"})
    for tag in re.findall(r"<input\b[^>]*>", html, re.I):
        if re.search(r"type\s*=\s*['\"]?(hidden|submit|button|image)", tag, re.I):
            continue
        ident = re.search(r"\bid\s*=\s*['\"]([^'\"]+)", tag)
        labelled = ("aria-label" in tag or "<label" in html.lower()
                    or (ident and re.search(rf"for\s*=\s*['\"]{re.escape(ident.group(1))}['\"]", html)))
        if not labelled:
            found.append({"rule": "label", "impact": "critical", "help": "label", "selector": "input"})
            break
    return found


def _served_page(backend, url, deep_qa, n):
    obs = PageObservation(url=url, backend="playwright")
    obs.status, html = _fetch(url)
    obs.ok, obs.final_url = 200 <= obs.status < 300, url
    if deep_qa:
        obs.axe_status, obs.axe_violations = "ok", _axe_like(html)
    if backend.screenshot_dir:
        name = os.path.basename(backend.screenshot_filename or "page.png")
        os.makedirs(backend.screenshot_dir, exist_ok=True)
        Path(backend.screenshot_dir, name).write_bytes(_png(n))
        obs.screenshot_ref = name
    return obs


def _browser_missing(backend, url, deep_qa, n):
    return PageObservation(url=url, backend="playwright",
                           fetch_error="playwright is not installed. Run: pip install playwright")


def _claims_unwritten_screenshot(backend, url, deep_qa, n):
    obs = PageObservation(url=url, backend="playwright", ok=True, status=200, final_url=url)
    obs.axe_status = "ok"
    obs.axe_violations = ([{"rule": r, "impact": "critical"} for r in TARGETS] if n == 0 else [])
    obs.screenshot_ref = "page.png"   # claimed, never written
    return obs


def _install_backend(monkeypatch, behaviour) -> list:
    calls: list = []

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        calls.append({"url": url, "deep_qa": deep_qa})
        return behaviour(self, url, deep_qa, len(calls) - 1)

    monkeypatch.setattr(PlaywrightBackend, "observe", observe)
    return calls


def _assert_screenshot_evidence(out: str, run_id: str, payload: dict) -> dict:
    root = RunStore(out, run_id).root
    records = {}
    for raw in payload["evidence"]:
        rec = EvidenceRecord.from_dict(raw)
        records[rec.path] = rec
    hashes = {}
    for side in ("before", "after"):
        ref = payload[side]["screenshot_ref"]
        assert ref and not os.path.isabs(ref), ref
        shot = (root / ref).resolve()
        assert root in shot.parents
        data = shot.read_bytes()
        assert data.startswith(PNG_SIG)
        digest = hashlib.sha256(data).hexdigest()
        rec = records.get(ref)
        assert rec is not None, f"no canonical EvidenceRecord for {side} screenshot {ref}"
        assert rec.evidence_type in ("screenshot", "screenshot_original")
        assert rec.content_hash in (digest, "sha256:" + digest)
        assert rec.internal_only and not rec.client_visible
        hashes[side] = digest
    return hashes


@pytest.fixture
def completed_run(tmp_path, monkeypatch):
    calls = _install_backend(monkeypatch, _served_page)
    out, run_id = str(tmp_path / "out"), _fresh_id()
    result = run_qa_demo(out, run_id)
    return out, run_id, result, calls


def test_same_fixture_url_goes_from_defective_to_repaired(completed_run):
    out, run_id, result, calls = completed_run
    assert result["status"] == "FIX_VERIFIED", result
    assert result["run_id"] == run_id
    assert sorted(result["resolved"]) == TARGETS and result["remaining"] == []
    assert sorted(result["targeted_rules"]) == TARGETS and result["limitations"]

    assert len(calls) == 2 and calls[0]["url"] == calls[1]["url"]  # SAME subject, retested
    assert all(c["deep_qa"] for c in calls)
    parts = urlsplit(calls[0]["url"])
    assert parts.scheme == "http" and parts.hostname == "127.0.0.1" and parts.port
    assert demo_site.FIXTURE_PAGES == _FIXTURE_PAGES_AT_IMPORT  # shared fixtures untouched

    assert set(TARGETS) <= {v["id"] for v in result["before"]["axe_violations"]}
    assert not set(TARGETS) & {v["id"] for v in result["after"]["axe_violations"]}
    hashes = _assert_screenshot_evidence(out, run_id, result)
    assert hashes["before"] != hashes["after"]

    root = RunStore(out, run_id).root
    assert all(root in p.resolve().parents for p in Path(out).rglob("*") if p.is_file())
    reports = list(root.rglob("*.html"))
    assert reports, "an offline HTML report must be exported"
    html = reports[0].read_text(encoding="utf-8")
    assert run_id in html and "image-alt" in html and "label" in html
    assert "<script src" not in html.lower() and "https://" not in html


def test_a_fresh_run_never_touches_an_earlier_one(completed_run, monkeypatch):
    out, first_id, _result, _calls = completed_run
    first_tree = _tree(RunStore(out, first_id).root)
    second = run_qa_demo(out, _fresh_id())
    assert second["status"] == "FIX_VERIFIED" and second["run_id"] != first_id
    assert _tree(RunStore(out, first_id).root) == first_tree


@pytest.mark.parametrize("behaviour", [_browser_missing, _claims_unwritten_screenshot])
def test_no_synthetic_screenshot_when_the_browser_did_not_capture(behaviour, tmp_path, monkeypatch):
    _install_backend(monkeypatch, behaviour)
    out, run_id = str(tmp_path / "out"), _fresh_id()
    result = run_qa_demo(out, run_id)
    assert result["status"] == "BLOCKED", result
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert p.suffix.lower() != ".png" and not p.read_bytes().startswith(PNG_SIG), p
    assert not [r for r in result.get("evidence", [])
                if r.get("evidence_type") in ("screenshot", "screenshot_original")]
    _assert_never_success(lambda: load_qa_demo(out, run_id))


# --- load_qa_demo ---------------------------------------------------------------------------------

def test_load_returns_the_persisted_result_without_rerunning(completed_run, monkeypatch):
    out, run_id, result, _calls = completed_run
    rerun = _forbid_side_effects(monkeypatch)
    loaded = load_qa_demo(out, run_id)
    assert rerun == []
    assert loaded["status"] == "FIX_VERIFIED" and loaded["run_id"] == run_id
    assert sorted(loaded["resolved"]) == sorted(result["resolved"]) and loaded["remaining"] == []
    _assert_screenshot_evidence(out, run_id, loaded)


def test_load_of_a_run_that_never_happened_is_not_success(tmp_path):
    _assert_never_success(lambda: load_qa_demo(str(tmp_path / "out"), _fresh_id()))
    assert not (tmp_path / "out").exists()


def _json_files(root: Path) -> list:
    return [p for p in root.rglob("*.json") if p.is_file()]


def _truncate_json(root, run_id, result):
    for p in _json_files(root):
        p.write_bytes(p.read_bytes()[: max(1, p.stat().st_size // 2)])


def _delete_json(root, run_id, result):
    for p in _json_files(root):
        p.unlink()


def _forge_minimal_json(root, run_id, result):
    for p in _json_files(root):
        p.write_text(json.dumps({"status": "FIX_VERIFIED", "run_id": run_id}), encoding="utf-8")


def _tamper_after_screenshot(root, run_id, result):
    shot = root / result["after"]["screenshot_ref"]
    shot.write_bytes(shot.read_bytes() + b"tampered")


def _delete_before_screenshot(root, run_id, result):
    (root / result["before"]["screenshot_ref"]).unlink()


@pytest.mark.parametrize("damage", [_truncate_json, _delete_json, _forge_minimal_json,
                                    _tamper_after_screenshot, _delete_before_screenshot])
def test_damaged_persisted_run_never_loads_as_success(damage, completed_run):
    out, run_id, result, _calls = completed_run
    damage(RunStore(out, run_id).root, run_id, result)
    _assert_never_success(lambda: load_qa_demo(out, run_id))


# --- regression controls: malformed persisted records and missing-vs-empty violation lists -------

def _rewrite_evidence(out, run_id, mutate) -> None:
    path = RunStore(out, run_id).root / "qa_demo_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["evidence"] = mutate(report["evidence"])
    path.write_text(json.dumps(report), encoding="utf-8")


@pytest.mark.parametrize("mutate", [
    lambda ev: [{"path": {}, "content_hash": "bad"}],                       # non-string path
    lambda ev: ev + [{**ev[0], "content_hash": "sha256:" + "0" * 64}],      # contradictory duplicate
], ids=["non_string_path", "duplicate_path"])
def test_malformed_persisted_evidence_record_loads_as_blocked(mutate, completed_run):
    out, run_id, _result, _calls = completed_run
    _rewrite_evidence(out, run_id, mutate)
    loaded = load_qa_demo(out, run_id)
    assert loaded["status"] == "BLOCKED", loaded


class _ControlledBackend:
    screenshot_filename = ""

    def __init__(self, violations):
        self.violations = violations

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        return PageObservation(url=url, backend="playwright", ok=True, status=200, final_url=url,
                               axe_status="ok", axe_violations=self.violations,
                               screenshot_ref=self.screenshot_filename)


def _observe_after(tmp_path, violations) -> dict:
    store = RunStore(str(tmp_path / "out"), _fresh_id())
    (store.root / "evidence").mkdir(parents=True)
    (store.root / "evidence" / "after.png").write_bytes(_png(1))
    after, _record = qa_demo._observe(_ControlledBackend(violations),
                                      "http://127.0.0.1:1/x", "after", store, "demo-qa-x")
    return after


@pytest.mark.parametrize("violations", [None, "image-alt", [{"rule": 123}], [{"rule": "unknown"}]],
                         ids=["none", "not_a_list", "non_string_rule", "unknown_sentinel"])
def test_missing_or_malformed_source_violations_are_blocked_not_empty(violations, tmp_path):
    after = _observe_after(tmp_path, violations)
    assert compare_retest(_obs("image-alt", "label"), after)["status"] == "BLOCKED", after


@pytest.mark.parametrize("violations", [[], [{"rule": "color-contrast", "impact": "serious"}]],
                         ids=["genuine_empty", "out_of_scope_only"])
def test_valid_source_violation_lists_still_verify(violations, tmp_path):
    after = _observe_after(tmp_path, violations)
    result = compare_retest(_obs("image-alt", "label"), after)
    assert result["status"] == "FIX_VERIFIED", result
    assert [v["id"] for v in after["axe_violations"]] == [v["rule"] for v in violations]


# --- lifecycle commit marker: state.json is written last and must confirm the report -------------

_STATE_DAMAGE = {
    "missing": None,
    "corrupt": b'{"status": "FIX_VER',
    "null": b"null",
    "list": b"[]",
    "running_after_crash": lambda s: {k: v for k, v in {**s, "status": "RUNNING"}.items()
                                      if k != "finished_at"},
    "other_run_id": lambda s: {**s, "run_id": "demo-qa-someoneelse"},
    "status_disagrees": lambda s: {**s, "status": "RETEST_FAILED"},
    "finished_at_disagrees": lambda s: {**s, "finished_at": "2001-01-01T00:00:00+00:00"},
    "finished_at_empty": lambda s: {**s, "finished_at": ""},
    "started_after_finished": lambda s: {**s, "started_at": "2999-01-01T00:00:00+00:00"},
}


@pytest.mark.parametrize("damage", sorted(_STATE_DAMAGE))
def test_report_without_matching_terminal_state_never_loads_as_success(damage, completed_run,
                                                                      monkeypatch):
    out, run_id, _result, _calls = completed_run
    state_path = RunStore(out, run_id).root / "state.json"
    change = _STATE_DAMAGE[damage]
    if change is None:
        state_path.unlink()
    elif isinstance(change, bytes):
        state_path.write_bytes(change)
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_path.write_text(json.dumps(change(state)), encoding="utf-8")
    rerun = _forbid_side_effects(monkeypatch)
    loaded = load_qa_demo(out, run_id)
    assert rerun == []  # a failed lifecycle check never re-executes the run
    assert loaded["status"] == "BLOCKED", (damage, loaded)
    assert "state" in loaded["reason"]


def test_terminal_state_mirrors_the_report(completed_run):
    out, run_id, result, _calls = completed_run
    state = RunStore(out, run_id).load_state()
    assert state["run_id"] == run_id and state["status"] == result["status"]
    assert state["started_at"] == result["started_at"]
    assert state["finished_at"] == result["finished_at"]


# --- product-neutral naming with legacy read compatibility ---------------------------------------

def test_new_runs_use_product_neutral_identifiers(completed_run):
    out, run_id, result, _calls = completed_run
    root = RunStore(out, run_id).root
    assert run_id.startswith("demo-qa-") and result["schema"] == "qa_evidence_retest/v1"
    assert {r["source_phase"] for r in result["evidence"]} == {"qa_evidence_retest"}
    for p in root.rglob("*"):
        if p.suffix in (".json", ".html"):
            assert "interview" not in p.read_text(encoding="utf-8").lower(), p


def test_new_runs_cannot_use_the_legacy_prefix(tmp_path, monkeypatch):
    calls = _forbid_side_effects(monkeypatch)
    with pytest.raises(ValueError):
        run_qa_demo(str(tmp_path / "out"), "demo-interview-x")
    assert calls == [] and not (tmp_path / "out").exists()


def _as_legacy_run(out: str, run_id: str, schema: str = "interview_qa_demo/v1") -> str:
    """Simulate a run saved before the naming change: legacy id prefix, schema and source_phase."""
    legacy_id = "demo-interview-" + run_id.removeprefix("demo-qa-")
    root = RunStore(out, legacy_id).root
    shutil.copytree(RunStore(out, run_id).root, root)
    for name in ("qa_demo_report.json", "state.json", "config.json"):
        data = json.loads((root / name).read_text(encoding="utf-8"))
        data["run_id"] = legacy_id
        if "schema" in data:
            data["schema"] = schema
        for rec in data.get("evidence", []):
            rec["source_phase"] = "interview_qa_demo"
        (root / name).write_text(json.dumps(data), encoding="utf-8")
    return legacy_id


def test_legacy_saved_run_still_loads_and_verifies(completed_run, monkeypatch):
    out, run_id, _result, _calls = completed_run
    legacy_id = _as_legacy_run(out, run_id)
    before = _tree(RunStore(out, legacy_id).root)
    rerun = _forbid_side_effects(monkeypatch)
    loaded = load_qa_demo(out, legacy_id)
    assert rerun == []
    assert loaded["status"] == "FIX_VERIFIED" and loaded["run_id"] == legacy_id
    assert loaded["schema"] == "interview_qa_demo/v1"
    _assert_screenshot_evidence(out, legacy_id, loaded)
    assert _tree(RunStore(out, legacy_id).root) == before  # read-only: history is not rewritten


def test_legacy_id_without_a_saved_run_is_blocked_not_refused(tmp_path):
    loaded = load_qa_demo(str(tmp_path / "out"), "demo-interview-neverran")
    assert loaded["status"] == "BLOCKED" and not (tmp_path / "out").exists()


def test_unknown_schema_is_still_blocked(completed_run):
    out, run_id, _result, _calls = completed_run
    legacy_id = _as_legacy_run(out, run_id, schema="some_other_demo/v1")
    assert load_qa_demo(out, legacy_id)["status"] == "BLOCKED"


# --- optional REAL local Chromium + axe acceptance ------------------------------------------------

def _real_browser_skip_reason() -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return f"playwright not installed ({type(exc).__name__})"
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception as exc:
        return f"Chromium for Playwright not installed or not launchable ({type(exc).__name__})"
    try:
        from core.scout.pipeline.browser_qa import load_axe_source
        load_axe_source()
    except Exception as exc:
        return f"axe-core source not installed ({type(exc).__name__})"
    return ""


@pytest.mark.final1_browser_acceptance
def test_real_chromium_axe_demo_verifies_the_predefined_fix(tmp_path):
    reason = _real_browser_skip_reason()
    if reason:
        pytest.skip(reason)
    out, run_id = str(tmp_path / "out"), _fresh_id()
    result = run_qa_demo(out, run_id)

    assert result["status"] == "FIX_VERIFIED", result
    assert result["before"]["axe_status"] == "ok" and result["after"]["axe_status"] == "ok"
    # Scoped: only the two target rules are asserted; other axe rules may legitimately remain.
    assert set(TARGETS) <= {v["id"] for v in result["before"]["axe_violations"]}
    assert not set(TARGETS) & {v["id"] for v in result["after"]["axe_violations"]}
    assert sorted(result["resolved"]) == TARGETS and result["remaining"] == []
    hashes = _assert_screenshot_evidence(out, run_id, result)
    assert hashes["before"] != hashes["after"]

    loaded = load_qa_demo(out, run_id)
    assert loaded["status"] == "FIX_VERIFIED" and loaded["run_id"] == run_id
    assert _assert_screenshot_evidence(out, run_id, loaded) == hashes
