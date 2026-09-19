"""Remote read-authority controls for MCP actuation and journal exposure.

These tests name the read boundary breaks that made the old two-door model too
wide: a grant that authorizes the write action must not also imply permission to
read bytes, API resources, or the operator journal.
"""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256

import pytest

from accountable_surface.api_effector import ApiCall, FakeApiDriver, GITHUB_ISSUE_COMMENTS
from accountable_surface.effector import FilesystemEffector
from accountable_surface.registry import EffectorRegistry, Exposed, _decode_bytes, load_effectors
from accountable_surface.remote_actuation import actuate_impl
from accountable_surface.server import AuthorityStore, interocept as mcp_interocept, remote_perceive_impl, session_journal_impl
from accountable_surface.surface import AccountableSurface
from accountable_surface.read_authority import (
    AuthorizedRead,
    ReadEnvelope,
    describe_api_read,
    describe_filesystem_read,
    select_read_decision,
)

THREAD = "/repos/octo/demo/issues/7/comments"


def _grant(actions=(), reads=(), *, revoked=False, receipt_id="rcpt-read-1"):
    return {
        "authorization_version": "0.1",
        "receipt_id": receipt_id,
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "mcp-caller"},
        "intent": "remote read authority test",
        "scope": {
            "allowed_actions": list(actions),
            "allowed_targets": [],
            "allowed_reads": list(reads),
        },
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": revoked,
    }


def _write_grants(path, grants):
    path.write_text(json.dumps(grants), encoding="utf-8")


def _store(tmp_path, grants):
    path = tmp_path / "grants.json"
    _write_grants(path, grants)
    return AuthorityStore(str(path))


def _fs_read_scope(root, *, paths=("**",), phases=("before", "backup", "after", "rollback")):
    return {
        "observation_kind": "fs.bytes",
        "phases": list(phases),
        "target_scope": {"kind": "fs", "root": str(root), "paths": list(paths)},
    }


def _api_read_scope(*, paths=None, phases=("before", "after", "rollback"), intents=("post_comment",)):
    op = GITHUB_ISSUE_COMMENTS.operations[0]
    return {
        "observation_kind": "api.resource",
        "phases": list(phases),
        "target_scope": {
            "kind": "api",
            "service": "github",
            "origins": [GITHUB_ISSUE_COMMENTS.origin],
            "intents": list(intents),
            "paths": list(paths or [op.path_shape]),
        },
    }


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


def _fs_registry(root, effector):
    return EffectorRegistry(
        {
            "fs.write": Exposed(
                "fs.write",
                effector,
                _decode_bytes,
                "test filesystem",
                lambda target, payload, phase, request_id: describe_filesystem_read(
                    root, target, phase, request_id
                ),
                lambda payload: ("before", "backup", "after", "rollback"),
            )
        },
        [],
    )


def _api_registry(tmp_path, driver):
    spec = tmp_path / "effectors.json"
    spec.write_text(json.dumps({"effectors": [{"action_kind": "api.post", "type": "api", "service": "github"}]}), encoding="utf-8")
    return load_effectors(str(spec), api_driver=driver)


def test_remote_filesystem_wrong_scope_refuses_before_reading_bytes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "safe2" / "note.txt"
    effector = CountingFilesystemEffector(root)
    store = _store(tmp_path, [_grant(["fs.write"], [_fs_read_scope(root, paths=("safe/**",))])])

    out = actuate_impl(AccountableSurface(), store, _fs_registry(root, effector), "fs.write", str(target), "hello")

    assert out["decision"] == "deny"
    assert out["acted"] is False
    assert effector.perceives == 0
    assert effector.writes == 0
    assert not target.exists()


def test_remote_filesystem_action_grant_without_read_scope_refuses_before_reading_bytes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "note.txt"
    effector = CountingFilesystemEffector(root)
    store = _store(tmp_path, [_grant(["fs.write"], [])])

    out = actuate_impl(AccountableSurface(), store, _fs_registry(root, effector), "fs.write", str(target), "hello")

    assert out["decision"] == "deny"
    assert "read authority" in out["reasons"][0]
    assert effector.perceives == 0
    assert effector.writes == 0
    assert not target.exists()


