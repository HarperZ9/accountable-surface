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

from .sight import describe_sight


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


class SightfulPilot:
    """Reacts to what it SEES — offline, deterministic. Reads the witnessed glyph grid, says what it
    can honestly tell from it, and records that observation. Proves the loop RESPONDS to sight (not
    canned text) without any model; a real model (ClaudePilot/OllamaPilot) does this far richer."""

    def __init__(self):
        self._seen = set()

    def propose(self, world_state, goal) -> Proposal:
        for s in world_state.get("sights", []):
            if s.get("digest") in self._seen:
                continue
            self._seen.add(s.get("digest"))
            name = s.get("name", "image")
            stem = name.rsplit(".", 1)[0]
            desc = describe_sight(s)
            return Proposal(
                target=f"observation-{stem}.md",
                content=f"# What I see in {name}\n\n{desc}\n\nWitnessed digest: {s.get('digest')}\n",
                justification=f"record what I perceive in {name}",
                reasoning=f"Looking at {name}, I see {desc}. I'll write that observation down.")
        return Proposal.finished("I've recorded what I can see in the world.")


_SYSTEM = (
    "You operate a body in a shared, accountable world. You are shown the WITNESSED state (real "
    "files, real content, real digests, the journal) — trust it over any memory of yours. Propose "
    "exactly ONE next action toward the goal as a single JSON object and nothing else, for example: "
    '{"reasoning": "the world has an image; I will describe what I see", "kind": "fs.write", '
    '"target": "notes.md", "content": "the full file content here", "justification": "record what I see"}. '
    "Use a real, NEW filename ending in .md for your notes; never overwrite an existing file or an "
    "image. The only action is fs.write — to extend a note, write its FULL new content (there is no "
    'append). When the goal is met, return {"done": true, "reasoning": "..."}. Every action is gated '
    "by an operator grant and verified by the body; propose only what is within the sandbox. If a "
    "write was refused or failed, read the witnessed result and adjust rather than repeating it. "
    "If the world shows you WHAT YOU SEE (a glyph grid of an image), say plainly what you observe in "
    "it as part of your reasoning before you act. Make REAL progress each step: build on the files "
    "you have already written (shown in FILES and their content) toward the goal — first record what "
    "you observe, then in later steps extend or refine your own notes; never rewrite a file you just "
    "wrote unchanged. Return done only when the goal is genuinely met."
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
    note_block = ""
    for name, content in (world_state.get("notes") or {}).items():
        note_block += f"\n--- your note {name} ---\n{content}\n"
    reel = world_state.get("reel")
    reel_block = ""
    if reel:
        reel_block = (f"\nMOVING MATERIAL: a {reel['count']}-frame reel is playing ({reel['fps']} fps). "
                      "One sampled frame (witnessed glyph grid):\n"
                      + "\n".join((reel.get("sample") or {}).get("ascii", [])) + "\n")
    return (f"GOAL: {goal}\nWORLD ROOT: {world_state.get('root', '')}\nFILES: {files}\n"
            f"FOCUS: {focus.get('name', '(none)')}{sight}{reel_block}\n"
            f"YOUR NOTES SO FAR:{note_block or ' (none yet)'}\n"
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


def _to_proposal(obj):
    """A Proposal from a parsed object, or None if it didn't parse (so the caller can retry a flaky
    model). A legit {"done": true} is a Proposal, not a parse failure."""
    if not isinstance(obj, dict):
        return None
    if obj.get("done"):
        return Proposal.finished(str(obj.get("reasoning", "")))
    return Proposal(kind=str(obj.get("kind", "fs.write")), target=str(obj.get("target", "")),
                    content=str(obj.get("content", "")),
                    justification=str(obj.get("justification", "")),
                    reasoning=str(obj.get("reasoning", "")))


def _drive(post, body, extract_text, attempts):
    """Call a model, retrying on UNPARSEABLE output (small/local models are flaky) — the scaffolding
    compensating for where models are weak. A transport error or a clean run of unusable output
    fails closed to a witnessed `done`, never a crash."""
    for _ in range(max(1, attempts)):
        try:
            raw = post(body)
        except Exception as exc:
            return Proposal.finished(f"pilot unavailable: {exc!r}")
        prop = _to_proposal(_extract_json(extract_text(raw)))
        if prop is not None:
            return prop
    return Proposal.finished("the model did not return a usable action after retries")


class ClaudePilot:
    """A real model driving the body via the Anthropic Messages API (stdlib urllib; no SDK).

    The API key is operator-supplied at runtime (env), never stored. `post` is injectable so the
    request-build and response-parse are testable without a network call; failures fail closed to a
    witnessed `done` rather than crashing the loop.
    """

    def __init__(self, api_key, model="claude-sonnet-4-6", *, post=None, max_tokens=1024, attempts=3):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.attempts = attempts
        self._post = post or self._http_post

    def request_body(self, world_state, goal) -> dict:
        return {"model": self.model, "max_tokens": self.max_tokens, "system": _SYSTEM,
                "messages": [{"role": "user", "content": _world_brief(world_state, goal)}]}

    @staticmethod
    def _text(raw) -> str:
        return "".join(b.get("text", "") for b in (raw or {}).get("content", []) if isinstance(b, dict))

    def propose(self, world_state, goal) -> Proposal:
        return _drive(self._post, self.request_body(world_state, goal), self._text, self.attempts)

    def _http_post(self, body) -> dict:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())


class OllamaPilot:
    """A real LOCAL model driving the body via Ollama's HTTP API (stdlib urllib; no SDK, no key, no
    cloud). Reasons over the WITNESSED state — including the glyph grid, the same shared sight the
    spectator sees. Even a small local model is kept honest by the gate + verify + witness; this is
    the thesis made cheap to run: scaffolding that makes a weak model safe and useful."""

    def __init__(self, model="llama3.2", *, host="http://localhost:11434", post=None, attempts=3):
        self.model = model
        self.host = host.rstrip("/")
        self.attempts = attempts
        self._post = post or self._http_post

    def request_body(self, world_state, goal) -> dict:
        return {"model": self.model, "stream": False,
                "messages": [{"role": "system", "content": _SYSTEM},
                             {"role": "user", "content": _world_brief(world_state, goal)}],
                "options": {"temperature": 0.4}}

    @staticmethod
    def _text(raw) -> str:
        return ((raw or {}).get("message") or {}).get("content", "")

    def propose(self, world_state, goal) -> Proposal:
        return _drive(self._post, self.request_body(world_state, goal), self._text, self.attempts)

    def _http_post(self, body) -> dict:
        req = urllib.request.Request(self.host + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
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
        try:
            step = world.act(kind=prop.kind, target=prop.target, content=prop.content,
                             justification=prop.justification, reasoning=prop.reasoning)
        except Exception:
            break  # a proposal the surface can't even attempt ends the run safely
        steps.append(step if isinstance(step, dict) else step.to_dict())
    return steps
