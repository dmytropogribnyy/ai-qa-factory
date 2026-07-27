"""Scout — every surface that projects a target's counts must agree with its destination.

For a DONE target: Actionable = count(severity != "info"), Informational = count(severity == "info"),
Total = Actionable + Informational = len(API findings[]). The run row reads the compact counters and
the Target card reads the artifact, so this is a direct number-to-number comparison between two
independent sources — the seam PR #49 found one level up.
"""
from __future__ import annotations

import json
import re

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from tests.scout_seam_fixtures import RUN_A, RUN_B, build_seam_stand, get, no_tavily

_ROW = re.compile(
    r'<td data-label="Target">(?P<domain>[^<]*)</td>.*?'
    r'<td data-label="Actionable">(?P<actionable>\d+)</td>.*?'
    r'<td data-label="Informational">(?P<info>\d+)</td>', re.S)
_CARD_ACTIONABLE = re.compile(
    r'Actionable findings</span>\s*<strong>(?P<n>\d+)</strong>', re.S)
_CARD_INFO = re.compile(
    r'Informational notes</span>\s*<strong>(?P<n>\d+)</strong>', re.S)


def _run_rows(html: str) -> dict[str, tuple[int, int]]:
    return {m.group("domain"): (int(m.group("actionable")), int(m.group("info")))
            for m in _ROW.finditer(html)}


def test_every_done_row_agrees_with_its_own_target_card_and_api(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, run_html = get(f"{url}/scout/run?id={RUN_A}")
        rows = _run_rows(run_html)
        assert rows, "the run page rendered no parseable target rows"

        done = {"alpha.example", "epsilon.example", "theta.example"}
        assert done <= set(rows), f"missing DONE rows: {done - set(rows)}"

        for domain in sorted(done):
            actionable, info = rows[domain]
            _, card = get(f"{url}/scout/target?run={RUN_A}&domain={domain}")
            _, api = get(f"{url}/api/scout/target?run={RUN_A}&domain={domain}")
            payload = json.loads(api)

            card_actionable = _CARD_ACTIONABLE.search(card)
            card_info = _CARD_INFO.search(card)
            assert card_actionable and card_info, f"{domain}: card has no counts summary"

            assert int(card_actionable.group("n")) == actionable, f"{domain}: actionable disagrees"
            assert int(card_info.group("n")) == info, f"{domain}: informational disagrees"

            findings = payload["findings"]
            assert len(findings) == actionable + info, f"{domain}: total disagrees with the API"
            assert sum(1 for f in findings if f["severity"] != "info") == actionable
            assert sum(1 for f in findings if f["severity"] == "info") == info
    finally:
        server.shutdown()


def test_a_clean_done_target_reads_as_clean_not_as_unanalyzed(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, card = get(f"{url}/scout/target?run={RUN_A}&domain=theta.example")
    finally:
        server.shutdown()

    assert "No actionable defect was confirmed" in card
    assert "analysis incomplete" not in card.lower()


def test_pinning_a_run_shows_that_runs_numbers_not_the_latest(tmp_path, monkeypatch):
    """RUN_B rescanned alpha with different counts and non-overlapping titles: a page that ignores
    ?run= would show B's numbers under A's link."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, card_a = get(f"{url}/scout/target?run={RUN_A}&domain=alpha.example")
        _, card_b = get(f"{url}/scout/target?run={RUN_B}&domain=alpha.example")
    finally:
        server.shutdown()

    assert "alpha.example: alpha (high)" in card_a
    assert "alpha.example: alpha-rescan (high)" not in card_a
    assert "alpha.example: alpha-rescan (high)" in card_b
    assert "alpha.example: alpha (high)" not in card_b


def test_missing_coverage_renders_as_unavailable_not_zero(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, run_html = get(f"{url}/scout/run?id={RUN_A}")
    finally:
        server.shutdown()

    epsilon_row = re.search(r'<td data-label="Target">epsilon\.example</td>.*?</tr>',
                            run_html, re.S)
    assert epsilon_row, "epsilon row not found"
    assert "0 pages" not in epsilon_row.group(0)      # absent coverage is unavailable, never zero
