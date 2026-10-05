"""LLM Output Evaluation — a bounded, offline evaluator for raw model outputs.

Grades raw output strings for a controlled extractive-QA task against the gold in
``fixtures/llm_eval_demo/cases.json``. Checks: ``schema`` (one strict JSON object with exactly
answer:str, abstain:bool, citations:unique str list; NaN/Infinity/duplicate keys invalid),
``abstention``, ``reference_match`` (trim + collapse whitespace + casefold, then exact match —
reference matching, NOT semantic entailment, factuality or hallucination detection),
``citations`` (set equals the gold source ids) and ``canary`` (planted synthetic token must not
leak — canary detection, not a prompt-injection defence). A check that did not run is
NOT_EVALUATED, never PASS. Any per-case regression yields REGRESSION_DETECTED even when the
average improves: a demo comparison policy, not release authorization.

Runs persist under ``<output_dir>/scout/<run_id>/`` via RunStore (config, exact input snapshots,
JSON report, offline HTML export, then ``state.json`` last). No model, provider or network is
called. The store is not tamper-proof against its own user; ``load_llm_eval_demo`` re-derives
the result from the saved inputs and refuses inconsistent records.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.orchestration.content_safety import ContentSecretScanner
from core.scout.store import RunStore, StoreError

EVALUATOR_VERSION = "llm-eval-demo/1.0"
EVALUATOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "llm_eval_demo"
CASES_PATH, RESPONSES_PATH = FIXTURE_DIR / "cases.json", FIXTURE_DIR / "responses.json"
MAX_IMPORT_BYTES = 1024 * 1024
REPORT_NAME, REPORT_HTML = "llm_eval_report.json", "report/llm_eval_report.html"
REPORT_SCHEMA = "llm-eval-demo-report/1"
CHECKS = ("schema", "abstention", "reference_match", "citations", "canary")
_OUTPUT_KEYS = {"answer", "abstain", "citations"}
_CASE_KEYS = {"id", "category", "prompt", "context", "expected"}
_PROVENANCE_KEYS = {"provider", "model", "prompt_version", "recorded_at"}
_RECORDED_KEYS = {"mode", "dataset_sha256", "provenance", "baseline", "candidate"}
_RUN_ID = re.compile(r"demo-llm-[A-Za-z0-9_-]+")

_COMMON_LIMITS = [
    "Reference matching is normalized exact string matching against gold answers; it is not "
    "semantic entailment, factuality or hallucination detection.",
    "The canary check only detects a planted synthetic token (canary detection); it is not a "
    "complete prompt-injection defence.",
    "REGRESSION_DETECTED / IMPROVED / STABLE is a demo comparison policy, not production "
    "release authorization.",
    "This run called no model or provider; cost and latency are unknown (null), not zero.",
]
_MODE_LIMITS = {
    "FIXTURE": "FIXTURE mode: outputs are constructed test examples, not captured inference "
               "responses; scores exercise the evaluator, not measured model performance.",
    "RECORDED": "RECORDED mode: outputs were imported from a local file; provider, model, prompt "
                "version and recording time are user-declared and not verified, and no live "
                "provider execution is proven.",
}


# --- strict JSON / small helpers -----------------------------------------------------------------

def _no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def _reject_non_finite(token):
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("non-finite numbers are not valid JSON")
    return value


def _strict_json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_reject_non_finite, parse_float=_reject_non_finite)
    except RecursionError:  # pathologically nested input is malformed, not a crash
        raise ValueError("JSON is nested too deeply") from None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _parse_time(value: Any) -> Optional[datetime]:
    """A timezone-aware ISO 8601 timestamp, or None (missing, nonsense, naive or invalid)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


# --- dataset -------------------------------------------------------------------------------------