def test_relative_filesystem_target_is_read_under_registry_root_not_process_cwd(tmp_path, monkeypatch):
    root = tmp_path / "root"
    cwd = tmp_path / "cwd"
    root.mkdir()
    cwd.mkdir()
    root_target = root / "note.txt"
    cwd_target = cwd / "note.txt"
    root_target.write_text("ROOT-BEFORE", encoding="utf-8")
    cwd_target.write_text("CWD-SECRET", encoding="utf-8")
    monkeypatch.chdir(cwd)
    effector = CountingFilesystemEffector(root)
    store = _store(tmp_path, [_grant(["fs.write"], [_fs_read_scope(root)])])

    out = actuate_impl(AccountableSurface(), store, _fs_registry(root, effector), "fs.write", "note.txt", "ROOT-AFTER")

    assert out["decision"] == "allow"
    assert root_target.read_text(encoding="utf-8") == "ROOT-AFTER"
    assert cwd_target.read_text(encoding="utf-8") == "CWD-SECRET"
    secret_sha = sha256(b"CWD-SECRET").hexdigest()
    assert secret_sha not in json.dumps(out)


def test_remote_filesystem_missing_after_and_rollback_authority_refuses_before_mutation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "note.txt"
    effector = CountingFilesystemEffector(root)
    store = _store(tmp_path, [_grant(["fs.write"], [_fs_read_scope(root, phases=("before",))])])

    out = actuate_impl(AccountableSurface(), store, _fs_registry(root, effector), "fs.write", str(target), "hello")

    assert out["decision"] == "deny"
    assert "phase" in out["reasons"][0]
    assert effector.writes == 0
    assert not target.exists()


