"""A process run from source must be able to say whether it is still serving current code.

The commit SHA alone cannot: an uncommitted edit never moves HEAD, so a Dashboard started from a
dirty tree both reported a clean commit it was not serving and stayed silent when that code changed
underneath it. These tests pin the fingerprint rule and, just as importantly, its boundary: docs,
outputs, evidence and tests are not executable code and must never demand a restart.
"""
from __future__ import annotations

import os

from core.build_identity import code_fingerprint, compute_identity


def _repo(tmp_path, *, extra=()):
    """A miniature checkout with the shapes the fingerprint must and must not care about."""
    (tmp_path / "main.py").write_text("print('app')\n", encoding="utf-8")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "core" / "sub").mkdir()
    (tmp_path / "core" / "sub" / "helper.py").write_text("HELP = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "RUNBOOK.md").write_text("# runbook\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "evidence.json").write_text("{}\n", encoding="utf-8")
    for rel, text in extra:
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return str(tmp_path)


def _touch(path, text):
    """Write and force a distinct mtime, so the test cannot pass by filesystem timing luck."""
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns + 2_000_000_000, stat.st_mtime_ns + 2_000_000_000))


def test_editing_executable_code_changes_the_fingerprint(tmp_path):
    root = _repo(tmp_path)
    before = code_fingerprint(root)
    _touch(tmp_path / "core" / "engine.py", "VALUE = 2\n")

    assert code_fingerprint(root) != before


def test_editing_a_nested_module_changes_the_fingerprint(tmp_path):
    root = _repo(tmp_path)
    before = code_fingerprint(root)
    _touch(tmp_path / "core" / "sub" / "helper.py", "HELP = 2\n")

    assert code_fingerprint(root) != before


def test_adding_a_module_changes_the_fingerprint(tmp_path):
    root = _repo(tmp_path)
    before = code_fingerprint(root)
    (tmp_path / "core" / "added.py").write_text("NEW = 1\n", encoding="utf-8")

    assert code_fingerprint(root) != before


def test_docs_outputs_and_tests_never_demand_a_restart(tmp_path):
    """The boundary the operator relies on: a flag that cries wolf is a flag they will ignore."""
    root = _repo(tmp_path)
    before = code_fingerprint(root)

    _touch(tmp_path / "docs" / "RUNBOOK.md", "# runbook, rewritten\n")
    _touch(tmp_path / "tests" / "test_thing.py", "def test_x(): assert True\n")
    _touch(tmp_path / "outputs" / "evidence.json", '{"findings": 3}\n')
    (tmp_path / "core" / "engine.pyc").write_text("compiled\n", encoding="utf-8")

    assert code_fingerprint(root) == before


def test_a_tree_with_no_code_is_unknown_rather_than_changed(tmp_path):
    """A fingerprint that cannot be taken must read as unknown, not as "the code changed".

    An empty walk would otherwise hash to a perfectly valid constant that differs from the frozen
    baseline -- so an unmounted drive or a wrong working directory would demand a restart the
    operator cannot explain.
    """
    root = _repo(tmp_path)
    real = code_fingerprint(root)
    missing = code_fingerprint(str(tmp_path / "does-not-exist"))

    assert real                                     # a real checkout does produce a fingerprint
    assert missing == ""                            # an absent one is explicitly unknown
    assert compute_identity(running_sha="a" * 40, head_sha="a" * 40, product_version="t",
                            started_at="2026-07-27T00:00:00+00:00",
                            running_code=real, current_code=missing)["restart_required"] is False


def _identity(**kw):
    base = dict(running_sha="a" * 40, head_sha="a" * 40, product_version="test",
                started_at="2026-07-27T00:00:00+00:00")
    base.update(kw)
    return compute_identity(**base)


def test_clean_start_needs_no_restart():
    ident = _identity(running_code="fp1", current_code="fp1", local_changes_at_start=False)

    assert ident["restart_required"] is False
    assert ident["code_changed"] is False
    assert ident["running_build"] == "a" * 12
    assert ident["warning"] == ""


