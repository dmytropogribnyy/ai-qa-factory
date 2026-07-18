"""v3.0.2 M6 - full operator lifecycle through the REAL public CLI (external process).

Invokes `python main.py ...` as a subprocess with a confined OUTPUT_DIR - no custom Python driver.
Proves a whole client job completes end to end (analyze -> status -> approve -> record-execution ->
validate -> review -> prepare-delivery -> mark-delivered) with real exit codes and real persisted
state, and that a brand-new process still reports COMPLETED. Negative cases prove the CLI refuses
every bypass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BRIEF = "Reproduce and fix a defect in a small Python module and add a regression test."


def _cli(args, output_dir, timeout=120):
    env = {**os.environ, "OUTPUT_DIR": str(output_dir), "LLM_MODE": "mock", "MODEL_PROFILE": "mock",
           "PROSPECT_RADAR_EXTERNAL_SEND_DISABLED": "1"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=str(_REPO), env=env,  # noqa: S603
                          capture_output=True, text=True, timeout=timeout, check=False)


def _ws(output_dir, pid):
    return Path(output_dir) / pid / "40_ark_work"


def _read(output_dir, pid, name):
    return json.loads((_ws(output_dir, pid) / name).read_text(encoding="utf-8"))


def _validate_argv(code):
    return json.dumps([sys.executable, "-c", code])


def _author_fix(output_dir, pid):
    ws = _ws(output_dir, pid)
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "notes.txt").write_text("regression: add(2,3)==5\n", encoding="utf-8")


def _reach(output_dir, pid, upto):
    """Drive the real CLI to a named lifecycle point; returns after the last step of 'upto'."""
    assert _cli(["analyze-job", "--project-id", pid, "--text", _BRIEF], output_dir).returncode == 0
    if upto == "analyzed":
        return
    assert _cli(["client-work", "approve", "--project-id", pid, "--reviewer", "op"],
                output_dir).returncode == 0
    _author_fix(output_dir, pid)
    assert _cli(["client-work", "record-execution", "--project-id", pid,
                 "--artifacts", "calc.py:fix", "--evidence", "evidence/notes.txt:regression"],
                output_dir).returncode == 0
    if upto == "recorded":
        return
    r = _cli(["client-work", "validate", "--project-id", pid,
              "--validation-argv-json", _validate_argv("import calc; assert calc.add(2, 3) == 5")],
             output_dir)
    assert r.returncode == 0, r.stderr
    if upto == "validated":
        return
    assert _cli(["client-work", "review", "--project-id", pid, "--reviewer", "op"],
                output_dir).returncode == 0
    if upto == "reviewed":
        return
    assert _cli(["client-work", "prepare-delivery", "--project-id", pid], output_dir).returncode == 0


def test_full_cli_lifecycle_completes_and_resumes(tmp_path):
    out = tmp_path / "outputs"
    pid = "clijob"

    assert _cli(["analyze-job", "--project-id", pid, "--text", _BRIEF], out).returncode == 0
    assert (_ws(out, pid) / "WORK_RUN_STATE.json").exists()

    st = _cli(["client-work", "status", "--project-id", pid], out)
    assert st.returncode == 0 and pid in st.stdout

    assert _cli(["client-work", "approve", "--project-id", pid, "--reviewer", "op"],
                out).returncode == 0
    _author_fix(out, pid)

    rec = _cli(["client-work", "record-execution", "--project-id", pid,
                "--artifacts", "calc.py:fix", "--evidence", "evidence/notes.txt:regression"], out)
    assert rec.returncode == 0

    val = _cli(["client-work", "validate", "--project-id", pid,
                "--validation-argv-json", _validate_argv("import calc; assert calc.add(2, 3) == 5")],
               out)
    assert val.returncode == 0 and "PASS" in val.stdout

    assert _cli(["client-work", "review", "--project-id", pid, "--reviewer", "op"],
                out).returncode == 0
    assert _cli(["client-work", "prepare-delivery", "--project-id", pid], out).returncode == 0
    deliver = _cli(["client-work", "mark-delivered", "--project-id", pid, "--note", "sent by hand"],
                   out)
    assert deliver.returncode == 0 and "COMPLETED" in deliver.stdout

    # Real persisted state: registered artifacts + validation evidence, hashes, review, manifest.
    state = _read(out, pid, "WORK_RUN_STATE.json")
    assert state["status"] == "COMPLETED"
    idx = _read(out, pid, "EVIDENCE_INDEX.json")
    paths = {e["relative_path"] for e in idx["evidence"]}
    assert "evidence/notes.txt" in paths
    assert any(p.startswith("evidence/validation/") for p in paths)      # registered validation evidence
    review = _read(out, pid, "REVIEW.json")
    assert review["approved"] is True and review["reviewer"] == "op"
    manifest = _read(out, pid, "WORK_DELIVERY_MANIFEST.json")
    assert manifest["manifest_digest"].startswith("sha256:")
    assert all(len(h) == 64 for h in manifest["artifact_hashes"].values())
    assert _read(out, pid, "DELIVERY_PREPARED.json")["manifest_digest"] == manifest["manifest_digest"]
    assert "sent nothing itself" in _read(out, pid, "DELIVERY_RECORD.json")["statement"]

    # A brand-new process (fresh CLI invocation) still reports COMPLETED (resume across processes).
    resumed = _cli(["client-work", "status", "--project-id", pid], out)
    assert resumed.returncode == 0 and "COMPLETED" in resumed.stdout


# --------------------------------------------------------------------------- negative CLI cases
def test_cli_invalid_project_id_is_rejected(tmp_path):
    out = tmp_path / "outputs"
    r = _cli(["client-work", "status", "--project-id", "../evil"], out)
    assert r.returncode != 0


def test_cli_traversal_artifact_is_rejected(tmp_path):
    out = tmp_path / "outputs"
    pid = "trav"
    _reach(out, pid, "analyzed")
    _cli(["client-work", "approve", "--project-id", pid, "--reviewer", "op"], out)
    (Path(out) / pid / "sentinel.txt").write_text("outside the workspace\n", encoding="utf-8")
    r = _cli(["client-work", "record-execution", "--project-id", pid,
              "--artifacts", "../sentinel.txt:report"], out)
    assert r.returncode != 0


def test_cli_missing_artifact_is_rejected(tmp_path):
    out = tmp_path / "outputs"
    pid = "miss"
    _reach(out, pid, "analyzed")
    _cli(["client-work", "approve", "--project-id", pid, "--reviewer", "op"], out)
    r = _cli(["client-work", "record-execution", "--project-id", pid,
              "--artifacts", "does_not_exist.py:fix"], out)
    assert r.returncode != 0 and "BLOCKED" in (r.stdout + r.stderr)


def test_cli_failed_validation_reports_nonzero(tmp_path):
    out = tmp_path / "outputs"
    pid = "failval"
    _reach(out, pid, "recorded")
    r = _cli(["client-work", "validate", "--project-id", pid,
              "--validation-argv-json", _validate_argv("raise SystemExit(1)")], out)
    assert r.returncode == 3 and "FAIL" in r.stdout


def test_cli_review_rejection_sends_to_repair(tmp_path):
    out = tmp_path / "outputs"
    pid = "reject"
    _reach(out, pid, "validated")
    rej = _cli(["client-work", "review", "--project-id", pid, "--reviewer", "op", "--reject"], out)
    assert rej.returncode == 0 and "REJECTED" in rej.stdout
    assert _read(out, pid, "WORK_RUN_STATE.json")["status"] == "REPAIR_REQUIRED"


def test_cli_mark_delivered_before_preparation_is_rejected(tmp_path):
    out = tmp_path / "outputs"
    pid = "early"
    _reach(out, pid, "reviewed")     # READY_FOR_DELIVERY, never prepared
    r = _cli(["client-work", "mark-delivered", "--project-id", pid], out)
    assert r.returncode != 0
    assert _read(out, pid, "WORK_RUN_STATE.json")["status"] == "READY_FOR_DELIVERY"


def test_cli_post_validation_mutation_blocks_delivery(tmp_path):
    out = tmp_path / "outputs"
    pid = "mutval"
    _reach(out, pid, "reviewed")
    (_ws(out, pid) / "calc.py").write_text("def add(a, b):\n    return 0  # tampered\n", encoding="utf-8")
    r = _cli(["client-work", "prepare-delivery", "--project-id", pid], out)
    assert r.returncode != 0 and "changed after validation" in (r.stdout + r.stderr)


def test_cli_post_preparation_mutation_blocks_completion(tmp_path):
    out = tmp_path / "outputs"
    pid = "mutprep"
    _reach(out, pid, "prepared")
    (_ws(out, pid) / "calc.py").write_text("def add(a, b):\n    return 0  # tampered\n", encoding="utf-8")
    r = _cli(["client-work", "mark-delivered", "--project-id", pid], out)
    assert r.returncode != 0 and "changed after preparation" in (r.stdout + r.stderr)


def test_cli_secret_containing_delivery_is_blocked(tmp_path):
    out = tmp_path / "outputs"
    pid = "secret"
    _reach(out, pid, "analyzed")
    _cli(["client-work", "approve", "--project-id", pid, "--reviewer", "op"], out)
    (_ws(out, pid) / "config.txt").write_text("aws_key=AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
    _cli(["client-work", "record-execution", "--project-id", pid, "--artifacts", "config.txt:report"],
         out)
    _cli(["client-work", "validate", "--project-id", pid,
          "--validation-argv-json", _validate_argv("print('ok')")], out)
    _cli(["client-work", "review", "--project-id", pid, "--reviewer", "op"], out)
    r = _cli(["client-work", "prepare-delivery", "--project-id", pid], out)
    assert r.returncode != 0 and "secret-like content" in (r.stdout + r.stderr)


@pytest.mark.parametrize("bad", ['{"not": "an array"}', "[]", "[oops", '["python", ""]'])
def test_cli_malformed_structured_argv_is_rejected(tmp_path, bad):
    out = tmp_path / "outputs"
    pid = "argv"
    _reach(out, pid, "recorded")
    r = _cli(["client-work", "validate", "--project-id", pid, "--validation-argv-json", bad], out)
    assert r.returncode == 1
