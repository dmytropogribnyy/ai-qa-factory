"""Phase 8.3.1 — dashboard/control integration through the real HTTP API.

Proves the controls actually drive an active, service-owned run (pause halts progress,
resume continues, cancel → CANCELLED, kill → KILLED) and that a read-only attached run
fail-closes (HTTP 409) instead of pretending a control succeeded. A gated backend makes the
transitions deterministic (no sleeps/races). No external network, no browser.
"""
from __future__ import annotations

import itertools
import json
import threading
import time
import urllib.error
import urllib.request

from core.scout.backends import StaticHttpBackend
from core.scout.config import ScoutRunConfig
from core.scout.dashboard import start_dashboard
from core.scout.engine import RUN_CANCELLED, RUN_COMPLETED, RUN_KILLED
from core.scout.service import ScoutService
from tests.scout_fixtures import serve_fixtures

_clock_counter = itertools.count()


def _clock():
    return f"2026-07-17T04:00:{next(_clock_counter):02d}+00:00"


class _GatedBackend:
    """Wraps StaticHttpBackend but blocks the FIRST observe() until released, so a control
    signal can be applied deterministically while the run is provably in flight."""

    name = "static"

    def __init__(self, inner: StaticHttpBackend) -> None:
        self._inner = inner
        self.entered = threading.Event()
        self._release = threading.Event()

    def release(self) -> None:
        self._release.set()

    def observe(self, url, timeout_s, max_bytes):
        if not self._release.is_set():
            self.entered.set()
            self._release.wait(timeout=10)
        return self._inner.observe(url, timeout_s, max_bytes)


def _seeds(base, names):
    return [f"{base}/{n}/index.html" for n in names]


def _cfg(base, host, tmp, names, run_id):
    return ScoutRunConfig(campaign_name="ctl", seeds=_seeds(base, names),
                          allowed_local_hosts=frozenset({host}), browser_mode="static",
                          output_dir=str(tmp), run_id=run_id, max_pages_per_site=3)


def _post(url):
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _status(url):
    with urllib.request.urlopen(url + "/api/status", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def _done_count(state):
    return sum(1 for p in state.get("prospects", {}).values() if p.get("status") == "DONE")


def test_pause_halts_then_resume_completes(tmp_path):
    with serve_fixtures() as (base, host):
        names = ("clean", "seo", "mobile", "accessibility", "structured_data")
        gated = _GatedBackend(StaticHttpBackend(
            policy=ScoutRunConfig(campaign_name="c", seeds=["https://x/"],
                                  allowed_local_hosts=frozenset({host})).url_policy()))
        svc = ScoutService(str(tmp_path))
        server, url = start_dashboard(svc)
        try:
            svc.start(_cfg(base, host, tmp_path, names, "pause-run"), clock=_clock, backend=gated)
            assert gated.entered.wait(timeout=5)     # worker is inside the first observe()

            code, body = _post(url + "/api/control?action=pause")
            assert code == 200 and body["ok"] is True
            assert _status(url)["controllable"] is True and _status(url)["mode"] == "ACTIVE"

            gated.release()                          # first observe returns; second-pass gate blocks
            time.sleep(0.3)
            paused = _status(url)
            assert paused["control"]["paused"] is True
            assert _done_count(paused["state"]) == 0  # no prospect completes while paused

            code, body = _post(url + "/api/control?action=resume")
            assert code == 200 and body["ok"] is True
            svc.join(timeout=30)
            final = _status(url)
            assert final["state"]["status"] == RUN_COMPLETED
            assert _done_count(final["state"]) >= 1
        finally:
            server.shutdown()


def test_cancel_produces_cancelled(tmp_path):
    with serve_fixtures() as (base, host):
        names = ("clean", "seo", "mobile", "accessibility")
        gated = _GatedBackend(StaticHttpBackend(
            policy=ScoutRunConfig(campaign_name="c", seeds=["https://x/"],
                                  allowed_local_hosts=frozenset({host})).url_policy()))
        svc = ScoutService(str(tmp_path))
        server, url = start_dashboard(svc)
        try:
            svc.start(_cfg(base, host, tmp_path, names, "cancel-run"), clock=_clock, backend=gated)
            assert gated.entered.wait(timeout=5)
            code, body = _post(url + "/api/control?action=cancel")
            assert code == 200 and body["ok"] is True
            gated.release()
            svc.join(timeout=30)
            assert _status(url)["state"]["status"] == RUN_CANCELLED
        finally:
            server.shutdown()


def test_global_kill_produces_killed(tmp_path):
    with serve_fixtures() as (base, host):
        names = ("clean", "seo", "mobile", "accessibility", "broken_link")
        gated = _GatedBackend(StaticHttpBackend(
            policy=ScoutRunConfig(campaign_name="c", seeds=["https://x/"],
                                  allowed_local_hosts=frozenset({host})).url_policy()))
        svc = ScoutService(str(tmp_path))
        server, url = start_dashboard(svc)
        try:
            svc.start(_cfg(base, host, tmp_path, names, "kill-run"), clock=_clock, backend=gated)
            assert gated.entered.wait(timeout=5)
            code, body = _post(url + "/api/control?action=kill")
            assert code == 200 and body["ok"] is True
            gated.release()
            svc.join(timeout=30)
            final = _status(url)
            assert final["state"]["status"] == RUN_KILLED
            assert svc.is_running() is False
        finally:
            server.shutdown()


def test_attached_finished_run_rejects_control(tmp_path):
    with serve_fixtures() as (base, host):
        # Produce a finished run with an owning service...
        owner = ScoutService(str(tmp_path))
        owner.start(_cfg(base, host, tmp_path, ("clean", "seo"), "attach-run"), clock=_clock)
        owner.join(timeout=30)
        # ...then attach READ-ONLY from a fresh service and serve it.
        viewer = ScoutService(str(tmp_path))
        viewer.attach("attach-run")
        server, url = start_dashboard(viewer)
        try:
            st = _status(url)
            assert st["mode"] == "READ_ONLY_ATTACHED" and st["controllable"] is False
            assert st["state"]["status"] == RUN_COMPLETED
            for action in ("pause", "resume", "cancel", "kill"):
                code, body = _post(url + f"/api/control?action={action}")
                assert code == 409 and body["ok"] is False  # no fake success
            # HTML overview hides controls for a read-only run.
            with urllib.request.urlopen(url + "/", timeout=5) as r:
                html = r.read().decode("utf-8")
            assert "Controls unavailable" in html and "GLOBAL KILL" not in html
        finally:
            server.shutdown()


def test_cross_origin_control_refused(tmp_path):
    with serve_fixtures() as (base, host):
        svc = ScoutService(str(tmp_path))
        svc.start(_cfg(base, host, tmp_path, ("clean",), "origin-run"), clock=_clock)
        svc.join(timeout=30)
        server, url = start_dashboard(svc)
        try:
            req = urllib.request.Request(url + "/api/control?action=kill", method="POST",
                                         headers={"Origin": "http://evil.example"})
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("cross-origin control should be refused")
            except urllib.error.HTTPError as e:
                assert e.code == 403
        finally:
            server.shutdown()
