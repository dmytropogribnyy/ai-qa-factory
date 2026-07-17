"""Phase 8.3.1 — run-id uniqueness + fail-closed resume/reuse semantics.

Proves a fresh scan never silently reuses (or mixes into) an existing run directory, and that
resume requires the same immutable configuration. Deterministic; no external network/browser.
"""
from __future__ import annotations

import itertools
import types

import pytest

from core.scout.cli import cmd_run
from core.scout.config import ScoutRunConfig, fresh_run_id, make_run_id
from core.scout.engine import ScoutEngine, RUN_COMPLETED
from core.scout.store import RunStore, StoreError
from tests.scout_fixtures import serve_fixtures

_counter = itertools.count()


def _clock():
    return f"2026-07-17T03:00:{next(_counter):02d}+00:00"


def _cfg(base, host, tmp, names=("clean",), **kw):
    seeds = [f"{base}/{n}/index.html" for n in names]
    kwargs = dict(campaign_name="rid", seeds=seeds, allowed_local_hosts=frozenset({host}),
                  browser_mode="static", output_dir=str(tmp), max_pages_per_site=4)
    kwargs.update(kw)
    return ScoutRunConfig(**kwargs)


def test_fresh_run_ids_are_unique():
    a, b = fresh_run_id("acme"), fresh_run_id("acme")
    assert a != b
    assert a.startswith("acme-") and b.startswith("acme-")


def test_make_run_id_is_deterministic():
    a = make_run_id("acme", ["https://x/"], "2026-01-01T00:00:00+00:00")
    b = make_run_id("acme", ["https://x/"], "2026-01-01T00:00:00+00:00")
    assert a == b  # explicit/demo ids stay stable; only fresh_run_id adds entropy


def test_fresh_run_refuses_existing_run_dir(tmp_path):
    with serve_fixtures() as (base, host):
        cfg = _cfg(base, host, tmp_path)
        state = ScoutEngine(cfg, RunStore(str(tmp_path), "run-x"), clock=_clock).run()
        assert state["status"] == RUN_COMPLETED
        # A second FRESH run reusing the same id must fail closed (no stale mixing).
        cfg2 = _cfg(base, host, tmp_path)
        with pytest.raises(StoreError):
            ScoutEngine(cfg2, RunStore(str(tmp_path), "run-x"), clock=_clock).run()


def test_resume_requires_existing_run(tmp_path):
    with serve_fixtures() as (base, host):
        cfg = _cfg(base, host, tmp_path, resume=True)
        with pytest.raises(StoreError):
            ScoutEngine(cfg, RunStore(str(tmp_path), "ghost"), clock=_clock).run()


def test_resume_rejects_changed_config(tmp_path):
    with serve_fixtures() as (base, host):
        ScoutEngine(_cfg(base, host, tmp_path, names=("clean",)),
                    RunStore(str(tmp_path), "run-y"), clock=_clock).run()
        # Resume with different seeds must not resume (and pollute) the original run.
        changed = _cfg(base, host, tmp_path, names=("seo",), resume=True)
        with pytest.raises(StoreError):
            ScoutEngine(changed, RunStore(str(tmp_path), "run-y"), clock=_clock).run()


def test_resume_with_matching_config_is_allowed(tmp_path):
    with serve_fixtures() as (base, host):
        ScoutEngine(_cfg(base, host, tmp_path, names=("clean", "seo")),
                    RunStore(str(tmp_path), "run-z"), clock=_clock).run()
        resumed = ScoutEngine(_cfg(base, host, tmp_path, names=("clean", "seo"), resume=True),
                              RunStore(str(tmp_path), "run-z"), clock=_clock).run()
    assert resumed["status"] == RUN_COMPLETED


def test_store_reset_is_path_confined(tmp_path):
    store = RunStore(str(tmp_path), "resettable")
    store.save_state({"status": "RUNNING"})
    assert store.exists()
    store.reset()
    assert not store.exists()
    assert not store.root.exists()


def test_cli_resume_without_run_id_fails(capsys):
    args = types.SimpleNamespace(
        seeds="https://example.com/", url=None, campaign="x", output="outputs",
        browser="static", max_sites=10, max_pages=5, concurrency=1, run_id="", resume=True)
    assert cmd_run(args) == 1
    assert "resume requires an explicit --run-id" in capsys.readouterr().err
