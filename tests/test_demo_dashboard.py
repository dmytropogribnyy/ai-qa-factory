"""Product Demos in the existing Dashboard: /demos, the guarded start and verified reads.

Every HTTP test drives the REAL ``start_dashboard`` over a socket with a temporary output root.
Where a dependency would make a test slow or environment-bound it is replaced by a clearly labelled
STUB: ``_install_stub_browser`` stands in for Chromium + axe inside the real ``run_qa_demo`` (the
fixture server, RunStore, evidence records and load verification all stay real); a few tests swap
``server.demo_controller.runners`` / ``loaders`` to block, raise or return adversarial text. The LLM
evaluation runs for real in FIXTURE mode (offline, no model call).

The single real-browser acceptance at the bottom is marked ``final1_browser_acceptance`` and skips
with an attributed reason when Playwright, Chromium or axe-core is missing; release acceptance
requires it to run, not skip.
"""
from __future__ import annotations

import html
import http.client
import json
import shutil
import struct
import threading
import zlib
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest

from core import llm_eval_demo
from core.dashboard import demos
from core.scout.backends import PageObservation, PlaywrightBackend
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore

TARGETS = ("image-alt", "label")
PNG_SIG = b"\x89PNG\r\n\x1a\n"
EVIL = "<script>alert('x')</script><img src=x onerror=alert(1)>"


# --- helpers -------------------------------------------------------------------------------------

def _request(url: str, method: str, path: str, body=None, headers=None):
    parts = urlsplit(url)
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=120)
    data = body if body is None or isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    hdrs = dict(headers or {})
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    try:
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        return resp.status, resp.headers, resp.read()
    finally:
        conn.close()


def _get(url, path, headers=None):
    return _request(url, "GET", path, headers=headers)


def _get_json(url, path):
    status, _h, raw = _get(url, path)
    return status, json.loads(raw)


def _start(dash, scenario):
    server, url, _out = dash
    status, _h, raw = _request(url, "POST", "/api/demos/start", {"scenario": scenario},
                               {"X-Scout-CSRF": server.scout_csrf_token, "Origin": url})
    return status, json.loads(raw)


def _demo_dirs(out: Path) -> list:
    root = out / "scout"
    return sorted(p.name for p in root.iterdir() if p.name.startswith("demo-")) if root.exists() else []


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _count_runs(server) -> list:
    """Wrap the controller's real runners so a test can prove what executed (and what did not)."""
    calls = []
    runners = server.demo_controller.runners
    for scenario, real in list(runners.items()):
        def counted(out, run_id, _real=real, _scenario=scenario):
            calls.append((_scenario, run_id))
            return _real(out, run_id)
        runners[scenario] = counted
    return calls


