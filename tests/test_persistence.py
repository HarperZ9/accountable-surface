"""Tests for durable journal persistence (Phase 3).

Offline. Proves the journal survives across sessions: append-only JSONL on
every perception/decision, replay on init, round-trip fidelity, and that a
corrupt line is surfaced (a tamper signal) rather than silently dropped.

The in-memory default (no path) is unchanged — guarded by the existing suite.
"""

from __future__ import annotations

import json

from accountable_surface.surface import AccountableSurface

FIXTURE = b"<!doctype html><html><head><title>T</title></head><body><p>hi</p></body></html>"


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-persist-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "persist-agent"},
        "intent": "persistence test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_perceive_appends_a_jsonl_line(tmp_path):
    path = tmp_path / "journal.jsonl"
    s = AccountableSurface(journal_path=path)
    s.perceive(FIXTURE)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["kind"] == "perception"
    assert "web-document" in rec["summary"]


def test_propose_appends_a_decision_line(tmp_path):
    path = tmp_path / "journal.jsonl"
    s = AccountableSurface(journal_path=path)
    s.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["kind"] == "decision"
    assert rec["detail"]["decision"] in {"allow", "deny", "needs-human"}


def test_replay_on_init_restores_prior_journal(tmp_path):
    path = tmp_path / "journal.jsonl"
    first = AccountableSurface(journal_path=path)
    first.perceive(FIXTURE)
    first.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    # A new session on the same path replays the prior journal into memory.
    second = AccountableSurface(journal_path=path)
    assert len(second.journal) == 2
    assert second.journal[0].kind == "perception"
    assert second.journal[1].kind == "decision"


def test_replay_round_trip_fidelity(tmp_path):
    path = tmp_path / "journal.jsonl"
    first = AccountableSurface(journal_path=path)
    first.perceive(FIXTURE)
    original = first.journal[0]
    restored = AccountableSurface(journal_path=path).journal[0]
    assert restored.kind == original.kind
    assert restored.summary == original.summary
    assert restored.detail == original.detail


def test_append_only_accumulates_across_sessions(tmp_path):
    path = tmp_path / "journal.jsonl"
    AccountableSurface(journal_path=path).perceive(FIXTURE)
    # Second session replays one entry and adds another; the file holds both,
    # in order, and nothing is rewritten.
    second = AccountableSurface(journal_path=path)
    second.perceive(FIXTURE)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert len(second.journal) == 2


def test_malformed_line_is_counted_not_dropped(tmp_path):
    path = tmp_path / "journal.jsonl"
    AccountableSurface(journal_path=path).perceive(FIXTURE)
    # A corrupt line appended out-of-band is a tamper signal, not noise.
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not valid json\n")
    reloaded = AccountableSurface(journal_path=path)
    assert len(reloaded.journal) == 1      # the valid entry still loads
    assert reloaded.replay_errors == 1     # the corruption is surfaced, not hidden


# --- Cycle 2: the payoff — a witnessed self-view that spans sessions --------

def test_interocept_spans_replayed_sessions(tmp_path):
    # The point of durability: the self-view counts history from prior sessions.
    path = tmp_path / "journal.jsonl"
    first = AccountableSurface(journal_path=path)
    first.perceive(FIXTURE)
    first.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    obs = AccountableSurface(journal_path=path).interocept()
    assert obs.data["perceptions"] == 1
    assert obs.data["decisions"] == 1


def test_interocept_digest_is_storage_independent(tmp_path):
    # The self-view digests journal CONTENT, not storage. The same activity
    # yields the same digest whether it was created in-session or replayed —
    # so persistence cannot silently alter what the surface attests to.
    path = tmp_path / "journal.jsonl"
    AccountableSurface(journal_path=path).perceive(FIXTURE)
    replayed = AccountableSurface(journal_path=path).interocept().data["journal_digest"]

    in_memory = AccountableSurface()
    in_memory.perceive(FIXTURE)
    assert replayed == in_memory.interocept().data["journal_digest"]


def test_no_path_writes_nothing(tmp_path):
    # Backward-compatible default: with no journal_path the surface touches no
    # disk at all — purely in-memory, exactly as before Phase 3.
    s = AccountableSurface()
    s.perceive(FIXTURE)
    s.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))
    assert len(s.journal) == 2
    assert list(tmp_path.iterdir()) == []
