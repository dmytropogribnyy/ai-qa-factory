"""Overview should answer "what needs me now", and Scout is the thing that usually does.

The page had grown into a stack of equally-sized panels that each repeated some version of "nothing
here": an empty attention hero, an empty active-work card, an empty campaigns card, an Advanced view
options fold and a full Runtime table. Four large blocks saying nothing is happening pushed the one
block that starts work below the fold, and buried a real restart warning among them.

So: Scout comes before client work, empty states shrink to a line instead of a panel, and the runtime
detail moves to Settings, where the operator goes when they want diagnostics rather than when they
want to start a scan. What stays on Overview is a single honest System-ready line that only grows
when something is actually wrong.
"""
from __future__ import annotations

import urllib.request

import pytest

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService


@pytest.fixture()
def dash(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        yield url
    finally:
        server.shutdown()


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


@pytest.fixture()
def overview(dash) -> str:
    return _get(dash + "/")


# --- order ---------------------------------------------------------------------------------------

def test_scout_comes_before_client_work(overview):
    """Scout is what the operator starts; client work is what is already running."""
    assert overview.index(">Scout</h2>") < overview.index(">Client work</h2>")


def test_the_sections_are_in_the_agreed_order(overview):
    order = [overview.index(marker) for marker in (
        'class="summary-grid', ">Scout</h2>", ">Needs your attention</h2>", ">Client work</h2>",
        'id="system-ready"')]
    assert order == sorted(order), order


# --- naming --------------------------------------------------------------------------------------

def test_the_scout_button_is_called_start_scout(overview):
    assert "Start Scout</a>" in overview
    assert "Start a Scout campaign" not in overview


def test_scout_results_are_one_click_away(overview):
    assert "View Scout results" in overview
    assert 'href="/results"' in overview


def test_active_work_is_called_client_work(overview):
    assert ">Client work</h2>" in overview
    assert ">Active work</h2>" not in overview


# --- empty states --------------------------------------------------------------------------------

def test_an_empty_attention_list_is_one_line_not_a_panel(overview):
    """With nothing to do it should read as a line, not as a card competing with real work."""
    assert "Nothing needs your attention" in overview
    assert 'class="card empty compact status-hero"' not in overview
    assert "attention-clear" in overview


def test_the_same_empty_state_is_not_repeated_in_several_big_panels(overview):
    """Three panels each saying "nothing yet" is three times the noise for the same fact."""
    assert overview.count('class="card empty') <= 1


# --- what moved off Overview ---------------------------------------------------------------------

def test_the_full_runtime_table_is_not_on_overview(overview):
    assert 'class="runtime-table"' not in overview
    assert "Local changes at process start" not in overview


def test_advanced_view_options_are_not_on_overview(dash, overview):
    """The fold rendered whenever the diagnostics view was on, so check that view too."""
    assert "Advanced view options" not in overview
    assert "Advanced view options" not in _get(dash + "/?diagnostics=1")


def test_a_filtered_view_still_says_it_is_filtered(dash):
    """Moving the switch to Settings must not make the filtered counts silently mean something else."""
    filtered = _get(dash + "/?diagnostics=1")

    assert "Showing diagnostic data" in filtered
    assert "Show production only" in filtered


def test_overview_keeps_a_compact_system_ready_line(overview):
    assert 'id="system-ready"' in overview
    assert "System ready" in overview


def test_system_details_are_reachable_from_the_line(overview):
    assert 'href="/settings#runtime"' in overview


def test_the_runtime_detail_lives_under_more(dash):
    """More -> Settings is where diagnostics belong; it must really carry them now."""
    settings = _get(dash + "/settings")

    assert 'id="runtime"' in settings
    assert "Local changes at process start" in settings
    assert "Running HEAD" in settings


def test_settings_is_reachable_from_the_more_menu(overview):
    assert 'href="/settings"' in overview


# --- accessibility / layout regressions the owner reported ---------------------------------------

def test_the_theme_button_is_not_clipped_off_the_right_edge(overview):
    """It sat outside the header's flex row, so it clipped at narrow widths."""
    assert "theme-toggle" in overview
    assert ".top .wrap{" in overview
    assert "flex-wrap:wrap" in overview


def test_every_summary_tile_is_a_real_link_with_a_label(overview):
    """A number with no destination is a dead end; screen readers need the words too."""
    import re
    tiles = re.findall(r'<a class="summary-item"[^>]*href="([^"]+)"', overview)
    assert len(tiles) >= 3
    assert all(t.startswith("/") for t in tiles)