def test_code_changed_after_start_requires_a_restart():
    ident = _identity(running_code="fp1", current_code="fp2", local_changes_at_start=False)

    assert ident["restart_required"] is True
    assert ident["code_changed"] is True
    assert ident["stale"] is False          # HEAD never moved -- only a SHA-blind check sees this
    assert ident["warning"]


def test_a_moved_head_still_requires_a_restart():
    ident = _identity(head_sha="b" * 40, running_code="fp1", current_code="fp1")

    assert ident["stale"] is True
    assert ident["restart_required"] is True


def test_a_dirty_start_is_never_reported_as_a_clean_commit():
    ident = _identity(running_code="fp1", current_code="fp1", local_changes_at_start=True)

    assert ident["running_build"] == "a" * 12 + " + local changes"
    assert ident["local_changes_at_start"] is True
    assert ident["restart_required"] is False      # dirty at start is not by itself stale


def test_unknown_fingerprints_never_raise_a_false_alarm():
    ident = _identity(running_code="", current_code="", local_changes_at_start=None)

    assert ident["code_changed"] is False
    assert ident["restart_required"] is False
    assert ident["local_changes_at_start"] is None


# --- what the operator actually reads ---------------------------------------------------------
#
# The runtime TABLE moved from Overview to Settings (the Unified Scout spec, §5): it is something an
# operator looks up when they suspect a problem, not something they need while deciding what to scan.
# What Overview keeps is the verdict — one System-ready line that grows only when something is wrong.
# Both surfaces are pinned here so neither can quietly lose the fact.

def _rendered(tmp_path, ident, path="/"):
    import core.build_identity as bi
    from core.scout.dashboard import start_dashboard
    from core.scout.service import ScoutService
    from tests.scout_seam_fixtures import get

    original = bi.current_identity
    bi.current_identity = lambda *a, **k: ident
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        return get(f"{url}{path}")[1]
    finally:
        server.shutdown()
        bi.current_identity = original


def _overview(tmp_path, ident):
    return _rendered(tmp_path, ident, "/")


def _settings(tmp_path, ident):
    return _rendered(tmp_path, ident, "/settings")


def test_settings_runtime_block_reports_a_fresh_process(tmp_path):
    html = _settings(tmp_path, _identity(running_code="fp1", current_code="fp1",
                                         local_changes_at_start=False))

    assert "Runtime &mdash; up to date" in html or "Runtime — up to date" in html
    assert "Process started" in html
    assert "Running HEAD" in html
    assert "Local changes at process start" in html
    assert "Restart required" in html
    assert "restart_dashboard.ps1" not in html          # nothing to do, so no instruction


def test_overview_says_system_ready_when_the_process_is_fresh(tmp_path):
    html = _overview(tmp_path, _identity(running_code="fp1", current_code="fp1",
                                         local_changes_at_start=False))

    assert "System ready" in html
    assert "Local changes at process start" not in html      # the detail lives in Settings now


def test_settings_runtime_block_opens_itself_when_a_restart_is_due(tmp_path):
    html = _settings(tmp_path, _identity(running_code="fp1", current_code="fp2",
                                         local_changes_at_start=True))

    assert "restart required" in html                   # visible in the summary, before unfolding
    assert "<details class=\"advanced compact-details\" open>" in html
    assert "restart_dashboard.ps1" in html              # and how to clear it
    assert "+ local changes" in html                    # never presented as a clean commit


def test_overview_still_raises_a_due_restart_without_being_opened(tmp_path):
    """A fact the operator must act on cannot depend on them visiting Settings to find it."""
    html = _overview(tmp_path, _identity(running_code="fp1", current_code="fp2",
                                         local_changes_at_start=True))

    assert "System needs attention" in html
    assert "executable code changed since this process started" in html
    assert 'href="/settings#runtime"' in html
    assert "System ready</strong>" not in html


def test_neither_surface_offers_to_restart_over_http(tmp_path):
    """Process control stays outside the HTTP surface -- the block informs, it does not act."""
    ident = _identity(running_code="fp1", current_code="fp2", local_changes_at_start=True)

    for html in (_overview(tmp_path, ident), _settings(tmp_path, ident)):
        assert "/api/restart" not in html
        assert "restartDashboard(" not in html
        assert ">Restart<" not in html