def _validate_case(case: Any) -> None:
    cid = case.get("id") if isinstance(case, dict) else None
    if not isinstance(cid, str) or not cid.strip():
        raise ValueError("case must be an object with a non-empty string id")
    if not _CASE_KEYS <= set(case) or set(case) - _CASE_KEYS - {"canary"}:
        raise ValueError(f"case {cid}: fields must be {sorted(_CASE_KEYS)} (+ optional canary)")
    if not all(isinstance(case[k], str) and case[k].strip() for k in ("category", "prompt")):
        raise ValueError(f"case {cid}: category and prompt must be non-empty strings")
    context, exp = case["context"], case["expected"]
    if not isinstance(context, dict) or not context or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in context.items()):
        raise ValueError(f"case {cid}: context must map source ids to text")
    if "canary" in case and not (isinstance(case["canary"], str) and case["canary"].strip()):
        raise ValueError(f"case {cid}: canary must be a non-empty string")
    if not isinstance(exp, dict) or set(exp) != {"abstain", "answers", "citations"} \
            or not isinstance(exp["abstain"], bool) or not _str_list(exp["answers"]) \
            or not _str_list(exp["citations"]) or len(set(exp["citations"])) != len(exp["citations"]):
        raise ValueError(f"case {cid}: expected must be {{abstain: bool, answers, citations}}")
    if not set(exp["citations"]) <= set(context):
        raise ValueError(f"case {cid}: gold citations must be context source ids")
    if exp["abstain"] == bool(exp["answers"] or exp["citations"]) or \
            (not exp["abstain"] and not (exp["answers"] and exp["citations"])):
        raise ValueError(f"case {cid}: abstention gold has no answers/citations; answerable gold has both")


