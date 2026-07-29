"""One ingestion path for every source, and a rejected line is never a site.

The operator can name sites three ways — paste, upload, discovery — and "where the list came from"
must not change what happens to it. These tests pin the intake contract the preview shows and the
queue then obeys: canonical-domain identity, an honest duplicate count, and rejections that say why.

The two values in the spec's acceptance file are the point of the rejection tests: `0.1` and
`http://localhost/` must never reach History looking like companies.

**These are unit tests and they do not touch the network.** Parsing, canonicalisation and
deduplication are pure string work; the only reason they ever reached a DNS resolver is that the
default ``UrlPolicy`` resolves, and nothing here said otherwise. That made seven of them fail in an
isolated environment with "Temporary failure in name resolution" -- a network report dressed up as a
parsing regression. Every call below goes through the offline policy, and the one test that does
need a real lookup is marked as an integration test and skips when there is no network.
"""
from __future__ import annotations

import socket

import pytest

from core.scout.intake import (KIND_MALFORMED, KIND_NON_PUBLIC, canonical_entry_url, parse_rows,
                               parse_targets, parse_text)
from core.scout.url_safety import UrlPolicy

# No DNS. A unit test's answer must not depend on the machine's network, its DNS server, or whether
# the company being parsed still exists.
OFFLINE = UrlPolicy(resolve_dns=False)


def _text(value, **kwargs):
    kwargs.setdefault("policy", OFFLINE)
    return parse_text(value, **kwargs)


def _targets(values, **kwargs):
    kwargs.setdefault("policy", OFFLINE)
    return parse_targets(values, **kwargs)


def _rows(rows, **kwargs):
    kwargs.setdefault("policy", OFFLINE)
    return parse_rows(rows, **kwargs)


def _domains(result):
    return [t.domain for t in result.targets]


# --- identity is the canonical domain, not the URL -------------------------------------------

def test_www_and_bare_host_are_one_site():
    result = _text("https://nolt.io/\nhttps://www.nolt.io/")

    assert _domains(result) == ["nolt.io"]
    assert result.counts()["unique_sites"] == 1
    assert result.counts()["duplicates"] == 1
    assert result.duplicates[0].duplicate_of == "https://nolt.io/"


def test_a_deep_page_with_tracking_is_the_same_site_as_the_home_page():
    result = _text("https://plausible.io/\nhttps://plausible.io/pricing?utm_source=scout-e2e")

    assert result.counts()["unique_sites"] == 1
    assert result.counts()["duplicates"] == 1


def test_the_page_the_operator_named_is_kept_but_tracking_is_stripped():
    """A pasted pricing page means that page; our own campaign tracking is not part of it."""
    assert canonical_entry_url("https://plausible.io/pricing?utm_source=scout-e2e&plan=pro") == \
        "https://plausible.io/pricing?plan=pro"
    assert canonical_entry_url("plausible.io") == "https://plausible.io/"
    assert canonical_entry_url("HTTPS://Plausible.IO/Pricing") == "https://plausible.io/Pricing"


def test_scheme_case_and_trailing_slash_do_not_create_a_second_site():
    result = _text("HTTP://Userlist.com\nhttps://userlist.com/\nuserlist.com")

    assert _domains(result) == ["userlist.com"]
    assert result.counts()["duplicates"] == 2


# --- a rejected line is not a site -------------------------------------------------------------

def test_a_bare_number_is_rejected_as_not_an_address():
    result = _text("0.1")

    assert result.targets == []
    assert result.rejected[0].kind == KIND_MALFORMED
    assert "not a website address" in result.rejected[0].reason
    assert result.counts()["unique_sites"] == 0


def test_localhost_and_private_addresses_are_rejected_as_non_public():
    result = _text("http://localhost/\nhttp://127.0.0.1/\nhttp://192.168.0.10/")

    assert result.targets == []
    assert {r.kind for r in result.rejected} == {KIND_NON_PUBLIC}
    assert all("public" in r.reason for r in result.rejected)


def test_unsupported_schemes_are_refused_with_a_reason():
    result = _text("ftp://example.com/\njavascript:alert(1)\nmailto:hi@example.com")

    assert result.targets == []
    assert len(result.rejected) == 3
    assert all(r.reason for r in result.rejected)


