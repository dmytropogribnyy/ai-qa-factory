"""Needs attention must count sites, not attempts — and must not call a typo a website.

Three separate untruths lived on this screen. Every campaign that hit the same blocked domain added
another identical row, so one company that had been retried four times read as four companies
needing help. A pasted `0.1` reached the list as though it were a site, because the canonicaliser
happily returns `0.1` for it (and `1.5` for `192.168.1.5`, which is worse: it invents a domain that
looks real). And the headline counted rows, so "13 targets were blocked" was really 13 *attempts* at
some smaller number of sites.

The fix is one inventory function that both the page and its counters read: identity is the canonical
domain, repeated blockages of that domain are its history, and a value that is not a public website
is reported as what it is instead of being listed beside real companies.
"""
from __future__ import annotations

import urllib.request

import pytest

from core.scout.dashboard import start_dashboard
from core.scout.needs_attention import attention_inventory
from core.scout.service import ScoutService
from core.scout.store import RunStore


def _blocked_run(out: str, run_id: str, *, url: str, when: str, pid: str = "01") -> None:
    """One persisted campaign run that left `url` waiting for a human."""
    store = RunStore(out, run_id)
    store.save_state({
        "status": "COMPLETED", "finished_at": when,
        "prospects": {pid: {"url": url, "status": "MANUAL_ACTION_REQUIRED",
                            "reason": "captcha_detected"}}})


# --- one row per site, attempts underneath -------------------------------------------------------

def test_two_campaigns_blocked_on_one_domain_produce_one_row(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "campaign-a", url="https://nolt.io/", when="2026-07-20T10:00:00+00:00")
    _blocked_run(out, "campaign-b", url="https://www.nolt.io/", when="2026-07-26T10:00:00+00:00")

    inv = attention_inventory(out)

    assert [s.domain for s in inv.sites] == ["nolt.io"]
    assert inv.unique_sites == 1
    assert inv.attempt_events == 2


def test_the_current_row_is_the_most_recent_attempt(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "campaign-old", url="https://nolt.io/", when="2026-07-20T10:00:00+00:00")
    _blocked_run(out, "campaign-new", url="https://nolt.io/", when="2026-07-26T10:00:00+00:00")

    site = attention_inventory(out).sites[0]

    assert site.run_id == "campaign-new"
    assert site.attempt_count == 2
    assert [a["run_id"] for a in site.attempts] == ["campaign-new", "campaign-old"]


def test_earlier_attempts_stay_available_as_history(tmp_path):
    """They really happened; they just are not separate companies."""
    out = str(tmp_path)
    _blocked_run(out, "campaign-old", url="https://nolt.io/", when="2026-07-20T10:00:00+00:00")
    _blocked_run(out, "campaign-new", url="https://nolt.io/", when="2026-07-26T10:00:00+00:00")

    site = attention_inventory(out).sites[0]

    assert {a["run_id"] for a in site.attempts} == {"campaign-old", "campaign-new"}
    assert all(a.get("updated_at") for a in site.attempts)


# --- values that are not websites ----------------------------------------------------------------

def test_a_malformed_target_is_not_listed_as_a_site(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "campaign-a", url="0.1", when="2026-07-26T10:00:00+00:00")

    inv = attention_inventory(out)

    assert inv.sites == []
    assert [i.value for i in inv.invalid] == ["0.1"]
    assert inv.invalid[0].kind == "malformed"
    assert inv.unique_sites == 0


def test_a_private_address_is_not_dressed_up_as_a_domain(tmp_path):
    """`canonical_domain("192.168.1.5")` returns "1.5" — a domain that never existed."""
    out = str(tmp_path)
    _blocked_run(out, "campaign-a", url="http://192.168.1.5/", when="2026-07-26T10:00:00+00:00")

    inv = attention_inventory(out)

    assert inv.sites == []
    assert [i.value for i in inv.invalid] == ["http://192.168.1.5/"]
    assert inv.invalid[0].kind == "non_public"
    assert "1.5" not in {getattr(s, "domain", "") for s in inv.sites}


def test_localhost_is_reported_as_non_public(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "campaign-a", url="http://localhost/", when="2026-07-26T10:00:00+00:00")

    inv = attention_inventory(out)

    assert inv.sites == []
    assert inv.invalid[0].kind == "non_public"


def test_real_sites_survive_alongside_invalid_ones(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "campaign-a", url="https://nolt.io/", when="2026-07-26T10:00:00+00:00")
    _blocked_run(out, "campaign-b", url="0.1", when="2026-07-26T11:00:00+00:00")

    inv = attention_inventory(out)

    assert [s.domain for s in inv.sites] == ["nolt.io"]
    assert len(inv.invalid) == 1
    assert inv.unique_sites == 1


# --- counters the headline is built from ---------------------------------------------------------

