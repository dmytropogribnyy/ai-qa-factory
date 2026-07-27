"""A public email found on a page Scout actually opened must not be thrown away.

Found by the live acceptance run against plausible.io. Scout walked twelve pages of the site and then
reported "Email not found", because contact extraction only ever read the LANDING page's
observation.json. Every other page it opened — including the one a company normally puts its address
on — was fetched, checked, and its links discarded.

That is the worst shape this can take: not a missing capability, but a capability that ran and whose
result was dropped on the floor. It also produced a wrong verdict — a site with eight confirmed
findings and a perfectly reachable public mailbox came out as "Needs review" instead of "Ready to
contact", which is the difference between work an operator can send and work they must go and redo
by hand.

The fix keeps the existing rules intact: only genuinely public addresses, only from a page Scout
really opened, and every address still carries the exact URL it was found on.
"""
from __future__ import annotations

from core.scout.backends import PageObservation
from core.scout.config import ScoutRunConfig
from core.scout.engine import ScoutEngine
from core.scout.outreach.qa_draft import extract_public_contact_records
from core.scout.store import RunStore

DOMAIN = "plausible.example"


class _SiteWithAContactPage:
    """A landing page that links to /contact, and a /contact page carrying the mailbox."""
    name = "static"
    screenshot_dir = None

    def observe(self, url, _timeout_s, _max_bytes, *, record_video=False, deep_qa=False):
        if url.rstrip("/").endswith("/contact"):
            return PageObservation(
                url=url, final_url=url, status=200, ok=True, backend="static",
                title="Contact", meta_description="Talk to us", has_viewport_meta=True,
                headings=[{"level": 1, "text": "Contact"}], landmarks={"main": 1},
                links=[f"mailto:hello@{DOMAIN}"])
        return PageObservation(
            url=url, final_url=f"https://{DOMAIN}/", status=200, ok=True, backend="static",
            title=DOMAIN, meta_description="Analytics", has_viewport_meta=True,
            headings=[{"level": 1, "text": "Analytics"}], landmarks={"main": 1},
            links=[f"https://{DOMAIN}/contact", f"https://{DOMAIN}/pricing"])


def _run(tmp_path) -> RunStore:
    store = RunStore(str(tmp_path), "contact-walk")
    cfg = ScoutRunConfig(campaign_name="adhoc", seeds=[f"https://{DOMAIN}/"], max_sites=1,
                         output_dir=str(tmp_path), run_id="contact-walk", resolve_dns=False)
    ScoutEngine(cfg, store, backend=_SiteWithAContactPage()).run()
    return store


def _pid(store: RunStore) -> str:
    return next(iter((store.load_state().get("prospects") or {})))


def test_an_email_on_a_walked_page_is_recorded_with_the_page_it_was_on(tmp_path):
    store = _run(tmp_path)

    contacts = store.load_prospect_artifact(_pid(store), "contacts.json") or {}

    assert [c["email"] for c in contacts.get("public", [])] == [f"hello@{DOMAIN}"]
    assert contacts["public"][0]["source_url"] == f"https://{DOMAIN}/contact"
    assert contacts["public"][0]["source"]


def test_the_landing_page_alone_would_have_found_nothing(tmp_path):
    """Pins the exact gap: the old path read only this, and this has no address on it."""
    store = _run(tmp_path)
    observation = store.load_prospect_artifact(_pid(store), "observation.json") or {}

    assert extract_public_contact_records(observation, domain=DOMAIN) == []


def test_the_target_read_model_surfaces_the_walked_page_contact(tmp_path):
    from core.scout.campaign_service import CampaignService

    _run(tmp_path)
    detail = CampaignService(str(tmp_path)).target_detail(DOMAIN, run="contact-walk")

    assert detail["contacts"] == [f"hello@{DOMAIN}"]
    assert detail["contact_records"][0]["source_url"] == f"https://{DOMAIN}/contact"


def test_a_findings_bearing_site_with_a_mailbox_becomes_ready_to_contact(tmp_path):
    """The verdict this bug got wrong: sendable work was reported as work needing a human."""
    from core.scout.campaign_service import CampaignService
    from core.scout.site_result import READY_TO_CONTACT, site_result

    _run(tmp_path)
    detail = CampaignService(str(tmp_path)).target_detail(DOMAIN, run="contact-walk")
    detail["findings"] = [{"title": "Broken checkout", "severity": "high"}]

    assert site_result(detail).result == READY_TO_CONTACT