def test_actuation_receipt_audits_selected_read_phases(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "note.txt"
    effector = CountingFilesystemEffector(root)
    store = _store(tmp_path, [_grant(["fs.write"], [_fs_read_scope(root)])])

    out = actuate_impl(AccountableSurface(), store, _fs_registry(root, effector), "fs.write", str(target), "hello")

    audit = out["journal_entry"]["detail"]["read_authority"]
    assert [item["phase"] for item in audit["decisions"]] == ["before", "backup", "after", "rollback"]
    assert all(item["verdict"] == "allow" for item in audit["decisions"])
    assert all("grant_digest" in item and "scope_digest" in item for item in audit["decisions"])
    assert "authorization-grant" not in json.dumps(audit)


def test_revocation_reloaded_after_before_read_stops_mutation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "note.txt"
    grant_path = tmp_path / "grants.json"
    active = _grant(["fs.write"], [_fs_read_scope(root)])
    revoked = _grant(["fs.write"], [_fs_read_scope(root)], revoked=True)
    _write_grants(grant_path, [active])

    class RevokingEffector(CountingFilesystemEffector):
        def perceive(self, target):
            observed = super().perceive(target)
            if self.perceives == 1:
                _write_grants(grant_path, [revoked])
            return observed

    effector = RevokingEffector(root)

    out = actuate_impl(
        AccountableSurface(), AuthorityStore(str(grant_path)), _fs_registry(root, effector),
        "fs.write", str(target), "hello"
    )

    assert out["decision"] == "deny"
    assert "revoked" in json.dumps(out).lower()
    assert effector.perceives == 1
    assert effector.writes == 0
    assert not target.exists()


def test_unexposed_action_refuses_before_authority_file_is_read(tmp_path):
    class ExplodingAuthority:
        def load_for_remote_call(self):
            raise AssertionError("grant file should not be read")

    out = actuate_impl(
        AccountableSurface(), ExplodingAuthority(), _fs_registry(tmp_path, CountingFilesystemEffector(tmp_path)),
        "api.post", THREAD, '{"intent": "post_comment", "body": {}}'
    )

    assert out["decision"] == "deny"
    assert out["journal_entry"] is None


def test_api_denied_read_scope_never_calls_driver_or_secret(tmp_path, monkeypatch):
    token_reads = []

    def fake_require_secret(name):
        token_reads.append(name)
        raise AssertionError("secret should not be read")

    monkeypatch.setattr("accountable_surface.api_effector.require_secret", fake_require_secret)
    driver = FakeApiDriver({THREAD: []})
    store = _store(tmp_path, [_grant(["api.post"], [_api_read_scope(paths=("/other",))])])

    out = actuate_impl(
        AccountableSurface(), store, _api_registry(tmp_path, driver),
        "api.post", THREAD, '{"intent": "post_comment", "body": {"body": "hello"}}'
    )

    assert out["decision"] == "deny"
    assert driver.requests == []
    assert token_reads == []


def test_remote_web_perceive_default_denies_without_surface_perceive(tmp_path):
    class CountingSurface(AccountableSurface):
        def __init__(self):
            super().__init__()
            self.perceive_calls = 0

        def perceive(self, subject):
            self.perceive_calls += 1
            return super().perceive(subject)

    surface = CountingSurface()
    out = remote_perceive_impl(surface, _store(tmp_path, []), "https://example.com/docs/a")

    assert out["decision"] == "deny"
    assert surface.perceive_calls == 0


def test_malformed_read_grant_missing_control_fields_denies_before_perception(tmp_path):
    class CountingSurface(AccountableSurface):
        def __init__(self):
            super().__init__()
            self.perceive_calls = 0

        def perceive(self, subject):
            self.perceive_calls += 1
            return super().perceive(subject)

    grant = _grant([], [{
        "observation_kind": "web.document",
        "phases": ["direct"],
        "target_scope": {"kind": "web", "origins": ["https://example.com"], "paths": ["/**"]},
    }])
    del grant["expires_at"]
    del grant["revoked"]
    surface = CountingSurface()

    out = remote_perceive_impl(surface, _store(tmp_path, [grant]), "https://example.com/private/path")

    assert out["decision"] == "deny"
    assert surface.perceive_calls == 0


def test_remote_journal_full_session_replay_requires_explicit_scope(tmp_path):
    surface = AccountableSurface()
    surface.propose(action_kind="summarize", target="page", authorization=_grant(["summarize"]))

    denied = session_journal_impl(surface, _store(tmp_path, []))
    scoped = _grant([], [{"observation_kind": "journal.session", "target_scope": {"kind": "journal", "visibility": "session"}}])
    allowed = session_journal_impl(surface, _store(tmp_path, [scoped]))

    assert denied["decision"] == "deny"
    assert denied.get("entries") in (None, [])
    assert allowed["decision"] == "allow"
    assert len(allowed["entries"]) == len(surface.journal)


def test_mcp_interocept_redacts_journal_entries(monkeypatch):
    surface = AccountableSurface()
    surface.propose(action_kind="summarize", target="secret-target", authorization=_grant(["summarize"]))
    monkeypatch.setattr("accountable_surface.server._surface", surface)

    out = mcp_interocept()

    assert out["data"]["perceptions"] == 0
    assert out["data"]["decisions"] == 1
    assert "entries" not in out["data"]
    assert "secret-target" not in json.dumps(out)


def test_remote_journal_own_session_scope_is_not_forgeable_on_stdio(tmp_path):
    scoped = _grant([], [{"observation_kind": "journal.own-session", "target_scope": {"kind": "journal", "visibility": "own-session"}}])
    out = session_journal_impl(AccountableSurface(), _store(tmp_path, [scoped]))
    assert out["decision"] == "needs-human"
    with pytest.raises(TypeError):
        session_journal_impl(AccountableSurface(), _store(tmp_path, [scoped]), caller_session="fake")


def test_caller_supplied_before_read_object_cannot_unlock_actuation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "note.txt"
    other = root / "other.txt"
    other.write_text("other", encoding="utf-8")
    effector = CountingFilesystemEffector(root)
    request = describe_filesystem_read(root, other, "before", "req-before")
    decision = select_read_decision([_grant([], [_fs_read_scope(root)])], request)
    forged = AuthorizedRead(request, decision, effector.perceive(str(other)))
    envelope = ReadEnvelope((decision,))

    outcome = AccountableSurface()._actuate_with_authorized_read(
        effector,
        target=str(target),
        content=b"hello",
        authorization=_grant(["fs.write"], [_fs_read_scope(root)]),
        authorized_before=forged,
        read_envelope=envelope,
    )

    assert outcome.acted is False
    assert not target.exists()


def test_same_subject_authorized_read_with_forged_observation_digest_refuses(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("REAL-BEFORE", encoding="utf-8")
    effector = CountingFilesystemEffector(root)
    requests = [
        describe_filesystem_read(root, target, phase, f"req-{phase}")
        for phase in ("before", "backup", "after", "rollback")
    ]
    decisions = tuple(select_read_decision([_grant(["fs.write"], [_fs_read_scope(root)])], request) for request in requests)
    actual_before = effector.perceive(str(target))
    forged_before = replace(actual_before, data={**actual_before.data, "sha256": "0" * 64})

    outcome = AccountableSurface()._actuate_with_authorized_read(
        effector,
        target=str(target),
        content=b"NEW-CONTENT",
        authorization=_grant(["fs.write"], [_fs_read_scope(root)]),
        authorized_before=AuthorizedRead(requests[0], decisions[0], forged_before),
        read_envelope=ReadEnvelope(decisions),
        expected_digest="0" * 64,
    )

    assert outcome.acted is False
    assert target.read_text(encoding="utf-8") == "REAL-BEFORE"