def _png(seed: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"\x00" + bytes([seed % 256, 0x40, 0x80])
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _install_stub_browser(monkeypatch, *, available: bool = True) -> list:
    """STUB for Chromium + axe: the first observation of a run sees both target defects, the
    retest sees none; each writes a distinct real PNG where the backend would. ``available=False``
    reports the browser as missing, exactly as the production backend does."""
    calls = []

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        n = len(calls)
        calls.append(url)
        if not available:
            return PageObservation(url=url, backend="playwright",
                                   fetch_error="playwright is not installed")
        obs = PageObservation(url=url, backend="playwright", ok=True, status=200, final_url=url)
        obs.axe_status = "ok"
        obs.axe_violations = ([{"rule": r, "impact": "critical"} for r in TARGETS]
                              if n % 2 == 0 else [])
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
        Path(self.screenshot_dir, self.screenshot_filename).write_bytes(_png(n))
        obs.screenshot_ref = self.screenshot_filename
        return obs

    monkeypatch.setattr(PlaywrightBackend, "observe", observe)
    return calls


@pytest.fixture
def dash(tmp_path):
    out = tmp_path / "out"
    server, url = start_dashboard(ScoutService(str(out)), operator_home=True)
    try:
        yield server, url, out
    finally:
        server.shutdown()
        server.server_close()


# --- pages and navigation ------------------------------------------------------------------------

def test_demos_page_offers_two_demos_and_runs_nothing(dash):
    server, url, out = dash
    calls = _count_runs(server)
    status, headers, raw = _get(url, "/demos")
    page = raw.decode("utf-8")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert "Content-Security-Policy" in headers
    assert 'id="run-qa"' in page and ">Run QA demo</button>" in page
    assert 'id="run-llm"' in page and ">Run evaluation</button>" in page
    assert "QA Evidence &amp; Retest" in page and "LLM Output Evaluation" in page
    assert "FIXTURE" in page and "no model or API call" in page and "predefined" in page
    assert 'href="/demos" aria-current="page"' in page
    assert 'role="status"' in page and 'role="alert"' in page
    assert "No demo has been run yet" in page
    assert "interview" not in page.lower()
    assert calls == [] and _demo_dirs(out) == []


def test_overview_links_to_demos(dash):
    _server, url, _out = dash
    status, _h, raw = _get(url, "/")
    assert status == 200
    assert 'id="demos-link"' in raw.decode("utf-8") and 'href="/demos"' in raw.decode("utf-8")


@pytest.mark.parametrize("path", ["/demos", "/demos/run?id=demo-llm-x", "/api/demos/run?id=demo-llm-x",
                                  "/demos/evidence?id=demo-qa-x&side=before",
                                  "/demos/export?id=demo-llm-x"])
def test_every_demo_read_inherits_the_loopback_host_guard(dash, path):
    _server, url, _out = dash
    status, _h, _raw = _get(url, path, headers={"Host": "attacker.example"})
    assert status == 403


# --- guarded start -------------------------------------------------------------------------------

def _bad_start(kind: str, server, url):
    token, ok = server.scout_csrf_token, {"X-Scout-CSRF": server.scout_csrf_token, "Origin": url}
    return {
        "no_csrf": ({"scenario": "llm"}, {"Origin": url}),
        "wrong_csrf": ({"scenario": "llm", "csrf_token": "nope"}, {"X-Scout-CSRF": "nope"}),
        "wrong_origin": ({"scenario": "llm"}, {"X-Scout-CSRF": token,
                                               "Origin": "http://attacker.example"}),
        "non_loopback_host": ({"scenario": "llm"}, {**ok, "Host": "attacker.example"}),
        "invalid_json": (b"{not json", ok),
        "non_object_json": (b'["llm"]', ok),
        "empty_body": (b"", ok),
        "output_dir": ({"scenario": "llm", "output_dir": "C:/elsewhere"}, ok),
        "url": ({"scenario": "qa", "url": "http://example.com"}, ok),
        "path": ({"scenario": "llm", "path": "../x"}, ok),
        "model": ({"scenario": "llm", "model": "gpt"}, ok),
        "responses_path": ({"scenario": "llm", "responses_path": "r.json"}, ok),
        "run_id": ({"scenario": "llm", "run_id": "demo-llm-mine"}, ok),
        "unknown_scenario": ({"scenario": "live"}, ok),
        "non_string_scenario": ({"scenario": ["qa"]}, ok),
        "missing_scenario": ({}, ok),
    }[kind]


@pytest.mark.parametrize("kind", [
    "no_csrf", "wrong_csrf", "wrong_origin", "non_loopback_host", "invalid_json", "non_object_json",
    "empty_body", "output_dir", "url", "path", "model", "responses_path", "run_id",
    "unknown_scenario", "non_string_scenario", "missing_scenario"])
def test_refused_start_has_zero_effects(dash, kind):
    server, url, out = dash
    calls = _count_runs(server)
    body, headers = _bad_start(kind, server, url)
    status, _h, raw = _request(url, "POST", "/api/demos/start", body, headers)
    expected = 403 if kind in ("no_csrf", "wrong_csrf", "wrong_origin", "non_loopback_host") else 400
    assert status == expected, raw
    assert json.loads(raw)["ok"] is False and b"Traceback" not in raw
    assert calls == [] and _demo_dirs(out) == []


def test_llm_run_persists_and_reads_never_rerun(dash):
    server, url, out = dash
    calls = _count_runs(server)
    status, j = _start(dash, "llm")
    assert status == 200 and j["ok"] is True, j
    run_id = j["run_id"]
    assert run_id.startswith("demo-llm-") and j["url"] == f"/demos/run?id={run_id}"
    assert (j["status"], j["verdict"], j["mode"]) == ("COMPLETED", "REGRESSION_DETECTED", "FIXTURE")
    assert calls == [("llm", run_id)]
    root = RunStore(str(out), run_id).root
    before = _tree(root)

    for path in (j["url"], j["url"], f"/api/demos/run?id={run_id}", "/demos",
                 f"/demos/export?id={run_id}"):
        assert _get(url, path)[0] == 200, path
    assert _request(url, "HEAD", j["url"])[0] == 200
    assert calls == [("llm", run_id)] and _tree(root) == before   # reload never re-executes

    status, view = _get_json(url, f"/api/demos/run?id={run_id}")
    assert status == 200 and view["record"] == "verified" and view["kind"] == "llm"
    result = view["result"]
    assert result["mode"] == "FIXTURE" and result["provider_called"] is False
    snapshot = json.loads((root / "inputs" / "cases.json").read_text(encoding="utf-8"))
    assert view["cases"] == {c["id"]: c for c in snapshot["cases"]}

    page = _get(url, j["url"])[2].decode("utf-8")
    assert ".demo-grid{" in page and ".demo-wrap," in page   # demo layout CSS on the detail page
    cmp = result["comparison"]
    for side in ("baseline", "candidate"):
        assert f"{cmp[side]['passed']}/{cmp[side]['total']}" in page
    assert "REGRESSION_DETECTED" in page and "not a measured model benchmark" in page
    assert "not release authorization" in page
    assert all(case_id in page for case_id in cmp["regressed"])
    assert page.count('<details class="demo-case card">') == len(cmp["per_case"])
    assert "Prompt:" in page and "Raw output" in page


def test_case_details_come_from_the_run_snapshot_not_the_current_fixture(dash, tmp_path,
                                                                           monkeypatch):
    _server, url, _out = dash
    _status, j = _start(dash, "llm")
    doc = json.loads(llm_eval_demo.CASES_PATH.read_text(encoding="utf-8"))
    original = doc["cases"][0]["prompt"]
    for case in doc["cases"]:
        case["prompt"] = "CHANGED-AFTER-THE-RUN"
    changed = tmp_path / "cases.json"
    changed.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(llm_eval_demo, "CASES_PATH", changed)
    page = _get(url, j["url"])[2].decode("utf-8")
    assert "CHANGED-AFTER-THE-RUN" not in page
    assert html.escape(original, quote=True) in page


def test_run_again_creates_a_fresh_run_and_leaves_the_earlier_one_unchanged(dash):
    _server, _url, out = dash
    _s, first = _start(dash, "llm")
    first_root = RunStore(str(out), first["run_id"]).root
    before = _tree(first_root)
    _s, second = _start(dash, "llm")
    assert second["ok"] and second["run_id"] != first["run_id"]
    assert _tree(first_root) == before
    assert _demo_dirs(out) == sorted([first["run_id"], second["run_id"]])


def test_qa_run_shows_the_genuine_screenshot_pair(dash, monkeypatch):
    server, url, out = dash
    _install_stub_browser(monkeypatch)
    calls = _count_runs(server)
    status, j = _start(dash, "qa")
    assert status == 200 and j["status"] == "FIX_VERIFIED", j
    run_id = j["run_id"]
    assert run_id.startswith("demo-qa-") and calls == [("qa", run_id)]
    root = RunStore(str(out), run_id).root

    page = _get(url, j["url"])[2].decode("utf-8")
    assert ".demo-shots{" in page   # the responsive screenshot grid CSS ships with the detail page
    assert "Scoped verdict: FIX_VERIFIED" in page
    assert "not a general accessibility certification" in page
    for rule in TARGETS:
        assert f'<code>{rule}</code></td><td data-label="Before">present</td>' \
               f'<td data-label="After">absent</td><td data-label="Result">resolved</td>' in page
    served = {}
    for side in ("before", "after"):
        src = f"/demos/evidence?id={run_id}&amp;side={side}"
        assert f'src="{src}"' in page
        status, headers, data = _get(url, src.replace("&amp;", "&"))
        assert status == 200 and headers["Content-Type"] == "image/png"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "no-store"
        assert data == (root / "evidence" / f"{side}.png").read_bytes()
        served[side] = data
    assert served["before"] != served["after"]
    assert calls == [("qa", run_id)]


def test_unavailable_browser_is_blocked_never_success(dash, monkeypatch):
    _server, url, _out = dash
    _install_stub_browser(monkeypatch, available=False)
    status, j = _start(dash, "qa")
    assert status == 200 and j["status"] == "BLOCKED", j
    status, view = _get_json(url, f"/api/demos/run?id={j['run_id']}")
    assert status == 200 and view["result"]["status"] == "BLOCKED"
    page = _get(url, j["url"])[2].decode("utf-8")
    assert "Scoped verdict: BLOCKED" in page and "FIX_VERIFIED" not in page
    assert "No screenshot was captured" in page
    # Missing is not absence: without an axe observation neither side may claim a rule is absent.
    for side in ("Before", "After"):
        assert page.count(f'data-label="{side}">not observed') == len(TARGETS)
        assert f'data-label="{side}">absent' not in page
        assert f'data-label="{side}">present' not in page
    assert _get(url, f"/demos/evidence?id={j['run_id']}&side=before")[0] == 404


def test_a_second_start_while_one_runs_is_409_and_the_lock_is_released(dash):
    server, _url, out = dash
    started, release, results = threading.Event(), threading.Event(), []
    real = server.demo_controller.runners["llm"]

    def slow(output_dir, run_id):   # STUB: holds the lock until the test releases it
        started.set()
        release.wait(30)
        return real(output_dir, run_id)

    server.demo_controller.runners["llm"] = slow
    worker = threading.Thread(target=lambda: results.append(_start(dash, "llm")))
    worker.start()
    try:
        assert started.wait(30)
        for scenario in ("qa", "llm"):
            status, j = _start(dash, scenario)
            assert status == 409 and j["ok"] is False
    finally:
        release.set()
        worker.join(60)
    assert results and results[0][0] == 200
    assert len(_demo_dirs(out)) == 1
    server.demo_controller.runners["llm"] = real
    assert _start(dash, "llm")[0] == 200


def test_runner_failure_is_reported_without_traceback_or_paths(dash):
    server, _url, out = dash

    def broken(output_dir, run_id):   # STUB: an engine failure that mentions a local path
        raise RuntimeError(f"failed while writing {output_dir}")

    server.demo_controller.runners["llm"] = broken
    status, j = _start(dash, "llm")
    raw = json.dumps(j)
    assert status == 500 and j["ok"] is False and "RuntimeError" in j["error"]
    assert str(out) not in raw and out.name not in raw and "Traceback" not in raw
    server.demo_controller.runners["llm"] = llm_eval_demo.run_llm_eval_demo
    assert _start(dash, "llm")[0] == 200   # the lock was released in finally


# --- verified reads ------------------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", ["", "../etc", "run-123", "demo-qa-", "demo-qa-a/b",
                                    "demo-llm-..", "DEMO-QA-x", "demo-qa-x y"])
