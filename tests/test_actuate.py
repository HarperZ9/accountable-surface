"""Tests for AccountableSurface.actuate — the full accountable-actuation loop.

Offline. Proves the loop perceive -> plan -> gate -> ACT -> re-perceive -> verify:
no grant -> no action; an authorized action is acted, self-verified, and journaled;
a faulty actuation is caught by the surface's own re-perception and rolled back.
"""

from __future__ import annotations

from pathlib import Path

from accountable_surface.effector import FilesystemEffector
from accountable_surface.surface import AccountableSurface


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-act-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "act-agent"},
        "intent": "actuate test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_no_grant_does_not_act(tmp_path):
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    out = s.actuate(eff, target=target, content=b"hello", authorization={})
    assert out.acted is False
    assert out.decision == "deny"
    assert not Path(target).exists()  # default-deny -> no effect on the world


def test_authorized_actuation_acts_verifies_journals(tmp_path):
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    out = s.actuate(eff, target=target, content=b"hello", authorization=_grant(["fs.write"]))
    assert out.acted is True
    assert out.decision == "allow"
    assert out.verified is True
    assert Path(target).read_bytes() == b"hello"
    assert any(e.kind == "actuation" for e in s.journal)


def test_unauthorized_action_kind_denied(tmp_path):
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    out = s.actuate(eff, target=target, content=b"hello", authorization=_grant(["summarize"]))
    assert out.acted is False
    assert out.decision == "deny"
    assert not Path(target).exists()


def test_faulty_actuation_is_caught_and_rolled_back(tmp_path):
    # A buggy effector that writes the WRONG content despite an authorized plan.
    # The surface's independent re-perception must catch it (verified=False) and
    # roll back, since the write is reversible. This is "checking its own work."
    class FaultyEffector(FilesystemEffector):
        def _write(self, path, content):
            path.write_bytes(b"CORRUPTED")

    s = AccountableSurface()
    eff = FaultyEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    Path(target).write_bytes(b"original")
    out = s.actuate(eff, target=target, content=b"hello", authorization=_grant(["fs.write"]))
    assert out.acted is True
    assert out.verified is False  # the surface caught its own bad work
    assert out.rolled_back is True
    assert Path(target).read_bytes() == b"original"  # restored
