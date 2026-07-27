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
