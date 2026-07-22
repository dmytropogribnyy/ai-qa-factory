"""Scout hotfix — Dashboard UI regressions (parts B and C).

Loopback-HTTP render checks (same pattern as test_v33_dashboard_scout) pinning the two real
Golden-Path UX defects the first live campaign surfaced:

  * B — chip-styled BUTTONS did not inherit a text colour (buttons don't inherit `color`), so action
        buttons showed dark default text on the dark surface. Central CSS now gives every chip button
        a contrasting colour + hover/focus/active/disabled + semantic primary/danger variants.
  * C — analyzed domains and campaign titles were dead text. They are now links; and after a terminal
        run state the Pause/Resume/Stop controls are disabled (honest UI).

All assertions target strings that exist ONLY because of the B/C edits (verified absent from the
pre-hotfix dashboard), so they are genuine regressions guards, not incidental matches.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService


def _dash(tmp_path):
    return start_dashboard(ScoutService(str(tmp_path)), operator_home=True)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


# -- part B: chip button contrast ------------------------------------------------------------------


def test_chip_buttons_have_contrasting_text_and_semantic_variants(tmp_path):
    server, url = _dash(tmp_path)
    try:
        _, body = _get(url + "/scout/new")
        # buttons now inherit a real text colour (the root-cause fix)
        assert "button.chip,a.chip{color:var(--text)" in body
        # semantic variants exist and use accessible ink-on-accent / error tokens
        assert ".chip.primary" in body and "var(--primary-ink)" in body
        assert ".chip.danger" in body
        # disabled chip buttons are visibly, distinctly disabled
        assert "button.chip:disabled" in body
    finally:
        server.shutdown()


def test_run_campaign_button_is_primary(tmp_path):
    server, url = _dash(tmp_path)
    try:
        _, body = _get(url + "/scout/new")
        assert 'id="run" class="chip primary"' in body      # the CTA reads as the primary action
    finally:
        server.shutdown()


# -- part C: interactivity (links + terminal-state control disabling) ------------------------------


def test_progress_page_links_domains_and_disables_terminal_controls(tmp_path):
    server, url = _dash(tmp_path)
    try:
        _, body = _get(url + "/scout/progress?id=none")
        # Pause / Resume / Stop carry stable ids so the client can disable them
        assert 'id="bp"' in body and 'id="br"' in body and 'id="bs"' in body
        # after a terminal run state those controls are disabled (honest UI)
        assert "stopped_with_checkpoint" in body and "disabled=term" in body
        # each analyzed domain row is rendered as a link to its target detail card (progress-specific
        # client builder; the pre-hotfix progress page rendered the domain as plain text)
        assert "encodeURIComponent(x.domain" in body and "/scout/target?domain=" in body
    finally:
        server.shutdown()


def test_campaigns_page_links_title_to_progress_and_has_open_column(tmp_path):
    # Seed one canonical *production* campaign (structured id) so a row renders.
    cid = "campaign-ui-regression-20260722t000000z-abcd12"
    rc = Path(str(tmp_path)) / "scout" / "_runcontrol"
    rc.mkdir(parents=True, exist_ok=True)
    (rc / f"{cid}.json").write_text(json.dumps({"campaign_id": cid}), encoding="utf-8")
    server, url = _dash(tmp_path)
    try:
        _, body = _get(url + "/scout/campaigns")
        assert "<th>Open</th>" in body                        # new Open column header
        assert f'href="/scout/progress?id={cid}"' in body     # title (and Open chip) link to progress
    finally:
        server.shutdown()
