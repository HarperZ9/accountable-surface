"""Tests for the Shared World server core — the live World (pub/sub over the body).

The HTTP/SSE plumbing is verified end-to-end in the browser; here we prove the in-process
World: a proposed action runs the real loop AND is pushed to every live subscriber (so watchers
see the body act in real time), and the snapshot reflects the world. Offline, stdlib only.
"""
from __future__ import annotations

from accountable_surface.world.server import World, _sandbox_grant


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
