"""Remote-actuation durable authority controls.

The controls here exercise Accountable Surface through its MCP-facing actuation
seam with synthetic filesystem targets only.
"""

from __future__ import annotations

import json
from pathlib import Path

from accountable_surface.effector import FilesystemEffector
from accountable_surface.registry import EffectorRegistry
from accountable_surface.remote_actuation import actuate_impl
from accountable_surface.server import AuthorityStore, propose_impl, remote_perceive_impl
from accountable_surface.surface import AccountableSurface
from read_authority_helpers import fs_exposed, fs_reads


class CountingFilesystemEffector(FilesystemEffector):
    def __init__(self, root):
        super().__init__(root)
        self.perceives = 0
        self.writes = 0

    def perceive(self, target):
        self.perceives += 1
        return super().perceive(target)

    def _write(self, path, content):
        self.writes += 1
        super()._write(path, content)


def _grant(root, receipt="rcpt-durable", nonce="nonce-1", max_actions=2):
    return {
        "authorization_version": "0.1",
        "receipt_id": receipt,
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "mcp-caller"},
        "intent": "durable remote authority test",
        "scope": {
            "allowed_actions": ["fs.write"],
            "allowed_targets": [],
            "allowed_reads": fs_reads(root),
            "max_actions": max_actions,
        },
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _web_scope():
    return {
        "observation_kind": "web.document",
        "target_scope": {"kind": "web", "origins": ["https://example.test"], "paths": ["/doc"]},
    }


def _write_grants(path, grants):
    path.write_text(json.dumps(grants), encoding="utf-8")


def _store(tmp_path, grants, *, journal_path=None):
    grant_path = tmp_path / "grants.json"
    state_path = tmp_path / "authority.sqlite3"
    _write_grants(grant_path, grants)
    return AuthorityStore(str(grant_path), authority_state_path=str(state_path), journal_path=str(journal_path) if journal_path else None)


def _registry(root, effector):
    return EffectorRegistry({"fs.write": fs_exposed("fs.write", effector, root)}, [])


def test_durable_remote_success_consumes_one_usage_slot(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    grant = _grant(root, max_actions=2)
    store = _store(tmp_path, [grant])
    target = root / "note.txt"
    effector = CountingFilesystemEffector(root)

    out = actuate_impl(AccountableSurface(), store, _registry(root, effector), "fs.write", str(target), "hello", idempotency_key="k1")

    assert out["decision"] == "allow"
    assert out["acted"] is True
    assert out["authority_state"]["usage_counted"] == 1
    assert target.read_text(encoding="utf-8") == "hello"


def test_protected_authority_paths_refuse_before_read_even_under_broad_grant(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    grant = _grant(root, max_actions=20)
    journal_path = root / "journal.jsonl"
    store = _store(root, [grant], journal_path=journal_path)
    effector = CountingFilesystemEffector(root)
    registry = _registry(root, effector)
    protected_targets = [
        Path(store.grants_path),
        Path(store.authority_state_path),
        Path(str(store.authority_state_path) + "-wal"),
        Path(str(store.authority_state_path) + "-shm"),
        journal_path,
    ]
    alias = root / "alias-to-grants.json"
    try:
        alias.symlink_to(store.grants_path)
        protected_targets.append(alias)
    except (OSError, NotImplementedError):
        pass

    for index, target in enumerate(protected_targets):
        out = actuate_impl(AccountableSurface(), store, registry, "fs.write", str(target), "overwrite", idempotency_key=f"protect-{index}")
        assert out["decision"] == "deny"
        assert "protected authority path" in out["reasons"][0]
    if alias.is_symlink():
        alias.unlink()
    assert effector.perceives == 0
    assert effector.writes == 0

    safe = root / "ordinary.txt"
    ok = actuate_impl(AccountableSurface(), store, registry, "fs.write", str(safe), "safe", idempotency_key="safe")
    assert ok["decision"] == "allow"


def test_duplicate_idempotency_replay_after_revocation_does_not_act_again(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    grant = _grant(root, max_actions=1)
    store = _store(tmp_path, [grant])
    effector = CountingFilesystemEffector(root)
    target = root / "note.txt"
    first = actuate_impl(AccountableSurface(), store, _registry(root, effector), "fs.write", str(target), "one", idempotency_key="repeat")
    assert first["acted"] is True

    store.record_revocation(grant, "operator revoked after first terminal operation")
    second = actuate_impl(AccountableSurface(), store, _registry(root, effector), "fs.write", str(target), "one", idempotency_key="repeat")

    assert second["decision"] == "replay-denied-new-action"
    assert second["acted"] is False
    assert second["journal_entry"] is None
    assert effector.writes == 1
    assert store.authority_state.usage_for(grant)["counted"] == 1


def test_idempotency_conflict_refuses_before_read_action_and_usage(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    grant = _grant(root, max_actions=2)
    store = _store(tmp_path, [grant])
    effector = CountingFilesystemEffector(root)
    first = actuate_impl(AccountableSurface(), store, _registry(root, effector), "fs.write", str(root / "a.txt"), "one", idempotency_key="same")
    assert first["acted"] is True

    out = actuate_impl(AccountableSurface(), store, _registry(root, effector), "fs.write", str(root / "b.txt"), "two", idempotency_key="same")

    assert out["decision"] == "deny"
    assert out["authority_state"]["reason"] == "idempotency-conflict"
    assert effector.writes == 1
    assert store.authority_state.usage_for(grant)["counted"] == 1



def test_separately_revoked_read_grant_cannot_authorize_new_target_read(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    action_grant = _grant(root, receipt="action", max_actions=1)
    action_grant["scope"]["allowed_reads"] = []
    read_grant = _grant(root, receipt="read", max_actions=1)
    read_grant["scope"]["allowed_actions"] = []
    store = _store(tmp_path, [action_grant, read_grant])
    store.record_revocation(read_grant, "operator revoked read grant")
    effector = CountingFilesystemEffector(root)

    out = actuate_impl(
        AccountableSurface(), store, _registry(root, effector),
        "fs.write", str(root / "note.txt"), "x", idempotency_key="revoked-read",
    )

    assert out["decision"] == "deny"
    assert "read authority denied" in out["reasons"][0]
    assert effector.perceives == 0
    assert effector.writes == 0
    assert store.authority_state.usage_for(action_grant)["counted"] == 0

def test_durable_revocation_survives_restart_and_stale_grant_source(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    grant = _grant(root, max_actions=2)
    grant["scope"]["allowed_reads"] = fs_reads(root) + [_web_scope()]
    store = _store(tmp_path, [grant])
    store.record_revocation(grant, "operator revoked")
    _write_grants(Path(store.grants_path), [grant])

    restarted = AuthorityStore(store.grants_path, authority_state_path=store.authority_state_path)
    effector = CountingFilesystemEffector(root)
    target = root / "note.txt"

    perceived = remote_perceive_impl(AccountableSurface(), restarted, "https://example.test/doc")
    proposed = propose_impl(AccountableSurface(), restarted.load_for_remote_call().grants, "fs.write", str(target))
    acted = actuate_impl(AccountableSurface(), restarted, _registry(root, effector), "fs.write", str(target), "x", idempotency_key="after-revoke")

    assert perceived["decision"] == "deny"
    assert proposed["decision"] == "deny"
    assert acted["decision"] == "deny"
    assert "durably revoked" in json.dumps(acted).lower()
    assert effector.perceives == 0
    assert effector.writes == 0
