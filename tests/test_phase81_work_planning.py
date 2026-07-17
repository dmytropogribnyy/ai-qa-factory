"""Phase 8.1 — planning-only universal work entrypoint tests.

Covers CLI contract, determinism, profile inference, deterministic-safety guards
(no LLM/network/subprocess/MCP), content secret detection + atomic rollback, state
transition enforcement, candidate-vs-discovered semantics, and planning-only invariants.
"""
from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

import main as main_module
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_workflow import WorkPlanningWorkflow
from core.orchestration.profile_selector import UniversalProfileSelector
from core.orchestration.requirement_extractor import RequirementExtractor
from core.orchestration.missing_information_analyzer import MissingInformationAnalyzer
from core.orchestration.content_safety import (
    ContentSecretScanner, ArtifactSafeWriter, ArtifactPublishError,
)
from core.orchestration.work_state_manager import WorkStateManager, InvalidTransitionError
from core.schemas.work_run_state import WorkRunState
from core.schemas.input_map import InputMap
from core.schemas.work_request import WorkRequest


def _wf(tmp: Path) -> WorkPlanningWorkflow:
    return WorkPlanningWorkflow(FixedClock(), SequentialIds(), output_dir=tmp)


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------

class TestCliContract:
    def test_stdin_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("Audit our website accessibility"))
        rc = main_module.main(["work", "--stdin", "--project-id", "cli-stdin"])
        assert rc == 0
        assert (tmp_path / "cli-stdin" / "40_ark_work" / "WORK_PACKET.json").exists()

    def test_text_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        rc = main_module.main(["work", "--text", "Audit the website", "--project-id", "cli-text"])
        assert rc == 0

    def test_input_file_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        brief = tmp_path / "brief.txt"
        brief.write_text("Audit the website accessibility", encoding="utf-8")
        rc = main_module.main(["work", "--input", str(brief), "--project-id", "cli-file"])
        assert rc == 0

    def test_invalid_project_id_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        assert main_module.main(["work", "--text", "x", "--project-id", "../evil"]) == 2

    def test_empty_input(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        assert main_module.main(["work", "--text", "   ", "--project-id", "ok"]) == 1

    def test_input_too_large(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        big = "a" * 200_001
        assert main_module.main(["work", "--text", big, "--project-id", "ok"]) == 1

    def test_mutually_exclusive_sources(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        with pytest.raises(SystemExit):  # argparse rejects two sources
            main_module.main(["work", "--text", "a", "--input", "f", "--project-id", "ok"])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_input_byte_identical(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        _wf(a).run("Audit the website accessibility and performance", "proj")
        _wf(b).run("Audit the website accessibility and performance", "proj")
        da = a / "proj" / "40_ark_work"
        db = b / "proj" / "40_ark_work"
        for f in da.iterdir():
            assert f.read_text(encoding="utf-8") == (db / f.name).read_text(encoding="utf-8"), f.name


# ---------------------------------------------------------------------------
# Profile inference (all eight + unresolved + override)
# ---------------------------------------------------------------------------

class TestProfileInference:
    CASES = {
        "web_app_audit": "accessibility audit lighthouse core web vitals of the web app",
        "api_project": "test our api openapi endpoints and rest contract",
        "data_project": "database postgres schema migration and rls policies",
        "code_project": "implement a new feature, refactor and write code sdk",
        "automation_project": "automate this workflow with n8n and scraping",
        "technical_writing": "technical writing documentation help center user guide",
        "mvp_launch_audit": "mvp launch readiness and production readiness review",
        "research_only": "research and compare options, feasibility analysis",
    }

    @pytest.mark.parametrize("profile,text", list(CASES.items()))
    def test_infers_each_profile(self, profile, text):
        sel = UniversalProfileSelector().select(text)
        assert sel.selected_profile == profile, f"{text!r} -> {sel.selected_profile}"

    def test_unresolved_on_no_signal(self):
        sel = UniversalProfileSelector().select("hello please help me with my thing")
        assert sel.selected_profile == ""
        assert sel.selection_source == "unresolved"
        assert sel.warnings

    def test_override_and_mismatch_warning(self):
        sel = UniversalProfileSelector().select(
            "accessibility audit lighthouse", override="api_project"
        )
        assert sel.selected_profile == "api_project"
        assert sel.selection_source == "override"
        assert sel.inferred_profile == "web_app_audit"  # inferred preserved
        assert any("differs from inferred" in w for w in sel.warnings)

    def test_invalid_override_ignored(self):
        sel = UniversalProfileSelector().select("accessibility audit", override="not_a_profile")
        assert sel.selected_profile == "web_app_audit"
        assert any("not a known profile" in w for w in sel.warnings)


# ---------------------------------------------------------------------------
# Requirements + missing info
# ---------------------------------------------------------------------------

class TestRequirementsAndMissingInfo:
    def test_requirement_extraction(self):
        reqs = RequirementExtractor(FixedClock(), SequentialIds()).extract(
            "The homepage must load fast. Users should be able to log in.",
            "web_app_audit", "WORK_REQUEST.json",
        )
        assert any(r.requirement_type == "functional" for r in reqs)
        assert any(r.requirement_type == "quality" for r in reqs)  # profile baseline
        assert all(r.verification_status == "unverified" for r in reqs)

    def test_missing_info_profile_aware(self):
        mi = MissingInformationAnalyzer().analyze(
            "api_project", WorkRequest(project_id="p"), InputMap(project_id="p"),
        )
        assert mi.has_blocking
        assert any("API" in b or "OpenAPI" in b for b in mi.blocking)

    def test_unresolved_profile_is_blocking(self):
        mi = MissingInformationAnalyzer().analyze(
            "", WorkRequest(project_id="p"), InputMap(project_id="p"),
        )
        assert mi.has_blocking


# ---------------------------------------------------------------------------
# Deterministic-safety guards: no LLM / network / subprocess / MCP
# ---------------------------------------------------------------------------

class TestNoSideEffects:
    def test_no_llm_network_subprocess(self, tmp_path, monkeypatch):
        import core.llm_router as llm

        def _boom(*a, **k):
            raise AssertionError("forbidden call in planning-only path")

        monkeypatch.setattr(llm.LLMRouter, "complete", _boom, raising=True)
        monkeypatch.setattr(socket.socket, "connect", _boom, raising=True)
        monkeypatch.setattr(subprocess, "Popen", _boom, raising=True)
        monkeypatch.setattr(subprocess, "run", _boom, raising=True)
        # Should complete with no forbidden calls.
        res = _wf(tmp_path).run("Audit the website accessibility", "safe")
        assert res.final_status in ("PLANNED", "WAITING_FOR_INFORMATION", "WAITING_FOR_APPROVAL")


# ---------------------------------------------------------------------------
# Candidate vs discovered MCP semantics
# ---------------------------------------------------------------------------

class TestMcpSemantics:
    def test_no_fake_tool_names_and_unverified(self, tmp_path):
        _wf(tmp_path).run("Audit the website accessibility", "mcp")
        tc = json.loads((tmp_path / "mcp" / "40_ark_work" / "TOOLCHAIN_PLAN.json").read_text())
        for step in tc["steps"]:
            if step["resolution_status"] in (
                "mcp_discovery_required", "mcp_server_candidate", "auth_setup_required"
            ):
                assert step["tool_name"] == ""
                assert step["availability_verified"] is False
                assert step["discovery_required"] is True

    def test_snapshot_is_not_live_discovery(self, tmp_path):
        _wf(tmp_path).run("Audit the website", "snap")
        snap = json.loads(
            (tmp_path / "snap" / "40_ark_work" / "MCP_CONFIGURED_SERVERS_SNAPSHOT.json").read_text()
        )
        assert snap["live_discovery_performed"] is False
        for s in snap["servers"]:
            assert s["discovered_tools"] == []


# ---------------------------------------------------------------------------
# Content secret detection + atomic rollback
# ---------------------------------------------------------------------------

class TestContentSafety:
    def test_scanner_detects_secrets(self):
        scanner = ContentSecretScanner()
        assert scanner.scan_text("x", "token sk_live_0123456789ABCDEFGHIJ here")
        assert scanner.scan_text("x", "Bearer abcdefghijklmnop1234")
        assert not scanner.scan_text("x", "url_ref: ref:stripe_mcp_host")  # placeholder allowed

    def test_publish_blocks_and_rolls_back(self, tmp_path):
        target = tmp_path / "proj" / "40_ark_work"
        writer = ArtifactSafeWriter(target)
        with pytest.raises(ArtifactPublishError):
            writer.publish({"A.json": '{"k":"sk_live_0123456789ABCDEFGHIJ"}'})
        assert not target.exists()  # nothing published
        assert not (tmp_path / "proj" / "40_ark_work.tmp_publish").exists()  # temp cleaned

    def test_publish_clean_ok(self, tmp_path):
        target = tmp_path / "proj" / "40_ark_work"
        ArtifactSafeWriter(target).publish({"A.md": "# clean\n", "B.json": "{}"})
        assert (target / "A.md").exists() and (target / "B.json").exists()


# ---------------------------------------------------------------------------
# State machine enforcement
# ---------------------------------------------------------------------------

class TestStateEnforcement:
    def test_valid_transition_increments_version(self):
        mgr = WorkStateManager(FixedClock())
        st = WorkRunState(project_id="p", status="RECEIVED", state_version=0)
        mgr.transition(st, "INTAKE_COMPLETE", "ok", "cli")
        assert st.status == "INTAKE_COMPLETE"
        assert st.state_version == 1
        assert st.history[-1].to_state == "INTAKE_COMPLETE"

    def test_invalid_transition_rejected(self):
        mgr = WorkStateManager(FixedClock())
        st = WorkRunState(project_id="p", status="RECEIVED")
        with pytest.raises(InvalidTransitionError):
            mgr.transition(st, "COMPLETED", "skip", "cli")

    def test_terminal_state_immutable(self):
        mgr = WorkStateManager(FixedClock())
        st = WorkRunState(project_id="p", status="COMPLETED")
        with pytest.raises(InvalidTransitionError):
            mgr.transition(st, "PLANNED", "reopen", "cli")

    def test_planning_only_never_reaches_execution(self, tmp_path):
        _wf(tmp_path).run("Audit the website accessibility", "st")
        st = json.loads((tmp_path / "st" / "40_ark_work" / "WORK_RUN_STATE.json").read_text())
        assert st["status"] in ("PLANNED", "WAITING_FOR_INFORMATION", "WAITING_FOR_APPROVAL")
        seen = [h["to_state"] for h in st["history"]]
        for forbidden in ("EXECUTING", "READY_TO_EXECUTE", "COMPLETED"):
            assert forbidden not in seen


# ---------------------------------------------------------------------------
# Planning-only invariants
# ---------------------------------------------------------------------------

class TestPlanningInvariants:
    def test_workrequest_reference_resolves(self, tmp_path):
        _wf(tmp_path).run("Audit the website", "ref")
        d = tmp_path / "ref" / "40_ark_work"
        wp = json.loads((d / "WORK_PACKET.json").read_text())
        wr = json.loads((d / "WORK_REQUEST.json").read_text())
        assert wp["work_request_ref"] == wr["id"]

    def test_no_delivery_approval(self, tmp_path):
        _wf(tmp_path).run("Audit the website", "del")
        # No delivery manifest is produced in planning; approvals stay unresolved.
        d = tmp_path / "del" / "40_ark_work"
        approvals = (d / "APPROVALS_REQUIRED.md").read_text()
        assert "unresolved" in approvals.lower()
        assert "No approval is granted or persisted" in approvals

    def test_output_confined_to_project_dir(self, tmp_path):
        _wf(tmp_path).run("Audit the website", "conf")
        produced = list(tmp_path.rglob("*"))
        # Every produced file lives under <output>/conf/40_ark_work
        base = tmp_path / "conf" / "40_ark_work"
        for p in produced:
            if p.is_file():
                assert base in p.parents

    def test_overwrite_guard_blocks_foreign_project(self, tmp_path):
        wf = _wf(tmp_path)
        wf.run("Audit the website", "shared")
        # Tamper: put a different project's packet where 'shared' lives.
        pkt = tmp_path / "shared" / "40_ark_work" / "WORK_PACKET.json"
        data = json.loads(pkt.read_text())
        data["project_id"] = "someone_else"
        pkt.write_text(json.dumps(data), encoding="utf-8")
        from core.orchestration.work_workflow import WorkPlanningError
        with pytest.raises(WorkPlanningError):
            _wf(tmp_path).run("Audit the website", "shared")


# ---------------------------------------------------------------------------
# Redaction chain (secrets must never reach any artifact or stdout)
# ---------------------------------------------------------------------------

class TestRedactionChain:
    SECRETS = [
        "password=SuperSecret123",
        "Authorization: Bearer abcdef0123456789ABCDEF",
        "api_key=sk_live_0123456789ABCDEFGHIJ",
        "token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123456",
        "Cookie: session=abc123def456",
        "https://user:p4ssw0rd@internal.example.com/db",
    ]

    def _brief(self):
        return "Audit our web app. Config: " + " ; ".join(self.SECRETS)

    def _raw_values(self):
        return ["SuperSecret123", "abcdef0123456789ABCDEF", "sk_live_0123456789ABCDEFGHIJ",
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "session=abc123def456", "p4ssw0rd"]

    def test_no_secret_in_any_artifact(self, tmp_path):
        _wf(tmp_path).run(self._brief(), "sec")
        d = tmp_path / "sec" / "40_ark_work"
        blob = "\n".join(p.read_text(encoding="utf-8") for p in d.iterdir())
        for secret in self._raw_values():
            assert secret not in blob, f"leaked: {secret}"
        # raw_brief specifically must be redacted
        wr = json.loads((d / "WORK_REQUEST.json").read_text())
        assert "SuperSecret123" not in wr.get("raw_brief", "")
        assert "REDACTED" in blob  # placeholders present

    def test_no_secret_in_json_stdout(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        main_module.main(["work", "--text", self._brief(), "--project-id", "secj", "--json"])
        out = capsys.readouterr().out
        for secret in self._raw_values():
            assert secret not in out


# ---------------------------------------------------------------------------
# Generated project id / collision / resume
# ---------------------------------------------------------------------------

class TestProjectId:
    def test_generated_id_deterministic_and_safe(self):
        from core.orchestration.providers import generate_project_id
        pid = generate_project_id("Build a Playwright framework", SequentialIds())
        assert pid == "build-a-playwright-framework-0000"
        assert main_module._valid_project_id(pid)

    def test_cli_generates_id_when_omitted(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        rc = main_module.main(["work", "--text", "Audit the website accessibility"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Project id (generated):" in out

    def test_explicit_id_resume_overwrites(self, tmp_path):
        _wf(tmp_path).run("Audit the website", "resume-me")
        # Same explicit id + same input (matching fingerprint) -> resume/regenerate allowed
        _wf(tmp_path).run("Audit the website", "resume-me")
        assert (tmp_path / "resume-me" / "40_ark_work" / "WORK_PACKET.json").exists()

    def test_generated_id_never_overwrites(self, tmp_path):
        from core.orchestration.work_workflow import WorkPlanningError
        _wf(tmp_path).run("Audit the website", "gen", fresh_only=False)
        with pytest.raises(WorkPlanningError):
            _wf(tmp_path).run("Audit the website", "gen", fresh_only=True)


# ---------------------------------------------------------------------------
# JSON output contract
# ---------------------------------------------------------------------------

class TestJsonContract:
    def test_single_json_object_with_required_fields(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        main_module.main(["work", "--text", "Test our REST API endpoints", "--project-id", "jc", "--json"])
        out = capsys.readouterr().out
        obj = json.loads(out)  # exactly one valid JSON object
        for key in ("project_id", "selected_profile", "state", "artifact_directory",
                    "artifact_paths", "missing_information", "approvals_required", "planning_only"):
            assert key in obj, key
        assert obj["planning_only"] is True
        assert isinstance(obj["missing_information"], int)
        assert isinstance(obj["approvals_required"], int)


# ---------------------------------------------------------------------------
# Atomic publication preserves old output on failure
# ---------------------------------------------------------------------------

class TestAtomicFailure:
    def test_failure_preserves_old_and_cleans_temp(self, tmp_path):
        target = tmp_path / "proj" / "40_ark_work"
        ArtifactSafeWriter(target).publish({"A.md": "v1", "B.json": "{}"})
        assert (target / "A.md").read_text() == "v1"
        # Second publish fails mid-staging (illegal nested path), must not touch old set.
        with pytest.raises(Exception):
            ArtifactSafeWriter(target).publish({"A.md": "v2", "no/such.json": "{}"})
        assert (target / "A.md").read_text() == "v1"      # old preserved
        assert not (target / "B.json").read_text() == ""  # B still present (old set intact)
        assert (target / "B.json").exists()
        assert not (tmp_path / "proj" / "40_ark_work.tmp_publish").exists()
        assert not (tmp_path / "proj" / "40_ark_work.bak_publish").exists()

    def test_rollback_after_backup_rename(self, tmp_path, monkeypatch):
        # The dangerous case: staging + `target -> .bak` succeed, then `tmp -> target` fails.
        import core.orchestration.content_safety as cs
        target = tmp_path / "proj" / "40_ark_work"
        ArtifactSafeWriter(target).publish({"A.md": "v1", "B.json": '{"n":1}'})
        real_replace = cs.os.replace

        def flaky(src, dst):
            if str(src).endswith(".tmp_publish"):   # fail only the final swap
                raise OSError("injected swap failure")
            return real_replace(src, dst)

        monkeypatch.setattr(cs.os, "replace", flaky)
        with pytest.raises(ArtifactPublishError):
            ArtifactSafeWriter(target).publish({"A.md": "v2", "B.json": '{"n":2}'})
        # Old output restored byte-for-byte; no mixed set; temp + backup gone.
        assert (target / "A.md").read_text() == "v1"
        assert (target / "B.json").read_text() == '{"n":1}'
        assert not (tmp_path / "proj" / "40_ark_work.tmp_publish").exists()
        assert not (tmp_path / "proj" / "40_ark_work.bak_publish").exists()


# ---------------------------------------------------------------------------
# Input fingerprint binding (explicit id can only resume the same work)
# ---------------------------------------------------------------------------

class TestInputFingerprint:
    def test_line_ending_normalization(self):
        from core.orchestration.work_workflow import input_fingerprint
        a = input_fingerprint("line one\nline two", "upwork", None)
        b = input_fingerprint("line one\r\nline two  ", "upwork", None)
        assert a == b

    def test_matching_input_allows_resume(self, tmp_path):
        _wf(tmp_path).run("Audit the website accessibility", "same")
        _wf(tmp_path).run("Audit the website accessibility", "same")  # no raise
        assert (tmp_path / "same" / "40_ark_work" / "WORK_PACKET.json").exists()

    def test_different_input_blocks_and_preserves(self, tmp_path):
        from core.orchestration.work_workflow import WorkPlanningError
        _wf(tmp_path).run("Audit the website accessibility", "reuse")
        pkt = tmp_path / "reuse" / "40_ark_work" / "WORK_PACKET.json"
        before = pkt.read_text(encoding="utf-8")
        with pytest.raises(WorkPlanningError):
            _wf(tmp_path).run("Completely different data project on postgres", "reuse")
        assert pkt.read_text(encoding="utf-8") == before  # existing output preserved

    def test_secret_redacted_before_hashing(self, tmp_path):
        # Two runs differing only by the secret VALUE -> same redacted text -> same fingerprint.
        _wf(tmp_path).run("Audit site password=AAAA1111 done", "sec-fp")
        _wf(tmp_path).run("Audit site password=BBBB2222 done", "sec-fp")  # resume allowed
        assert (tmp_path / "sec-fp" / "40_ark_work" / "WORK_PACKET.json").exists()

    def test_profile_override_changes_fingerprint(self, tmp_path):
        from core.orchestration.work_workflow import WorkPlanningError
        _wf(tmp_path).run("Audit the website accessibility", "ovr")
        with pytest.raises(WorkPlanningError):
            _wf(tmp_path).run("Audit the website accessibility", "ovr", profile_override="api_project")

    def test_fingerprint_not_derived_from_raw_secret(self, tmp_path):
        from core.orchestration.work_workflow import input_fingerprint
        # Redacted input is what gets hashed; the raw secret never appears in the digest input.
        fp = input_fingerprint("audit password=[REDACTED_password_assignment]", "upwork", None)
        assert "password=" not in fp and len(fp) == 64


# ---------------------------------------------------------------------------
# Generated project id must be built from redacted text
# ---------------------------------------------------------------------------

class TestGeneratedIdRedaction:
    BRIEF = "password=SuperSecret123 audit the website accessibility"

    def test_secret_absent_everywhere(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        rc = main_module.main(["work", "--text", self.BRIEF, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "SuperSecret123" not in out                      # JSON stdout
        obj = json.loads(out)
        assert "SuperSecret123" not in obj["project_id"]        # generated id
        assert "SuperSecret123" not in obj["artifact_directory"]
        # filesystem paths + artifacts
        for p in tmp_path.rglob("*"):
            assert "SuperSecret123" not in str(p)
            if p.is_file():
                assert "SuperSecret123" not in p.read_text(encoding="utf-8")

    def test_human_stdout_has_no_secret(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        main_module.main(["work", "--text", self.BRIEF])
        assert "SuperSecret123" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Credential-bearing URL: keep host/path, drop only userinfo
# ---------------------------------------------------------------------------

class TestCredentialUrlRedaction:
    def test_userinfo_removed_host_path_kept(self):
        from core.orchestration.content_safety import redact_intake_text
        r = redact_intake_text("see https://user:pass@alpha.example.com/a/b")
        assert "user" not in r.text and "pass@" not in r.text
        assert "alpha.example.com/a/b" in r.text
        assert r.secrets_found

    def test_distinct_hosts_distinct_fingerprints_no_creds(self):
        from core.orchestration.content_safety import redact_intake_text
        from core.orchestration.work_workflow import input_fingerprint
        ra = redact_intake_text("https://user:pass@alpha.example.com/a")
        rb = redact_intake_text("https://user:pass@beta.example.com/b")
        fa = input_fingerprint(ra.text, "upwork", None)
        fb = input_fingerprint(rb.text, "upwork", None)
        assert fa != fb                                  # host/path preserved -> distinct identity
        assert "pass" not in fa and "pass" not in fb     # digest carries no credentials


# ---------------------------------------------------------------------------
# Fail-closed overwrite guard
# ---------------------------------------------------------------------------

class TestFailClosedGuard:
    def _seed_target(self, tmp_path, pid, packet_content):
        d = tmp_path / pid / "40_ark_work"
        d.mkdir(parents=True)
        if packet_content is not None:
            (d / "WORK_PACKET.json").write_text(packet_content, encoding="utf-8")
        return d

    def _expect_block(self, tmp_path, pid):
        from core.orchestration.work_workflow import WorkPlanningError
        with pytest.raises(WorkPlanningError):
            _wf(tmp_path).run("Audit the website accessibility", pid)

    def test_missing_packet_blocks(self, tmp_path):
        self._seed_target(tmp_path, "p", None)
        self._expect_block(tmp_path, "p")

    def test_malformed_packet_blocks(self, tmp_path):
        self._seed_target(tmp_path, "p", "{not valid json")
        self._expect_block(tmp_path, "p")

    def test_missing_fingerprint_blocks(self, tmp_path):
        self._seed_target(tmp_path, "p", json.dumps({"project_id": "p"}))
        self._expect_block(tmp_path, "p")

    def test_missing_project_id_blocks(self, tmp_path):
        self._seed_target(tmp_path, "p", json.dumps({"input_fingerprint": "abc"}))
        self._expect_block(tmp_path, "p")

    def test_mismatched_project_id_blocks(self, tmp_path):
        self._seed_target(tmp_path, "p", json.dumps({"project_id": "other", "input_fingerprint": "abc"}))
        self._expect_block(tmp_path, "p")

    def test_generated_collision_on_project_dir(self, tmp_path):
        from core.orchestration.work_workflow import WorkPlanningError
        # outputs/<id>/ exists but no 40_ark_work yet -> generated id must still collide.
        (tmp_path / "gid").mkdir()
        (tmp_path / "gid" / "other.txt").write_text("x", encoding="utf-8")
        with pytest.raises(WorkPlanningError):
            _wf(tmp_path).run("Audit the website", "gid", fresh_only=True)


# ---------------------------------------------------------------------------
# ArtifactSafeWriter: name confinement + crash recovery
# ---------------------------------------------------------------------------

class TestWriterHardening:
    @pytest.mark.parametrize("bad", ["../escape.json", "sub/nested.json", "..\\win.json", "/abs.json"])
    def test_rejects_unsafe_names(self, tmp_path, bad):
        with pytest.raises(ArtifactPublishError):
            ArtifactSafeWriter(tmp_path / "p" / "40_ark_work").publish({bad: "{}"})
        assert not (tmp_path / "p" / "40_ark_work").exists()

    def test_stale_backup_missing_target_is_restored(self, tmp_path):
        target = tmp_path / "p" / "40_ark_work"
        bak = tmp_path / "p" / "40_ark_work.bak_publish"
        bak.mkdir(parents=True)
        (bak / "old.md").write_text("recovered", encoding="utf-8")
        # New publish must recover (not delete) the backup, then publish the new set.
        ArtifactSafeWriter(target).publish({"new.md": "n"})
        assert (target / "new.md").exists()
        assert not bak.exists()   # consumed by recovery+swap, never left dangling

    def test_target_and_backup_both_present_fail_closed(self, tmp_path):
        target = tmp_path / "p" / "40_ark_work"
        bak = tmp_path / "p" / "40_ark_work.bak_publish"
        target.mkdir(parents=True)
        (target / "t.txt").write_text("t", encoding="utf-8")
        bak.mkdir(parents=True)
        (bak / "b.txt").write_text("b", encoding="utf-8")
        with pytest.raises(ArtifactPublishError):
            ArtifactSafeWriter(target).publish({"x.md": "x"})
        # Neither directory is auto-deleted.
        assert (target / "t.txt").read_text() == "t"
        assert (bak / "b.txt").read_text() == "b"

    def test_stale_temp_cleaned(self, tmp_path):
        target = tmp_path / "p" / "40_ark_work"
        tmp = tmp_path / "p" / "40_ark_work.tmp_publish"
        target.mkdir(parents=True)
        (target / "v.md").write_text("v1", encoding="utf-8")
        tmp.mkdir(parents=True)
        (tmp / "junk.md").write_text("junk", encoding="utf-8")
        ArtifactSafeWriter(target).publish({"v.md": "v2"})
        assert (target / "v.md").read_text() == "v2"
        assert not tmp.exists()

    def test_no_file_written_outside_target(self, tmp_path):
        target = tmp_path / "p" / "40_ark_work"
        ArtifactSafeWriter(target).publish({"a.md": "1", "b.json": "{}"})
        for f in tmp_path.rglob("*"):
            if f.is_file():
                assert target in f.parents


# ---------------------------------------------------------------------------
# State precedence + API approval state
# ---------------------------------------------------------------------------

class TestStatePrecedence:
    def test_api_with_url_reaches_approval_state(self, tmp_path):
        # Brief starting with an API doc URL -> classified as a URL source, so the
        # 'missing API url' blocker is satisfied and the run needs approval instead.
        _wf(tmp_path).run(
            "https://api.example.com/openapi.json test the REST api endpoints and contract",
            "apiapp",
        )
        d = tmp_path / "apiapp" / "40_ark_work"
        st = json.loads((d / "WORK_RUN_STATE.json").read_text())
        assert st["status"] == "WAITING_FOR_APPROVAL"
        tc = json.loads((d / "TOOLCHAIN_PLAN.json").read_text())
        assert tc["approvals_required"]

    def test_approvals_listed_even_when_waiting_for_info(self, tmp_path):
        res = _wf(tmp_path).run("Test our REST API endpoints and contract", "apiinfo")
        assert res.final_status == "WAITING_FOR_INFORMATION"
        assert res.approvals_required_count > 0  # approvals still surfaced
        approvals = (tmp_path / "apiinfo" / "40_ark_work" / "APPROVALS_REQUIRED.md").read_text()
        assert "execution blocked until approved" in approvals

    def test_research_only_stays_planned(self, tmp_path):
        res = _wf(tmp_path).run("Research and compare options, feasibility analysis", "res")
        assert res.final_status == "PLANNED"
        assert res.approvals_required_count == 0
