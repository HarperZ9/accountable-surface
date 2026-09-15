"""Read-authority scope matching for the remote Control boundary."""

from __future__ import annotations

import pytest

from accountable_surface.api_effector import ApiCall, GITHUB_ISSUE_COMMENTS
from accountable_surface.read_authority import (
    ReadRequest,
    describe_api_read,
    describe_filesystem_read,
    describe_journal_read,
    describe_web_read,
    select_read_decision,
)


THREAD = "/repos/octo/demo/issues/7/comments"


def _grant(reads):
    return {
        "authorization_version": "0.1",
        "receipt_id": "read-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "remote-agent"},
        "intent": "read test",
        "scope": {"allowed_actions": [], "allowed_targets": [], "allowed_reads": list(reads)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _fs_scope(root, paths=(), phases=("before",)):
    return {
        "observation_kind": "fs.bytes",
        "phases": list(phases),
        "target_scope": {"kind": "fs", "root": str(root), "paths": list(paths)},
    }


def test_filesystem_scope_matches_path_segments_not_string_prefix(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    request = describe_filesystem_read(root, root / "safe2" / "note.txt", "before", "req-1")
    decision = select_read_decision([_grant([_fs_scope(root, ["safe/**"])])], request)
    assert decision.verdict == "deny"


def test_filesystem_subtree_wildcard_covers_descendant(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    request = describe_filesystem_read(root, root / "safe" / "note.txt", "before", "req-1")
    decision = select_read_decision([_grant([_fs_scope(root, ["safe/**"])])], request)
    assert decision.verdict == "allow"


@pytest.mark.parametrize("pattern", ["safe*", "safe/**/deep", "../safe/**", "safe/../**"])
def test_filesystem_malformed_wildcards_deny(tmp_path, pattern):
    root = tmp_path / "sandbox"
    root.mkdir()
    request = describe_filesystem_read(root, root / "safe" / "note.txt", "before", "req-1")
    decision = select_read_decision([_grant([_fs_scope(root, [pattern])])], request)
    assert decision.verdict == "deny"


def test_filesystem_dotdot_target_refuses_before_scope_check(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    with pytest.raises(ValueError, match="dotdot"):
        describe_filesystem_read(root, root / "safe" / ".." / "note.txt", "before", "req-1")


def test_web_origin_matching_rejects_host_prefix_and_scheme_changes():
    scope = {
        "observation_kind": "web.document",
        "target_scope": {"kind": "web", "origins": ["https://example.com"], "paths": ["/docs/**"]},
    }
    evil_host = describe_web_read("https://example.com.evil/docs/a", "req-1")
    http_scheme = describe_web_read("http://example.com/docs/a", "req-2")
    assert select_read_decision([_grant([scope])], evil_host).verdict == "deny"
    assert select_read_decision([_grant([scope])], http_scheme).verdict == "deny"


def test_web_scope_without_paths_does_not_default_to_all_paths():
    scope = {
        "observation_kind": "web.document",
        "target_scope": {"kind": "web", "origins": ["https://example.com"]},
    }
    request = describe_web_read("https://example.com/private/path", "req-1")
    assert select_read_decision([_grant([scope])], request).verdict == "deny"


@pytest.mark.parametrize("url", ["file:///tmp/a", "https://user@example.com/docs/a"])
def test_web_rejects_non_http_and_userinfo_before_read(url):
    with pytest.raises(ValueError):
        describe_web_read(url, "req-1")


def test_api_read_request_derives_intent_and_path_shape_from_service_metadata():
    request = describe_api_read(
        GITHUB_ISSUE_COMMENTS, THREAD, ApiCall("post_comment", {"body": "hi"}), "before", "req-1",
    )
    op = GITHUB_ISSUE_COMMENTS.operations[0]
    assert request.observation_kind == "api.resource"
    assert request.target_scope["service"] == "github"
    assert request.target_scope["intent"] == op.intent
    assert request.target_scope["path_shape"] == op.path_shape


def test_api_origin_scope_must_be_a_list_not_a_string_prefix():
    request = describe_api_read(
        GITHUB_ISSUE_COMMENTS, THREAD, ApiCall("post_comment", {"body": "hi"}), "before", "req-1",
    )
    scope = {
        "observation_kind": "api.resource",
        "phases": ["before"],
        "target_scope": {
            "kind": "api",
            "service": "github",
            "origins": "https://api.github.com.evil",
            "intents": ["post_comment"],
            "paths": [GITHUB_ISSUE_COMMENTS.operations[0].path_shape],
        },
    }
    assert select_read_decision([_grant([scope])], request).verdict == "deny"


def test_unknown_observation_kind_with_valid_identity_hash_denies():
    request = ReadRequest(
        "read",
        "unknown.organ",
        "unknown://subject",
        "direct",
        {"kind": "unknown", "identity_sha256": "0" * 64},
        "req-unknown",
        "2026-06-19T00:00:00+00:00",
    )
    scope = {
        "observation_kind": "unknown.organ",
        "target_scope": {"kind": "unknown", "identity_sha256": "0" * 64},
    }
    assert select_read_decision([_grant([scope])], request).verdict == "deny"


def test_journal_own_session_is_needs_human_on_stdio():
    request = describe_journal_read("own-session", "req-1")
    decision = select_read_decision([
        _grant([{"observation_kind": "journal.own-session",
                 "target_scope": {"kind": "journal", "visibility": "own-session"}}])
    ], request)
    assert decision.verdict == "needs-human"


def test_read_request_is_typed_read_authority():
    request = describe_journal_read("own-call", "req-1")
    assert isinstance(request, ReadRequest)
    assert request.authority_class == "read"
