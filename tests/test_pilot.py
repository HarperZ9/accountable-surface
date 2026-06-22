"""Tests for the pilots + the autopilot loop — a mind driving the body, kept honest by the surface.

The autopilot loop is proven with a deterministic ScriptedPilot (no network): the mind proposes,
the body gates+acts+verifies+witnesses on REAL files, and the loop is bounded. ClaudePilot's
request-build and response-parse are proven with an injected transport — the real Anthropic call
is the only un-mocked seam. Offline, stdlib only.
"""
from __future__ import annotations

from pathlib import Path

from accountable_surface.world.session import WorldSession
from accountable_surface.world.server import _sandbox_grant
from accountable_surface.world.pilot import (
    Proposal, ScriptedPilot, ClaudePilot, OllamaPilot, SightfulPilot, autopilot, _extract_json,
)


def test_scripted_pilot_replays_then_signals_done():
    p = ScriptedPilot([Proposal(target="a.txt", content="x")])
    first = p.propose({}, "goal")
    assert first.target == "a.txt" and first.done is False
    assert p.propose({}, "goal").done is True


def test_autopilot_drives_the_body_through_real_witnessed_steps(tmp_path):
    ws = WorldSession(tmp_path / "w", _sandbox_grant(["fs.write"]))
    pilot = ScriptedPilot([
        Proposal(target="one.txt", content="first", justification="step 1", reasoning="start here"),
        Proposal(target="two.txt", content="second", justification="step 2", reasoning="then this"),
    ])
    steps = autopilot(ws, pilot, goal="write two notes", max_steps=6)
    assert len(steps) == 2  # stops when the pilot signals done after its two proposals
    assert all(s["acted"] and s["verified"] for s in steps)
    assert all(s["certificate"]["verdict"] == "verified" for s in steps)
    assert steps[0]["reasoning"] == "start here"  # the mind's voice rides the witnessed step
    assert (Path(tmp_path) / "w" / "two.txt").read_text() == "second"  # real files, really written


def test_autopilot_is_bounded_by_max_steps(tmp_path):
    ws = WorldSession(tmp_path / "w", _sandbox_grant(["fs.write"]))
    pilot = ScriptedPilot([Proposal(target=f"f{i}.txt", content="x") for i in range(10)])
    steps = autopilot(ws, pilot, goal="many", max_steps=3)
    assert len(steps) == 3


def test_autopilot_witnesses_a_refused_overreach(tmp_path):
    # the mind proposes an escape; the surface refuses it and witnesses the 'no' — the loop survives
    ws = WorldSession(tmp_path / "w", _sandbox_grant(["fs.write"]))
    pilot = ScriptedPilot([Proposal(target="../escape.txt", content="nope", reasoning="try to escape")])
    steps = autopilot(ws, pilot, goal="overreach", max_steps=2)
    assert len(steps) == 1
    assert steps[0]["acted"] is False
    assert steps[0]["certificate"]["verdict"] == "refuted"


def test_claude_pilot_request_body_carries_witnessed_state():
    cp = ClaudePilot("sk-test", model="claude-sonnet-4-6")
    state = {"root": "/w", "files": [{"name": "a.txt", "size": 3}], "focus": {"name": "a.txt", "content": "abc"},
             "journal": [], "grant": {"allowed_actions": ["fs.write"]}}
    body = cp.request_body(state, "make it better")
    assert body["model"] == "claude-sonnet-4-6"
    assert body["system"] and body["messages"][0]["role"] == "user"
    msg = body["messages"][0]["content"]
    assert "GOAL: make it better" in msg and "a.txt" in msg  # the mind sees the witnessed state


def test_claude_pilot_parses_a_proposal_from_a_canned_response():
    canned = {"content": [{"type": "text", "text":
              'My move:\n{"reasoning":"need a readme","kind":"fs.write","target":"README.md",'
              '"content":"# Hi","justification":"document it"} — done.'}]}
    cp = ClaudePilot("sk-test", post=lambda body: canned)
    prop = cp.propose({"files": []}, "make a readme")
    assert prop.done is False
    assert prop.target == "README.md" and prop.content == "# Hi"
    assert prop.reasoning == "need a readme"


def test_claude_pilot_fails_closed_on_done_garbage_and_errors():
    done = {"content": [{"type": "text", "text": '{"done": true, "reasoning": "goal met"}'}]}
    assert ClaudePilot("k", post=lambda b: done).propose({}, "g").done is True
    garbage = {"content": [{"type": "text", "text": "I cannot help with that."}]}
    assert ClaudePilot("k", post=lambda b: garbage).propose({}, "g").done is True  # no JSON -> done

    def boom(_):
        raise RuntimeError("network down")
    assert ClaudePilot("k", post=boom).propose({}, "g").done is True  # never crashes the loop


def test_extract_json_pulls_a_balanced_object_from_prose():
    obj = _extract_json('blah {"a": {"b": 1}, "c": "}"} trailing')
    assert obj == {"a": {"b": 1}, "c": "}"}
    assert _extract_json("no json here") is None


def test_sightful_pilot_reacts_to_what_it_sees():
    sight = {"name": "diagram.png", "kind": "image", "width": 40, "height": 40,
             "ascii": ["   @@@   ", "  @@@@@  ", "   @@@   "], "phash": "00ff00ff00ff00ff",
             "digest": "sha256:abc"}
    p = SightfulPilot()
    prop = p.propose({"sights": [sight]}, "observe the world")
    assert prop.done is False
    assert prop.kind == "fs.write" and prop.target.startswith("observation-diagram")
    assert "diagram.png" in prop.content
    assert "see" in prop.reasoning.lower()          # the mind's voice references what it sees
    assert p.propose({"sights": [sight]}, "x").done is True  # doesn't re-observe the same image


def test_sightful_pilot_done_when_nothing_to_see():
    assert SightfulPilot().propose({"sights": []}, "g").done is True


def test_ollama_pilot_builds_request_and_parses_response():
    op = OllamaPilot("qwen2.5:0.5b", host="http://localhost:11434")
    body = op.request_body({"files": [], "sights": []}, "do it")
    assert body["model"] == "qwen2.5:0.5b" and body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert "GOAL: do it" in body["messages"][1]["content"]
    canned = {"message": {"content":
              '{"reasoning":"a readme","kind":"fs.write","target":"R.md","content":"# Hi","justification":"doc"}'}}
    prop = OllamaPilot("m", post=lambda b: canned).propose({}, "g")
    assert prop.target == "R.md" and prop.reasoning == "a readme"


def test_ollama_pilot_fails_closed_on_transport_error():
    def boom(_):
        raise RuntimeError("ollama down")
    assert OllamaPilot("m", post=boom).propose({}, "g").done is True
