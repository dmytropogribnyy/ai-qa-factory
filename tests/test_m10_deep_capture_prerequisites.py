"""M10 — Deep Capture may not be offered on a host whose documented setup cannot deliver it.

Both live claims on `/scout` advertise Deep Capture as "a real browser: screenshots, **axe
accessibility**, performance timing …" and name **Chromium** as the one prerequisite. On this
repository at the M10 base:

  * `core/scout/pipeline/vendor/axe.min.js` does not exist;
  * `browser_qa.load_axe_source()` therefore falls through to three optional packages and raises;
  * `requirements.txt` declares neither Playwright nor any axe distribution;
  * `scripts/setup-local.ps1` installs `requirements.txt` and nothing else;
  * `preflight.py` probes tavily / browser / network / evidence — there is no axe probe;
  * `campaign_start.py` refuses a Deep Capture run without Chromium and has no equivalent for axe.

So a fresh machine is offered a capability its documented setup cannot produce, and the run is spent
before anyone finds out.

I first reported the defect as *strictly* pre-run, on the grounds that a missing module already
degrades a run. It does not. `_check_modules` counted a gap only where a receipt equals the literal
`"not_executed"`, while the Deep Capture failure path writes `"unavailable"` — which read PASS,
identical to a module that ran, even as the operator's own evidence page showed CAPTURE_FAILED for
the same run. The gap predicate is corrected here; the receipt keeps its distinct value, because
"nothing was recorded" and "it was tried and failed" are different facts.

The dependency is declared, never vendored: `axe-playwright-python==0.1.8` ships axe-core 4.12.1
under MPL-2.0 (© Deque Systems), at a path `load_axe_source()` already searches, so the production
loader finds it with no code change. Playwright is pinned to the version this repository proves —
installing the axe wrapper alone resolves a different one.
"""
from __future__ import annotations

import json
import pathlib
import re
import urllib.request

import pytest

from core.scout.campaign_start import CampaignLauncher
from core.scout.dashboard import start_dashboard
from core.scout.preflight import NOT_READY, READY, SKIPPED
from core.scout.service import ScoutService

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DEEP_REQS = _ROOT / "requirements-deep-capture.txt"
_SETUP = _ROOT / "scripts" / "setup-local.ps1"

# Proven in this repository and again in a throwaway isolated venv; see the M10 checkpoint.
_PINNED_AXE = "axe-playwright-python==0.1.8"
_PINNED_PLAYWRIGHT = "playwright==1.61.0"

_HOST = "127.0.0.1:8941"
_SEED = "http://127.0.0.1:8941/"


# --- the documented setup path must be able to make Deep Capture ready ---------------------------

def test_an_explicit_deep_capture_dependency_file_exists():
    assert _DEEP_REQS.exists(), (
        "Deep Capture advertises axe accessibility and no documented install path declares an axe "
        "distribution — the capability cannot be obtained by following the setup instructions"
    )


