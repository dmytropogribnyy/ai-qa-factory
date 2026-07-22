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

from core.scout.curated_import import CuratedImportError, parse_curated_list
from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.service import ScoutService


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
    finally:
        server.shutdown()
