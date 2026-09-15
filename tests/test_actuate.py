"""Tests for AccountableSurface.actuate -- the full accountable-actuation loop.

Offline. Proves the loop perceive -> plan -> gate -> ACT -> re-perceive -> verify:
no grant -> no action; an authorized action is acted, self-verified, and journaled;
a faulty actuation is caught by the surface's own re-perception and rolled back.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from coherence_membrane.observation import Observation

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


def test_wrong_filesystem_expected_digest_refuses_before_write(tmp_path):
    """Catches the bug where expected_digest silently vanished for fs writes."""
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = tmp_path / "f.txt"
    target.write_bytes(b"original")
    wrong = hashlib.sha256(b"not the original file").hexdigest()

    out = s.actuate(
        eff,
        target=str(target),
        content=b"replacement",
        authorization=_grant(["fs.write"]),
        expected_digest=wrong,
    )

    assert out.acted is False
    assert out.decision == "deny"
    assert target.read_bytes() == b"original"
    decision = [e for e in s.journal if e.kind == "decision"][-1]
    assert decision.detail["checks"]["state"] == "fail"


def test_matching_filesystem_expected_digest_allows_write(tmp_path):
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = tmp_path / "f.txt"
    target.write_bytes(b"original")
    expected = hashlib.sha256(b"original").hexdigest()

    out = s.actuate(
        eff,
        target=str(target),
        content=b"replacement",
        authorization=_grant(["fs.write"]),
        expected_digest=expected,
    )

    assert out.acted is True
    assert out.verified is True
    assert target.read_bytes() == b"replacement"
    decision = [e for e in s.journal if e.kind == "decision"][-1]
    assert decision.detail["checks"]["state"] == "pass"


def test_absent_filesystem_target_cannot_satisfy_expected_digest(tmp_path):
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = tmp_path / "f.txt"
    expected = hashlib.sha256(b"").hexdigest()

    out = s.actuate(
        eff,
        target=str(target),
        content=b"replacement",
        authorization=_grant(["fs.write"]),
        expected_digest=expected,
    )

    assert out.acted is False
    assert out.decision == "deny"
    assert out.verdict == "precondition-unverifiable"
    assert not target.exists()


class _OpaqueFilesystemEffector(FilesystemEffector):
    def perceive(self, target: str) -> Observation:
        observed = super().perceive(target)
        return Observation(
            organ="opaque-test-effector",
            subject=observed.subject,
            summary=observed.summary,
            status=observed.status,
            provenance=observed.provenance,
            data={"exists": observed.data["exists"], "size": observed.data["size"]},
        )


def test_unknown_observation_identity_refuses_expected_digest_before_write(tmp_path):
    s = AccountableSurface()
    eff = _OpaqueFilesystemEffector(tmp_path)
    target = tmp_path / "f.txt"
    target.write_bytes(b"original")
    expected = hashlib.sha256(b"original").hexdigest()

    out = s.actuate(
        eff,
        target=str(target),
        content=b"replacement",
        authorization=_grant(["fs.write"]),
        expected_digest=expected,
    )

    assert out.acted is False
    assert out.decision == "deny"
    assert out.verdict == "precondition-unverifiable"
    assert target.read_bytes() == b"original"


class _MalformedIdentityFilesystemEffector(FilesystemEffector):
    def perceive(self, target: str) -> Observation:
        observed = super().perceive(target)
        data = dict(observed.data)
        data["sha256"] = "sha256:" + data["sha256"]
        return Observation(
            organ=observed.organ,
            subject=observed.subject,
            summary=observed.summary,
            status=observed.status,
            provenance=observed.provenance,
            data=data,
        )


def test_malformed_observation_identity_refuses_expected_digest_before_write(tmp_path):
    s = AccountableSurface()
    eff = _MalformedIdentityFilesystemEffector(tmp_path)
    target = tmp_path / "f.txt"
    target.write_bytes(b"original")
    expected = hashlib.sha256(b"original").hexdigest()

    out = s.actuate(
        eff,
        target=str(target),
        content=b"replacement",
        authorization=_grant(["fs.write"]),
        expected_digest=expected,
    )

    assert out.acted is False
    assert out.decision == "deny"
    assert out.verdict == "precondition-unverifiable"
    assert target.read_bytes() == b"original"


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


def test_verified_actuation_carries_composed_certificate(tmp_path):
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    out = s.actuate(eff, target=target, content=b"hello", authorization=_grant(["fs.write"]))
    assert out.verified is True
    assert out.certificate["verdict"] == "verified"   # gate allow . effect pass -> VERIFIED
    assert out.certificate["oracle"] == "composed-v1"
    act = [e for e in s.journal if e.kind == "actuation"][-1]
    assert act.detail["certificate"]["verdict"] == "verified"  # the witness IS the verdict


def test_denied_actuation_certificate_is_refuted(tmp_path):
    s = AccountableSurface()
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    out = s.actuate(eff, target=target, content=b"hello", authorization={})  # no grant -> deny
    assert out.acted is False
    assert out.certificate["verdict"] == "refuted"    # gate deny -> REFUTED


def test_rolled_back_actuation_certificate_is_refuted(tmp_path):
    # the faulty write fails re-perception -> effect REFUTED -> action REFUTED (honest)
    class FaultyEffector(FilesystemEffector):
        def _write(self, path, content):
            path.write_bytes(b"CORRUPTED")

    s = AccountableSurface()
    eff = FaultyEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    Path(target).write_bytes(b"original")
    out = s.actuate(eff, target=target, content=b"hello", authorization=_grant(["fs.write"]))
    assert out.certificate["verdict"] == "refuted"
