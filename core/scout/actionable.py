"""One set of findings, behind every number that describes them.

A target page could say "1 confirmed issue" and, a few centimetres below, offer to fix two. Neither
number was invented — they were counted from different collections. The verdict filtered out
informational findings; the fix offer did not; the draft letter used a third rule of its own. Every
surface was individually defensible and the page as a whole was untrue.

So the split happens once, here, and everything downstream reads the result:

**Actionable** — a confirmed problem with a severity. These are what a count means, what a talking
point is drawn from, and the only thing an offer to fix may refer to.
**Informational** — real observations that are not problems to fix. Counted, shown, never sold.
**Suppressed** — findings dropped as duplicates of one already in the set, kept with the reason so
a missing count can be explained rather than merely noticed.

The one rule that does the work: a finding is actionable when its severity is a real severity. An
interaction trace, a recorder validation and an informational observation all fail that test, which
is what keeps a fixture that proved the video pipeline works out of a client's list of defects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

# Severities that mean "not a problem to fix". Everything else is a real severity.
_NON_ACTIONABLE_SEVERITIES = frozenset({"info", "informational", "none", ""})

# The decision, as it travels. A finding that carries one of these has already been classified by
# the canonical split; nothing downstream may classify it again.
KIND_ACTIONABLE = "actionable"
KIND_INFORMATIONAL = "informational"


def kind_of(finding: Dict[str, Any]) -> str:
    """Read the decision a finding carries; classify only if it carries none.

    The fallback is for records written before the label existed. It answers the classification
    question correctly — the rule is the same one — but it cannot restore IDENTITY, which is why
    the totals a surface prints must be counted from labels rather than recovered by re-splitting.
    """
    carried = str((finding or {}).get("kind") or "").strip().lower()
    if carried in (KIND_ACTIONABLE, KIND_INFORMATIONAL):
        return carried
    return KIND_ACTIONABLE if is_actionable(finding) else KIND_INFORMATIONAL


def count_kinds(findings: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """How many of each kind an already-split collection holds. Never re-splits or deduplicates."""
    out = {KIND_ACTIONABLE: 0, KIND_INFORMATIONAL: 0}
    for finding in findings or []:
        out[kind_of(finding)] += 1
    return out


def is_actionable(finding: Dict[str, Any]) -> bool:
    """The ONE rule. A finding is actionable when it carries a real severity."""
    severity = str((finding or {}).get("severity") or "").strip().lower()
    return severity not in _NON_ACTIONABLE_SEVERITIES


def _identity(finding: Dict[str, Any]) -> str:
    """What makes two findings the same problem: the signature if the engine gave one, else the
    title and URL a reader would compare."""
    signature = str((finding or {}).get("signature") or "").strip().lower()
    if signature:
        return signature
    return (str((finding or {}).get("title") or "").strip().lower() + "\x00"
            + str((finding or {}).get("url") or "").strip().lower())


@dataclass(frozen=True)
class ActionableDisplay:
    """How many of the actionable findings a surface is showing, and how many there are.

    A shortened list is a legitimate thing for an email to contain; passing its length off as the
    finding count is not, and `len(bullets)` is a perfectly valid expression that no reviewer and no
    type checker will ever object to. Carrying both numbers in one object removes the opportunity:
    there is no way to read the cap while believing you read the total.
    """

    shown: int
    total: int

    @property
    def capped(self) -> bool:
        return self.shown < self.total

    @property
    def caption(self) -> str:
        """What the surface must say when it is showing a subset. Empty when it is showing all."""
        if not self.capped:
            return ""
        return (f"Showing the top {self.shown} of {self.total} confirmed "
                f"{'issue' if self.total == 1 else 'issues'}.")


@dataclass
class ActionableSet:
    """The canonical split for one target."""

    actionable: List[Dict[str, Any]] = field(default_factory=list)
    informational: List[Dict[str, Any]] = field(default_factory=list)
    suppressed: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Everything that survived deduplication — actionable and informational together."""
        return len(self.actionable) + len(self.informational)

    @property
    def confirmed_issue_count(self) -> int:
        """The number an operator reads as "issues". Nothing else may disagree with it."""
        return len(self.actionable)

    def labelled(self) -> List[Dict[str, Any]]:
        """The surviving findings in canonical order, each carrying the decision made about it.

        This is what makes the split survive a lossy projection. Re-running the split after fields
        have been dropped is not a recount — it is a different question asked of poorer data: two
        findings kept apart by their signatures become one finding once the signature is gone, and
        the second disappears between a page's count and the page's own list.

        So the decision is made once, here, and travels as `kind`. Everything downstream reads a
        label it was handed instead of re-deriving one from fields that may no longer exist.
        """
        return ([{**f, "kind": KIND_ACTIONABLE} for f in self.actionable]
                + [{**f, "kind": KIND_INFORMATIONAL} for f in self.informational])

    def display(self, shown: int) -> ActionableDisplay:
        """Bind a surface's visible count to the total it was drawn from."""
        return ActionableDisplay(shown=max(0, int(shown)), total=self.confirmed_issue_count)

    def severity_breakdown(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for finding in self.actionable:
            key = str(finding.get("severity") or "unknown").strip().lower()
            out[key] = out.get(key, 0) + 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {"confirmed_issues": self.confirmed_issue_count,
                "informational": len(self.informational),
                "suppressed": len(self.suppressed),
                "total": self.total,
                "severity_breakdown": self.severity_breakdown(),
                "suppressed_reasons": [s.get("suppressed_reason", "") for s in self.suppressed]}


def actionable_set(findings: Iterable[Dict[str, Any]]) -> ActionableSet:
    """Split one target's confirmed findings into the canonical collections.

    Deduplication happens BEFORE the split, so a problem reported twice is one problem in every
    number that follows rather than one in the count and two in the offer.
    """
    result = ActionableSet()
    seen: Dict[str, Dict[str, Any]] = {}
    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        key = _identity(finding)
        if key in seen:
            result.suppressed.append({
                **finding,
                "suppressed_reason": f"duplicate of {seen[key].get('title') or 'an earlier finding'}"})
            continue
        seen[key] = finding
        (result.actionable if is_actionable(finding) else result.informational).append(finding)
    return result
