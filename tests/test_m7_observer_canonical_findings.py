"""M7 (+M8) — the Observer's findings surface publishes one explained canonical contract.

`ObserverAPI.list_findings()` bypassed the canonical split entirely: it flattened
`load_verified_findings()` across promoted runs, projected six fields, and reported
`total = len(rows)`. No `kind`, no dedup, no suppression — a raw count no other surface agreed with,
published beside `target_detail`'s canonical 10 / 8 actionable / 2 informational / 4 suppressed.
`get_finding()` read the same raw source, so a finding fetched by id also arrived unlabelled.

The fix must canonicalize **per exact persisted target**, never over a campaign-wide flattened pile.
That is not a stylistic preference. On this repository's own evidence, `actionable.py::_identity`
keys on `signature`; `checks.py` emits signatures that are rule identifiers with no site component
(`missing_canonical`, `a11y_axe_active`, `no_cache_control`, `axe:{rule}`); and `ScoutFinding` never
persists `kind`, so `_carried_decision()` returns `""` and the dedup always applies. Measured across
the real store: 433 verified rows, `prospect_ref` present on every one, and `missing_canonical`
alone appearing 33 times across different targets. A campaign-wide split would keep one of those 33
and file the other 32 as `duplicate of ...` — a systematic under-report wearing the word "canonical".

Contract implemented here is the reviewer's final option (a) (`5150571121`): bare `total` stays a
documented legacy raw-count alias also exposed as `raw_total`, the canonical collection is labelled
and paginated by its own explicit `canonical_total` / `page_count`, and a machine-readable
count-semantics object ties each number to what it counts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.scout.observer_api import ObserverAPI
from core.scout.store import RunStore

_CAMPAIGN = "campaign-m7-20260801t080000z-aa11bb"
_RUN = "scout-20260801t080000z-m7run"
_A = "01-alpha-example"
_B = "02-beta-example"

# A signature that legitimately occurs on BOTH targets. Its two rows must both survive: they are two
# sites with the same problem, not one problem reported twice.
_SHARED = "missing_canonical"


def _f(pid: str, n: int, *, signature: str, severity: str = "medium", url: str | None = None) -> dict:
    return {
        "finding_id": f"{pid}-{n}",
        "run_id": _RUN,
        "prospect_ref": pid,
        "url": url or f"https://{(pid.split('-', 1) + [pid])[1].replace('-', '.')}/page{n}",
        "check_family": "seo",
        "category": "seo",
        "title": f"{signature} on {pid}",
        "severity": severity,
        "confidence": "high",
        "signature": signature,
        "evidence_refs": [],
    }


def _seed(tmp_path: Path) -> None:
    """14 raw rows over two targets -> 10 canonical (8 actionable + 2 informational), 4 suppressed.

    The shape is the audit's own reproduction, built so every number in it is checkable by hand.
    """
    store = RunStore(str(tmp_path), _RUN)
    store.write_config({"campaign_name": "m7", "browser_mode": "static",
                        "check_families": ["seo", "links"]})

    # Target A: 8 raw -> 2 within-target duplicates suppressed -> 6 survivors (5 actionable + 1 info)
    a = [
        _f(_A, 1, signature=_SHARED),
        _f(_A, 2, signature="noindex"),
        _f(_A, 3, signature="img_missing_alt"),
        _f(_A, 4, signature="unlabeled_input"),
        _f(_A, 5, signature="no_cache_control"),
        _f(_A, 6, signature="perf_static_limitation", severity="info"),
        _f(_A, 7, signature="noindex"),            # duplicate INSIDE target A -> suppressed
        _f(_A, 8, signature="img_missing_alt"),    # duplicate INSIDE target A -> suppressed
    ]
    # Target B: 6 raw -> 2 within-target duplicates suppressed -> 4 survivors (3 actionable + 1 info)
    b = [
        _f(_B, 1, signature=_SHARED),              # SAME signature as A-1, different target
        _f(_B, 2, signature="missing_title"),
        _f(_B, 3, signature="a11y_axe_active"),
        _f(_B, 4, signature="console_static_limitation", severity="info"),
        _f(_B, 5, signature="missing_title"),      # duplicate INSIDE target B -> suppressed
        _f(_B, 6, signature="a11y_axe_active"),    # duplicate INSIDE target B -> suppressed
    ]
    store.save_state({"prospects": {_A: {"url": f"https://{_A}"}, _B: {"url": f"https://{_B}"}}})
    store.save_prospect_artifact(_A, "findings.json", {"verified": a})
    store.save_prospect_artifact(_B, "findings.json", {"verified": b})

    camp = RunStore(str(tmp_path), _CAMPAIGN)
    camp.write_config({"campaign_name": "m7-campaign", "browser_mode": "static"})
    camp.save_state({"candidates": [{"registrable_domain": "alpha.example",
                                     "promoted_scout_run": _RUN,
                                     "promotion_decision": "promoted"}]})


def _listing(tmp_path: Path, **kw) -> dict:
    _seed(tmp_path)
    return ObserverAPI(str(tmp_path)).list_findings(_CAMPAIGN, **kw)


# --- the fixture must reproduce the audit's shape, or nothing below means anything ---------------

def test_the_fixture_really_is_14_raw_rows(tmp_path):
    _seed(tmp_path)
    from core.scout.priority import load_verified_findings
    rows = load_verified_findings(RunStore(str(tmp_path), _RUN))
    assert len(rows) == 14, f"the fixture no longer reproduces the reported shape: {len(rows)}"


# --- discriminator 1: the same signature on two targets must survive twice -----------------------

def test_the_same_signature_on_two_targets_survives_twice(tmp_path):
    """The whole reason the split is per-target. Signatures name rules, not sites."""
    res = _listing(tmp_path)
    shared = [r for r in res.get("findings", []) if r.get("finding_id") in (f"{_A}-1", f"{_B}-1")]
    assert len(shared) == 2, (
        f"{_SHARED!r} occurs on two different targets and only {len(shared)} survived — a "
        f"campaign-wide split merged two sites' problems into one: "
        f"{[r.get('finding_id') for r in res.get('findings', [])]}"
    )
    assert {r.get("prospect_ref") or r.get("finding_id", "").split("-")[0] for r in shared}


# --- discriminator 2: a duplicate inside one target is suppressed, with a reason ------------------

def test_a_duplicate_inside_one_target_is_suppressed_once_and_explained(tmp_path):
    res = _listing(tmp_path)
    ids = {r.get("finding_id") for r in res.get("findings", [])}
    for dup in (f"{_A}-7", f"{_A}-8", f"{_B}-5", f"{_B}-6"):
        assert dup not in ids, f"{dup} duplicates an earlier finding in its own target and survived"
    summary = res.get("summary") or {}
    assert summary.get("suppressed") == 4, f"suppressed={summary.get('suppressed')}, expected 4"
    reasons = summary.get("suppressed_reasons") or []
    assert len(reasons) == 4 and all(str(r).strip() for r in reasons), (
        f"suppression is reported as a bare number with no explanation: {reasons}"
    )


# --- discriminator 3: the real shape is exactly explainable from ONE response ---------------------

def test_the_whole_raw_to_canonical_shape_is_explainable_from_one_response(tmp_path):
    res = _listing(tmp_path)
    summary = res.get("summary") or {}
    assert res.get("raw_total") == 14, f"raw_total={res.get('raw_total')}"
    assert res.get("canonical_total") == 10, f"canonical_total={res.get('canonical_total')}"
    assert summary.get("confirmed_issues") == 8, f"confirmed_issues={summary.get('confirmed_issues')}"
    assert summary.get("informational") == 2, f"informational={summary.get('informational')}"
    assert summary.get("suppressed") == 4, f"suppressed={summary.get('suppressed')}"
    assert summary.get("confirmed_issues", 0) + summary.get("informational", 0) == res["canonical_total"]
    assert res["raw_total"] == res["canonical_total"] + summary["suppressed"], (
        "the raw and canonical numbers do not reconcile, so the difference cannot be explained"
    )
    assert summary.get("severity_breakdown"), "no severity breakdown to explain the actionable count"


# --- discriminator 4: raw and canonical are never interchangeable --------------------------------

def test_total_is_a_documented_raw_alias_and_never_labels_the_canonical_list(tmp_path):
    """Option (a): `total` keeps its raw meaning for `run_validation`, and says so."""
    res = _listing(tmp_path)
    assert res.get("total") == res.get("raw_total") == 14, (
        f"total={res.get('total')} raw_total={res.get('raw_total')} — `total` must stay the raw count"
    )
    assert res.get("total") != res.get("canonical_total"), (
        "raw and canonical totals are equal here by accident of the fixture; that would make this "
        "test unable to tell them apart"
    )
    sem = res.get("count_semantics") or {}
    for key in ("total", "raw_total", "canonical_total", "page_count"):
        assert key in sem and str(sem[key]).strip(), (
            f"no machine-readable statement of what {key!r} counts: {sem}"
        )
    assert "raw" in str(sem["total"]).lower() and "raw" in str(sem["raw_total"]).lower()
    assert "canonical" in str(sem["canonical_total"]).lower()


# --- discriminator 5: pagination belongs to the canonical collection -----------------------------

def test_pagination_applies_to_the_canonical_collection_only(tmp_path):
    first = _listing(tmp_path, limit=4, offset=0)
    assert first.get("page_count") == len(first.get("findings", [])) == 4, (
        f"page_count={first.get('page_count')} rows={len(first.get('findings', []))}"
    )
    assert first.get("canonical_total") == 10, "the pre-pagination canonical total changed with a page"

    seen, offset = [], 0
    while offset < 10:
        page = _listing(tmp_path, limit=4, offset=offset)
        seen.extend(r["finding_id"] for r in page.get("findings", []))
        offset += 4
    assert len(seen) == 10 and len(set(seen)) == 10, (
        f"paging the canonical collection did not yield it exactly once: {len(seen)} rows, "
        f"{len(set(seen))} distinct"
    )


def test_every_returned_row_carries_the_decision_it_was_handed(tmp_path):
    res = _listing(tmp_path)
    for row in res.get("findings", []):
        assert row.get("kind") in ("actionable", "informational"), (
            f"{row.get('finding_id')} arrives unlabelled ({row.get('kind')!r}), so the reader has to "
            "re-derive the split from a projection that no longer carries the signature"
        )
    # The contract is "deterministic TARGET order, and canonical actionable-then-informational
    # order" — i.e. per target. A global regroup would satisfy a naive reading of the second half
    # while destroying the first, scattering each target's rows through the list.
    order = [(r["finding_id"].rsplit("-", 1)[0], r["kind"]) for r in res["findings"]]
    targets = [t for t, _ in order]
    assert targets == sorted(targets, key=targets.index), f"targets are interleaved: {targets}"
    for target in dict.fromkeys(targets):
        kinds = [k for t, k in order if t == target]
        assert kinds == sorted(kinds, key=lambda k: 0 if k == "actionable" else 1), (
            f"{target}: canonical order is not actionable-then-informational: {kinds}"
        )


# --- discriminator 6: single-item parity ---------------------------------------------------------

def test_get_finding_returns_the_same_labelled_row_as_the_listing(tmp_path):
    _seed(tmp_path)
    api = ObserverAPI(str(tmp_path))
    listed = api.list_findings(_CAMPAIGN).get("findings", [])
    assert listed, "nothing listed, so parity cannot be checked"
    for row in listed[:3]:
        one = api.get_finding(_CAMPAIGN, row["finding_id"]).get("finding")
        assert one == row, (
            f"get_finding disagrees with the listing for {row['finding_id']}:\n  listed: {row}\n"
            f"  single: {one}"
        )


def test_a_suppressed_finding_is_not_resurrected_unlabelled_by_get_finding(tmp_path):
    _seed(tmp_path)
    api = ObserverAPI(str(tmp_path))
    got = api.get_finding(_CAMPAIGN, f"{_A}-7")          # a within-target duplicate
    assert "finding" not in got or (got.get("finding") or {}).get("kind"), (
        f"a suppressed row comes back through the canonical single-item endpoint with no label: {got}"
    )


# --- discriminator 7: the AI review bundle carries labelled canonical rows ------------------------

def test_the_ai_review_bundle_receives_labelled_canonical_rows(tmp_path):
    _seed(tmp_path)
    api = ObserverAPI(str(tmp_path))
    written = api.export_ai_review_bundle(_CAMPAIGN)
    payload = json.loads((Path(tmp_path) / written["json"]).read_text(encoding="utf-8"))
    rows = payload.get("findings") or []
    assert rows, "the AI review bundle carried no findings"
    assert len(rows) == 10, f"the bundle received {len(rows)} rows, not the canonical 10"
    for row in rows:
        assert row.get("kind") in ("actionable", "informational"), (
            f"the bundle an external reviewer reads carries an unlabelled row: {row}"
        )


# --- the invariant that must survive the change --------------------------------------------------

def test_reads_leave_persisted_evidence_byte_and_mtime_unchanged(tmp_path):
    _seed(tmp_path)
    files = sorted((Path(tmp_path) / "scout" / _RUN / "prospects").glob("*/findings.json"))
    assert files, "no persisted findings to guard"
    before = [(p, hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files]

    api = ObserverAPI(str(tmp_path))
    api.list_findings(_CAMPAIGN)
    api.list_findings(_CAMPAIGN, limit=3, offset=3)
    api.get_finding(_CAMPAIGN, f"{_A}-1")
    api.export_ai_review_bundle(_CAMPAIGN)

    for path, sha, mtime in before:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, f"{path.name} was rewritten"
        assert path.stat().st_mtime_ns == mtime, f"{path.name} mtime moved"


# --- contract point 6: the raw validation comparison keeps its meaning ---------------------------

def test_the_observer_zero_findings_regression_is_still_caught(tmp_path, monkeypatch):
    """A GUARD, not a red discriminator — it passes before this change too, and says so.

    `run_validation.py` deliberately compares `list_findings(...)["total"]` against raw persisted
    rows: its own comment says comparing raw against the canonical actionable count "would
    manufacture a disagreement out of the split itself". M7 therefore leaves `total` raw. This test
    exists so that a later reading of the audit cannot quietly turn `total` canonical and break the
    detector that was built for the historic failure — a direct run reporting zero findings through
    the Observer while its own target pages listed them.
    """
    from core.scout.campaign_service import CampaignService
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.observer_api import ObserverAPI as _OA
    from core.scout.run_validation import FAIL, PASS, validate_run
    from core.scout.store import RunStore

    rows = [_f("01", 1, signature="noindex"), _f("01", 2, signature="img_missing_alt")]
    for r in rows:
        r["run_id"] = "run-zero"
        r["prospect_ref"] = "01"
        r["url"] = "https://zero.example/"

    store = RunStore(str(tmp_path), "run-zero")
    store.write_config({"campaign_name": "adhoc", "run_purpose": "production",
                        "seeds": ["https://zero.example/"],
                        "intake": {"kind": "paste", "rows_read": 1, "rows_accepted": 1,
                                   "rows_rejected": 0, "duplicates": 0, "rows_capped": 0}})
    store.save_state({"status": "COMPLETED", "started_at": "2026-08-01T09:00:00+00:00",
                      "finished_at": "2026-08-01T09:05:00+00:00", "prospects": {
                          "01": {"status": "DONE", "url": "https://zero.example/",
                                 "verified_findings": 2, "verified_defects": 2}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": rows})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("zero.example", status=ANALYZED,
                                                        campaign_id="run-zero")
    for ev in ("run_started", "prospect_done", "run_finished"):
        store.append_event({"event": ev, "prospect": "01"})

    healthy = validate_run(str(tmp_path), "run-zero", read_model=CampaignService(str(tmp_path)))
    healthy_check = {c.check_id: c for c in healthy.checks}["surface_agreement"]
    assert healthy_check.status == PASS, f"the baseline run does not validate: {healthy_check.observed}"

    # Now blind the Observer exactly as the historic defect did: the store still has the findings.
    real = _OA.list_findings
    monkeypatch.setattr(_OA, "list_findings",
                        lambda self, cid, **kw: {**real(self, cid, **kw), "total": 0})
    blinded = validate_run(str(tmp_path), "run-zero", read_model=CampaignService(str(tmp_path)))
    blinded_check = {c.check_id: c for c in blinded.checks}["surface_agreement"]
    assert blinded_check.status == FAIL, (
        "the Observer reports no finding for a run that has some, and validation still passes — the "
        f"regression detector was lost: {blinded_check.observed}"
    )
    assert "observer" in json.dumps(blinded_check.observed).lower()
