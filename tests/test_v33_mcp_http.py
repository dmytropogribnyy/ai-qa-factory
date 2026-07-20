"""v3.3 — authenticated streamable-HTTP MCP transport (guarded; skips without web deps).

Security-critical: the remote transport must reject any request lacking the correct bearer token,
and the server must refuse to start without a token (no open endpoint). Full authorized round-trip
is covered by tools/mcp_http_smoke.py (real HTTP client).
"""
from __future__ import annotations

import importlib.util

import pytest

# Function-level skip + lazy imports (see test_v33_mcp_transport.py): keeps the module importable
# without web deps so the browser-acceptance job DESELECTS it (no browser marker) rather than
# counting a skip against its zero-skip gate.
pytestmark = pytest.mark.skipif(
    any(importlib.util.find_spec(m) is None for m in ("mcp", "starlette", "uvicorn")),
    reason="mcp/starlette/uvicorn not installed")


def test_http_rejects_missing_and_wrong_token():
    from starlette.testclient import TestClient

    from integrations.mcp.server import build_http_app
    app = build_http_app("s3cret-token")
    with TestClient(app) as client:
        no_auth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert no_auth.status_code == 401
        wrong = client.post("/mcp", headers={"Authorization": "Bearer nope"},
                            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert wrong.status_code == 401


def test_http_server_refuses_to_start_without_token(monkeypatch):
    from integrations.mcp.server import run_http_server
    monkeypatch.delenv("AIQA_MCP_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        run_http_server(token="")            # refuses an open/unauthenticated endpoint
