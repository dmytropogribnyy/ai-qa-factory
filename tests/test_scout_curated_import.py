"""Scout — curated-list import (XLSX/CSV) parsing for Manual Scan.

A bounded, security-hardened file-import layer over the EXISTING manual seed workflow: it parses an
uploaded .xlsx/.csv into canonical seed domains + display-only metadata and a disposition against the
existing AnalyzedSiteRegistry. It never persists the workbook, never executes formulas/macros, treats
every cell as untrusted data, and enforces hard ceilings. Launch reuses the manual Scout path.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import urllib.error
import urllib.request

import pytest

from core.scout.backends import PageObservation
from core.scout.campaign_service import CampaignService
from core.scout.config import ScoutRunConfig
from core.scout.curated_import import CuratedImportError, parse_curated_list
from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.service import ScoutService
from core.scout.store import RunStore


def _csv_bytes(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode("utf-8")


def _xlsx_bytes(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# -- happy path -------------------------------------------------------------------------------------


def test_csv_url_column_parsed_to_canonical_seeds():
    data = _csv_bytes([["Company", "URL"], ["Acme", "https://www.acme.com/pricing"],
                       ["Beta", "beta.io"]])
    res = parse_curated_list(data, "list.csv")
    assert res.kind == "csv" and res.column.lower() == "url"
    doms = {r.canonical_domain: r for r in res.rows}
    assert "acme.com" in doms and doms["acme.com"].seed_url == "https://acme.com"
    assert "beta.io" in doms                              # bare domain -> canonical + https seed
    assert res.counters["valid_unique"] == 2


def test_xlsx_scout_seed_url_column_and_metadata_preserved():
    data = _xlsx_bytes([["Scout seed URL", "Product", "Priority"],
                        ["https://shop.example/", "Store", "A"]])
    res = parse_curated_list(data, "curated.xlsx")
    assert res.kind == "xlsx"
    row = res.rows[0]
    assert row.canonical_domain == "shop.example"
    assert row.metadata.get("Product") == "Store" and row.metadata.get("Priority") == "A"


def test_dedup_within_file_and_invalid_rows_counted():
    data = _csv_bytes([["Website"], ["acme.com"], ["https://acme.com/x"], ["not a url"], [""]])
    res = parse_curated_list(data, "l.csv")
    assert res.counters["dup_in_file"] == 1              # the 2nd acme is a duplicate
    assert res.counters["valid_unique"] == 1
    assert res.counters["invalid"] >= 1                  # "not a url" / blank


def test_registry_disposition_marks_already_analyzed_and_rejected(tmp_path):
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.record_analysis("done.com", status="analyzed")
    reg.record_rejection("spam.com", "not a company")
    data = _csv_bytes([["Domain"], ["done.com"], ["spam.com"], ["fresh.com"]])
    res = parse_curated_list(data, "l.csv", registry=reg)
    disp = {r.canonical_domain: r.disposition for r in res.rows}
    assert disp["done.com"] == "already_analyzed"
    assert disp["spam.com"] == "rejected"
    assert disp["fresh.com"] == "new"


# -- security bounds --------------------------------------------------------------------------------


def test_rejects_unsupported_extension():
    with pytest.raises(CuratedImportError):
        parse_curated_list(b"whatever", "legacy.xls")     # .xls / .xlsm / macros are refused


def test_rejects_oversized_file():
    with pytest.raises(CuratedImportError):
        parse_curated_list(b"x" * (5_000_001), "big.csv", max_bytes=5_000_000)


def test_rejects_when_no_url_or_domain_column():
    data = _csv_bytes([["Name", "Notes"], ["Acme", "hello"]])
    with pytest.raises(CuratedImportError):
        parse_curated_list(data, "l.csv")


def test_rejects_too_many_rows():
    rows = [["URL"]] + [[f"d{i}.com"] for i in range(600)]
    with pytest.raises(CuratedImportError):
        parse_curated_list(_csv_bytes(rows), "l.csv", max_rows=500)


def test_malformed_xlsx_is_refused_not_crashed():
    with pytest.raises(CuratedImportError):
        parse_curated_list(b"PK\x03\x04 not really a workbook", "bad.xlsx")


def test_row_limit_is_exact_no_off_by_one():
    ok = [["URL"]] + [[f"d{i}.com"] for i in range(500)]       # exactly 500 data rows -> allowed
    assert parse_curated_list(_csv_bytes(ok), "l.csv", max_rows=500).counters["total"] == 500
    over = [["URL"]] + [[f"d{i}.com"] for i in range(501)]     # 501 data rows -> refused
    with pytest.raises(CuratedImportError):
        parse_curated_list(_csv_bytes(over), "l.csv", max_rows=500)


def test_rejects_too_many_columns_early():
    wide = [["URL"] + [f"c{i}" for i in range(40)], ["acme.com"] + ["x"] * 40]   # 41 columns
    with pytest.raises(CuratedImportError):
        parse_curated_list(_csv_bytes(wide), "l.csv", max_cols=40)


def test_malformed_csv_oversized_field_is_refused_not_crashed():
    huge = "x" * 200000                                        # exceeds csv's default field-size limit
    with pytest.raises(CuratedImportError):
        parse_curated_list(("URL\n" + huge + "\n").encode(), "l.csv")   # csv.Error wrapped, not a 500


def test_zip_bomb_ratio_is_refused_before_openpyxl():
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("payload.bin", b"\x00" * (10 * 1024 * 1024))   # 10MB zeros -> tiny; ratio huge
    with pytest.raises(CuratedImportError):
        parse_curated_list(buf.getvalue(), "bomb.xlsx")


# -- golden path: Recommended-action preselection + metadata ---------------------------------------


def test_recommended_action_preselects_only_scout_now():
    data = _csv_bytes([["URL", "Recommended action", "Priority"],
                       ["a.com", "Scout now", "A"], ["b.com", "Backlog", "C"],
                       ["c.com", "scout now", "B"], ["d.com", "Exclude", "D"]])   # case-insensitive
    res = parse_curated_list(data, "l.csv")
    assert res.has_recommended_action is True
    pre = {r.canonical_domain: r.preselect for r in res.rows}
    assert pre == {"a.com": True, "b.com": False, "c.com": True, "d.com": False}
    assert res.counters["preselected"] == 2


def test_without_recommended_action_preselects_valid_new_only(tmp_path):
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.record_analysis("done.com", status="analyzed")
    res = parse_curated_list(_csv_bytes([["URL"], ["fresh.com"], ["done.com"]]), "l.csv", registry=reg)
    assert res.has_recommended_action is False
    pre = {r.canonical_domain: r.preselect for r in res.rows}
    assert pre["fresh.com"] is True and pre["done.com"] is False   # already-analyzed never preselected


def test_metadata_columns_captured_and_recommended_action_exposed():
    data = _csv_bytes([["url", "Product", "Priority", "Weighted score", "Recommended action"],
                       ["a.com", "Widget", "A", "87", "Scout now"]])
    row = parse_curated_list(data, "l.csv").rows[0]
    assert row.metadata.get("Product") == "Widget" and row.metadata.get("Weighted score") == "87"
    assert row.recommended_action == "Scout now"


def test_formula_like_cell_is_treated_as_untrusted_text_never_evaluated():
    # A cell that looks like a formula must be handled as data (and rejected as a non-URL), never run.
    data = _csv_bytes([["URL"], ["=cmd|' /c calc'!A1"], ["good.com"]])
    res = parse_curated_list(data, "l.csv")
    doms = {r.canonical_domain for r in res.rows if r.valid}
    assert doms == {"good.com"}                            # the formula-like row is invalid, not run


# -- guarded /api/scout/import endpoint (loopback HTTP) --------------------------------------------


def _post_import(url, filename, data_bytes, csrf=None):
    body = {"filename": filename, "content_b64": base64.b64encode(data_bytes).decode()}
    headers = {"Content-Type": "application/json"}
    if csrf:
        headers["X-Scout-CSRF"] = csrf
    req = urllib.request.Request(url + "/api/scout/import", method="POST",
                                 data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_import_endpoint_refused_without_csrf(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        code, _ = _post_import(url, "l.csv", _csv_bytes([["URL"], ["acme.com"]]))
        assert code == 403                                # the shared mutation guard refuses it
    finally:
        server.shutdown()


def test_import_endpoint_parses_and_persists_manifest_only(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/api/csrf", timeout=5) as r:
            csrf = json.loads(r.read())["csrf_token"]
        code, out = _post_import(url, "curated.csv",
                                 _csv_bytes([["URL"], ["acme.com"], ["beta.io"]]), csrf=csrf)
        assert code == 200 and out["ok"] is True
        res = out["result"]
        assert res["counters"]["valid_unique"] == 2
        assert {r["canonical_domain"] for r in res["rows"]} == {"acme.com", "beta.io"}
        assert out["manifest_saved"] is True              # persistence reported honestly
        manifest = tmp_path / "scout" / "_imports" / (res["import_id"] + ".json")
        assert manifest.exists()                          # the parsed manifest is persisted
    finally:
        server.shutdown()


def test_manual_scan_page_shows_import_ui(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/scout", timeout=5) as r:
            body = r.read().decode()
        assert 'id="impfile"' in body and "function importList()" in body   # upload + parse wired
        assert "/api/scout/import" in body                                  # posts to the guarded endpoint
        assert "impconfirm" in body                                         # launch requires explicit confirm
    finally:
        server.shutdown()


# -- golden path: imported/manual run registers completed targets in History + Target detail --------


class _FakeAnalyzeBackend:
    """A no-network backend: every seed yields a valid observation so the engine reaches P_DONE and
    the domain is registered as analyzed (proves the manual/imported run -> History/Target model)."""
    name = "static"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                               title="T", meta_description="d", html_bytes=1000,
                               headings=[{"level": 1, "text": "h"}], landmarks={"main": 1},
                               headers={"content-type": "text/html", "cache-control": "max-age=60"})


def test_register_analyzed_run_puts_completed_targets_in_history(tmp_path):
    svc = ScoutService(str(tmp_path))
    store = RunStore(str(tmp_path), "curated-run-1")
    state = {"prospects": {"01-a": {"status": "DONE", "url": "https://acme.com/"},
                           "02-b": {"status": "FAILED", "url": "https://broken.com/"}}}
    svc._register_analyzed_run(store, state)
    hist = {r["domain"] for r in CampaignService(str(tmp_path)).history()}
    assert "acme.com" in hist and "broken.com" not in hist    # only DONE targets are registered


def test_target_detail_resolves_a_manual_run_via_registry(tmp_path):
    # A manual run registers run_id as the domain's campaign; target_detail must find its findings.
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.record_analysis("acme.com", status=ANALYZED, campaign_id="curated-run-9")
    store = RunStore(str(tmp_path), "curated-run-9")
    store.save_state({"status": "COMPLETED", "prospects": {"01-a": {"status": "DONE"}}})
    store.save_prospect_artifact("01-a", "findings.json", {"verified": [
        {"finding_id": "f1", "signature": "missing_meta_description", "category": "seo",
         "severity": "low", "title": "Missing meta description", "is_client_safe": True}], "rejected": []})
    detail = CampaignService(str(tmp_path)).target_detail("acme.com")
    assert detail.get("entry") is not None
    assert detail.get("scout_run") == "curated-run-9"          # resolved via the registry campaign id
    assert any(f.get("title") == "Missing meta description" for f in (detail.get("findings") or []))


def test_curated_import_end_to_end_launch_history_target_no_dupes(tmp_path):
    rows = [["URL", "Recommended action", "Product", "Weighted score"]]
    rows += [[f"scoutnow{i}.com", "Scout now", f"P{i}", str(90 - i)] for i in range(10)]
    rows += [[f"backlog{i}.com", "Backlog", f"B{i}", str(40 - i)] for i in range(5)]
    res = parse_curated_list(_xlsx_bytes(rows), "curated.xlsx")
    assert res.counters["total"] == 15 and res.counters["preselected"] == 10   # 10 Scout now, 5 Backlog
    selected = [r.seed_url for r in res.rows if r.preselect]
    assert len(selected) == 10 and all("scoutnow" in s for s in selected)

    svc = ScoutService(str(tmp_path))
    svc.start(ScoutRunConfig(campaign_name="curated", seeds=selected, browser_mode="static",
                             resolve_dns=False, output_dir=str(tmp_path)), backend=_FakeAnalyzeBackend())
    svc.join(timeout=60)
    cs = CampaignService(str(tmp_path))
    hist = {r["domain"] for r in cs.history()}
    assert "scoutnow0.com" in hist and "backlog0.com" not in hist   # only launched (Scout now) targets
    detail = cs.target_detail("scoutnow0.com")
    assert detail.get("entry") is not None                          # target detail opens for it

    before = len(cs.history())                                      # re-run the same target -> no dup row
    svc2 = ScoutService(str(tmp_path))
    svc2.start(ScoutRunConfig(campaign_name="curated2", seeds=["https://scoutnow0.com"],
                              browser_mode="static", resolve_dns=False, output_dir=str(tmp_path)),
               backend=_FakeAnalyzeBackend())
    svc2.join(timeout=60)
    assert len(cs.history()) == before