def test_invalid_ids_are_refused(dash, bad_id):
    _server, url, _out = dash
    q = quote(bad_id, safe="")
    assert _get(url, f"/api/demos/run?id={q}")[0] == 400
    assert _get(url, f"/demos/run?id={q}")[0] == 400
    assert _get(url, f"/demos/export?id={q}")[0] == 400


def test_unknown_run_is_404_and_executes_nothing(dash):
    server, url, out = dash
    calls = _count_runs(server)
    for run_id in ("demo-llm-neverran", "demo-qa-neverran", "demo-interview-neverran"):
        status, view = _get_json(url, f"/api/demos/run?id={run_id}")
        assert status == 404 and view["ok"] is False
        assert _get(url, f"/demos/run?id={run_id}")[0] == 404
    assert calls == [] and _demo_dirs(out) == []


def test_corrupt_llm_record_is_a_truthful_non_success_without_paths(dash, tmp_path):
    _server, url, out = dash
    _s, j = _start(dash, "llm")
    root = RunStore(str(out), j["run_id"]).root
    (root / "inputs" / "cases.json").unlink()   # the engine's error names the absolute path
    status, headers, raw = _get(url, f"/api/demos/run?id={j['run_id']}")
    view = json.loads(raw)
    assert status == 422 and view["record"] == "unverifiable"
    assert view["result"]["status"] == "BLOCKED" and "comparison" not in view["result"]
    text = raw.decode("utf-8")
    assert tmp_path.name not in text and "Traceback" not in text
    status, _h, page = _get(url, j["url"])
    assert status == 422 and b"could not be verified" in page and tmp_path.name.encode() not in page
    assert _get(url, f"/demos/export?id={j['run_id']}")[0] == 409