def test_the_deep_capture_dependencies_are_pinned_not_open_ended():
    text = _DEEP_REQS.read_text(encoding="utf-8")
    assert _PINNED_AXE in text, f"{_PINNED_AXE} is not pinned: {text!r}"
    assert _PINNED_PLAYWRIGHT in text, (
        f"{_PINNED_PLAYWRIGHT} is not pinned. Installing the axe wrapper alone resolves a different "
        "Playwright than this repository proves, so an unbounded transitive requirement is not a "
        "reproducibility contract"
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert "==" in stripped, f"unpinned Deep Capture dependency: {stripped!r}"


def test_the_dependency_note_records_provenance_rather_than_vendoring_the_bundle():
    text = _DEEP_REQS.read_text(encoding="utf-8")
    assert re.search(r"MPL-2\.0|Mozilla Public License", text), (
        "the bundled axe.min.js is MPL-2.0 (© Deque Systems); the note must say so rather than "
        "leaving a reader to infer the licence from the wrapper's own metadata, which says MIT"
    )
    assert not (_ROOT / "core" / "scout" / "pipeline" / "vendor" / "axe.min.js").exists(), (
        "the third-party bundle was copied into this repository; the binding decision declares the "
        "dependency instead of carrying it"
    )


def test_the_setup_script_offers_the_deep_capture_path_and_installs_the_browser_too():
    text = _SETUP.read_text(encoding="utf-8")
    assert "DeepCapture" in text, "setup-local.ps1 has no Deep Capture switch"
    assert "requirements-deep-capture.txt" in text, (
        "the Deep Capture switch does not install the declared dependency file"
    )
    assert re.search(r"playwright\s+install\s+chromium", text, re.I), (
        "the opt-in path installs Python packages but never the browser, so Deep Capture still "
        "cannot run after following it"
    )


def test_the_base_setup_never_implies_deep_capture_is_ready():
    """The base path stays light; its closing message must not leave the opposite impression."""
    text = _SETUP.read_text(encoding="utf-8")
    tail = text.split("Setup complete.", 1)[-1]
    assert "DeepCapture" in tail or "Deep Capture" in tail, (
        "the base setup finishes without telling the operator that Deep Capture needs a separate "
        "opt-in — silence here is what let the advertised capability go missing"
    )


# --- a real readiness probe, not "installed == ready" --------------------------------------------

def test_an_axe_readiness_probe_exists():
    from core.scout import preflight
    assert hasattr(preflight, "probe_axe"), (
        "preflight probes tavily/browser/network/evidence but never axe, so the operator learns "
        "that Deep Capture cannot deliver its advertised module only after spending a run"
    )


def test_the_axe_probe_reports_not_ready_when_the_source_cannot_load():
    from core.scout import preflight

    def _explode():
        raise RuntimeError("axe-core source not available")

    check = preflight.probe_axe(load_source=_explode)
    assert check.status == NOT_READY, check.detail
    assert check.required is True
    assert "axe" in check.detail.lower()


def test_the_axe_probe_is_not_satisfied_by_a_loadable_source_alone():
    """Loading bytes proves nothing about a page being able to run them."""
    from core.scout import preflight

    def _inject_fails(_source):
        raise RuntimeError("Chromium executable not found")

    check = preflight.probe_axe(load_source=lambda: "/*! axe v4.12.1 */", inject=_inject_fails)
    assert check.status == NOT_READY, (
        f"the probe reported readiness although axe could not be injected: {check.detail!r}"
    )


def test_the_axe_probe_reports_ready_only_when_axe_run_is_callable():
    from core.scout import preflight
    seen = {}

    def _inject(source):
        seen["source"] = source
        return "4.12.1"

    check = preflight.probe_axe(load_source=lambda: "/*! axe v4.12.1 */", inject=_inject)
    assert check.status == READY, check.detail
    assert "4.12.1" in check.detail
    assert seen["source"] == "/*! axe v4.12.1 */", (
        "the probe did not hand the loaded source to the injection step, so it proved nothing about "
        "the bytes the product would actually use"
    )


def test_the_axe_probe_is_part_of_the_readiness_REPORT_not_only_a_function(monkeypatch):
    """A probe with no production caller is a promise, not a guarantee — the M6 defect exactly.

    `run_preflight` is what the Dashboard readiness page and the Observer deep check aggregate. If
    axe is missing from it, a host that cannot deliver Deep Capture — the mode the start form selects
    by DEFAULT — still reads ready.
    """
    from core.scout import preflight

    monkeypatch.setattr(preflight, "probe_axe",
                        lambda **_: preflight.PreflightCheck("axe", "axe", NOT_READY, "absent", True))
    monkeypatch.setattr(preflight, "probe_browser",
                        lambda **_: preflight.PreflightCheck("browser", "browser", READY, "", True))
    report = preflight.run_preflight(output_dir="outputs", do_network=False)

    keys = [c.key for c in report.checks]
    assert "axe" in keys, f"the readiness report has no axe check: {keys}"
    assert report.ok is False, (
        "a host with Chromium but no usable axe-core reported READY for a product whose start form "
        "defaults to Deep Capture"
    )


def test_the_readiness_report_does_not_launch_a_browser_when_launches_are_disabled(monkeypatch):
    """The cheap path stays cheap: `probe_browser_launch=False` must not start Chromium for axe."""
    from core.scout import preflight

    def _explode(**_):
        raise AssertionError("the axe probe launched a browser on the no-launch path")

    monkeypatch.setattr(preflight, "probe_axe", _explode)
    report = preflight.run_preflight(output_dir="outputs", do_network=False,
                                     probe_browser_launch=False)
    axe = [c for c in report.checks if c.key == "axe"]
    assert axe and axe[0].status == SKIPPED, axe


def test_the_axe_probe_defaults_to_the_production_loader():
    """A probe wired to its own copy of the search logic could pass while the product fails."""
    import inspect

    from core.scout import preflight
    source = inspect.getsource(preflight)
    assert "load_axe_source" in source, (
        "probe_axe does not reference the production loader (browser_qa.load_axe_source); a "
        "second, parallel discovery path would not be evidence about the real one"
    )


# --- Deep Capture must refuse BEFORE a run record is spent ---------------------------------------

class _FakeService:
    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        self._running = False
        self.started_configs = []

    def start(self, cfg):
        self._running = True
        self.started_configs.append(cfg)
        return cfg.run_id

    def is_running(self):
        return self._running


def _launcher(tmp_path, *, browser_probe, axe_probe):
    svc = _FakeService(str(tmp_path))
    registry = tmp_path / "reg"
    launcher = CampaignLauncher(svc, registry_dir=str(registry),
                                allowed_local_hosts=frozenset({_HOST}), resolve_dns=False,
                                starter=svc.start, browser_probe=browser_probe,
                                axe_probe=axe_probe)
    return launcher, svc, registry


def _req(key, **extra):
    body = {"confirm": True, "idempotency_key": key, "seeds": [_SEED], "browser_mode": "playwright"}
    body.update(extra)
    return body


def test_deep_capture_is_refused_when_axe_is_not_ready_even_though_chromium_is(tmp_path):
    launcher, svc, registry = _launcher(tmp_path, browser_probe=lambda: True,
                                        axe_probe=lambda: False)
    result = launcher.start(_req("m10-refuse"))
    assert result.ok is False, "Deep Capture started on a host that cannot run axe"
    assert result.status == 503, result.status
    assert svc.started_configs == [], "the starter ran despite the refusal"
    assert list(registry.glob("*.json")) == [], (
        "a run record was written before the refusal — the operator spends a run to learn this"
    )


def test_the_refusal_names_the_setup_path_and_the_static_alternative(tmp_path):
    launcher, _, _ = _launcher(tmp_path, browser_probe=lambda: True, axe_probe=lambda: False)
    message = launcher.start(_req("m10-message")).message
    lowered = message.lower()
    assert "axe" in lowered, message
    assert "requirements-deep-capture" in lowered or "deepcapture" in lowered.replace(" ", ""), (
        f"the refusal does not name the setup path an operator should run: {message!r}"
    )
    assert "static" in lowered, f"the refusal does not offer the Static alternative: {message!r}"


def test_a_ready_host_still_starts_deep_capture(tmp_path):
    launcher, svc, _ = _launcher(tmp_path, browser_probe=lambda: True, axe_probe=lambda: True)
    result = launcher.start(_req("m10-ready"))
    assert result.ok is True, result.message
    assert [c.browser_mode for c in svc.started_configs] == ["playwright"]


def test_a_missing_chromium_is_still_reported_as_a_browser_problem(tmp_path):
    """The new gate must not swallow the older, more specific diagnosis."""
    launcher, _, _ = _launcher(tmp_path, browser_probe=lambda: False, axe_probe=lambda: True)
    result = launcher.start(_req("m10-nochrome"))
    assert result.ok is False and result.status == 503
    assert "chromium" in result.message.lower(), result.message


def test_static_scans_never_consult_the_axe_probe(tmp_path):
    def _axe_probe():
        raise AssertionError("a static scan consulted the axe probe")

    launcher, svc, _ = _launcher(tmp_path, browser_probe=lambda: False, axe_probe=_axe_probe)
    result = launcher.start(_req("m10-static", browser_mode="static"))
    assert result.ok is True, result.message
    assert [c.browser_mode for c in svc.started_configs] == ["static"]


# --- the advertised prerequisites must match reality on the live surface --------------------------

@pytest.fixture(scope="module")
def scout_page(tmp_path_factory):
    """Render the real route. Source text is not a live surface — an M9 lesson kept."""
    tmp = tmp_path_factory.mktemp("m10")
    server, url = start_dashboard(ScoutService(str(tmp)), operator_home=True)
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/scout", timeout=10) as response:
            assert response.status == 200, response.status
            yield re.sub(r"\s+", " ", response.read().decode("utf-8", "replace"))
    finally:
        server.shutdown()


def test_every_rendered_deep_capture_claim_names_axe_among_its_prerequisites(scout_page):
    claims = re.findall(r"Deep Capture = real browser:.{0,200}?\(needs ([^)]*)\)", scout_page)
    assert len(claims) == 2, (
        f"expected the two known Deep Capture claims on /scout, found {len(claims)} — the scan is "
        "stale, so a claim may have moved out from under this guard"
    )
    for prerequisites in claims:
        assert re.search(r"axe", prerequisites, re.I), (
            "a rendered Deep Capture claim advertises axe accessibility but names only "
            f"{prerequisites!r} as what the host needs"
        )


# --- post-run: a browser that ran without axe must not read as a clean run ------------------------
#
# I first wrote a test here pinning "an unexecuted axe module reports PARTIAL", believing the defect
# was strictly pre-run. It was not. `_check_modules` counted a gap only where a receipt equals the
# literal `"not_executed"`, while the Deep Capture failure path writes `"unavailable"`
# (`backends.py:582`) — which passed straight through and read PASS, identical to `"ok"`. Meanwhile
# `evidence_state` showed the operator CAPTURE_FAILED for the same run. Correction and scope
# decision: issue #57 comments 5152788052 / 5152794864.
#
# Every fixture below completes ALL the other receipts, so accessibility is the only variable. My
# first attempt did not, read PARTIAL off a missing `screenshots.json`, and would have "confirmed"
# the guarantee for an unrelated reason.

def _run_with_axe_status(root: pathlib.Path, axe_status: str) -> "object":
    """A real evidence tree whose only open question is accessibility."""
    from core.scout.run_validation import _Evidence

    run = root / "scout" / "run-m10"
    prospect = run / "prospects" / "example-test"
    prospect.mkdir(parents=True, exist_ok=True)
    (run / "state.json").write_text(json.dumps(
        {"status": "COMPLETED", "prospects": {"example-test": {"domain": "example.test"}}}),
        encoding="utf-8")
    (prospect / "observation.json").write_text(
        json.dumps({"axe_status": axe_status, "perf": {"ttfb_ms": 12}}), encoding="utf-8")
    (prospect / "screenshots.json").write_text(json.dumps({"captured": 2}), encoding="utf-8")
    (prospect / "interaction_scenario.json").write_text(
        json.dumps({"outcome": "recorded"}), encoding="utf-8")
    return _Evidence(str(root), "run-m10")


def test_a_browser_run_whose_axe_could_not_inject_degrades_the_run(tmp_path):
    from core.scout.run_validation import PARTIAL, _check_modules

    check = _check_modules(_run_with_axe_status(tmp_path, "unavailable"))
    assert check.status == PARTIAL, (
        "axe could not be injected, the operator's evidence page says CAPTURE_FAILED, and "
        f"validation still calls the modules complete: {check.to_dict()}"
    )


def test_the_unavailable_receipt_is_reported_as_such_not_rewritten(tmp_path):
    """Degrading the verdict must not cost the distinction the receipt carries.

    "No receipt at all" and "the browser ran and axe would not inject" are different facts, and
    collapsing the second into the first would hide a diagnosable failure behind a generic absence.
    """
    from core.scout.run_validation import _check_modules

    check = _check_modules(_run_with_axe_status(tmp_path, "unavailable"))
    assert check.observed["example-test"]["accessibility"] == "unavailable", check.observed
    assert "unavailable" in str(check.explanation).lower(), (
        f"the explanation does not distinguish an explicit failure receipt: {check.explanation!r}"
    )


def test_an_absent_receipt_still_degrades_the_run(tmp_path):
    """The pre-existing guarantee, unchanged."""
    from core.scout.run_validation import PARTIAL, _check_modules

    check = _check_modules(_run_with_axe_status(tmp_path, ""))
    assert check.status == PARTIAL, check.to_dict()
    assert check.observed["example-test"]["accessibility"] == "not_executed", check.observed


def test_a_run_whose_axe_actually_ran_still_passes(tmp_path):
    """Guard against over-correcting: a real axe run must not be dragged down with the failures."""
    from core.scout.run_validation import PASS, _check_modules

    check = _check_modules(_run_with_axe_status(tmp_path, "ok"))
    assert check.status == PASS, check.to_dict()


def test_a_degraded_module_check_blocks_validation(tmp_path):
    """`validated` is not modified by this slice; this pins that PARTIAL already suffices."""
    from core.scout.run_validation import PASS, Check, RunValidation, _check_modules

    degraded = _check_modules(_run_with_axe_status(tmp_path, "unavailable"))
    report = RunValidation(run_id="run-m10", generated_at="2026-01-01T00:00:00+00:00",
                           checks=[Check("other", PASS, expected="", observed=None), degraded])
    assert report.validated is False, "a run missing its advertised accessibility module read VALIDATED"
    assert report.status == "PARTIAL", report.status


def test_the_operator_surface_and_validation_describe_the_same_run(tmp_path):
    """The divergence that made this a defect rather than a preference — asserted, not assumed."""
    from core.scout.evidence_state import CAPTURE_FAILED, evidence_states
    from core.scout.run_validation import PARTIAL, _check_modules

    detail = {"network": {"axe_status": "unavailable", "axe_violations": [], "perf": {"ttfb_ms": 12}}}
    states = {s.kind: s for s in evidence_states(detail)}
    assert states["accessibility"].state == CAPTURE_FAILED, states["accessibility"]
    assert _check_modules(_run_with_axe_status(tmp_path, "unavailable")).status == PARTIAL, (
        "the operator's evidence page and the validation report disagree about the same run"
    )
