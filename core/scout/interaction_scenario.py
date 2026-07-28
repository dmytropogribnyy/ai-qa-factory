"""A recorded interaction, and an honest name for what it proved.

Scout could already record one kind of video: a broken flow entry, replayed. That covers a single
signature, so almost every run finished with no video and an explanation of why not. The gap it left
is the one thing a still frame genuinely cannot show — a control that responds, and changes nothing.

This module performs ONE bounded reversible interaction on a public page and describes it in three
separate layers, because conflating them is how a recording becomes a lie:

**Baseline** — what was measurably true before anything was touched.
**Observed** — what was measurably true after the action.
**Cleanup** — proof the page was put back.

From those three it derives an outcome, and the outcome decides what the recording is allowed to be
used for:

``defect``
    An expectation was violated: a filter was applied, and neither the stated result count nor the
    visible result set changed. That is a functional defect, and the clip is its evidence.
``interaction_trace``
    The control behaved correctly. The recording proves the pipeline records — it is NOT a finding,
    never a talking point, and never part of an offer to fix anything.
``not_run``
    No qualifying control, a precondition that did not hold, or an action with no observable effect
    at all. Nothing is claimed.

Nothing here decides *which* control to touch by hardcoded selector. The page is inspected first and
the control is found by shape — a checkbox inside a group of checkboxes on a page that displays a
result count; a select with real options; a button that adds something removable. A site that has
changed since anyone last looked simply yields no candidate, which is the correct answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.scout.public_action_policy import is_irreversible, is_reversible

SCENARIO_FILTER = "reversible_filter"
SCENARIO_SELECT = "reversible_select"
SCENARIO_ADD_REMOVE = "reversible_add_remove"

OUTCOME_DEFECT = "defect"
OUTCOME_TRACE = "interaction_trace"
OUTCOME_NOT_RUN = "not_run"
# Reversibility was not PROVEN. Distinct from not_run ("nothing to do here"): something was found,
# and the recorder declined it or could not put the page back.
OUTCOME_NOT_APPLICABLE = "not_applicable"

# The only requests a recorded interaction may cause. A domain sitting in the allow-list is
# permission to READ it — never permission to change it, and same-origin is not an exception.
SAFE_HTTP_METHODS = frozenset({"GET", "HEAD"})

_MIN_LABEL_CHARS = 2
_MAX_LABEL_CHARS = 80

# Only this one may become a finding. The others prove the recorder works, which is not a defect.
DEFECT_SIGNATURE = "interaction_filter_ineffective"


@dataclass
class ScenarioResult:
    """One attempted interaction, described so it can be checked rather than believed."""

    scenario: str = ""
    outcome: str = OUTCOME_NOT_RUN
    reason: str = "no qualifying control was found on this page"
    url: str = ""
    final_url: str = ""
    control_label: str = ""
    # What was actually clicked, when that differs from the control whose state is being read: a
    # styled checkbox is an invisible input behind a visible label.
    click_selector: str = ""
    action: str = ""
    action_performed: bool = False
    baseline: Dict[str, Any] = field(default_factory=dict)
    observed: Dict[str, Any] = field(default_factory=dict)
    after_cleanup: Dict[str, Any] = field(default_factory=dict)
    cleanup_ok: bool = False
    steps: List[str] = field(default_factory=list)
    # Writes the page attempted and the recorder refused. Kept because an operator reading a clip
    # of a page that did nothing deserves to know it did nothing because it was STOPPED.
    blocked_requests: List[Dict[str, Any]] = field(default_factory=list)
    video_ref: str = ""
    error: str = ""

    @property
    def is_defect(self) -> bool:
        return self.outcome == OUTCOME_DEFECT

    @property
    def keeps_video(self) -> bool:
        """A clip is worth keeping only when a real action ran and the page was put back.

        Without the action it is a page-load clip; without the cleanup it is a recording of a page
        left in a state Scout changed and did not restore, which is not evidence of anything good.
        """
        return bool(self.action_performed and self.cleanup_ok
                    and self.outcome in (OUTCOME_DEFECT, OUTCOME_TRACE))

    def to_dict(self) -> Dict[str, Any]:
        return {"scenario": self.scenario, "outcome": self.outcome, "reason": self.reason,
                "url": self.url, "final_url": self.final_url,
                "control_label": self.control_label, "action": self.action,
                "click_selector": self.click_selector,
                "action_performed": self.action_performed, "baseline": dict(self.baseline),
                "observed": dict(self.observed), "after_cleanup": dict(self.after_cleanup),
                "cleanup_ok": self.cleanup_ok, "steps": list(self.steps),
                "blocked_requests": list(self.blocked_requests),
                "video_ref": self.video_ref, "error": self.error}


def screen_candidate(candidate: Optional[Dict[str, Any]]) -> tuple:
    """Decide whether Scout may touch this control at all. Returns ``(allowed, refusal_reason)``.

    Fail-closed, and deliberately not one rule for everything. Positive recognition comes from
    different places for different controls, and using one criterion for both would either wave
    through "Add payment method" or refuse every genuine filter:

    * a FILTER or a SELECT is recognised by its SHAPE — a checkbox among siblings on a page that
      states a result count, a select with real alternatives. Its label is a facet value ("Blue",
      "Under $50") and could never appear on a list of approved actions, so the label is screened
      only for being present, readable and not an irreversible boundary.
    * an ADD control is recognised by its LABEL, because there the label IS the action. A bare
      "Add" says nothing about what it adds, so it must positively match a known reversible action
      rather than merely fail to match a forbidden one.

    A control with no label at all is refused outright: nothing about it can be checked, and an
    unreadable control is exactly the one whose consequences cannot be predicted.
    """
    if not isinstance(candidate, dict) or candidate.get("kind") not in (
            SCENARIO_FILTER, SCENARIO_SELECT, SCENARIO_ADD_REMOVE):
        return False, "no reversible control that Scout can act on safely was found on this page"
    kind = str(candidate["kind"])
    label = str(candidate.get("label") or "").strip()
    if len(label) < _MIN_LABEL_CHARS:
        return False, "the control has no readable label, so its effect cannot be checked"
    if len(label) > _MAX_LABEL_CHARS:
        return False, "the control's label is not a label a person would read"
    if is_irreversible(label):
        return False, f"the control's label crosses an irreversible boundary: {label!r}"
    if kind == SCENARIO_ADD_REMOVE and not is_reversible(label):
        return False, (f"{label!r} does not name a known reversible action, and an ambiguous "
                       "control is refused rather than guessed at")
    side_effect = str(candidate.get("side_effect") or "").strip()
    if side_effect:
        return False, side_effect
    return True, ""


def candidate_is_safe(candidate: Optional[Dict[str, Any]]) -> bool:
    """Boolean form of :func:`screen_candidate`, kept for callers that only need the verdict."""
    return screen_candidate(candidate)[0]


def safe_option(label: str) -> tuple:
    """Screen the option a select is about to be switched TO.

    The select itself passing the label check says nothing about its contents: a "Plan" dropdown is
    an ordinary reversible control right up until the option chosen from it is "Cancel subscription".
    """
    text = (label or "").strip()
    if len(text) < _MIN_LABEL_CHARS:
        return False, "the alternative option has no readable label"
    if is_irreversible(text):
        return False, f"the alternative option crosses an irreversible boundary: {text!r}"
    return True, ""


def classify(scenario: str, baseline: Dict[str, Any], observed: Dict[str, Any],
             *, action_performed: bool, cleanup_ok: bool, navigated_away: bool = False,
             blocked_writes: int = 0):
    """Name what the interaction showed. Returns ``(outcome, reason)``.

    The rules are deliberately asymmetric. A control whose own state refuses to change is reported
    as "no observable effect" rather than as a defect, because Scout cannot know what that control
    was for. A FILTER is different: a filter that leaves both the stated count and the visible
    results exactly as they were has failed at the one thing its label promises, and that is a
    finding a client can act on.
    """
    if not action_performed:
        return OUTCOME_NOT_RUN, "the action never ran, so nothing was observed"
    if navigated_away:
        return OUTCOME_NOT_RUN, "the page navigated away, so this was not a same-page interaction"
    if blocked_writes:
        # The page tried to write and was stopped, so what happened next is a picture of a page
        # missing a response it would normally have had. Calling that a defect would report our own
        # guard as the site's fault.
        return OUTCOME_NOT_APPLICABLE, (
            f"the control triggered {blocked_writes} request(s) that would have changed data on the "
            "site; they were refused, so the result of the interaction cannot be judged")
    if action_performed and not cleanup_ok:
        # Reversibility is the licence for touching a stranger's page at all. Unproven, the only
        # honest outcome is that this scenario did not apply here.
        return OUTCOME_NOT_APPLICABLE, (
            "the page could not be verified as restored, so this interaction is not reported")

    if scenario == SCENARIO_FILTER:
        if not observed.get("control_engaged"):
            return OUTCOME_NOT_RUN, "the filter control did not register the selection"
        count_before, count_after = baseline.get("result_count"), observed.get("result_count")
        items_before, items_after = baseline.get("item_signature"), observed.get("item_signature")
        if count_before is None and items_before is None:
            return OUTCOME_NOT_RUN, "the page exposes no result count or result list to compare"
        count_changed = (count_before is not None and count_after is not None
                         and count_before != count_after)
        items_changed = (items_before is not None and items_after is not None
                         and items_before != items_after)
        if count_changed or items_changed:
            return OUTCOME_TRACE, ("the filter narrowed the results, which is correct behaviour — "
                                   "this recording is evidence that the interaction was captured, "
                                   "not a defect")
        return OUTCOME_DEFECT, (
            f"the {baseline.get('control_label') or 'filter'} filter was applied and accepted, but "
            f"the result count stayed at {count_after} and the visible results did not change")

    if scenario == SCENARIO_SELECT:
        if baseline.get("selected_label") == observed.get("selected_label"):
            return OUTCOME_NOT_RUN, "the selection did not change, so no interaction was captured"
        return OUTCOME_TRACE, ("a different option was selected and the original was restored — "
                               "an interaction trace, not a defect")

    if scenario == SCENARIO_ADD_REMOVE:
        before, after = baseline.get("removable_count", 0), observed.get("removable_count", 0)
        if after <= before:
            return OUTCOME_NOT_RUN, "the control added nothing observable, so nothing is claimed"
        if not cleanup_ok:
            return OUTCOME_NOT_RUN, "what was added could not be removed again"
        return OUTCOME_TRACE, ("an element was added and removed again — an interaction trace, not "
                               "a defect")

    return OUTCOME_NOT_RUN, f"unknown scenario {scenario!r}"


def finding_from(result: ScenarioResult, *, run_id: str, prospect_ref: str, video_ref: str = ""):
    """Turn a defect outcome into a ScoutFinding. Returns ``None`` for anything else.

    The gate is the whole point: an interaction trace looks exactly like a defect from the outside —
    same recording, same steps, same evidence — and only the outcome separates a fixture that proved
    the recorder works from a real problem a client should hear about.
    """
    if not result.is_defect:
        return None
    from core.scout.findings import ScoutFinding

    control = result.control_label or "filter"
    count = result.observed.get("result_count")
    return ScoutFinding(
        finding_id=f"{prospect_ref}-interaction-filter",
        run_id=run_id,
        prospect_ref=prospect_ref,
        url=result.url,
        check_family="business_flow",
        category="functional",
        title=f"The {control} filter does not filter",
        severity="high",
        confidence="high",
        reproduction_steps=list(result.steps),
        expected=(f"selecting the {control} filter narrows the results to matching items"),
        actual=(f"the filter is accepted but the result count stays at {count} and the same "
                f"non-matching items remain listed"),
        business_impact=("Visitors who narrow a catalogue and see it unchanged lose confidence in "
                         "the listing and commonly leave rather than scroll."),
        evidence_refs=[ref for ref in (video_ref, "interaction_scenario.json") if ref],
        signature=DEFECT_SIGNATURE,
    )


# --- what the browser runs -----------------------------------------------------------------------
#
# Kept here rather than in the backend so the contract is readable in one place and the classifier
# above can be tested against the exact shapes these produce.

FIND_CANDIDATE_JS = r"""
() => {
  const vis = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const labelOf = el => {
    const id = el.getAttribute('id');
    let lab = id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : null;
    if (!lab) lab = el.closest('label');
    const text = (lab ? lab.textContent : '') || el.getAttribute('aria-label') ||
                 el.getAttribute('title') || el.value || '';
    return text.replace(/\s+/g, ' ').trim().slice(0, 80);
  };
  // Tag the chosen elements instead of writing a CSS path back out. A generated path is brittle
  // against re-rendering (the very thing a filter does), and a path that stops resolving reads as
  // "the control reported nothing" — indistinguishable from a control that ignored the click.
  // The attribute lives only in this ephemeral browser context; nothing is sent anywhere.
  const tag = (el, name) => {
    document.querySelectorAll('[' + name + ']').forEach(e => e.removeAttribute(name));
    if (el) el.setAttribute(name, '1');
    return '[' + name + ']';
  };

  // What touching this control would ALSO do. This check was described in a comment here for
  // months and never actually performed, so a select that submitted its form on change was
  // indistinguishable from an inert one. A GET form is safe by definition — it is the non-GET
  // form, the submit button and the inline handler that reach through to somebody's server.
  const sideEffect = el => {
    // The PROPERTY, not the attribute: a bare <button> inside a form has no type attribute and is
    // a submit button anyway, which is exactly the case an attribute check would wave through.
    const type = String(el.type || el.getAttribute('type') || '').toLowerCase();
    if (type === 'submit' || type === 'image' || type === 'reset')
      return 'the control submits or resets a form';
    for (const attr of ['onchange', 'onclick', 'oninput'])
      if (/submit\s*\(|\.submit\b/i.test(el.getAttribute(attr) || ''))
        return 'the control runs an inline handler that submits a form';
    const f = el.form || el.closest('form');
    if (!f) return '';
    if ((f.getAttribute('method') || 'get').toLowerCase() !== 'get')
      return 'the control is inside a form that does not use GET';
    if (f.getAttribute('onsubmit')) return 'the surrounding form runs an onsubmit handler';
    return '';
  };

  // What a person would actually click. A styled checkbox hides the real <input> behind a label
  // or a span, so acting on the input itself either fails or bypasses the site's own handler.
  const clickTargetFor = el => {
    const id = el.getAttribute('id');
    const forLabel = id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : null;
    const own = el.closest('label');
    for (const cand of [forLabel, own]) if (cand && vis(cand)) return cand;
    return vis(el) ? el : (el.parentElement && vis(el.parentElement) ? el.parentElement : el);
  };

  // 1. A filter: an unchecked checkbox among siblings, on a page that states a result count.
  //    ``vis`` is deliberately NOT required of the input — a custom filter control is normally an
  //    invisible input with a visible label, and skipping those would skip most real filters.
  const boxes = Array.from(document.querySelectorAll('input[type=checkbox]'));
  const hasCount = /(\d[\d,]*)\s*(product|result|item|match)/i.test(document.body.innerText || '');
  if (hasCount && boxes.length >= 2) {
    const group = boxes.filter(b => !b.checked && !b.disabled && vis(clickTargetFor(b)));
    if (group.length >= 2) {
      const el = group[0];
      return {kind: 'reversible_filter', label: labelOf(el), side_effect: sideEffect(el),
              selector: tag(el, 'data-aiqa-control'),
              click_selector: tag(clickTargetFor(el), 'data-aiqa-click')};
    }
  }
  // 2. An add/remove pair: a button that adds something, with nothing removable yet.
  const buttons = Array.from(document.querySelectorAll('button, input[type=button]')).filter(vis);
  const adder = buttons.find(b => /^\s*add\b/i.test(b.textContent || b.value || ''));
  if (adder && !buttons.some(b => /delete|remove/i.test(b.textContent || b.value || ''))) {
    return {kind: 'reversible_add_remove', label: labelOf(adder), side_effect: sideEffect(adder),
            selector: tag(adder, 'data-aiqa-control'),
            click_selector: tag(adder, 'data-aiqa-click')};
  }
  // 3. A select with real alternatives and no submit-on-change form around it.
  const sel = Array.from(document.querySelectorAll('select')).filter(vis).find(
    s => s.options.length >= 2 && !s.multiple && !s.disabled);
  if (sel) return {kind: 'reversible_select', label: labelOf(sel), side_effect: sideEffect(sel),
                   option_labels: Array.from(sel.options).map(o => o.text).slice(0, 12),
                   selector: tag(sel, 'data-aiqa-control'),
                   click_selector: tag(sel, 'data-aiqa-click')};
  return null;
}
"""

MEASURE_JS = r"""
(args) => {
  const selector = (args && args.selector) || '';
  const wanted = ((args && args.label) || '').trim().toLowerCase();
  let el = selector ? document.querySelector(selector) : null;
  // A single-page app re-renders after a filter is applied, which can drop the marker attribute.
  // Losing the control would report "the control said nothing" — which is exactly the observation
  // under investigation — so it is found again by its label before that conclusion is drawn.
  if (!el && wanted) {
    const labelText = e => {
      const id = e.getAttribute('id');
      const lab = (id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : null)
                  || e.closest('label');
      return ((lab ? lab.textContent : '') || e.getAttribute('aria-label') || '')
        .replace(/\s+/g, ' ').trim().toLowerCase();
    };
    el = Array.from(document.querySelectorAll('input[type=checkbox], select')).find(
      e => labelText(e) === wanted) || null;
    if (el && selector.startsWith('[') && selector.endsWith(']')) {
      el.setAttribute(selector.slice(1, -1), '1');
    }
  }
  const body = document.body ? (document.body.innerText || '') : '';
  const m = body.match(/(\d[\d,]*)\s*(?:product|result|item|match)/i);
  const count = m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
  const vis = e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  // A bounded fingerprint of what is actually LISTED, so "the count stayed the same" can be told
  // apart from "the same items are still there".
  //
  // Finding the results generically is the hard part: querying for li/article/[class*=item] also
  // returns the navigation, whose text never changes, which would make every filter look broken.
  // Instead: the results are the largest group of SIBLINGS that share a structure — that is what a
  // rendered collection looks like, whatever the site calls its classes.
  const chrome = e => !!e.closest('nav, header, footer, [role=navigation], [role=banner]');
  let items = null, best = 0;
  for (const parent of Array.from(document.querySelectorAll('body *'))) {
    const kids = Array.from(parent.children).filter(k => vis(k) && !chrome(k));
    if (kids.length < 3) continue;
    const shape = k => k.nodeName + '|' + (k.className || '').toString().split(/\s+/)[0];
    const groups = {};
    for (const k of kids) groups[shape(k)] = (groups[shape(k)] || []).concat([k]);
    for (const key of Object.keys(groups)) {
      const group = groups[key];
      if (group.length > best && group.length >= 3) {
        best = group.length;
        items = group.slice(0, 12).map(e => (e.textContent || '').replace(/\s+/g, ' ').trim()
          .slice(0, 60)).filter(Boolean);
      }
    }
  }
  if (items) items = [String(best)].concat(items);   // the SIZE of the collection matters too
  const removable = Array.from(document.querySelectorAll('button, input[type=button]')).filter(
    e => vis(e) && /delete|remove/i.test(e.textContent || e.value || '')).length;
  const out = {result_count: count, item_signature: items, removable_count: removable,
               url: location.href};
  if (el) {
    if (el.type === 'checkbox') out.control_engaged = !!el.checked;
    if (el.tagName === 'SELECT') {
      out.selected_label = (el.options[el.selectedIndex] || {}).text || '';
      out.selected_value = el.value;
      out.option_labels = Array.from(el.options).map(o => o.text).slice(0, 12);
    }
  }
  return out;
}
"""