def test_corrupt_report_json_is_unverifiable(dash):
    _server, url, out = dash
    _s, j = _start(dash, "llm")
    (RunStore(str(out), j["run_id"]).root / "llm_eval_report.json").write_text("{broken",
                                                                                 encoding="utf-8")
    status, view = _get_json(url, f"/api/demos/run?id={j['run_id']}")
    assert status == 422 and view["record"] == "unverifiable"


def test_tampered_screenshot_is_never_served_or_shown_as_verified(dash, monkeypatch):
    _server, url, out = dash
    _install_stub_browser(monkeypatch)
    _s, j = _start(dash, "qa")
    shot = RunStore(str(out), j["run_id"]).root / "evidence" / "after.png"
    shot.write_bytes(_png(99))
    status, view = _get_json(url, f"/api/demos/run?id={j['run_id']}")
    assert status == 422 and view["record"] == "unverifiable"
    for side in ("before", "after"):
        assert _get(url, f"/demos/evidence?id={j['run_id']}&side={side}")[0] == 409
    assert b"FIX_VERIFIED" not in _get(url, j["url"])[2]


def _spy_reads(monkeypatch) -> list:
    """Record every Path.read_bytes / read_text call (they are what the core loaders use)."""
    reads: list = []
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def read_bytes(self, *a, **k):
        reads.append(Path(self))
        return real_bytes(self, *a, **k)

    def read_text(self, *a, **k):
        reads.append(Path(self))
        return real_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    return reads


