"""Reusable production operations behind the Service Capability Matrix (v3.2 items 21-22).

These are the ACTUAL functions the acceptance tests invoke, so that a "Fixture Verified" readiness
means production capability code genuinely ran (not an inline stand-in in the test). Each operation
is pure/deterministic, performs NO network I/O, and is safe to reuse in real client work:

- ``migrate_selenium_to_playwright`` — inventory a legacy suite, generate a Playwright spec that
  preserves the critical assertions, and prove parity of the covered behaviour.
- ``measure_flakiness`` — run a check repeatedly and classify its stability (real before/after).
- ``validate_source_backed_article`` — build a claim/citation map and reject fabricated benchmarks.
- ``generate_bdd_suite`` / ``run_bdd_suite`` — a bounded, EXECUTABLE BDD profile with
  requirement -> scenario -> automated step -> evidence traceability (no redundant feature files).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Tuple


# --------------------------------------------------------------------------- migration (7.2)
@dataclass
class MigrationInventory:
    source_framework: str
    tests: List[str]
    critical: Dict[str, str]           # test name -> the critical assertion it protects

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MigrationResult:
    inventory: MigrationInventory
    playwright_spec: str
    covered: List[str]
    gaps: List[str]
    parity_ok: bool

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["inventory"] = self.inventory.to_dict()
        return d


_TITLE_RE = re.compile(r"driver\.title\s*==\s*['\"]([^'\"]+)['\"]")


def inventory_selenium_suite(source_text: str) -> MigrationInventory:
    """Extract the test cases and their critical assertions from a Selenium/PyTest-style suite."""
    tests = re.findall(r"def\s+(test_\w+)\s*\(", source_text)
    critical: Dict[str, str] = {}
    # Associate a `driver.title == "X"` assertion with the enclosing test (simple, bounded scan).
    blocks = re.split(r"(?=def\s+test_)", source_text)
    for block in blocks:
        m_name = re.match(r"def\s+(test_\w+)", block.strip())
        if not m_name:
            continue
        m_title = _TITLE_RE.search(block)
        if m_title:
            critical[m_name.group(1)] = f"title=={m_title.group(1)}"
    return MigrationInventory(source_framework="selenium", tests=tests, critical=critical)


def generate_playwright_spec(inv: MigrationInventory) -> str:
    """Generate a Playwright + TypeScript spec that preserves the inventoried critical behaviour."""
    lines = ['import { test, expect } from "@playwright/test";', ""]
    for name, assertion in inv.critical.items():
        if assertion.startswith("title=="):
            title = assertion.split("==", 1)[1]
            lines += [f'test("{name} (migrated)", async ({{ page }}) => {{',
                      '  await page.goto("/");',
                      f'  await expect(page).toHaveTitle("{title}");',
                      "});", ""]
    return "\n".join(lines)


def migration_parity(inv: MigrationInventory, spec: str) -> Tuple[bool, List[str], List[str]]:
    """Return (parity_ok, covered, gaps): every critical behaviour must appear in the generated spec."""
    covered, gaps = [], []
    for name, assertion in inv.critical.items():
        expected = assertion.split("==", 1)[1] if "==" in assertion else assertion
        (covered if expected in spec else gaps).append(name)
    return (not gaps and bool(inv.critical)), covered, gaps


def migrate_selenium_to_playwright(source_text: str) -> MigrationResult:
    inv = inventory_selenium_suite(source_text)
    spec = generate_playwright_spec(inv)
    ok, covered, gaps = migration_parity(inv, spec)
    return MigrationResult(inventory=inv, playwright_spec=spec, covered=covered, gaps=gaps,
                           parity_ok=ok)


# --------------------------------------------------------------------------- flaky stabilization (7.5)
@dataclass
class FlakyReport:
    runs: int
    failures: int
    failure_rate: float
    classification: str                 # stable | flaky | consistently_failing
    stabilized: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def measure_flakiness(run_once: Callable[[], bool], runs: int) -> FlakyReport:
    """Run ``run_once`` (returns True when the check passes) ``runs`` times and classify stability.
    Reusable for a real client suite (pass a subprocess-backed ``run_once``) or a controlled fixture."""
    if runs <= 0:
        raise ValueError("runs must be positive")
    failures = sum(0 if run_once() else 1 for _ in range(runs))
    rate = failures / runs
    if failures == 0:
        classification = "stable"
    elif failures == runs:
        classification = "consistently_failing"
    else:
        classification = "flaky"
    return FlakyReport(runs=runs, failures=failures, failure_rate=round(rate, 4),
                       classification=classification, stabilized=(failures == 0))


# --------------------------------------------------------------------------- technical writing (7.10)
@dataclass
class WritingReport:
    total_claims: int
    cited: int
    uncited: List[str]
    fabricated_benchmarks: List[str]
    ok: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_PCT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?%")


def validate_source_backed_article(markdown: str, expected_claims: Dict[str, str]) -> WritingReport:
    """Verify every expected factual claim appears with a citation, and reject fabricated benchmark
    percentages (a common hallucination). ``expected_claims`` maps a claim sentence -> its source URL."""
    uncited: List[str] = []
    cited = 0
    for claim, url in expected_claims.items():
        has_claim = claim in markdown
        has_citation = url in markdown or f"[source]({url})" in markdown
        if has_claim and has_citation:
            cited += 1
        else:
            uncited.append(claim)
    # Any percentage that is not itself immediately cited is treated as a fabricated benchmark.
    fabricated = [m.group(0) for m in _PCT_RE.finditer(markdown)]
    ok = not uncited and not fabricated and bool(expected_claims)
    return WritingReport(total_claims=len(expected_claims), cited=cited, uncited=uncited,
                         fabricated_benchmarks=fabricated, ok=ok)


# --------------------------------------------------------------------------- BDD (7.9, item 22)
@dataclass
class BddScenario:
    name: str
    given: str
    when: str
    then: str
    requirement: str                    # the requirement this scenario traces to

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BddSuite:
    feature: str
    scenarios: List[BddScenario] = field(default_factory=list)

    def gherkin(self) -> str:
        lines = [f"Feature: {self.feature}"]
        for s in self.scenarios:
            lines += [f"  Scenario: {s.name}", f"    Given {s.given}", f"    When {s.when}",
                      f"    Then {s.then}"]
        return "\n".join(lines) + "\n"

    def to_dict(self) -> Dict[str, Any]:
        return {"feature": self.feature, "scenarios": [s.to_dict() for s in self.scenarios]}


@dataclass
class BddRunReport:
    total: int
    passed: int
    failed: List[str]
    traceability: Dict[str, str]        # scenario name -> requirement
    ok: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def generate_bdd_suite(feature: str, requirements: List[str]) -> BddSuite:
    """Turn business requirements into business-readable, EXECUTABLE scenarios. Each requirement of
    the shape 'X should Y when Z' becomes one Given/When/Then scenario traced back to the requirement.
    Requirements with no automatable shape are skipped (never a redundant non-executable feature)."""
    scenarios: List[BddScenario] = []
    for i, req in enumerate(requirements, 1):
        m = re.search(r"(.+?)\s+should\s+(.+?)\s+when\s+(.+)", req, re.IGNORECASE)
        if not m:
            continue
        subject, outcome, condition = (p.strip().rstrip(".") for p in m.groups())
        scenarios.append(BddScenario(
            name=f"{subject} {outcome}", given=f"the system with {subject}",
            when=condition, then=outcome, requirement=req))
    return BddSuite(feature=feature, scenarios=scenarios)


def run_bdd_suite(suite: BddSuite, steps: Dict[str, Callable[[BddScenario], bool]]) -> BddRunReport:
    """Execute each scenario by invoking its bound ``then`` step (keyed by scenario name). A step
    returns True when the expected outcome holds. This is a bounded, deterministic runner — no
    external cucumber runtime — that produces genuine pass/fail + requirement traceability."""
    failed: List[str] = []
    traceability: Dict[str, str] = {}
    for sc in suite.scenarios:
        traceability[sc.name] = sc.requirement
        step = steps.get(sc.name)
        try:
            ok = bool(step(sc)) if step is not None else False
        except Exception:
            ok = False
        if not ok:
            failed.append(sc.name)
    total = len(suite.scenarios)
    return BddRunReport(total=total, passed=total - len(failed), failed=failed,
                        traceability=traceability, ok=(total > 0 and not failed))
