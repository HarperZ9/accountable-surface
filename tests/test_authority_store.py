"""AuthorityStore grant-file loading fails closed without exposing grant bodies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from accountable_surface.server import AuthorityStore


def _fs_read_scope(root):
    return {
        "observation_kind": "fs.bytes",
        "phases": ["before", "backup", "after", "rollback"],
        "target_scope": {"kind": "fs", "root": str(root), "paths": ["**"]},
    }


def _grant(reads=(), *, revoked=False):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-authority-store-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "mcp-caller"},
        "intent": "authority store test",
        "scope": {"allowed_actions": ["fs.write"], "allowed_targets": [], "allowed_reads": list(reads)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": revoked,
    }


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("{", "invalid JSON"),
        (["not a grant"], "wrong top-level"),
        ({"kind": "authorization-grant"}, "scope is malformed"),
        (_grant([_fs_read_scope(Path("C:/tmp"))], revoked=True), "revoked"),
        ({**_grant([_fs_read_scope(Path("C:/tmp"))]), "expires_at": "2000-01-01T00:00:00+00:00"}, "expired"),
        ({**_grant([_fs_read_scope(Path("C:/tmp"))]), "granted_at": "2999-01-01T00:00:00+00:00"}, "not yet active"),
    ],
)
def test_authority_store_malformed_or_inactive_grants_have_no_usable_body(tmp_path, payload, reason):
    path = tmp_path / "grants.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    state = AuthorityStore(str(path)).load_for_remote_call()
    assert state.grants == []
    assert reason in state.reason


def test_authority_store_missing_file_has_no_usable_grants(tmp_path):
    state = AuthorityStore(str(tmp_path / "absent.json")).load_for_remote_call()
    assert state.grants == []
    assert "unreadable" in state.reason


@pytest.mark.parametrize("missing_field", ["expires_at", "revoked"])
def test_authority_store_rejects_grants_missing_required_control_fields(tmp_path, missing_field):
    grant = _grant([_fs_read_scope(tmp_path)])
    del grant[missing_field]
    path = tmp_path / "grants.json"
    path.write_text(json.dumps([grant]), encoding="utf-8")

    state = AuthorityStore(str(path)).load_for_remote_call()

    assert state.grants == []
    assert "malformed" in state.reason
