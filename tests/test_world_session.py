"""Tests for WorldSession — the body alive in a shared world.

Proves one PROPOSED action becomes one witnessed turn through the REAL perceive->gate->act->
verify loop on real files under a sandbox root: a granted write acts, self-verifies, and carries
a verified certificate; an out-of-grant action is default-denied and refuted with no effect; the
snapshot reflects the world root + the witnessed journal. Offline, stdlib only.
"""
from __future__ import annotations

from pathlib import Path

from accountable_surface.world.session import WorldSession, WorldStep


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-world-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "world-agent"},
        "intent": "operate in the shared world",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_granted_write_acts_verifies_and_witnesses(tmp_path):
    ws = WorldSession(tmp_path / "world", _grant(["fs.write"]))
    step = ws.act(kind="fs.write", target="note.txt", content="hello world",
                  justification="record the greeting")
    assert isinstance(step, WorldStep)
    assert step.acted is True and step.verified is True
    assert step.decision == "allow"
    assert step.verdict == "pass"
    assert step.certificate["verdict"] == "verified"
    assert step.certificate["oracle"] == "composed-v1"
    assert step.material == "hello world"
    # the body acted on a REAL file under the sandbox root
    assert (Path(tmp_path) / "world" / "note.txt").read_text() == "hello world"


def test_out_of_grant_action_is_denied_and_refuted(tmp_path):
    ws = WorldSession(tmp_path / "world", _grant(["summarize"]))  # wrong action -> default-deny
    step = ws.act(kind="fs.write", target="note.txt", content="hello")
    assert step.acted is False
    assert step.decision == "deny"
    assert step.certificate["verdict"] == "refuted"
    assert not (Path(tmp_path) / "world" / "note.txt").exists()  # no effect on the world


def test_snapshot_reflects_world_root_and_journal(tmp_path):
    ws = WorldSession(tmp_path / "world", _grant(["fs.write"]))
    ws.act(kind="fs.write", target="a.txt", content="alpha", justification="first")
    snap = ws.snapshot()
    assert snap["root"].replace("\\", "/").endswith("world")
    assert "a.txt" in [f["name"] for f in snap["files"]]
    assert snap["focus"]["name"] == "a.txt"
    assert snap["focus"]["content"] == "alpha"
    # the witnessed journal carries the actuation, append-only
    assert any(e["kind"] == "actuation" for e in snap["journal"])
    assert snap["grant"]["allowed_actions"] == ["fs.write"]


def test_step_serializes_to_a_wire_dict(tmp_path):
    ws = WorldSession(tmp_path / "world", _grant(["fs.write"]))
    step = ws.act(kind="fs.write", target="b.txt", content="beta", justification="second")
    d = step.to_dict()
    assert d["kind"] == "fs.write" and d["target"].endswith("b.txt")
    assert d["certificate"]["verdict"] == "verified"
    assert d["before_digest"] and d["after_digest"]  # provenance both sides of the act
