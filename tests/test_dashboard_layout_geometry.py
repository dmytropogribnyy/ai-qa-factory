"""Two controls that rendered wrong while every HTML assertion passed.

Both were reported from a screenshot, and neither could have been caught by checking markup: the
elements were present, correctly labelled and accessible. They were simply in the wrong place.

- The source switch on Start Scout: a form-stack rule stretches inputs to the full row width, which
  is right for a text field and wrong for a radio. The radio filled its tile and pushed the label
  out past the border into the NEXT tile, so "Find websites" read as "Fi w".
- The More menu: its links are inline with no rule making them stack, so five items flowed as a
  paragraph and wrapped mid-list.

The tests therefore measure geometry in a real browser rather than assert on strings.
"""
from __future__ import annotations

import pytest

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.playwright_acceptance


@pytest.fixture()
def dash(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        yield url
    finally:
        server.shutdown()


def test_each_source_label_sits_inside_its_own_tile(dash):
    """The label must be within the border that frames it, not spilling into the next choice."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(dash + "/scout/new", wait_until="load")
        tiles = page.locator("#sources .option-tile")
        boxes = []
        for index in range(tiles.count()):
            tile = tiles.nth(index).bounding_box()
            label = tiles.nth(index).locator("span").bounding_box()
            boxes.append((tile, label))
        browser.close()

    assert len(boxes) == 3
    for tile, label in boxes:
        assert label["x"] >= tile["x"], "the label starts left of its tile"
        assert label["x"] + label["width"] <= tile["x"] + tile["width"] + 1, (
            "the label overflows its tile and runs into the next choice")


def test_the_radio_does_not_swallow_its_tile(dash):
    """The form-stack full-width rule is for text inputs; a radio must stay radio-sized."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(dash + "/scout/new", wait_until="load")
        radio = page.locator('#sources .option-tile input[type="radio"]').first.bounding_box()
        tile = page.locator("#sources .option-tile").first.bounding_box()
        browser.close()

    assert radio["width"] < 40, f"the radio is {radio['width']}px wide"
    assert radio["width"] < tile["width"] / 2


def test_the_more_menu_is_a_vertical_list(dash):
    """Five items flowed as a wrapped paragraph; a menu has to read as one item per line."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(dash + "/", wait_until="load")
        page.locator("nav details summary").click()
        page.wait_for_timeout(150)
        links = page.locator(".nav-menu a")
        boxes = [links.nth(i).bounding_box() for i in range(links.count())]
        browser.close()

    assert len(boxes) >= 4
    lefts = {round(b["x"]) for b in boxes}
    assert len(lefts) == 1, f"menu items are not aligned on one column: {sorted(lefts)}"
    tops = sorted(round(b["y"]) for b in boxes)
    assert len(set(tops)) == len(tops), "two menu items share a line"