def _inside(root: Path, reads: list) -> list:
    root = root.resolve()
    return [p for p in reads if root in p.resolve().parents]


def test_oversized_screenshot_is_refused_before_any_bytes_are_read(dash, monkeypatch):
    _server, url, out = dash
    _install_stub_browser(monkeypatch)
    _s, j = _start(dash, "qa")
    run_id, root = j["run_id"], RunStore(str(out), j["run_id"]).root
    monkeypatch.setattr(demos, "MAX_SCREENSHOT_BYTES", 8)
    reads = _spy_reads(monkeypatch)

    status, _h, raw = _get(url, f"/demos/evidence?id={run_id}&side=before")
    assert status == 413 and not raw.startswith(PNG_SIG)
    status, view = _get_json(url, f"/api/demos/run?id={run_id}")
    assert status == 422 and view["record"] == "unverifiable" and view["ok"] is False
    assert _get(url, f"/demos/export?id={run_id}")[0] == 409
    assert _get(url, f"/demos/run?id={run_id}")[0] == 422
    touched = _inside(root, reads)
    assert not [p for p in touched if p.suffix == ".png"], touched
    assert touched == []   # the preflight stopped before the core loader read anything

    monkeypatch.undo()     # declared limits restored: the same intact run serves normally
    status, headers, data = _get(url, f"/demos/evidence?id={run_id}&side=before")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert data == (root / "evidence" / "before.png").read_bytes()
    assert _get(url, f"/demos/export?id={run_id}")[0] == 200


