"""Challenge detector: a CAPTCHA or bot check is on screen, so the agent stops.

It reads markers from page evidence and never interacts with them. A hit means
the policy check returns `stop` and the target is paused until a person deals with
the page and clears the pause from their own terminal. Nothing in this package
solves, waits out, retries, or routes around a challenge.

Markers, in the order they are checked:

- frames: an iframe whose source names a challenge provider, or whose title says
  captcha or challenge;
- containers: class, id, or name tokens a challenge widget carries
  (`g-recaptcha`, `h-captcha`, `cf-turnstile`, `data-sitekey`, `challenge-form`);
- titles and text: the phrases a challenge page shows, matched on word
  boundaries so prose about robotics does not trip them. Two phrases that are
  common in ordinary prose ("just a moment", "attention required") count only
  in the title, where the interstitial pages put them;
- control names: a checkbox or button labelled with the same phrases;
- HTTP: a 403, 429, or 503 carrying `cf-mitigated: challenge`.

Limit: this is lexical and structural. A challenge vendor with unknown markers
and no telltale text passes it. The structural rules (tiers, confirmation for
irreversible steps) still hold in that case; a stop that should happen may not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VERSION = "1"
PROVIDER_SOURCES = (
    "google.com/recaptcha", "recaptcha.net", "hcaptcha.com", "challenges.cloudflare.com",
    "arkoselabs.com", "funcaptcha.com", "geetest.com",
)
MARKER_TOKENS = (
    "captcha", "g-recaptcha", "h-captcha", "cf-turnstile", "turnstile", "data-sitekey",
    "challenge-form", "cf-challenge", "arkose", "funcaptcha", "geetest",
)
FRAME_TITLE_TOKENS = ("captcha", "challenge", "turnstile")
TITLE_ONLY_PHRASES = ("just a moment", "attention required")
PHRASES = (
    "verify you are human", "verify you're human", "verify that you are human",
    "i'm not a robot", "i am not a robot", "are you a robot", "press and hold",
    "unusual traffic from your computer", "complete the security check",
    "checking your browser", "checking if the site connection is secure",
    "prove you are human", "prove you're human", "human verification",
    "select all images", "confirm you are human", "bot check",
)
CHALLENGE_STATUSES = (403, 429, 503)


@dataclass(frozen=True)
class ChallengeHit:
    where: str  # frame | container | title | text | control | http
    marker: str

    def to_dict(self) -> dict:
        return {"where": self.where, "marker": self.marker}


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").replace("‘", "'").lower().split())


def _phrase_hits(text: str, phrases) -> list[str]:
    norm = _norm(text)
    return [p for p in phrases if re.search(r"(?<![\w])" + re.escape(p) + r"(?![\w])", norm)]


def _frames(evidence) -> list[ChallengeHit]:
    hits = []
    for src, title in evidence.frames:
        low_src, low_title = src.lower(), title.lower()
        hits += [ChallengeHit("frame", p) for p in PROVIDER_SOURCES if p in low_src]
        hits += [ChallengeHit("frame", f"title:{t}") for t in FRAME_TITLE_TOKENS if t in low_title]
    return hits


def _containers(evidence) -> list[ChallengeHit]:
    found = sorted({tok for m in evidence.markers for tok in MARKER_TOKENS if tok in m})
    return [ChallengeHit("container", tok) for tok in found]


def _text(evidence) -> list[ChallengeHit]:
    hits = [ChallengeHit("title", p) for p in _phrase_hits(evidence.title, PHRASES + TITLE_ONLY_PHRASES)]
    hits += [ChallengeHit("text", p) for p in _phrase_hits(evidence.text, PHRASES)]
    for control in evidence.controls:
        hits += [ChallengeHit("control", p) for p in _phrase_hits(control.name, PHRASES)]
    return hits


def _http(evidence) -> list[ChallengeHit]:
    if evidence.http_status in CHALLENGE_STATUSES and evidence.header("cf-mitigated").lower() == "challenge":
        return [ChallengeHit("http", f"{evidence.http_status} cf-mitigated: challenge")]
    return []


def scan(evidence) -> tuple[ChallengeHit, ...]:
    """Every challenge marker in the evidence. Empty means none was recognised,
    which is not proof that no challenge is present."""
    if evidence is None:
        return ()
    return tuple(_frames(evidence) + _containers(evidence) + _text(evidence) + _http(evidence))


def lexicon() -> dict:
    """The exact marker set, hashed into the policy digest on every receipt."""
    return {"version": VERSION, "providers": PROVIDER_SOURCES, "markers": MARKER_TOKENS,
            "frame_titles": FRAME_TITLE_TOKENS, "title_only": TITLE_ONLY_PHRASES,
            "phrases": PHRASES, "statuses": CHALLENGE_STATUSES}
