"""Phase 8.3 — Scout engine + store integration (deterministic fixtures, no browser)."""
from __future__ import annotations

import itertools

import pytest

from core.scout.config import ScoutRunConfig
from core.scout.control import RunControl
from core.scout.engine import ScoutEngine, RUN_COMPLETED, RUN_KILLED, P_DONE, P_MANUAL
from core.scout.store import RunStore, StoreCorruptionError
from tests.scout_fixtures import serve_fixtures

_SCENARIOS = ["clean", "broken_link", "accessibility", "seo", "structured_data",
              "mobile", "presubmit", "business_flow", "captcha", "access_prohibition"]


def _config(base, host, tmp, **kw):
    seeds = [f"{base}/{name}/index.html" for name in _SCENARIOS]
    base_kw = dict(campaign_name="e2e", seeds=seeds, allowed_local_hosts=frozenset({host}),
                   browser_mode="static", output_dir=str(tmp), max_pages_per_site=6)
    base_kw.update(kw)
    return ScoutRunConfig(**base_kw)


_counter = itertools.count()


def _clock():
    return f"2026-07-17T00:00:{next(_counter):02d}+00:00"


class TestEngineE2E:
    def test_full_pipeline(self, tmp_path):
        with serve_fixtures() as (base, host):
            cfg = _config(base, host, tmp_path)
            store = RunStore(str(tmp_path), "run-e2e")
            state = ScoutEngine(cfg, store, clock=_clock).run()

        assert state["status"] == RUN_COMPLETED
        prospects = state["prospects"]
        # CAPTCHA and access-prohibition become manual-action (identified by URL).
        manual_urls = {p["url"] for p in prospects.values() if p["status"] == P_MANUAL}
        assert any("captcha" in u for u in manual_urls)
        assert any("access_prohibition" in u for u in manual_urls)
        # The safe rest completed.
        done = [p for p in prospects.values() if p["status"] == P_DONE]
        assert len(done) >= 6
        # At least one verified defect exists across the run.
        assert sum(p.get("verified_defects", 0) for p in prospects.values()) >= 1

    def test_clean_control_yields_no_defects(self, tmp_path):
        with serve_fixtures() as (base, host):
            cfg = _config(base, host, tmp_path, seeds=[f"{base}/clean/index.html"])
            store = RunStore(str(tmp_path), "run-clean")
            state = ScoutEngine(cfg, store, clock=_clock).run()
        pid = next(iter(state["prospects"]))
        assert state["prospects"][pid]["status"] == P_DONE
        assert state["prospects"][pid].get("verified_defects", 0) == 0

    def test_verified_findings_are_client_safe(self, tmp_path):
        with serve_fixtures() as (base, host):
            cfg = _config(base, host, tmp_path,
                          seeds=[f"{base}/seo/index.html", f"{base}/mobile/index.html"])
            store = RunStore(str(tmp_path), "run-safe")
            ScoutEngine(cfg, store, clock=_clock).run()
            data = store.load_prospect_artifact("01-127-0-0-1", "findings.json")
        assert data and data["verified"]
        assert all(f["is_client_safe"] for f in data["verified"])

    def test_global_kill_stops_work(self, tmp_path):
        with serve_fixtures() as (base, host):
            cfg = _config(base, host, tmp_path)
            store = RunStore(str(tmp_path), "run-kill")
            control = RunControl()
            control.kill()  # kill before any work
            state = ScoutEngine(cfg, store, control=control, clock=_clock).run()
        assert state["status"] == RUN_KILLED
        assert all(p["status"] != P_DONE for p in state["prospects"].values())

    def test_interrupted_run_resumes(self, tmp_path):
        with serve_fixtures() as (base, host):
            control = RunControl()

            def _cancel_after_first(event):
                if event.get("event") == "prospect_done":
                    control.cancel()

            cfg = _config(base, host, tmp_path)
            store = RunStore(str(tmp_path), "run-resume")
            first = ScoutEngine(cfg, store, control=control, clock=_clock,
                                progress=_cancel_after_first).run()
            done_first = sum(1 for p in first["prospects"].values() if p["status"] == P_DONE)
            assert first["status"] == "CANCELLED"
            assert done_first >= 1
            pending_first = sum(1 for p in first["prospects"].values() if p["status"] == "PENDING")
            assert pending_first >= 1

            # Resume with a fresh control: completed prospects are skipped, run finishes.
            cfg2 = _config(base, host, tmp_path, resume=True)
            resumed = ScoutEngine(cfg2, store, control=RunControl(), clock=_clock).run()
        assert resumed["status"] == RUN_COMPLETED
        # No prospect regressed to PENDING.
        assert not any(p["status"] == "PENDING" for p in resumed["prospects"].values())


class TestStore:
    def test_corruption_fails_closed(self, tmp_path):
        store = RunStore(str(tmp_path), "run-corrupt")
        store.save_state({"status": "RUNNING"})
        (store.root / "state.json").write_text("{ not json", encoding="utf-8")
        with pytest.raises(StoreCorruptionError):
            store.load_state()

    def test_atomic_write_survives_and_path_confined(self, tmp_path):
        store = RunStore(str(tmp_path), "run-x")
        store.save_state({"a": 1})
        store.save_state({"a": 2})   # overwrite atomically
        assert store.load_state()["a"] == 2
        from core.scout.store import StoreError
        with pytest.raises(StoreError):
            store.save_prospect_artifact("../escape", "x.json", {})

    def test_unsafe_run_id_rejected(self, tmp_path):
        from core.scout.store import StoreError
        with pytest.raises(StoreError):
            RunStore(str(tmp_path), "../evil")
