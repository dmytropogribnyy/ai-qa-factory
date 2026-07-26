"""Scout — a hard interruption between findings.json and the compact state update leaves a prospect
PENDING while its confirmed findings are already on disk.

The engine turns ordinary failures into FAILED (engine.py:151), but that handler catches Exception;
KeyboardInterrupt and SystemExit derive from BaseException and pass straight through. This test
persists that exact state so the operator-surface contract can be pinned against something real.
"""
from __future__ import annotations

import pytest

from core.scout.backends import PageObservation
from core.scout.config import ScoutRunConfig
from core.scout.engine import ScoutEngine
from core.scout.store import RunStore


class _OkBackend:
    name = "static"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                               title="T", meta_description="", html_bytes=1000,
                               headings=[{"level": 1, "text": "h"}], landmarks={"main": 1},
                               headers={"content-type": "text/html"})


def test_interruption_after_findings_write_leaves_pending_with_findings(tmp_path, monkeypatch):
    cfg = ScoutRunConfig(campaign_name="seam", browser_mode="static", resolve_dns=False,
                         output_dir=str(tmp_path), run_id="interrupted-run",
                         seeds=["https://first.example/", "https://second.example/"])
    store = RunStore(str(tmp_path), "interrupted-run")

    real_save = RunStore.save_prospect_artifact
    interrupted: list[str] = []
    findings_writes: list[str] = []

    def _save_then_interrupt(self, pid, name, obj):
        # Perform the REAL write first — interrupting before it would prove nothing.
        ref = real_save(self, pid, name, obj)
        if name == "findings.json":
            findings_writes.append(pid)
            # engine.run() only flushes the PENDING-populated prospects dict to state.json
            # AFTER a prospect's processing completes (engine.py:155-156); the very first
            # prospect processed has no prior state.json save that contains its PENDING entry
            # (the line-115 save happens before the PENDING-population loop). Interrupting on
            # the SECOND prospect's findings.json write reproduces the real scenario: prospect
            # #1's completed state is already flushed to disk, and prospect #2 is caught with
            # its confirmed findings written but its compact-state entry still PENDING.
            if len(findings_writes) == 2 and not interrupted:
                interrupted.append(pid)
                raise KeyboardInterrupt("hard stop after findings.json")
        return ref

    monkeypatch.setattr(RunStore, "save_prospect_artifact", _save_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        ScoutEngine(cfg, store, backend=_OkBackend()).run()

    hit = interrupted[0]
    state = RunStore(str(tmp_path), "interrupted-run").load_state()
    prospect = state["prospects"][hit]

    assert prospect["status"] == "PENDING"                     # the compact state never advanced
    assert "verified_defects" not in prospect                  # counters are written only with DONE
    findings = store.load_prospect_artifact(hit, "findings.json")
    assert findings is not None and "verified" in findings     # the artifact IS on disk
    assert state["status"] != "COMPLETED"                      # the run itself is left unfinished