def test_a_real_file_mixes_all_four_outcomes():
    """The spec's acceptance input, exactly."""
    result = _text("https://userlist.com/\nhttps://nolt.io/\nhttps://www.nolt.io/\n0.1\n"
                        "http://localhost/")
    counts = result.counts()

    assert _domains(result) == ["userlist.com", "nolt.io"]
    assert counts == {"lines_read": 5, "unique_sites": 2, "duplicates": 1, "rejected": 2,
                      "already_analyzed": 0}
    assert {r.value for r in result.rejected} == {"0.1", "http://localhost/"}


# --- history awareness -------------------------------------------------------------------------

def test_a_site_already_in_history_is_flagged_but_still_scannable():
    """Re-scanning is legitimate; what must not happen is a second CURRENT row for the site."""
    result = _text("https://plausible.io/", known_domains=frozenset({"plausible.io"}))

    assert _domains(result) == ["plausible.io"]              # still queued
    assert result.counts()["already_analyzed"] == 1
    # The flag rides on the TARGET, not on a duplicate entry: the line was not dropped, so counting
    # it among the ignored duplicates would contradict the fact that it is about to be scanned.
    assert result.targets[0].already_analyzed is True
    assert result.duplicates == []


# --- pinned semantics ---------------------------------------------------------------------------

def test_operator_named_targets_are_pinned_and_discovery_results_are_not():
    assert _text("https://userlist.com/").targets[0].pinned is True
    assert _targets(["https://userlist.com/"], pinned=False).targets[0].pinned is False


# --- spreadsheet rows ----------------------------------------------------------------------------

def test_a_curated_row_yields_its_address_and_ignores_the_rest():
    rows = [["Scout seed URL", "Product", "Priority"],
            ["https://plausible.io/", "Plausible", "A"],
            ["userlist.com", "Userlist", "B"],
            ["", "", ""],
            ["not a url", "junk", "C"]]
    result = _rows(rows)

    assert _domains(result) == ["plausible.io", "userlist.com"]
    # The header and the junk row carry no address. They are REPORTED rather than silently dropped,
    # so a file that was only half understood cannot look fully understood.
    assert result.counts()["rejected"] == 2
    assert {r.value for r in result.rejected} == {"Scout seed URL", "not a url"}


def test_blank_input_reads_as_nothing_rather_than_an_error():
    result = _text("   \n\n  ")

    assert result.counts() == {"lines_read": 0, "unique_sites": 0, "duplicates": 0,
                               "rejected": 0, "already_analyzed": 0}
    assert result.seeds() == []


# --- a line that is queued was not "ignored" -----------------------------------------------------

def test_a_site_already_in_history_is_not_counted_as_an_ignored_line():
    """Seen in the live preview: three lines produced "2 duplicate line(s) ignored" when one was.

    An already-analyzed site IS queued — re-scanning is the point of pasting it again. Counting it
    among the ignored duplicates told the operator a line had been dropped while it was about to be
    scanned, and the two numbers then contradicted each other in the same sentence.
    """
    result = _text("https://plausible.io/\nhttps://www.plausible.io/\n0.1",
                  known_domains=frozenset({"plausible.io"}))

    assert result.counts() == {"lines_read": 3, "unique_sites": 1, "duplicates": 1,
                               "rejected": 1, "already_analyzed": 1}
    assert [d.value for d in result.duplicates] == ["https://www.plausible.io/"]
    assert [t.domain for t in result.targets] == ["plausible.io"]


def test_already_analyzed_is_reported_on_the_target_that_will_be_rescanned():
    result = _text("https://nolt.io/", known_domains=frozenset({"nolt.io"}))

    assert result.counts()["duplicates"] == 0        # nothing was dropped
    assert result.counts()["already_analyzed"] == 1
    assert result.targets[0].already_analyzed is True


# --- the one place a real lookup belongs ----------------------------------------------------------

def _network_available() -> bool:
    try:
        socket.getaddrinfo("example.com", 443)
        return True
    except OSError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _network_available(), reason="no DNS available in this environment")
def test_a_hostname_that_does_not_resolve_is_refused_when_dns_is_consulted():
    """Resolution is a SAFETY control, not a parsing step.

    It belongs in an integration test that says so: refusing a name that resolves nowhere is real
    protection, and it is also the only behaviour here that can fail because of the network rather
    than because of the code.
    """
    result = parse_text("https://this-host-should-not-exist-aiqa.invalid/",
                        policy=UrlPolicy(resolve_dns=True))

    assert result.targets == []
    assert result.rejected and result.rejected[0].reason
