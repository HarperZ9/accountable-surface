"""Irreversible classification (R7) and money movement (R5).

A step is irreversible when any of these hold, and each can only raise the class:

1. the effector plans it irreversible (`web.submit`, `browser.evaluate`,
   `uia.invoke`, `os.run`, a non-reversible API operation);
2. the pressed control's accessible name carries a verb from the lexicon
   (send, submit, publish, post, buy, pay, delete, accept, agree, ...);
3. the control is structurally a form submit: a button in a form that is not
   `type=button` or `type=reset`, or an `input` of type submit or image. This rule
   does not read the label, so it holds in any language;
4. the caller declared it irreversible.

Only a press (click, submit, invoke) is classed by the control. Filling a field
labelled "Post title" types text and posts nothing.

Some verbs are also everyday nouns (order, post, share, archive, release). On a
link those count only inside a longer phrase ("place order"), and on a button
they do not count when a navigation noun follows ("Order history"). The strong
verbs count anywhere in the label.

Money movement is separate and stricter: transfers, withdrawals, trades, and
swaps are never confirmable, so the policy returns `stop` and the person acts.
Buying goods is a purchase and stays confirmable.

Limit: the lexicon is English. Rule 3 catches most submits in other languages;
a press on a non-submit control labelled in another language escapes rule 2.
"""

from __future__ import annotations

import re

VERSION = "1"
PRESS_KINDS = ("click", "submit", "invoke")
EFFECTOR_IRREVERSIBLE = frozenset({"web.submit", "browser.evaluate", "uia.invoke", "os.run"})
STRONG = frozenset({
    "send", "submit", "publish", "buy", "purchase", "pay", "checkout", "donate", "delete",
    "remove", "erase", "discard", "accept", "agree", "consent", "confirm", "transfer",
    "withdraw", "deactivate", "unsubscribe", "merge", "deploy", "subscribe", "register",
    "authorize", "approve", "revoke", "wipe",
})
WEAK = frozenset({
    "post", "share", "reply", "order", "archive", "release", "book", "reserve", "apply",
    "upgrade", "invite", "allow", "grant", "vote",
})
PHRASES = (
    "place order", "submit order", "check out", "close account", "delete account",
    "sign up", "create account", "sign document", "sign agreement", "sign contract",
    "empty trash", "start trial", "factory reset",
)
NAV_NOUNS = frozenset({
    "history", "status", "details", "notes", "page", "pages", "list", "feed", "settings",
    "archive", "archives", "summary", "tracking", "center", "log", "overview", "feedback",
})
FILLERS = frozenset({"i", "yes", "ok", "okay", "please"})
FUNDS_WORDS = frozenset({"transfer", "wire", "withdraw", "withdrawal", "trade", "swap"})
FUNDS_PHRASES = (
    "send money", "send funds", "buy shares", "sell shares", "buy stock", "sell stock",
    "buy crypto", "sell crypto", "convert currency", "cash out",
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def _lexicon_hits(control) -> list[str]:
    tokens = _tokens(control.name)
    joined = " ".join(tokens)
    hits = [f"lexicon:{p}" for p in PHRASES if f" {p} " in f" {joined} "]
    while tokens and tokens[0] in FILLERS:
        tokens = tokens[1:]
    hits += [f"lexicon:{t}" for t in sorted(set(tokens) & STRONG)]
    if control.role != "link" and tokens and tokens[0] in WEAK:
        if not (len(tokens) > 1 and tokens[1] in NAV_NOUNS):
            hits.append(f"lexicon:{tokens[0]}")
    return hits


def _structural_submit(control) -> bool:
    if control.role != "button" or not control.in_form:
        return False
    return control.input_type in ("submit", "image")


def classify(action_kind: str, control, *, declared: bool, plan_reversible: bool) -> list[str]:
    """Every reason the step is irreversible. Empty means reversible, as far as
    these four rules can tell."""
    reasons = []
    if action_kind in EFFECTOR_IRREVERSIBLE or not plan_reversible:
        reasons.append("effector:irreversible")
    if control is not None and action_kind.rsplit(".", 1)[-1] in PRESS_KINDS:
        reasons += _lexicon_hits(control)
        if _structural_submit(control):
            reasons.append("structural:form-submit")
    if declared:
        reasons.append("declared")
    return reasons


def funds_move(action_kind: str, control, args: dict) -> list[str]:
    """Reasons the step moves money. Read from the pressed control's name and
    from an API operation's own name."""
    texts = []
    if control is not None and action_kind.rsplit(".", 1)[-1] in PRESS_KINDS:
        texts.append(control.name)
    if action_kind.startswith("api."):
        texts.append(action_kind[4:].replace("_", " "))
    hits = []
    for text in texts:
        tokens = _tokens(text)
        joined = f" {' '.join(tokens)} "
        hits += [f"funds:{t}" for t in sorted(set(tokens) & FUNDS_WORDS)]
        hits += [f"funds:{p}" for p in FUNDS_PHRASES if f" {p} " in joined]
    return hits


def lexicon() -> dict:
    return {"version": VERSION, "strong": sorted(STRONG), "weak": sorted(WEAK), "phrases": list(PHRASES),
            "nav_nouns": sorted(NAV_NOUNS), "effector": sorted(EFFECTOR_IRREVERSIBLE),
            "funds_words": sorted(FUNDS_WORDS), "funds_phrases": list(FUNDS_PHRASES)}
