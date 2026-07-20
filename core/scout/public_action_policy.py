"""Public-action policy — the bounded, fail-closed interaction contract (v3.3).

Three interaction modes:

- **Mode 1 — public passive:** navigation, screenshots, a11y, SEO, responsive, console/network,
  passive observation. Always allowed.
- **Mode 2 — public reversible interactive:** search / filter / sort / pagination / menu / modal /
  product variant / quantity / guest-cart add-update-remove (with verified cleanup) / date-guest
  selection / availability viewing / non-binding option / client-side validation WITHOUT
  submission. Allowed automatically, no per-site confirmation.
- **Mode 3 — optional isolated test account:** only after explicit per-domain operator approval
  (handled by `core/scout/test_account.py`).

`IRREVERSIBLE_MARKERS` are boundaries that are NEVER crossed automatically: submit / send message /
booking / reservation / order / payment / production signup / account creation. Any attempt to act
on such a control raises `PolicyStop`, which callers turn into a non-client-safe, "stopped before
boundary" result. This module decides nothing site-specific; it is a pure guard.
"""
from __future__ import annotations

MODE_PASSIVE = "public_passive"
MODE_REVERSIBLE = "public_reversible"
MODE_TEST_ACCOUNT = "test_account"

# Irreversible boundaries — always stop, never automated.
IRREVERSIBLE_MARKERS = (
    "reserve", "book now", "book a", "confirm booking", "confirm reservation", "confirm order",
    "confirm payment", "confirm", "hold", "checkout", "check out", "place order", "complete order",
    "complete purchase", "buy now", "buy", "pay ", "payment", "proceed to payment",
    "submit", "send message", "send request", "send enquiry", "send inquiry", "contact us now",
    "sign up", "signup", "create account", "register", "subscribe", "apply now", "start free trial",
    "add payment", "make reservation", "order now",
)

# Reversible interactive actions permitted automatically in Mode 2.
REVERSIBLE_MARKERS = (
    "search", "filter", "sort", "next", "previous", "prev", "page", "menu", "open", "close",
    "expand", "collapse", "add to cart", "add to bag", "add to basket", "remove", "update quantity",
    "quantity", "select date", "choose date", "check availability", "availability", "view",
    "details", "guests", "guest", "adults", "children", "variant", "size", "colour", "color",
)


class PolicyStop(Exception):
    """Raised when a flow reaches an irreversible boundary (or an unsafe/ambiguous action)."""

    def __init__(self, action: str, boundary: str = "irreversible_boundary") -> None:
        super().__init__(f"stopped before irreversible boundary: {action!r} ({boundary})")
        self.action = action
        self.boundary = boundary


def _norm(label: str) -> str:
    return (label or "").strip().lower()


def is_irreversible(label: str) -> bool:
    lab = _norm(label)
    return any(m in lab for m in IRREVERSIBLE_MARKERS)


def is_reversible(label: str) -> bool:
    """A clearly reversible interactive action AND not irreversible (irreversible always wins)."""
    lab = _norm(label)
    if is_irreversible(lab):
        return False
    return any(m in lab for m in REVERSIBLE_MARKERS)


def check_action(label: str, *, allowed_mode: str = MODE_REVERSIBLE) -> None:
    """Guard an interactive action before it happens. Raises `PolicyStop` if the action crosses
    an irreversible boundary, or if Mode-2 is requested but the action is not clearly reversible
    (fail-closed on ambiguity)."""
    lab = _norm(label)
    if is_irreversible(lab):
        raise PolicyStop(lab)
    if allowed_mode == MODE_PASSIVE:
        raise PolicyStop(lab, boundary="interaction_not_allowed_in_passive_mode")
    if allowed_mode == MODE_REVERSIBLE and not is_reversible(lab):
        # Unknown/ambiguous interactive action under Mode 2 => stop rather than guess.
        raise PolicyStop(lab, boundary="ambiguous_action_fail_closed")
