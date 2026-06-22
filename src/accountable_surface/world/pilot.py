"""Pilots — the mind that drives the body, kept honest by the surface around it.

A Pilot perceives the WITNESSED world state (real files, real digests, the journal — never its
own recollection) and proposes ONE next action; the body still gates, acts, verifies its own
work, and witnesses the result, which is fed back as ground truth for the next step. This is
scaffolding for exactly where models are weak: it externalizes perception (the model can't
hallucinate the state — it's handed the real one), verification (a botched action is caught and
rolled back, not assumed done), and memory (the journal), and bounds reach (the gate). The mind
proposes; the surface keeps it true.

Model-agnostic: ScriptedPilot (deterministic, offline — tests + demos) or ClaudePilot (a real
model via the Anthropic Messages API over stdlib urllib — no SDK, zero third-party deps).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Proposal:
    """One proposed move + the mind's voice. `done` ends the run (goal met / nothing to do)."""
    kind: str = "fs.write"
    target: str = ""
    content: str = ""
    justification: str = ""
    reasoning: str = ""
    done: bool = False

    @classmethod
    def finished(cls, reasoning: str = "") -> "Proposal":
        return cls(done=True, reasoning=reasoning)


class ScriptedPilot:
    """Replays a fixed list of proposals, then signals done. Deterministic — tests + offline demos."""

    def __init__(self, proposals):
        self._q = list(proposals)

    def propose(self, world_state, goal) -> Proposal:
        return self._q.pop(0) if self._q else Proposal.finished("nothing left to do")


_SYSTEM = (
    "You operate a body in a shared, accountable world. You are shown the WITNESSED state (real "
    "files, real content, real digests, the journal) — trust it over any memory of yours. Propose "
    "exactly ONE next action toward the goal as a single JSON object and nothing else: "
    '{"reasoning": "...", "kind": "fs.write", "target": "<file under the world root>", '
    '"content": "<full new file content>", "justification": "<crisp premise>"}. '
    'When the goal is met, return {"done": true, "reasoning": "..."}. Every action is gated by an '
    "operator grant and verified by the body; propose only what is within the sandbox. If a write "
    "was refused or failed, read the witnessed result and adjust rather than repeating it."
)


def _world_brief(world_state, goal) -> str:
    """Render the witnessed world state into the prompt — the ground truth the mind reasons over."""
    files = ", ".join(f'{f["name"]} ({f["size"]}B)' for f in world_state.get("files", [])) or "(empty)"
    focus = world_state.get("focus") or {}
    journal = world_state.get("journal", [])
    recent = "; ".join(f'{e.get("kind")}: {e.get("summary", "")}' for e in journal[-4:]) or "(none yet)"
    grant = world_state.get("grant", {}).get("allowed_actions", [])
    sight = ""
    for s in world_state.get("sights", []):
        sight += (f"\nWHAT YOU SEE — {s.get('name')} ({s.get('width')}x{s.get('height')}, "
                  f"phash {s.get('phash')}), the witnessed glyph grid:\n" + "\n".join(s.get("ascii", [])) + "\n")
    return (f"GOAL: {goal}\nWORLD ROOT: {world_state.get('root', '')}\nFILES: {files}\n"
            f"FOCUS: {focus.get('name', '(none)')}\n--- focus content ---\n{focus.get('content', '')}\n---{sight}\n"
            f"RECENT WITNESSED JOURNAL: {recent}\nGRANTED ACTIONS: {grant}\n"
            "Propose the next action as one JSON object.")


def _extract_json(text):
    """Pull the first balanced {...} object out of the model's text (string-aware; it may wrap it)."""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _to_proposal(obj) -> Proposal:
    if not isinstance(obj, dict):
        return Proposal.finished("could not parse a proposal from the model")
    if obj.get("done"):
        return Proposal.finished(str(obj.get("reasoning", "")))
    return Proposal(kind=str(obj.get("kind", "fs.write")), target=str(obj.get("target", "")),
                    content=str(obj.get("content", "")),
                    justification=str(obj.get("justification", "")),
                    reasoning=str(obj.get("reasoning", "")))


class ClaudePilot:
    """A real model driving the body via the Anthropic Messages API (stdlib urllib; no SDK).

    The API key is operator-supplied at runtime (env), never stored. `post` is injectable so the
    request-build and response-parse are testable without a network call; failures fail closed to a
    witnessed `done` rather than crashing the loop.
    """

    def __init__(self, api_key, model="claude-sonnet-4-6", *, post=None, max_tokens=1024):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._post = post or self._http_post

    def request_body(self, world_state, goal) -> dict:
        return {"model": self.model, "max_tokens": self.max_tokens, "system": _SYSTEM,
                "messages": [{"role": "user", "content": _world_brief(world_state, goal)}]}

    def propose(self, world_state, goal) -> Proposal:
        try:
            raw = self._post(self.request_body(world_state, goal))
        except Exception as exc:  # network / auth / decode — never crash the loop
            return Proposal.finished(f"pilot unavailable: {exc!r}")
        text = "".join(b.get("text", "") for b in (raw or {}).get("content", []) if isinstance(b, dict))
        return _to_proposal(_extract_json(text))

    def _http_post(self, body) -> dict:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())


def autopilot(world, pilot, *, goal, max_steps=6, should_continue=None):
    """The mind drives the body: perceive witnessed state -> propose -> gate+act+verify+witness ->
    feed the real outcome back -> repeat. Bounded by max_steps, the pilot's own `done`, and an
    optional `should_continue()` predicate (the operator's stop). `world` is anything with
    .snapshot() -> dict and .act(**kw) -> dict | WorldStep.
    """
    steps = []
    for _ in range(max(0, max_steps)):
        if should_continue is not None and not should_continue():
            break
        prop = pilot.propose(world.snapshot(), goal)
        if prop is None or prop.done:
            break
        step = world.act(kind=prop.kind, target=prop.target, content=prop.content,
                         justification=prop.justification, reasoning=prop.reasoning)
        steps.append(step if isinstance(step, dict) else step.to_dict())
    return steps