def _load_dataset(data: bytes) -> Dict[str, Any]:
    doc = _strict_json(data.decode("utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("version"), str) \
            or not isinstance(doc.get("cases"), list):
        raise ValueError("dataset must be an object with a version and a cases list")
    return doc


def load_cases() -> List[Dict[str, Any]]:
    """Return the versioned fixture cases (located relative to this module, not the cwd)."""
    return _load_dataset(CASES_PATH.read_bytes())["cases"]


# --- single-output evaluation --------------------------------------------------------------------

def _check(status: str, reason: str) -> Dict[str, str]:
    return {"status": status, "reason": reason}


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _parse_output(raw: str) -> Tuple[Optional[dict], str]:
    try:
        data = _strict_json(raw)
    except ValueError as exc:
        return None, f"not a single strict JSON value: {exc}"
    if not isinstance(data, dict):
        return None, "output is not a JSON object"
    if set(data) != _OUTPUT_KEYS:
        return None, (f"fields must be exactly answer/abstain/citations (missing "
                      f"{sorted(_OUTPUT_KEYS - set(data))}, unknown {sorted(set(data) - _OUTPUT_KEYS)})")
    if not isinstance(data["answer"], str):
        return None, "answer must be a string"
    if not isinstance(data["abstain"], bool):
        return None, "abstain must be a JSON boolean"
    cites = data["citations"]
    if not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
        return None, "citations must be a list of strings"
    if len(set(cites)) != len(cites):
        return None, "citations must be unique"
    return data, ""


def evaluate_output(case: Dict[str, Any], raw_output: str) -> Dict[str, Any]:
    """Grade one raw output string against one case's gold. Never executes anything."""
    _validate_case(case)
    if not isinstance(raw_output, str):
        raise TypeError("raw_output must be the raw model output string")
    canary, checks = case.get("canary"), {}
    if canary is None:
        checks["canary"] = _check("NOT_EVALUATED", "case has no canary token")
    elif canary.casefold() in raw_output.casefold():
        checks["canary"] = _check("FAIL", "synthetic canary token leaked into the output")
    else:
        checks["canary"] = _check("PASS", "synthetic canary token absent (canary detection only)")
    parsed, error = _parse_output(raw_output)
    if parsed is None:
        checks["schema"] = _check("FAIL", error)
        for name in ("abstention", "reference_match", "citations"):
            checks[name] = _check("NOT_EVALUATED", "output schema invalid")
    else:
        checks["schema"] = _check("PASS", "strict {answer, abstain, citations} object")
        _grade_answer(case["expected"], case["context"], parsed, checks)
    failed = [n for n in CHECKS if checks[n]["status"] == "FAIL"]
    return {"case_id": case["id"], "category": case["category"],
            "status": "FAIL" if failed else "PASS", "raw_output": raw_output, "parsed": parsed,
            "checks": {n: checks[n] for n in CHECKS}}


def _grade_answer(exp: dict, context: dict, out: dict, checks: dict) -> None:
    if exp["abstain"]:
        checks["abstention"] = (
            _check("FAIL", "answered although the documents lack the answer") if not out["abstain"]
            else _check("FAIL", "abstained but answer/citations are not empty")
            if out["answer"].strip() or out["citations"] else _check("PASS", "correctly abstained"))
    else:
        checks["abstention"] = (_check("FAIL", "abstained on an answerable question") if out["abstain"]
                                else _check("PASS", "answered an answerable question"))
    if exp["abstain"] or out["abstain"]:
        why = "not applicable: " + ("gold expects abstention" if exp["abstain"] else "output abstained")
        checks["reference_match"], checks["citations"] = (_check("NOT_EVALUATED", why),
                                                          _check("NOT_EVALUATED", why))
        return
    matched = _norm(out["answer"]) in {_norm(a) for a in exp["answers"]}
    checks["reference_match"] = _check("PASS" if matched else "FAIL", (
        "normalized exact match with an allowed answer" if matched else
        "no normalized exact match with an allowed answer") + " (reference match, not semantic entailment)")
    got, want = set(out["citations"]), set(exp["citations"])
    checks["citations"] = _check("PASS", "citation set equals the gold source ids") if got == want \
        else _check("FAIL", f"unknown {sorted(got - set(context))}, missing {sorted(want - got)}, "
                            f"not gold {sorted((got & set(context)) - want)}")


# --- pair comparison -----------------------------------------------------------------------------

def _rate(statuses: List[str]) -> Dict[str, Any]:
    passed = sum(s == "PASS" for s in statuses)
    return {"total": len(statuses), "passed": passed, "failed": len(statuses) - passed,
            "pass_rate": passed / len(statuses)}


def _string_map(value: Any, side: str, ids: List[str]) -> Dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise ValueError(f"{side} must map case id -> raw output string")
    if set(value) != set(ids):
        raise ValueError(f"{side} must cover exactly the dataset case ids (missing "
                         f"{sorted(set(ids) - set(value))}, extra {sorted(set(value) - set(ids))})")
    return value


def evaluate_pair(cases: List[Dict[str, Any]], baseline_outputs: Dict[str, str],
                  candidate_outputs: Dict[str, str]) -> Dict[str, Any]:
    """Grade both sides on exactly the same case ids and apply the demo regression policy."""
    if not isinstance(cases, list) or not cases:
        raise ValueError("dataset is empty")
    for case in cases:
        _validate_case(case)
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("dataset has duplicate case ids")
    _string_map(baseline_outputs, "baseline", ids)
    _string_map(candidate_outputs, "candidate", ids)
    per_case, changes = [], {"improved": [], "regressed": [], "unchanged": []}
    for case in cases:
        base = evaluate_output(case, baseline_outputs[case["id"]])
        cand = evaluate_output(case, candidate_outputs[case["id"]])
        pair = (base["status"], cand["status"])
        change = ("improved" if pair == ("FAIL", "PASS") else
                  "regressed" if pair == ("PASS", "FAIL") else "unchanged")
        changes[change].append(case["id"])
        per_case.append({"case_id": case["id"], "category": case["category"],
                         "baseline": base, "candidate": cand, "change": change})
    categories = list(dict.fromkeys(c["category"] for c in cases))
    summaries = {}
    for side in ("baseline", "candidate"):
        summaries[side] = {**_rate([p[side]["status"] for p in per_case]), "by_category": {
            cat: _rate([p[side]["status"] for p in per_case if p["category"] == cat])
            for cat in categories}}
    verdict = ("REGRESSION_DETECTED" if changes["regressed"] else
               "IMPROVED" if changes["improved"] else "STABLE")
    return {"verdict": verdict, **summaries, **changes, "per_case": per_case}


# --- inputs --------------------------------------------------------------------------------------

def _parse_fixture(data: bytes, ids: List[str]) -> Tuple[dict, dict, dict]:
    doc = _strict_json(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("mode") != "fixture" \
            or not set(doc) <= {"mode", "dataset_version", "note", "baseline", "candidate"}:
        raise ValueError("fixture responses must be {mode: 'fixture', baseline, candidate}")
    return (_string_map(doc.get("baseline"), "baseline", ids),
            _string_map(doc.get("candidate"), "candidate", ids), {})


def _refuse_secrets(texts: List[str]) -> None:
    scanner = ContentSecretScanner()
    labels = sorted({f.split(":")[-1] for t in texts for f in scanner.scan_text("responses", t)})
    if labels:  # pattern labels only — the secret itself is never echoed
        raise ValueError(f"imported responses contain secret-like content ({', '.join(labels)}); "
                         "refusing to persist them")


def _parse_recorded(data: bytes, dataset_sha256: str, ids: List[str]) -> Tuple[dict, dict, dict]:
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError("recorded responses exceed the 1 MiB limit")
    text = data.decode("utf-8")
    _refuse_secrets([text])
    doc = _strict_json(text)
    if not isinstance(doc, dict) or set(doc) != _RECORDED_KEYS:
        raise ValueError(f"recorded responses must have exactly {sorted(_RECORDED_KEYS)} "
                         "(caller-provided summaries or scores are not accepted)")
    if doc["mode"] != "recorded":
        raise ValueError("recorded responses must declare mode 'recorded'")
    if doc["dataset_sha256"] != dataset_sha256:
        raise ValueError("dataset_sha256 does not match the current cases.json")
    prov = doc["provenance"]
    if not isinstance(prov, dict) or set(prov) != _PROVENANCE_KEYS \
            or not all(isinstance(v, str) and v.strip() for v in prov.values()):
        raise ValueError(f"provenance must have non-empty string fields {sorted(_PROVENANCE_KEYS)}")
    baseline = _string_map(doc["baseline"], "baseline", ids)
    candidate = _string_map(doc["candidate"], "candidate", ids)
    _refuse_secrets([*prov.values(), *baseline.values(), *candidate.values()])  # escaped forms
    return baseline, candidate, prov


def _read_import(responses_path) -> bytes:
    path = Path(responses_path)
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("recorded responses exceed the 1 MiB limit")
    return path.read_bytes()


def _store(output_dir: str, run_id: str) -> RunStore:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError(f"unsafe run_id {run_id!r}: expected demo-llm-[A-Za-z0-9_-]+")
    try:
        return RunStore(str(output_dir), run_id)
    except StoreError as exc:
        raise ValueError(str(exc)) from exc


def _case_ids(dataset: dict) -> List[str]:
    return [c.get("id") for c in dataset["cases"] if isinstance(c, dict)]


# --- run / load ----------------------------------------------------------------------------------

def run_llm_eval_demo(output_dir: str, run_id: str,
                      responses_path: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate fixture (default) or imported recorded outputs into a fresh run. No provider call."""
    store = _store(output_dir, run_id)
    if store.root.exists():
        raise FileExistsError(f"run {run_id} already exists; runs are never overwritten")
    started_at = _now()
    cases_bytes = CASES_PATH.read_bytes()
    dataset = _load_dataset(cases_bytes)
    if responses_path is None:
        mode, resp_bytes = "FIXTURE", RESPONSES_PATH.read_bytes()
        baseline, candidate, provenance = _parse_fixture(resp_bytes, _case_ids(dataset))
    else:
        mode, resp_bytes = "RECORDED", _read_import(responses_path)
        baseline, candidate, provenance = _parse_recorded(resp_bytes, _sha(cases_bytes),
                                                          _case_ids(dataset))
    comparison = evaluate_pair(dataset["cases"], baseline, candidate)
    report = {
        "schema": REPORT_SCHEMA, "run_id": run_id, "status": "COMPLETED", "mode": mode,
        "origin": "fixture" if mode == "FIXTURE" else "user_declared", "provenance": provenance,
        "provider_called": False, "provider_execution_verified": False,
        "model": None, "cost_usd": None, "latency_ms": None,
        "verdict": comparison["verdict"], "comparison": comparison,
        "dataset_id": dataset.get("dataset_id"), "dataset_version": dataset["version"],
        "dataset_sha256": _sha(cases_bytes), "responses_sha256": _sha(resp_bytes),
        "evaluator_version": EVALUATOR_VERSION, "evaluator_sha256": EVALUATOR_SHA256,
        "started_at": started_at, "finished_at": _now(),
        "limitations": _COMMON_LIMITS + [_MODE_LIMITS[mode]], "report_html": REPORT_HTML,
    }
    html_bytes = _render_html(report).encode("utf-8")
    # Everything is validated and rendered in memory; only now claim the fresh run directory.
    store.root.mkdir(parents=True, exist_ok=False)
    store.write_config({"run_id": run_id, "mode": mode, "evaluator_version": EVALUATOR_VERSION})
    store.save_bytes(["inputs", "cases.json"], cases_bytes)
    store.save_bytes(["inputs", "responses.json"], resp_bytes)
    store.save_artifact(REPORT_NAME, report)
    store.save_bytes(REPORT_HTML.split("/"), html_bytes)
    store.save_state({"run_id": run_id, "status": "COMPLETED", "verdict": report["verdict"],
                      "started_at": started_at, "finished_at": report["finished_at"]})
    return report


class _Blocked(Exception):
    pass


def _require(condition: Any, reason: str) -> None:
    if not condition:
        raise _Blocked(reason)


def load_llm_eval_demo(output_dir: str, run_id: str) -> Dict[str, Any]:
    """Read a persisted run, re-derive it from its saved inputs, refuse inconsistencies."""
    store = _store(output_dir, run_id)
    try:
        return _verify(store, run_id)
    except (_Blocked, StoreError) as exc:
        reason = str(exc)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError) as exc:
        reason = f"persisted record is malformed ({type(exc).__name__}: {exc})"
    return {"run_id": run_id, "status": "BLOCKED", "reason": reason}


def _verify(store: RunStore, run_id: str) -> Dict[str, Any]:
    _require(store.root.is_dir(), "run does not exist")
    state = store.load_state()
    _require(isinstance(state, dict) and state.get("run_id") == run_id
             and state.get("status") == "COMPLETED", "state.json is not this run's terminal marker")
    started, finished = _parse_time(state.get("started_at")), _parse_time(state.get("finished_at"))
    _require(started is not None and finished is not None,
             "state timestamps are missing or not timezone-aware ISO 8601")
    _require(started <= finished, "state started_at is after finished_at")  # real times, any offset
    report = store.load_artifact(REPORT_NAME)
    _require(isinstance(report, dict) and report.get("schema") == REPORT_SCHEMA
             and report.get("run_id") == run_id and report.get("status") == "COMPLETED",
             "report is missing, of an unknown schema, or not this completed run")
    _require(all(report.get(k) == state.get(k) for k in ("started_at", "finished_at", "verdict")),
             "report does not match the terminal state")
    mode = report.get("mode")
    _require(mode in _MODE_LIMITS and report.get("origin") ==
             ("fixture" if mode == "FIXTURE" else "user_declared"), "unknown mode/origin label")
    _require(report.get("provider_called") is False and report.get("provider_execution_verified") is False
             and all(k in report and report[k] is None for k in ("model", "cost_usd", "latency_ms")),
             "report claims provider execution or measured cost/latency this demo never produces")
    _require(report.get("report_html") == REPORT_HTML and (store.root / REPORT_HTML).is_file(),
             "HTML export is missing")
    _require(_str_list(report.get("limitations")) and report["limitations"], "limitations missing")
    cases_bytes = (store.root / "inputs" / "cases.json").read_bytes()
    resp_bytes = (store.root / "inputs" / "responses.json").read_bytes()
    _require(_sha(cases_bytes) == report.get("dataset_sha256"), "dataset snapshot hash mismatch")
    _require(_sha(resp_bytes) == report.get("responses_sha256"), "responses snapshot hash mismatch")
    if (report.get("evaluator_sha256"), report.get("evaluator_version")) != (EVALUATOR_SHA256,
                                                                             EVALUATOR_VERSION):
        return {"run_id": run_id, "status": "REVIEW_REQUIRED", "mode": mode,
                "reason": "evaluator source changed since this run was recorded; the stored result "
                          "is not re-interpreted automatically - review required",
                "recorded_evaluator_sha256": report.get("evaluator_sha256"),
                "current_evaluator_sha256": EVALUATOR_SHA256}
    dataset = _load_dataset(cases_bytes)
    parse = _parse_fixture if mode == "FIXTURE" else (
        lambda data, ids: _parse_recorded(data, _sha(cases_bytes), ids))
    baseline, candidate, provenance = parse(resp_bytes, _case_ids(dataset))
    _require(report.get("provenance") == provenance, "provenance does not match the snapshot")
    recomputed = json.loads(json.dumps(evaluate_pair(dataset["cases"], baseline, candidate)))
    _require(report.get("comparison") == recomputed and report["verdict"] == recomputed["verdict"],
             "stored comparison differs from re-evaluating the saved inputs")
    return report


# --- offline HTML export (static, escaped, no scripts or external resources) ---------------------

def _render_html(r: Dict[str, Any]) -> str:
    def e(value: Any) -> str:
        return html.escape(str(value), quote=True)

    cmp, sides = r["comparison"], ("baseline", "candidate")
    by_cat = "".join(f"<tr><td>{e(cat)}</td>" + "".join(
        f"<td>{cmp[s]['by_category'][cat]['passed']}/{cmp[s]['by_category'][cat]['total']}</td>"
        for s in sides) + "</tr>" for cat in cmp["baseline"]["by_category"])

    def failed(ev: Dict[str, Any]) -> str:
        return ", ".join(n for n, c in ev["checks"].items() if c["status"] == "FAIL") or "none"

    rows = ""
    for p in cmp["per_case"]:
        cells = "".join(f"<td>{e(p[s]['status'])}<br><small>failed: {e(failed(p[s]))}</small>"
                        f"<pre>{e(p[s]['raw_output'])}</pre></td>" for s in sides)
        rows += (f"<tr class='{e(p['change'])}'><td>{e(p['case_id'])}</td><td>{e(p['category'])}</td>"
                 f"{cells}<td>{e(p['change'])}</td></tr>\n")
    totals = " | ".join(f"{s}: {cmp[s]['passed']}/{cmp[s]['total']} passed" for s in sides)
    prov = json.dumps(r["provenance"], sort_keys=True) if r["provenance"] else "none (fixture)"
    limits = "".join(f"<li>{e(x)}</li>" for x in r["limitations"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>LLM Output Evaluation {e(r['run_id'])}</title>
<style>body{{font-family:sans-serif;margin:2em}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:4px;vertical-align:top}}pre{{white-space:pre-wrap;max-width:32em}}
.regressed{{background:#fdd}}.improved{{background:#dfd}}</style></head><body>
<h1>LLM Output Evaluation</h1>
<p>Run <b>{e(r['run_id'])}</b> &middot; mode <b>{e(r['mode'])}</b> &middot; origin {e(r['origin'])}
&middot; verdict <b>{e(r['verdict'])}</b> (demo comparison policy, not release authorization)</p>
<p>{e(totals)}. Improved: {e(', '.join(cmp['improved']) or 'none')}.
Regressed: {e(', '.join(cmp['regressed']) or 'none')}.</p>
<p>Provenance: {e(prov)} &middot; provider called by this run: {e(r['provider_called'])}
&middot; provider execution verified: {e(r['provider_execution_verified'])}
&middot; model, cost, latency: unknown</p>
<p>Dataset {e(r['dataset_id'])} v{e(r['dataset_version'])} sha256 {e(r['dataset_sha256'])}<br>
Responses sha256 {e(r['responses_sha256'])}<br>
Evaluator {e(r['evaluator_version'])} sha256 {e(r['evaluator_sha256'])}<br>
Started {e(r['started_at'])} &middot; finished {e(r['finished_at'])}</p>
<h2>Limitations</h2><ul>{limits}</ul>
<h2>By category (passed/total)</h2>
<table><tr><th>category</th><th>baseline</th><th>candidate</th></tr>{by_cat}</table>
<h2>Per case</h2>
<table><tr><th>case</th><th>category</th><th>baseline</th><th>candidate</th><th>change</th></tr>
{rows}</table>
</body></html>
"""
