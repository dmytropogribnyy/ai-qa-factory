"""Final Phase I — findings, evidence center, normalization, and lifecycle (deterministic)."""
from __future__ import annotations

from core.scout.pipeline.evidence import EvidenceCenter
from core.scout.pipeline.finding import NormalizedFinding
from core.scout.pipeline.normalize import (
    RawObservation,
    normalize_findings,
    reconcile_lifecycle,
    verify_findings,
)
from core.scout.store import RunStore


def _obs(key, **kw):
    base = dict(capability="axe", category="accessibility", title=f"t-{key}", severity="medium",
                url="https://x.example/", root_impact_key=key, signature=f"sig-{key}",
                reproduction_steps=[f"open {key}"], provenance={"tool": "axe", "rule": key})
    base.update(kw)
    return RawObservation(**base)


def _norm(obs, **kw):
    base = dict(campaign_id="c", company_id="co", session_id="s", url="https://x.example/",
                clock_iso="2026-07-17T00:00:00+00:00")
    base.update(kw)
    return normalize_findings(obs, **base)


def test_client_safe_requires_verified_sanitized_clean_active_unexpired():
    f = NormalizedFinding(finding_id="f1", verification_state="VERIFIED", sanitized=True,
                          category="accessibility")
    assert f.is_client_safe and f.is_draftable
    f.lifecycle_state = "RESOLVED"
    assert not f.is_draftable  # a resolved finding can never enter a draft
    f.lifecycle_state = "ACTIVE"
    f.evidence_expired = True
    assert not f.is_client_safe  # expired evidence
    f.evidence_expired = False
    f.from_clean_session = False
    assert not f.is_client_safe  # unclean reversible session


def test_normalize_merges_by_root_impact_and_preserves_provenance():
    obs = [_obs("k1", provenance={"tool": "perf"}), _obs("k1", provenance={"tool": "browser"}),
           _obs("k2")]
    findings = _norm(obs)
    assert len(findings) == 2  # k1 merged, k2 separate
    k1 = next(f for f in findings if f.root_impact_key == "k1")
    assert len(k1.provenance) == 2  # both sources preserved, never dropped


def test_normalize_never_merges_distinct_keys_with_similar_titles():
    obs = [_obs("kA", title="Slow render"), _obs("kB", title="Slow render")]
    findings = _norm(obs)
    assert len(findings) == 2  # identical titles, different root impact => distinct findings


def test_verification_requires_second_pass_reproduction():
    findings = _norm([_obs("k1"), _obs("k2")])
    sigs = {f.signature for f in findings if f.root_impact_key == "k1"}
    verified, rejected = verify_findings(findings, sigs)
    assert {f.root_impact_key for f in verified} == {"k1"}
    assert {f.root_impact_key for f in rejected} == {"k2"}
    assert verified[0].is_client_safe


def test_unclean_session_finding_never_client_safe():
    findings = _norm([_obs("k1", from_clean_session=False)])
    verified, rejected = verify_findings(findings, {findings[0].signature})
    assert not verified and rejected[0].verification_state == "REJECTED"
    assert not rejected[0].is_client_safe


def test_reconcile_marks_resolved_and_regressed():
    prior = _norm([_obs("k1"), _obs("k2")])
    for f in prior:
        f.lifecycle_state = "ACTIVE"
    # k1 gone -> resolved; run a later scan where k2 persists.
    summary = reconcile_lifecycle(prior, _norm([_obs("k2")]), clock_iso="t2")
    assert summary["resolved_count"] == 1
    # Now k1 reappears after being resolved -> regressed, needs new verification.
    resolved_k1 = NormalizedFinding.from_dict(summary["resolved"][0])
    again = _norm([_obs("k1")])
    summary2 = reconcile_lifecycle([resolved_k1], again, clock_iso="t3")
    assert summary2["regressed_count"] == 1
    assert again[0].lifecycle_state == "REGRESSED" and again[0].verification_state == "UNVERIFIED"


def test_evidence_center_sanitizes_and_hashes(tmp_path):
    store = RunStore(str(tmp_path), "sess-run")
    ec = EvidenceCenter(store, "c", "co", "01-site")
    item = ec.add_text("axe_summary", {"rule": "image-alt", "note": "ok"}, finding_id="f1",
                       tool="axe", tool_version="4.x")
    assert item.content_hash.startswith("sha256:") and item.storage_ref
    assert item.retention_deadline and item.sanitization_status == "sanitized"
    # A secret-bearing payload is rejected (never stored).
    leak = ec.add_text("console_sanitized", {"line": "token sk_live_0123456789ABCDEFGH"},
                       finding_id="f2")
    assert leak.sanitization_status in ("sanitized", "rejected")
    # After sanitization the secret must not survive in stored evidence.
    for p in tmp_path.rglob("*.json"):
        assert b"sk_live_0123456789ABCDEFGH" not in p.read_bytes()