def test_unique_sites_and_attempt_events_are_counted_separately(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "c1", url="https://nolt.io/", when="2026-07-20T10:00:00+00:00")
    _blocked_run(out, "c2", url="https://nolt.io/", when="2026-07-21T10:00:00+00:00")
    _blocked_run(out, "c3", url="https://plausible.io/", when="2026-07-22T10:00:00+00:00")

    inv = attention_inventory(out)

    assert inv.unique_sites == 2
    assert inv.attempt_events == 3
    assert inv.headline() == "2 sites need review. 3 blocked attempts were recorded."


def test_the_headline_is_singular_for_one_of_each(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "c1", url="https://nolt.io/", when="2026-07-20T10:00:00+00:00")

    assert attention_inventory(out).headline() == (
        "1 site needs review. 1 blocked attempt was recorded.")


def test_an_empty_inventory_says_nothing_needs_review(tmp_path):
    assert attention_inventory(str(tmp_path)).headline() == "No sites need review."


# --- what must keep working ----------------------------------------------------------------------

def test_a_manual_attempt_run_is_not_a_second_target(tmp_path):
    """PR #51 folded manual retries into their origin; that must survive the rewrite."""
    out = str(tmp_path)
    _blocked_run(out, "campaign-a", url="https://nolt.io/", when="2026-07-26T10:00:00+00:00")
    store = RunStore(out, "manual-nolt-1")
    store.save_state({"status": "COMPLETED", "manual_attempt_for": "campaign-a",
                      "finished_at": "2026-07-26T12:00:00+00:00",
                      "prospects": {"01": {"url": "https://nolt.io/",
                                           "status": "MANUAL_ACTION_REQUIRED"}}})

    inv = attention_inventory(out)

    assert inv.unique_sites == 1
    assert inv.attempt_events == 1          # the folded retry is not an independent event

def test_a_resolved_target_leaves_the_list(tmp_path):
    out = str(tmp_path)
    store = RunStore(out, "campaign-a")
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-26T10:00:00+00:00",
                      "prospects": {"01": {"url": "https://nolt.io/",
                                           "status": "RESOLVED_BY_MANUAL_CHECK"}}})

    assert attention_inventory(out).sites == []


def test_the_reason_comes_from_the_stop_record_when_there_is_one(tmp_path):
    out = str(tmp_path)
    _blocked_run(out, "campaign-a", url="https://nolt.io/", when="2026-07-26T10:00:00+00:00")
    RunStore(out, "campaign-a").save_prospect_artifact(
        "01", "manual_action.json", {"reason": "human_verification_page"})

    assert attention_inventory(out).sites[0].reason == "human_verification_page"


# --- the screen the operator actually reads ------------------------------------------------------

@pytest.fixture()
def attention_page(tmp_path):
    """A dashboard over a store holding two tries at one site, one at another, and two non-sites."""
    out = str(tmp_path)
    _blocked_run(out, "c1", url="https://nolt.io/", when="2026-07-20T10:00:00+00:00")
    _blocked_run(out, "c2", url="https://www.nolt.io/", when="2026-07-26T10:00:00+00:00")
    _blocked_run(out, "c3", url="https://plausible.io/", when="2026-07-25T10:00:00+00:00")
    _blocked_run(out, "c4", url="0.1", when="2026-07-24T10:00:00+00:00")
    _blocked_run(out, "c5", url="http://192.168.1.5/", when="2026-07-23T10:00:00+00:00")
    server, url = start_dashboard(ScoutService(out), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/scout/attention", timeout=10) as response:
            yield response.read().decode("utf-8")
    finally:
        server.shutdown()


def test_the_page_lists_one_row_per_site(attention_page):
    assert attention_page.count('data-label="Site"') == 2               # nolt.io and plausible.io
    assert attention_page.count(">nolt.io<") == 1
    assert 'href="/scout/target?run=c2&domain=nolt.io"' in attention_page   # the current attempt


def test_the_headline_names_sites_and_attempts_separately(attention_page):
    """Two companies, tried three times between them. The non-sites are not attempts at a site."""
    assert "2 sites need review" in attention_page
    assert "3 blocked attempts were recorded" in attention_page


def test_a_non_site_is_not_offered_as_a_target_to_open(attention_page):
    """`0.1` and a private IP appear as rejected input, never as a company with a link."""
    assert "domain=0.1" not in attention_page
    assert ">1.5<" not in attention_page                                # the invented domain
    assert "not a website address" in attention_page


def test_the_action_says_what_it_does(attention_page):
    """"Resolve" promised the blockage would be cleared; opening the target is what happens."""
    assert ">Resolve<" not in attention_page
    assert "Open manual check" in attention_page


def test_earlier_attempts_are_shown_as_that_sites_history(attention_page):
    assert "2 attempts" in attention_page