def test_oversized_report_is_refused_before_the_loader_reads_it(dash, monkeypatch):
    _server, url, out = dash
    _s, j = _start(dash, "llm")
    run_id, root = j["run_id"], RunStore(str(out), j["run_id"]).root
    monkeypatch.setattr(demos, "MAX_REPORT_BYTES", 8)
    reads = _spy_reads(monkeypatch)
    status, view = _get_json(url, f"/api/demos/run?id={run_id}")
    assert status == 422 and view["record"] == "unverifiable"
    assert "size limit" in view["result"]["reason"]
    assert _inside(root, reads) == []
    monkeypatch.undo()
    status, view = _get_json(url, f"/api/demos/run?id={run_id}")
    assert status == 200 and view["record"] == "verified"


@pytest.mark.parametrize("side", ["", "middle", "BEFORE", "before.png", "../before",
                                  "evidence/before.png", "../../state.json"])
def test_evidence_side_is_a_fixed_enum(dash, monkeypatch, side):
    _server, url, _out = dash
    _install_stub_browser(monkeypatch)
    _s, j = _start(dash, "qa")
    status, _h, raw = _get(url, f"/demos/evidence?id={j['run_id']}&side={quote(side, safe='')}")
    assert status == 400 and not raw.startswith(PNG_SIG)


def test_evidence_is_only_for_qa_runs_in_the_demo_namespace(dash):
    _server, url, _out = dash
    _s, j = _start(dash, "llm")
    assert _get(url, f"/demos/evidence?id={j['run_id']}&side=before")[0] == 400
    for bad in ("../../etc", "scout-run-1", quote("demo-qa-x/../../y", safe="")):
        assert _get(url, f"/demos/evidence?id={bad}&side=before")[0] == 400
    assert _get(url, "/demos/evidence?id=demo-qa-neverran&side=before")[0] == 404


def test_export_is_an_escaped_attachment_built_from_the_verified_record(dash, monkeypatch):
    _server, url, _out = dash
    _s, llm = _start(dash, "llm")
    status, headers, raw = _get(url, f"/demos/export?id={llm['run_id']}")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert headers["Content-Disposition"] == f'attachment; filename="{llm["run_id"]}-report.html"'
    assert "sandbox" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    doc = raw.decode("utf-8")
    assert "<script" not in doc and llm["run_id"] in doc and "FIXTURE" in doc

    _install_stub_browser(monkeypatch)
    _s, qa = _start(dash, "qa")
    doc = _get(url, f"/demos/export?id={qa['run_id']}")[2].decode("utf-8")
    assert doc.count("data:image/png;base64,") == 2 and "<script" not in doc


