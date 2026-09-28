"""Instructions inside observed content are data (R8).

Authority never comes from a page: grants, tiers, approvals, and pauses load out
of band, and no tool parameter carries them. This detector is the second line. It
flags page sentences that address an agent ("ignore previous instructions", "note
to AI agents", "the operator approves") and keeps them with the evidence. A step
that echoes a flagged span, by taking its URL, control, or value from it, or by
navigating to an origin the page named only inside flagged content, is held for a
person, and the approval rendering shows the person the span.

Limit: lexical. A paraphrased instruction passes it; then the structural rules
(no authority from content, tiers, bounds, confirmation for irreversible steps)
carry the load. A clean result proves nothing about intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from accountable_surface.page_evidence import origin_of

VERSION = "1"
MAX_SPAN = 300
PHRASES = (
    "ignore previous instructions", "ignore all previous instructions", "ignore the above",
    "disregard previous", "disregard all previous", "forget your instructions", "new instructions",
    "you are now", "system prompt", "as an ai", "assistant:", "ai agent", "ai agents",
    "ai assistant", "note to ai", "attention ai", "dear ai", "call the tool", "use the tool",
    "run this command", "execute this command", "paste your", "enter your password",
    "enter your api key", "api key", "grant access", "the operator approves",
    "operator has approved", "the user has approved", "you have permission", "authorize this",
    "approve this",
)
_URL = re.compile(r"https?://[^\s<>\"']+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Flag:
    phrase: str
    span: str
    urls: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"phrase": self.phrase, "span": self.span, "urls": list(self.urls)}


def _has(phrase: str, text: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(phrase) + r"(?![\w])", text) is not None


def flag_spans(text: str) -> tuple[Flag, ...]:
    """Every sentence that addresses an agent, once per phrase it carries."""
    flags = []
    for sentence in _SENTENCE.split(text or ""):
        low = sentence.replace("’", "'").lower()
        for phrase in PHRASES:
            if _has(phrase, low):
                urls = tuple(u.rstrip(".,;:)") for u in _URL.findall(sentence))
                flags.append(Flag(phrase, sentence.strip()[:MAX_SPAN], urls))
    return tuple(flags)


def _field_echoes(fields: dict, flag: Flag, page_origin: str) -> list[str]:
    span = flag.span.lower()
    reasons = []
    for key in ("url", "origin", "selector", "value"):
        value = str(fields.get(key) or "").strip().lower()
        if len(value) < 3 or (key == "origin" and value == page_origin.lower()):
            continue
        if value in span or (len(span) >= 12 and span in value):
            reasons.append(f"step {key} echoes a span flagged {flag.phrase!r}")
    return reasons


def echo(fields: dict, flags, *, page_origin: str) -> list[str]:
    """Reasons a step echoes flagged content. The reasons name the step field and
    the phrase, never the span, so a receipt does not replay the instruction."""
    reasons = []
    for flag in flags:
        reasons += _field_echoes(fields, flag, page_origin)
    target = origin_of(str(fields.get("url") or ""))
    if target and target != page_origin.lower():
        if any(origin_of(u) == target for flag in flags for u in flag.urls):
            reasons.append("step navigates to an origin named only inside flagged content")
    return sorted(set(reasons))


def lexicon() -> dict:
    return {"version": VERSION, "phrases": list(PHRASES), "max_span": MAX_SPAN}
