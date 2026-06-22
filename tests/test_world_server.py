"""Tests for the Shared World server core — the live World (pub/sub over the body).

The HTTP/SSE plumbing is verified end-to-end in the browser; here we prove the in-process
World: a proposed action runs the real loop AND is pushed to every live subscriber (so watchers
see the body act in real time), and the snapshot reflects the world. Offline, stdlib only.
"""
from __future__ import annotations

from coherence_membrane.pngencode import encode_png

from accountable_surface.world.server import World, _sandbox_grant
from accountable_surface.world.pilot import ScriptedPilot, SightfulPilot, Proposal


def test_act_runs_the_loop_and_notifies_subscribers(tmp_path):
    w = World(tmp_path / "w", _sandbox_grant())
    q = w.subscribe()
    step = w.act(kind="fs.write", target="x.txt", content="hi", justification="greet")
    assert step["acted"] is True and step["verified"] is True
    assert step["certificate"]["verdict"] == "verified"
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    kinds = [e[0] for e in events]
    assert "step" in kinds and "world" in kinds  # watchers get the step + the new world state


def test_denied_action_still_witnessed_to_subscribers(tmp_path):
    w = World(tmp_path / "w", _sandbox_grant(actions=["summarize"]))  # no fs.write -> deny
    q = w.subscribe()
    step = w.act(kind="fs.write", target="x.txt", content="hi")
    assert step["acted"] is False and step["certificate"]["verdict"] == "refuted"
    # the refusal is a witnessed event pushed to watchers, not a silent drop
    seen = []
    while not q.empty():
        seen.append(q.get_nowait()[0])
    assert "step" in seen


def test_snapshot_reflects_the_world(tmp_path):
    w = World(tmp_path / "w", _sandbox_grant())
    w.act(kind="fs.write", target="y.txt", content="yo")
    snap = w.snapshot()
    assert "y.txt" in [f["name"] for f in snap["files"]]
    assert snap["grant"]["allowed_actions"] == ["fs.write"]


def test_chat_grounds_in_the_sight_and_remembers(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    (root / "pic.png").write_bytes(encode_png(8, 8, bytes([200] * 8 * 8 * 3), channels=3))
    w = World(root, _sandbox_grant(), SightfulPilot(), "sightful")  # no converse -> offline reply
    r1 = w.chat("what do you see?")
    assert "make out" in r1["reply"].lower()    # an honest reading of the shared sight
    assert len(r1["history"]) == 2              # user + assistant, remembered
    r2 = w.chat("anything else?")
    assert len(r2["history"]) == 4              # the conversation accumulates (small memory)
    assert w.chat_history[-1]["role"] == "assistant"


def test_run_autopilot_drives_the_body_and_streams_to_watchers(tmp_path):
    pilot = ScriptedPilot([Proposal(target="a.txt", content="x", reasoning="first move"),
                           Proposal(target="b.txt", content="y", reasoning="second move")])
    w = World(tmp_path / "w", _sandbox_grant(), pilot, "scripted")
    q = w.subscribe()
    w.run_autopilot("write two notes", max_steps=5)
    assert (tmp_path / "w" / "b.txt").read_text() == "y"   # the mind really drove the hands
    assert w.running is False
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait()[0])
    assert kinds.count("step") == 2 and "autopilot" in kinds  # both steps + the finished signal streamed