def test_adversarial_record_text_is_escaped_everywhere(dash):
    server, url, out = dash

    def evil_llm(_out, run_id):   # STUB loader: hostile strings in every rendered field
        def side(status):
            return {"status": status, "raw_output": EVIL,
                    "checks": {"schema": {"status": "FAIL", "reason": EVIL}}}
        return {"run_id": run_id, "status": "COMPLETED", "mode": "FIXTURE",
                "verdict": "REGRESSION_DETECTED", "provenance": {}, "limitations": [EVIL],
                "started_at": EVIL, "finished_at": EVIL, "provider_called": False,
                "comparison": {"baseline": {"total": 1, "passed": 1, "pass_rate": 1.0},
                               "candidate": {"total": 1, "passed": 0, "pass_rate": 0.0},
                               "improved": [], "regressed": [EVIL], "unchanged": [],
                               "per_case": [{"case_id": EVIL, "category": EVIL, "change": EVIL,
                                             "baseline": side("PASS"), "candidate": side("FAIL")}]}}

    def evil_qa(_out, run_id):    # STUB loader
        obs = {"screenshot_ref": "", "error": EVIL, "axe_status": "ok",
               "axe_violations": [{"id": EVIL}]}
        return {"run_id": run_id, "status": "RETEST_FAILED", "reason": EVIL, "repair": EVIL,
                "resolved": [], "remaining": ["label"], "targeted_rules": list(TARGETS),
                "before": obs, "after": obs, "evidence": [{"path": EVIL, "content_hash": EVIL}],
                "limitations": [EVIL], "out_of_scope": {"before": [EVIL], "after": []},
                "tool": {"x": EVIL}, "fixture": EVIL, "started_at": EVIL, "finished_at": EVIL}

    server.demo_controller.loaders.update(llm=evil_llm, qa=evil_qa)
    for run_id in ("demo-llm-evil", "demo-qa-evil"):
        (out / "scout" / run_id).mkdir(parents=True)
        for path in (f"/demos/run?id={run_id}", "/demos", f"/demos/export?id={run_id}"):
            status, _h, raw = _get(url, path)
            page = raw.decode("utf-8")
            assert status == 200, (path, page[:300])
            assert "<script>alert" not in page and "<img src=x" not in page, path
            assert "&lt;script&gt;" in page or path == "/demos", path
        page = _get(url, f"/demos/run?id={run_id}")[2].decode("utf-8")
        assert page.count("<script") == 2   # only the Dashboard shell's own two scripts


def test_legacy_qa_record_stays_readable_and_new_ids_are_neutral(dash, monkeypatch):
    _server, url, out = dash
    _install_stub_browser(monkeypatch)
    _s, j = _start(dash, "qa")
    legacy_id = "demo-interview-" + j["run_id"].removeprefix("demo-qa-")
    root = RunStore(str(out), legacy_id).root
    shutil.copytree(RunStore(str(out), j["run_id"]).root, root)
    for name in ("qa_demo_report.json", "state.json", "config.json"):
        data = json.loads((root / name).read_text(encoding="utf-8"))
        data["run_id"] = legacy_id
        if "schema" in data:
            data["schema"] = "interview_qa_demo/v1"
        (root / name).write_text(json.dumps(data), encoding="utf-8")
    before = _tree(root)
    status, view = _get_json(url, f"/api/demos/run?id={legacy_id}")
    assert status == 200 and view["legacy"] is True and view["result"]["status"] == "FIX_VERIFIED"
    assert b"legacy record" in _get(url, f"/demos/run?id={legacy_id}")[2]
    assert _get(url, f"/demos/evidence?id={legacy_id}&side=after")[0] == 200
    assert _tree(root) == before
    assert all(not d.startswith("demo-interview-") or d == legacy_id for d in _demo_dirs(out))


def test_recent_runs_are_bounded_and_truncation_is_explicit(dash):
    _server, url, out = dash
    for i in range(22):
        llm_eval_demo.run_llm_eval_demo(str(out), f"demo-llm-seed{i:02d}")
    (out / "scout" / "campaign-not-a-demo").mkdir()
    page = _get(url, "/demos")[2].decode("utf-8")
    assert page.count('<td data-label="Run">') == 20
    assert "Showing the 20 most recent of 22 demo runs." in page
    assert "campaign-not-a-demo" not in page


# --- REAL browser acceptance -----------------------------------------------------------------------

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


