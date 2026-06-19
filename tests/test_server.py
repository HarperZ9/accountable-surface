"""Logic tests for the Accountable Surface MCP server.

Tests the tool impl functions directly (offline). The live MCP protocol is
proven separately by smoke_mcp.py (a real stdio client round-trip).

Run: PYTHONPATH="<coherence-membrane>/src;<proof-surface>/src" python -m pytest
"""

from __future__ import annotations

import hashlib
import json

from accountable_surface.server import load_journal_path, load_operator_grants, perceive_impl, propose_impl
from accountable_surface.surface import AccountableSurface

FIXTURE = b"<!doctype html><html><head><title>T</title></head><body><p>hi</p></body></html>"


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-srv-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "srv-agent"},
        "intent": "server test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_perceive_impl_is_witnessed(tmp_path):
    page = tmp_path / "page.html"
    page.write_bytes(FIXTURE)
    d = perceive_impl(AccountableSurface(), str(page))
    assert d["organ"] == "web-document"
    assert d["data"]["title"] == "T"
    assert d["provenance"]["digest"] == "sha256:" + hashlib.sha256(FIXTURE).hexdigest()


def test_propose_no_grants_is_default_deny():
    out = propose_impl(AccountableSurface(), [], "summarize", "page")
    assert out["decision"] == "deny"
    assert out["executed"] is False


def test_propose_authorized_allows():
    out = propose_impl(AccountableSurface(), [_grant(["summarize"])], "summarize", "page")
    assert out["decision"] == "allow"
    assert out["executed"] is False


def test_propose_unauthorized_denies():
    out = propose_impl(AccountableSurface(), [_grant(["summarize"])], "delete", "page")
    assert out["decision"] == "deny"


def test_load_operator_grants_from_file(tmp_path):
    path = tmp_path / "grants.json"
    path.write_text(json.dumps([_grant(["summarize"])]), encoding="utf-8")
    grants = load_operator_grants(str(path))
    assert len(grants) == 1
    assert grants[0]["scope"]["allowed_actions"] == ["summarize"]


def test_load_operator_grants_missing_is_default_deny():
    assert load_operator_grants(None) == []


def test_load_journal_path_from_arg(tmp_path):
    path = tmp_path / "journal.jsonl"
    assert load_journal_path(str(path)) == path


def test_load_journal_path_missing_is_none(monkeypatch):
    monkeypatch.delenv("ACCOUNTABLE_SURFACE_JOURNAL", raising=False)
    assert load_journal_path(None) is None


def test_load_journal_path_from_env(monkeypatch, tmp_path):
    path = tmp_path / "env-journal.jsonl"
    monkeypatch.setenv("ACCOUNTABLE_SURFACE_JOURNAL", str(path))
    assert load_journal_path() == path


def test_server_surface_persists_when_journal_loaded(tmp_path):
    # End-to-end at the impl layer: a surface built with a loaded journal path
    # persists perceptions; a fresh surface on that path replays them.
    page = tmp_path / "page.html"
    page.write_bytes(FIXTURE)
    path = tmp_path / "journal.jsonl"
    perceive_impl(AccountableSurface(journal_path=load_journal_path(str(path))), str(page))
    replayed = AccountableSurface(journal_path=load_journal_path(str(path)))
    assert len(replayed.journal) == 1
    assert replayed.journal[0].kind == "perception"


def test_tools_are_registered():
    from accountable_surface import server

    assert server.mcp is not None
    # the tool impls are present and callable
    assert callable(server.perceive_impl)
    assert callable(server.propose_impl)
