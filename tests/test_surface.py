"""Tests for the Accountable Surface spike -- the keystone loop.

Proves: witnessed perception; authorized -> allow; unauthorized/expired/empty
grant -> deny; integrity mismatch -> state deny; integrity match -> allow; the
surface never executes; the journal records perception + decision.

Run: PYTHONPATH="<coherence-membrane>/src;<proof-surface>/src" python -m pytest
"""

from __future__ import annotations

import hashlib

from accountable_surface.surface import AccountableSurface

FIXTURE = (
    b"<!doctype html><html><head><title>T</title></head>"
    b"<body><p>hello world</p><a href='/x'>x</a></body></html>"
)


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-spike-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "spike-agent"},
        "intent": "spike demo",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_perceive_is_witnessed():
    s = AccountableSurface()
    obs = s.perceive(FIXTURE)
    assert obs.organ == "web-document"
    assert obs.provenance.digest == "sha256:" + hashlib.sha256(FIXTURE).hexdigest()
    assert any(e.kind == "perception" for e in s.journal)


def test_authorized_action_allowed():
    s = AccountableSurface()
    out = s.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    assert out.decision == "allow"
    assert out.executed is False


def test_unauthorized_action_refused():
    s = AccountableSurface()
    out = s.propose(action_kind="delete", target="page", authorization=_grant(["summarize"]))
    assert out.decision == "deny"
    assert out.executed is False
    assert out.checks.get("authorization") == "fail"
    assert any("not in allowed_actions" in r or "authorization" in r.lower() for r in out.reasons)


def test_empty_authorization_denied():
    s = AccountableSurface()
    out = s.propose(action_kind="summarize", target="page", authorization={})
    assert out.decision == "deny"


def test_expired_grant_denied():
    s = AccountableSurface()
    grant = _grant(["summarize"])
    grant["expires_at"] = "2020-01-01T00:00:00+00:00"
    out = s.propose(action_kind="summarize", target="page", authorization=grant)
    assert out.decision == "deny"


def test_integrity_mismatch_denied():
    s = AccountableSurface()
    obs = s.perceive(FIXTURE)
    other = hashlib.sha256(b"a different page").hexdigest()
    out = s.propose(
        action_kind="summarize",
        target="page",
        authorization=_grant(["summarize"]),
        observation=obs,
        expected_digest=other,
    )
    assert out.decision == "deny"
    assert out.checks.get("state") == "fail"


def test_integrity_match_allowed():
    s = AccountableSurface()
    obs = s.perceive(FIXTURE)
    same = obs.data["identity_sha256"]
    out = s.propose(
        action_kind="summarize",
        target="page",
        authorization=_grant(["summarize"]),
        observation=obs,
        expected_digest=same,
    )
    assert out.decision == "allow"
    assert out.checks.get("state") == "pass"


def test_surface_never_executes():
    s = AccountableSurface()
    out = s.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    assert out.executed is False


def test_journal_records_perception_and_decision():
    s = AccountableSurface()
    s.perceive(FIXTURE)
    s.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    kinds = {e.kind for e in s.journal}
    assert kinds == {"perception", "decision"}
