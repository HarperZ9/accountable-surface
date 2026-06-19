"""Tests for interoception — the surface perceiving its own session (Phase 3).

Offline. Proves the self-view is witnessed, accurate, tamper-evident, and inert.
"""

from __future__ import annotations

from accountable_surface.surface import AccountableSurface

FIXTURE = b"<!doctype html><html><head><title>T</title></head><body><p>hi</p></body></html>"


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-io-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "io-agent"},
        "intent": "interoception test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_empty_session_self_view():
    obs = AccountableSurface().interocept()
    assert obs.organ == "interoception"
    assert obs.subject == "self://session"
    assert obs.data["perceptions"] == 0
    assert obs.data["decisions"] == 0
    assert obs.data["journal_digest"].startswith("sha256:")
    assert len(obs.data["journal_digest"].split(":", 1)[1]) == 64


def test_self_view_counts_perceptions_and_decisions():
    s = AccountableSurface()
    s.perceive(FIXTURE)
    s.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    s.propose(action_kind="delete", target="page", authorization=_grant(["summarize"]))
    obs = s.interocept()
    assert obs.data["perceptions"] == 1
    assert obs.data["decisions"] == 2
    assert obs.data["decision_counts"].get("allow") == 1
    assert obs.data["decision_counts"].get("deny") == 1
    assert obs.data["pending_needs_human"] == 0


def test_journal_digest_changes_with_activity():
    s = AccountableSurface()
    before = s.interocept().data["journal_digest"]
    s.perceive(FIXTURE)
    after = s.interocept().data["journal_digest"]
    assert before != after


def test_self_view_is_witnessed_and_advisory():
    from coherence_membrane.observation import Status

    obs = AccountableSurface().interocept()
    assert obs.provenance.digest.startswith("sha256:")
    assert len(obs.provenance.digest.split(":", 1)[1]) == 64
    assert obs.status in {Status.PASS, Status.WARN, Status.UNVERIFIED,
                          Status.NEEDS_HUMAN, Status.BLOCK}


def test_interocept_does_not_mutate_journal():
    s = AccountableSurface()
    s.perceive(FIXTURE)
    n_before = len(s.journal)
    s.interocept()
    s.interocept()
    assert len(s.journal) == n_before  # pure read