def test_a_site_with_no_public_address_anywhere_still_says_so(tmp_path):
    """The honest empty state must survive the fix — absence is still reported as absence."""
    from core.scout.campaign_service import CampaignService

    class _NoAddresses(_SiteWithAContactPage):
        def observe(self, url, _timeout_s, _max_bytes, *, record_video=False, deep_qa=False):
            observation = super().observe(url, _timeout_s, _max_bytes)
            observation.links = [link for link in observation.links
                                 if not link.lower().startswith("mailto:")]
            return observation

    store = RunStore(str(tmp_path), "no-contact")
    cfg = ScoutRunConfig(campaign_name="adhoc", seeds=[f"https://{DOMAIN}/"], max_sites=1,
                         output_dir=str(tmp_path), run_id="no-contact", resolve_dns=False)
    ScoutEngine(cfg, store, backend=_NoAddresses()).run()

    detail = CampaignService(str(tmp_path)).target_detail(DOMAIN, run="no-contact")
    assert detail["contacts"] == []


def test_an_address_on_another_company_is_never_collected(tmp_path):
    """A walked page may link off-site; a third party's mailbox is not this target's contact."""
    class _ForeignAddress(_SiteWithAContactPage):
        def observe(self, url, _timeout_s, _max_bytes, *, record_video=False, deep_qa=False):
            observation = super().observe(url, _timeout_s, _max_bytes)
            if url.rstrip("/").endswith("/contact"):
                observation.links = ["mailto:sales@some-other-company.example"]
            return observation

    store = RunStore(str(tmp_path), "foreign")
    cfg = ScoutRunConfig(campaign_name="adhoc", seeds=[f"https://{DOMAIN}/"], max_sites=1,
                         output_dir=str(tmp_path), run_id="foreign", resolve_dns=False)
    ScoutEngine(cfg, store, backend=_ForeignAddress()).run()

    contacts = store.load_prospect_artifact(_pid(store), "contacts.json") or {}
    assert [c["email"] for c in contacts.get("public", [])] == []


# --- and the reason it still found nothing on the real site --------------------------------------

class _LinkRichSite:
    """A landing page like plausible.io's: two dozen feature pages, with /contact far down."""
    name = "static"
    screenshot_dir = None

    def observe(self, url, _timeout_s, _max_bytes, *, record_video=False, deep_qa=False):
        if url.rstrip("/").endswith("/contact"):
            return PageObservation(url=url, final_url=url, status=200, ok=True, backend="static",
                                   title="Contact", has_viewport_meta=True,
                                   headings=[{"level": 1, "text": "Contact"}],
                                   landmarks={"main": 1}, links=[f"mailto:hello@{DOMAIN}"])
        if url.rstrip("/") != f"https://{DOMAIN}":
            return PageObservation(url=url, final_url=url, status=200, ok=True, backend="static",
                                   title="Feature", has_viewport_meta=True,
                                   headings=[{"level": 1, "text": "Feature"}],
                                   landmarks={"main": 1}, links=[])
        return PageObservation(
            url=url, final_url=f"https://{DOMAIN}/", status=200, ok=True, backend="static",
            title=DOMAIN, has_viewport_meta=True, headings=[{"level": 1, "text": "Analytics"}],
            landmarks={"main": 1},
            # /contact sits after twenty-five feature pages, exactly as it does on the real site.
            links=[f"https://{DOMAIN}/feature-{i:02d}" for i in range(25)]
                  + [f"https://{DOMAIN}/contact"])


def test_the_contact_page_is_reached_even_on_a_link_rich_site(tmp_path):
    """The live plausible.io run walked twelve pages and /contact was the twenty-sixth link.

    Finding a public address is one of the pipeline's stated outputs, so a page that plainly IS the
    contact page is worth one of the budgeted slots ahead of the twentieth feature page. The ceiling
    itself does not move — only the order in which candidates are offered to it.
    """
    store = RunStore(str(tmp_path), "link-rich")
    cfg = ScoutRunConfig(campaign_name="adhoc", seeds=[f"https://{DOMAIN}/"], max_sites=1,
                         output_dir=str(tmp_path), run_id="link-rich", resolve_dns=False)
    ScoutEngine(cfg, store, backend=_LinkRichSite()).run()

    contacts = store.load_prospect_artifact(_pid(store), "contacts.json") or {}
    assert [c["email"] for c in contacts.get("public", [])] == [f"hello@{DOMAIN}"]


def test_prioritising_contact_pages_does_not_widen_the_page_budget(tmp_path):
    """Reordering candidates must not become a way to fetch more pages than the ceiling allows."""
    store = RunStore(str(tmp_path), "budget")
    cfg = ScoutRunConfig(campaign_name="adhoc", seeds=[f"https://{DOMAIN}/"], max_sites=1,
                         coverage="adaptive", output_dir=str(tmp_path), run_id="budget",
                         resolve_dns=False)
    ScoutEngine(cfg, store, backend=_LinkRichSite()).run()

    coverage = store.load_prospect_artifact(_pid(store), "coverage.json") or {}
    assert coverage["meaningful_pages_tested"] <= coverage["page_ceiling"]
