"""v3.0.0 Milestone 4b - the guarded localhost campaign-START endpoint.

Covers the policy core (CampaignLauncher) and the HTTP guards (loopback Host, Origin, CSRF):
explicit confirmation, idempotency, one-active-campaign, persist-before-execution, unsafe-target
rejection, request-cannot-widen-allowlist, restart recovery, and a safe stop then restart. No real
network, browser, email, or scan happens - the injected starter records the bounded config only.
"""
from __future__ import annotations

import http.client
import json

from core.scout.campaign_start import CampaignLauncher
from core.scout.dashboard import start_dashboard

_FIXTURE_HOST = "127.0.0.1:8931"
_FIXTURE_SEED = "http://127.0.0.1:8931/"


class _FakeService:
    """Minimal ScoutService stand-in: precise control over is_running() without a real engine."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        self._running = False
        self.started_configs = []
        self.controls = []
        self.run_id = ""

    def start(self, cfg):
        if self._running:
            raise RuntimeError("a run is already active")
        self._running = True
        self.run_id = cfg.run_id
        self.started_configs.append(cfg)
        return cfg.run_id

    def is_running(self) -> bool:
        return self._running

    def control(self, action):
        self.controls.append(action)
        if action in ("cancel", "kill"):
            self._running = False
        return True, 200, "ok"

    def status(self):
        return {"running": self._running, "mode": "ACTIVE" if self._running else "IDLE",
                "controllable": self._running, "run_id": self.run_id, "state": {}, "control": {}}


def _launcher(tmp_path, service=None, starter=None, allow_fixture=True):
    service = service or _FakeService(str(tmp_path))
    return CampaignLauncher(
        service, registry_dir=str(tmp_path / "registry"),
        allowed_local_hosts=frozenset({_FIXTURE_HOST} if allow_fixture else set()),
        resolve_dns=False, starter=starter or service.start), service


def _req(confirm=True, key="k1", seeds=None, **extra):
    body = {"confirm": confirm, "idempotency_key": key, "seeds": seeds or [_FIXTURE_SEED]}
    body.update(extra)
    return body


# --------------------------------------------------------------------------- policy core

def test_requires_explicit_confirmation(tmp_path):
    launcher, _ = _launcher(tmp_path)
    r = launcher.start(_req(confirm=False))
    assert not r.ok and r.status == 400 and "confirm" in r.message


def test_requires_idempotency_key(tmp_path):
    launcher, _ = _launcher(tmp_path)
    r = launcher.start({"confirm": True, "seeds": [_FIXTURE_SEED]})
    assert not r.ok and r.status == 400 and "idempotency_key" in r.message


def test_rejects_unsafe_targets_with_reasons(tmp_path):
    launcher, svc = _launcher(tmp_path, allow_fixture=False)
    r = launcher.start(_req(seeds=["http://10.0.0.1/", "ftp://example.com/x", "http://localhost/"]))
    assert not r.ok and r.status == 422 and len(r.rejected) == 3
    assert not svc.started_configs  # nothing started


def test_rejects_too_many_seeds(tmp_path):
    launcher, _ = _launcher(tmp_path)
    r = launcher.start(_req(seeds=[f"https://example{i}.com/" for i in range(11)]))
    assert not r.ok and r.status == 422 and "too many seeds" in r.message


def test_persists_before_execution(tmp_path):
    seen = {}

    def starter(cfg):
        # The registry record must already exist on disk when the starter runs.
        reg = list((tmp_path / "registry").glob("*.json"))
        seen["record_present"] = bool(reg)
        seen["status_at_start"] = json.loads(reg[0].read_text(encoding="utf-8"))["status"]
        return cfg.run_id

    launcher, _ = _launcher(tmp_path, starter=starter)
    r = launcher.start(_req())
    assert r.ok and r.status == 202
    assert seen["record_present"] and seen["status_at_start"] == "STARTING"


def test_successful_start_records_and_returns_run_id(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req())
    assert r.ok and r.status == 202 and r.run_id
    assert len(svc.started_configs) == 1
    cfg = svc.started_configs[0]
    assert cfg.browser_mode == "static" and cfg.concurrency == 1  # bounded read-only
    rec = json.loads(next((tmp_path / "registry").glob("*.json")).read_text(encoding="utf-8"))
    assert rec["status"] == "STARTED" and rec["run_id"] == r.run_id


def test_idempotent_duplicate_returns_same_run_id_single_start(tmp_path):
    launcher, svc = _launcher(tmp_path)
    first = launcher.start(_req(key="same"))
    svc._running = False  # pretend the run finished so is_running no longer blocks
    second = launcher.start(_req(key="same"))
    assert first.ok and second.ok and second.idempotent
    assert second.run_id == first.run_id
    assert len(svc.started_configs) == 1  # the campaign was started exactly once


def test_one_active_campaign_blocks_a_different_start(tmp_path):
    launcher, svc = _launcher(tmp_path)
    assert launcher.start(_req(key="a")).ok           # now running
    r = launcher.start(_req(key="b"))
    assert not r.ok and r.status == 409 and "already active" in r.message


def test_restart_recovery_is_idempotent_via_persisted_registry(tmp_path):
    launcher, svc = _launcher(tmp_path)
    first = launcher.start(_req(key="persist"))
    # Simulate a full restart: a brand-new service + launcher over the SAME registry dir.
    launcher2, svc2 = _launcher(tmp_path, service=_FakeService(str(tmp_path)))
    again = launcher2.start(_req(key="persist"))
    assert again.ok and again.idempotent and again.run_id == first.run_id
    assert not svc2.started_configs  # the new process did NOT start a second campaign


def test_request_cannot_widen_local_allowlist(tmp_path):
    # A malicious body trying to allow-list localhost must be ignored (no SSRF bypass).
    launcher, svc = _launcher(tmp_path, allow_fixture=False)
    r = launcher.start(_req(seeds=["http://localhost/"], allowed_local_hosts=["localhost"]))
    assert not r.ok and r.status == 422 and not svc.started_configs


# --------------------------------------------------------------------------- HTTP guards

def _http(server, method, path, *, headers=None, body=None, host_header=None):
    addr = server.server_address
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=5)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host_header or f"{addr[0]}:{addr[1]}")
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        if body is not None:
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(raw)))
        conn.endheaders()
        if raw:
            conn.send(raw)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    finally:
        conn.close()


def _serve(tmp_path, service=None):
    launcher, svc = _launcher(tmp_path, service=service)
    server, _url = start_dashboard(svc, launcher=launcher, csrf_token="test-csrf-token")
    return server, svc


def test_http_csrf_required(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        status, body = _http(server, "POST", "/api/campaign/start", body=_req())
        assert status == 403 and "CSRF" in (body.get("error") or "")
        assert not svc.started_configs
    finally:
        server.shutdown()


def test_http_start_ok_with_csrf_header(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        status, body = _http(server, "POST", "/api/campaign/start",
                             headers={"X-Scout-CSRF": "test-csrf-token"}, body=_req())
        assert status == 202 and body["ok"] and body["run_id"]
        assert len(svc.started_configs) == 1
    finally:
        server.shutdown()


def test_http_start_ok_with_csrf_in_body(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        status, body = _http(server, "POST", "/api/campaign/start",
                             body=_req(csrf_token="test-csrf-token"))
        assert status == 202 and body["ok"]
    finally:
        server.shutdown()


def test_http_non_loopback_host_refused(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        status, body = _http(server, "POST", "/api/campaign/start", host_header="evil.example.com",
                             headers={"X-Scout-CSRF": "test-csrf-token"}, body=_req())
        assert status == 403 and "loopback" in (body.get("error") or "")
        assert not svc.started_configs
    finally:
        server.shutdown()


def test_http_cross_origin_refused(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        status, body = _http(server, "POST", "/api/campaign/start",
                             headers={"X-Scout-CSRF": "test-csrf-token",
                                      "Origin": "http://evil.example.com"}, body=_req())
        assert status == 403 and "cross-origin" in (body.get("error") or "")
        assert not svc.started_configs
    finally:
        server.shutdown()


def test_http_duplicate_start_is_idempotent(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        h = {"X-Scout-CSRF": "test-csrf-token"}
        s1, b1 = _http(server, "POST", "/api/campaign/start", headers=h, body=_req(key="dup"))
        svc._running = False
        s2, b2 = _http(server, "POST", "/api/campaign/start", headers=h, body=_req(key="dup"))
        assert s1 == 202 and s2 == 200 and b2["idempotent"] and b2["run_id"] == b1["run_id"]
        assert len(svc.started_configs) == 1
    finally:
        server.shutdown()


def test_http_safe_stop_then_restart(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        h = {"X-Scout-CSRF": "test-csrf-token"}
        s1, _ = _http(server, "POST", "/api/campaign/start", headers=h, body=_req(key="one"))
        assert s1 == 202 and svc.is_running()
        # Stop Safely = graceful cancel; the campaign stops and a new one may start.
        sc, bc = _http(server, "POST", "/api/control?action=cancel", headers=h)
        assert sc == 200 and bc["ok"] and not svc.is_running()
        s2, b2 = _http(server, "POST", "/api/campaign/start", headers=h, body=_req(key="two"))
        assert s2 == 202 and b2["ok"] and len(svc.started_configs) == 2
    finally:
        server.shutdown()


def test_http_csrf_endpoint_exposes_token(tmp_path):
    server, svc = _serve(tmp_path)
    try:
        status, body = _http(server, "GET", "/api/csrf")
        assert status == 200 and body["csrf_token"] == "test-csrf-token"
    finally:
        server.shutdown()