def _assert_fits(page, label: str) -> None:
    for width in (1280, 390):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(150)
        scroll, client = page.evaluate(
            "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        assert scroll <= client, f"{label} overflows horizontally at {width}px ({scroll} > {client})"
    page.set_viewport_size({"width": 1280, "height": 900})


def _assert_qa_images_fit(page) -> None:
    """scrollWidth cannot see clipping (the base CSS hides horizontal overflow), so measure the
    screenshots themselves: side by side on desktop, fully inside the viewport at 390px."""
    imgs = page.locator(".demo-shots img")
    assert imgs.count() == 2
    page.set_viewport_size({"width": 1280, "height": 900})
    page.wait_for_timeout(150)
    first, second = imgs.nth(0).bounding_box(), imgs.nth(1).bounding_box()
    assert abs(first["y"] - second["y"]) < 1, (first, second)
    assert second["x"] >= first["x"] + first["width"] - 1, (first, second)
    page.set_viewport_size({"width": 390, "height": 900})
    page.wait_for_timeout(150)
    client = page.evaluate("() => document.documentElement.clientWidth")
    for i in range(2):
        box = imgs.nth(i).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= client + 0.5, (i, box, client)
    page.set_viewport_size({"width": 1280, "height": 900})


@pytest.mark.final1_browser_acceptance
def test_real_browser_runs_both_demos_and_reload_never_reruns(tmp_path):
    reason = _real_browser_skip_reason()
    if reason:
        pytest.skip(reason)
    from playwright.sync_api import sync_playwright

    out = tmp_path / "out"
    server, url = start_dashboard(ScoutService(str(out)), operator_home=True)
    calls = _count_runs(server)
    errors: list = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}")
                    if m.type == "error" else None)

            page.goto(url + "/demos", wait_until="load")
            _assert_fits(page, "/demos")

            # LLM Output Evaluation: click, wait for the result, reload without re-running.
            page.click("#run-llm")
            page.wait_for_url("**/demos/run?id=demo-llm-*", timeout=60_000)
            llm_id = page.url.split("id=", 1)[1]
            body = page.inner_text("main")
            assert "FIXTURE" in body and "REGRESSION_DETECTED" in body
            view = page.evaluate("async id => (await fetch('/api/demos/run?id=' + id)).json()",
                                 llm_id)
            for side in ("baseline", "candidate"):
                s = view["result"]["comparison"][side]
                assert f"{s['passed']}/{s['total']}" in body
            page.locator("details.demo-case summary").first.click()
            assert page.locator("details.demo-case").first.get_attribute("open") is not None
            assert "Prompt:" in page.inner_text("details.demo-case >> nth=0")
            _assert_fits(page, "LLM result")
            page.reload(wait_until="load")
            assert [c for c in calls if c[0] == "llm"] == [("llm", llm_id)]

            # QA Evidence & Retest by keyboard: visible focus, busy state, real captures.
            page.goto(url + "/demos", wait_until="load")
            for _ in range(40):
                page.keyboard.press("Tab")
                if page.evaluate("() => document.activeElement && document.activeElement.id") \
                        == "run-qa":
                    break
            else:
                pytest.fail("Run QA demo is not reachable by keyboard")
            outline = page.evaluate("() => { const s = getComputedStyle(document.activeElement);"
                                    " return [s.outlineStyle, s.outlineWidth]; }")
            assert outline[0] != "none" and outline[1] != "0px", outline
            page.keyboard.press("Enter")
            assert page.evaluate("() => ['run-qa', 'run-llm'].map("
                                 "i => document.getElementById(i).disabled)") == [True, True]
            assert page.inner_text("#demo-status").strip()
            page.wait_for_url("**/demos/run?id=demo-qa-*", timeout=180_000)
            qa_id = page.url.split("id=", 1)[1]
            assert "Scoped verdict: FIX_VERIFIED" in page.inner_text("main")
            loaded = page.evaluate("() => [...document.querySelectorAll('.demo-shots img')]"
                                   ".map(i => i.complete && i.naturalWidth > 0)")
            assert loaded == [True, True]
            _assert_fits(page, "QA result")
            _assert_qa_images_fit(page)
            page.reload(wait_until="load")
            assert page.evaluate("() => [...document.querySelectorAll('.demo-shots img')]"
                                 ".map(i => i.complete && i.naturalWidth > 0)") == [True, True]
            _assert_qa_images_fit(page)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    assert calls == [("llm", llm_id), ("qa", qa_id)]   # reloads and reads never re-executed
    assert _demo_dirs(out) == sorted([llm_id, qa_id])
    evidence = RunStore(str(out), qa_id).root / "evidence"
    assert (evidence / "before.png").read_bytes() != (evidence / "after.png").read_bytes()
    assert errors == []
