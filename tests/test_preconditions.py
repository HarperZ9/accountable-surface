"""State-precondition identity contract for AccountableSurface.actuate."""

from __future__ import annotations

import hashlib

from coherence_membrane.observation import Observation

from accountable_surface.effector import FilesystemEffector
from accountable_surface.surface import AccountableSurface


def _grant(actions):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-precondition-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "precondition-agent"},
        "intent": "precondition test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": []},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


class _UnmappedIdentityFilesystemEffector(FilesystemEffector):
    def perceive(self, target: str) -> Observation:
        observed = super().perceive(target)
        data = dict(observed.data)
        data["identity_sha256"] = data["sha256"]
        return Observation(
            organ="unmapped-identity-effector",
            subject=observed.subject,
            summary=observed.summary,
            status=observed.status,
            provenance=observed.provenance,
            data=data,
        )


def test_valid_identity_sha256_from_unmapped_organ_refuses_before_write(tmp_path):
    target = tmp_path / "f.txt"
    target.write_bytes(b"original")
    expected = hashlib.sha256(b"original").hexdigest()

    out = AccountableSurface().actuate(
        _UnmappedIdentityFilesystemEffector(tmp_path),
        target=str(target),
        content=b"replacement",
        authorization=_grant(["fs.write"]),
        expected_digest=expected,
    )

    assert out.acted is False
    assert out.decision == "deny"
    assert out.verdict == "precondition-unverifiable"
    assert target.read_bytes() == b"original"
