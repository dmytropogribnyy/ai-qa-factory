"""Final Phase II — complete deterministic local-sink v2 E2E + benchmark (nothing sent externally)."""
from __future__ import annotations

from core.scout.comms.benchmark import run_benchmark
from core.scout.comms.demo import run_radar_demo
from core.scout.comms.repository import CommsRepository
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_ARTIFACTS_PREFIXES = ("DRAFT_REVISION_", "APPROVAL_RECORD_", "PRE_SEND_REVALIDATION_",
                       "OUTBOUND_MESSAGE_", "SEND_ATTEMPT_", "PROVIDER_RESULT_")
_ARTIFACTS = ("COMMERCIAL_METRICS.json", "OUTREACH_CONTROL_STATE.json",
              "PROVIDER_REGISTRY_SNAPSHOT.json", "FINAL_PRODUCT_HEALTH.json", "FINAL_E2E_REPORT.md")


def test_radar_demo_full_product_and_no_real_send(tmp_path):
    summary = run_radar_demo(str(tmp_path))
    assert summary["send_status"] == "accepted" and summary["any_real_send"] is False
    from core.scout.store import RunStore
    store = RunStore(str(tmp_path), summary["campaign_id"])
    report = store.report_dir()
    for name in _ARTIFACTS:
        assert (report / name).exists(), f"missing artifact: {name}"
    files = {p.name for p in report.glob("*.json")}
    for prefix in _ARTIFACTS_PREFIXES:
        assert any(f.startswith(prefix) for f in files), f"missing artifact prefix: {prefix}"
    # The message went only to a confined local sink.
    assert len(list((store.root / "sink").glob("*.json"))) == 1
    # No secret VALUE leaks (the scanner detects real secret patterns, not env-var names).
    from core.orchestration.content_safety import ContentSecretScanner
    scanner = ContentSecretScanner()
    for p in tmp_path.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".md", ".log"):
            assert not scanner.scan_text(p.name, p.read_text(encoding="utf-8", errors="replace"))


def test_benchmark_meets_zero_incident_targets(tmp_path):
    report = run_benchmark(str(tmp_path / "bench"))
    assert report["all_targets_zero"], report["zero_incidents"]
    assert report["clean_accepted"] is True
    assert report["sink_files"] == 1                 # only the clean approved prospect sent
    assert report["duplicate_command_status"] != "accepted"
    assert report["any_real_send"] is False
    # Every unsafe scenario was blocked.
    for name in ("suppressed", "inferred", "opted_out", "stale_finding"):
        assert report["scenarios"][name] != "accepted"
    assert report["scenarios"]["responsible_disclosure"] == "blocked_at_build"


def test_dashboard_comms_view_has_no_send_button(tmp_path):
    import json
    import urllib.request

    from core.scout.dashboard import start_dashboard
    from core.scout.service import ScoutService
    from core.scout.store import RunStore
    summary = run_radar_demo(str(tmp_path))
    RunStore(str(tmp_path), summary["campaign_id"])  # ensure report exists
    service = ScoutService(str(tmp_path))
    service.attach(summary["campaign_id"])
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/api/comms", timeout=5) as r:
            data = json.loads(r.read())
            assert data["has_send_button"] is False and data["any_real_send"] is False
        with urllib.request.urlopen(url + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        assert "no send button" in html.lower() and "scout send" in html
    finally:
        server.shutdown()


def test_backup_restart_restore_preserves_send_history(tmp_path):
    summary = run_radar_demo(str(tmp_path))
    from core.scout.store import RunStore
    store = RunStore(str(tmp_path), summary["campaign_id"])
    db_path = str(store.root / "memory.db")
    db = MemoryDB(db_path)
    comms = CommsRepository(db)
    before = comms.count("outbound_messages")
    assert before >= 1
    backup = db.backup(str(tmp_path / "b" / "mem.bak"))
    db.close()
    restored = MemoryDB.restore(backup, str(tmp_path / "restored.db"))
    rcomms = CommsRepository(restored)
    assert rcomms.count("outbound_messages") == before          # send history preserved
    assert rcomms.count("draft_revisions") >= 1 and rcomms.count("approval_records") >= 1
    # Suppression history is preserved too.
    rmem = MemoryRepository(restored)
    assert rmem.count("companies") >= 1
    restored.close()
